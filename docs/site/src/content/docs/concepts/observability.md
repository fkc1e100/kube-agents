---
title: Observability
description: OpenTelemetry traces, Prometheus metrics, and Cloud Logging routing for the Platform Agent and its inference gateway.
sidebar:
  order: 9
---

The Platform Agent (Hermes) Deployment exports OpenTelemetry traces and two sets of Prometheus metrics, the event watcher's from its `agent-api-auth` sidecar and the inbound chat message count from the Hermes container, and the credential-proxy Pod exports the broker's; LiteLLM and vLLM export both OpenTelemetry traces and Prometheus metrics to GKE Managed telemetry, and the Hindsight memory API exports Prometheus metrics. When the operator sets `A2A_CURATOR=true`, the OKF memory curator (`<name>-curator`) also exports Prometheus metrics. Container logs go to Cloud Logging. The Platform Agent's persona also generates Cloud Console links inline in Chat replies whenever it's discussing telemetry.

## What gets exported

This section has its own dedicated reference page: [Observability: Exported telemetry](/kube-agents/concepts/observability-exports/).

## Session metadata plumbing

Every Chat message carries session context (space ID, user, thread) that flows through Hermes as OpenTelemetry span attributes and out to Cloud Trace. The `session_store` and `session_otel_bridge` plugins that do this run on the Planning Agent profile, which owns chat ingress. The trace is documented in [`docs/designs/gchat-session-metadata-data-flow.md`](https://github.com/gke-labs/kube-agents/blob/main/docs/designs/gchat-session-metadata-data-flow.md).

## Inline Console links

`SOUL.md §5` requires the agent, whenever it's discussing telemetry, tracing, logs, or debugging, to generate clickable Cloud Console links using the active project ID. The URL templates live in [`agents/platform/docs/gcp-console-links.md`](https://github.com/gke-labs/kube-agents/blob/main/agents/platform/docs/gcp-console-links.md) — a shared runtime reference baked into the agent image at `/opt/defaults/docs/` and inlined directly into `SOUL.md §5` — covering Logs Explorer, Trace Explorer, Metrics Explorer, and the GKE Workloads console. The agent substitutes the runtime project ID and formats the links as Markdown so they render clickable in Chat.

## Auditing the agent itself

The [`kube-agents-observability` skill](https://github.com/gke-labs/kube-agents/tree/main/agents/platform/skills/kube-agents-observability) audits the harness's own telemetry — logs, traces, metrics, API/dashboard observability of the Platform Agent. Use it when triaging "why did the agent do X?" or "why isn't the agent responding?".

## Tool-call audit

The `tool_call_audit` plugin (enabled on every profile: the Planning Agent, the Platform Agent and each Cluster Agent) writes per-tool-call records for every skill invocation and MCP tool call, and the `chat_message_audit` hook writes a record at each stage of a chat turn: `chat_message_start`, one `chat_message_step` per agent iteration, `chat_message_end`.

Each record is one JSON object: `event_type` (and `audit_event`, the same value under the name the Admin Console queries), `severity`, `timestamp`, and the event's own fields: `tool`, `status` and `task_id` on the tool-call records, with `duration_ms` on the one that ends a call; `status` on the approval records; `session_id` and a pseudonymised `principal` on `gateway_dispatch` and the chat-turn records. The tool-call records also carry the `session_id` of the session the call ran in, empty for a call outside any session.

Arguments, results and message text are redacted (`AuditRedactor`) and truncated by the emitters, and inside Hermes the whole line then passes through Hermes' own `redact_sensitive_text`, the engine its `RedactingFormatter` applies to `agent.log` and whose token list is the wider of the two, forced so that a profile's `security.redact_secrets: false` does not reopen a trail that leaves the pod. Each emitter appends its record to `logs/audit.jsonl` under the profile's home, one JSON object per line: `/opt/data/logs/audit.jsonl` for the Planning Agent, `/opt/data/profiles/<name>/logs/audit.jsonl` for a named profile.

The two emitters rotate that file themselves at 5 MiB with three backups, the bound Hermes keeps by default on its `agent.log`. They are not its only possible writer, though: any process under the agent's uid with a path to the profile's `logs/` can append a line the sidecar ships as a record, which is the volume's boundary rather than the sidecar's.

The `fluent-bit` sidecar tails every profile's copy with its JSON parser, so the record's keys arrive as fields of their own, `jsonPayload.event_type`, `jsonPayload.tool` and so on, with `jsonPayload.file_path` naming the file and therefore the profile; no regex over a Hermes log line is involved, so a Hermes release that changes its log format does not touch the trail, and a line in `agent.log` shaped like a record does not enter the structured trail (the Admin Console's text-form query still reads such lines, as it reads the records written that way before the file existed).

The writes from the gateway and its worker processes are serialised by a lock file beside the audit file, `audit.jsonl.lock`, which nothing tails; the lock is taken without blocking and retried for 1.5 s, after which the record takes the fallback below rather than hold up the tool call the plugin's hook is part of. A record the emitter cannot write to the file, because the volume is full or read-only, the lock is held past that wait, or Hermes refuses to materialise the profile's directory, is printed instead to the emitting process's stdout as the same JSON line, and an `ERROR` naming the file and the error, without the record, goes to that process's `agent.log`.

What the two reach depends on the process. From the gateway the stdout is the container log, so the GKE log agent ships the record to Cloud Logging as `jsonPayload` under the agent container rather than the sidecar and `jsonPayload.audit_event:*` still finds it, and the `ERROR` lands in the Planning Agent's `agent.log`, which the sidecar tails. From a kanban worker neither reaches Cloud Logging: the stdout is the worker's captured transcript, the board's `logs/<task>.log` on the same volume, and the `ERROR` lands in the named profile's `agent.log`, which the sidecar's `*.log` input under `/opt/data/logs/` does not reach; on a full volume the transcript write fails too, and the `ERROR` is the only trace.

`jsonPayload.audit_event:*` in Logs Explorer is the query for the trail (`event_type` is on the broker's records too; `audit_event` is only on these). Roll the operator with or before an agent image that carries these emitters: under an operator whose sidecar configuration predates the `agent.audit` input, the file is written and nothing tails it, and the records reach Cloud Logging only once the operator's ConfigMap carries that input.

## Sharing a usage and feedback summary

An install that cannot send telemetry can still share how it is doing: `scripts/feedback-summary.sh` prints one fenced Markdown block, short enough to read in full before pasting it into an email or a chat message. It writes nothing.

It reads the `PlatformAgent` resource with `kubectl get`. Unless `--no-exec` is given, it also reads the cluster's object counts and runs `kubectl exec` into the credential broker pod for its metrics on port `8766`, and into the gateway pod for the task feed and the inference gateway's metrics. A section whose source cannot be read prints as `unavailable` (the `scale` line is omitted when unread), one line on stderr says why. A task count with a `+` means the feed was cut at its ceiling.

```bash
scripts/feedback-summary.sh --namespace kubeagents-system
```

The block carries the image tag, the mode, the model as `provider/name` from `status.inference` (when the status has no `inference` key, under an older operator or CRD, from the LiteLLM config ConfigMap by the `model-default` entry rule; a Vertex AI endpoint path or a Bedrock ARN keeps its resource id only, so its project, region and account are not printed), the Kubernetes version, the install's age and readiness, the cluster's scale counts, the `status.usage` counters (including friction counters and `lastHumanActive`), the readings marked as the forge or the gateway reports them (`no reading` when absent), the top five credential broker `tool/subcommand` pairs since the broker pod last started, the performance figures and a short feedback template.

The `reasoning effort:` line under `model:` is the effort configured on that model, `unset` when the config states none and `unavailable` whenever the model is.

The performance figures open with the token and spend totals since install, read from `status.usage`, which survive a LiteLLM restart; the live LiteLLM figures beneath them do not.

One `proposals by origin:` line follows the readings. It lists the origins above zero and ends `(as the agent reports)`. It reads `none` when all nine are zero and `no reading` when the status has none.

The operator publishes its own reading of the broker's counter as `status.usage.topTools` every five minutes: the five largest pairs, summed across the broker pods it read. The script prints that list when it cannot read the broker itself, `--no-exec` included, and the in-chat `/feedback summary` always prints it from there, line for line the same block; a status with no list prints `unavailable`.

The script needs more than a read of the resource for a full block. The broker and gateway reads run `kubectl exec`, so they need `pods/exec` (and `pods` list) in the install's namespace; the `scale` line needs cluster-wide `list` on namespaces, deployments, pods, nodes and CustomResourceDefinitions. The resource read alone still prints the counters, the readings and the status's tools list.

It names no cluster, project, namespace, user or workload: the script refuses to print, with exit code 3, if the resource's name or namespace, or any string from the spec blocks that name the install (`harness`, `scope`, `integration`, `security`, `chat`, `telemetry`, `networkPolicy`), appears in the block outside the `model:` and `proposals by origin:` lines as a whole token; booleans, numbers, strings under three characters and the block's own vocabulary are not checked, and the `deployment` block is not read because nothing the block prints draws from it. The task feed is the Platform Agent's own board; per-conversation session pods keep no board.

## Where to go next

- [Deploy → Telemetry](/kube-agents/deploy/telemetry/) — install-side details on the GKE Managed OTel and Prometheus config.
- [Reference → Attribution](/kube-agents/reference/attribution/) — how a tool call ties back to the authenticated human.
