---
title: "Credential isolation: Metadata denial & troubleshooting"
description: "How the shell sandbox is blocked from the GCP metadata server and how to diagnose broker refusals."
---

Part of [Credential isolation](/kube-agents/reference/credential-isolation/).

## Denying the sandbox the metadata server

`spec.security.egressPolicy: Allowlist` renders one NetworkPolicy on the agent Pod: default-deny egress, with rules for a fixed set of destinations and whatever `spec.security.egressAllowlist` adds. The fixed set is DNS, the credential broker, LiteLLM, the namespace of the OpenTelemetry collector the agent resolved, the Hindsight memory API, and the A2A NATS pods on TCP `4222`. The collector is the managed one by default, and there is no rule when the endpoint names nothing in-cluster. The metadata server's credential API is denied by not appearing on that list.

The DNS rule is the one place a metadata address does appear, on port 53 alone. On a cluster using [Cloud DNS for GKE](https://cloud.google.com/kubernetes-engine/docs/how-to/cloud-dns) the node answers DNS at `169.254.169.254:53` and every Pod's `resolv.conf` names it. Withholding it would leave the Pod with no name resolution, and every destination in this allowlist is reached by name. The token is minted over TCP 80 pre-NAT and 988 post-NAT, and no rule permits _this address_ on either. (TCP 80 is permitted to the LiteLLM Pod selector, which no link-local address matches.)

The peer does widen one thing, on one kind of cluster. Where CoreDNS forwards externally — the stock configuration — it grants nothing the `k8s-app: kube-dns` peers above do not already grant, since those resolve arbitrary external names. Where an administrator has removed that forwarding to close DNS as an exfiltration path, this peer hands the Pod the node's GCE recursive resolver and reopens it. GKE's metadata interception rewrites TCP 80 and 8080, not 53, so the address answers DNS there on any GCE node not running `gke-metadata-server` or metadata concealment. If that describes your cluster, the peer is the one part of this policy to weigh rather than accept.

### This blocks nothing today

**Turning this on does not take any egress away from the agent Pod. It cannot.** Adding a NetworkPolicy is a monotone operation: policies selecting one Pod are unioned, the Pod may send whatever any of them permits, and the API has no deny rule at all. The agent Pod is already selected for egress by `<name>-gateway-netpol`, which the operator renders on every reconcile whether or not you set this field. So with the flag on the Pod's permitted egress is a strict _superset_ of what it was with the flag off.

In the default shape it adds the credential broker on TCP 8765 and, when the agent is not exporting telemetry, the managed collector namespace on 4317/4318. The gateway policy renders its own OTel rule only while there is an endpoint to export to. This one keeps `gke-managed-otel` on a cluster that resolved to no collector, so that exports are not blocked the moment a collector appears there. With an endpoint, both policies read the namespace off it and name the same one.

That holds wherever another policy still permits the wider egress, which is every install shape but one. `spec.networkPolicy.enabled: false` stops the operator rendering `<name>-gateway-netpol` at all and deletes one it owns. With the field false, this policy really is the only one selecting the agent Pod, and on an enforcing CNI it then default-denies for real. That denies the metadata server, but also GitHub, web search, external 443 and everything else not on the allowlist. Everywhere else it is a property of the API, not of a particular cluster.

What `<name>-gateway-netpol` already permits, and this therefore cannot remove:

- No metadata path: it names `169.254.169.254/32` on port 53 only, as this policy does, for the Cloud DNS reason above. The rules that used to admit TCP 80 and the metadata-daemon port went with the gateway's Workload Identity.
- TCP 443 to `0.0.0.0/0` minus the private ranges, unless FQDNNetworkPolicy is enabled. Every HTTPS destination on the public internet stays open, and with it the exfiltration half of what this is meant to be.

The gateway policy no longer permits the metadata path: the gateway holds no Google identity to fetch a token for. The overlap that remains is its TCP 443 rule to `0.0.0.0/0` minus the private and link-local ranges, which the allowlist does not subtract while that rule stands.

**So what is it for today?** Two things, neither of them enforcement. It renders an auditable statement of the destinations the agent is supposed to need, as an object you can diff and a reviewer can read. And it settles the field, the refusal rules and the reconcile behaviour now, so that narrowing the gateway policy later is a one-policy change rather than a new feature. If you were planning a capability-impact review before enabling this, you do not need one yet; [what it will cost](#what-it-will-cost-once-it-does-block-something) says when you will.

The complementary control, removing the identity rather than the route, is in place: neither the gateway's ServiceAccount nor the `<name>-shell` Pod's carries an `iam.gke.io/gcp-service-account` annotation, so neither has a Google service account to mint, whatever the CNI enforces.

### The other conditions, plainly

None of these is enforced by the operator. The broker always runs outside the agent Pod, so the field has no prerequisite to refuse.

1. **The cluster CNI must enforce NetworkPolicy, and the operator cannot tell whether it does.** An unenforced policy is accepted, stored, and returned by `kubectl get` exactly like an enforced one; there is no field, condition or event to read. GKE Autopilot and GKE Dataplane V2 always enforce. A GKE Standard cluster created without network policy gets a no-op.
2. **No other policy may widen it**, which is the point above and also applies to anything an administrator adds later. Nothing detects that.
3. **The allowlist has to stay complete**, and it deliberately is not — see [what it will cost](#what-it-will-cost-once-it-does-block-something). Every gap is pressure toward a broader rule.

### What a refusal does, and does not do

**Refused means not reconciled, not stopped.** On a new agent those are the same thing — no Deployment is created. On an agent that is already running, the existing Pods keep running exactly as they were, **with metadata access**, and every subsequent change to the resource is ignored while the operator retries every 30 seconds. The refusal protects you from believing you have the control; it does not take the workload down to make the point. `kubectl describe platformagent` is where you find out.

One refusal reason remains. `EgressAllowlistRefused` **still renders the policy**, minus the destinations it refused. The objection is to one value, not to the control, so the guardrail keeps being reconciled (delete it and the next pass puts it back) while the status stays `Degraded` until the spec is fixed.

### Turning it back off, which has an order

**Setting `egressPolicy: None` does not delete the policy.** The operator will not remove a guardrail it may not have created, so `<name>-sandbox-metadata-deny` stays in the namespace after the field goes off. On its own that is fail-closed and fine: the Pod it selects keeps a door shut that nothing is asking to open.

To remove it, two steps in order:

1. Set `egressPolicy: None`.
2. `kubectl -n NAMESPACE delete networkpolicy NAME-sandbox-metadata-deny`. This is safe only after step 1 — delete it while the field still says `Allowlist` and the next reconcile puts it straight back.

There is no ordering to get wrong beyond those two steps: the broker cannot come back into the agent Pod.

### Pre-enable checks

Two things to verify on the cluster, neither of which the operator can check for you:

- **Does the CNI enforce NetworkPolicy?** `gcloud container clusters describe CLUSTER --format='value(networkPolicy.enabled,networkConfig.datapathProvider)'`. Autopilot and Dataplane V2 always do. A GKE Standard cluster created without network policy gets a policy object that enforces nothing.
- **Does the cluster run NodeLocal DNSCache, and does DNS still resolve after enabling?** This one can take the agent down. NodeLocal DNSCache runs with `hostNetwork`, so on Cilium and Dataplane V2 its traffic carries a host or remote-node identity. Neither the `k8s-app: node-local-dns` Pod selector nor the `169.254.20.10/32` CIDR peer in the rendered rule is guaranteed to match that, because CIDR peers do not select node identities unless `policy-cidr-match-mode` includes `nodes`, which is off by default. Both peers work on an iptables dataplane, which is why both are rendered.
  - The rule also carries the resolved cluster DNS ClusterIP, for the dataplanes that match the Service VIP instead, and `169.254.169.254/32` for Cloud DNS for GKE.
  - If neither peer matches, DNS is blocked outright and every destination in the allowlist becomes unreachable, because they are all reached by name. Check with `kubectl -n kube-system get ds node-local-dns` first, and after enabling confirm resolution from the agent container before trusting the policy.

### What it will cost, once it does block something

**None of this happens today** — with the one exception above: an install running `spec.networkPolicy.enabled: false` on an enforcing CNI pays this whole bill the moment the flag goes on. Everywhere else, every destination below is one `<name>-gateway-netpol` still permits to the same Pod, so you can enable the flag and observe no behaviour change in either direction. This is the bill that falls due once the gateway policy is narrowed, and it is here so that the narrowing is not a surprise.

At that point the allowlist covers DNS, the broker, LiteLLM, the OTel collector, the Hindsight memory API and the A2A NATS pods. The DNS rule carries selector peers, the resolved cluster DNS ClusterIP, and the Cloud DNS resolver, the same ladder the gateway policy renders. Everything the agent container reaches on its own would go away:

- DuckDuckGo web search, which `deploy/shared/defaults/config.yaml` turns on for every profile (`web.backend: ddgs`), and the `browser` toolset on any profile that does not disable it (the Chat, Platform and Cluster Agents all do, through `agent.disabled_toolsets`);
- `github.com` reached directly from the sandbox — not the version-control verbs, which go through the broker;
- the metadata lookup in `cluster_agent_reconcile.py`, which is how that script finds the management project (`RECONCILE_PROJECT`, the old override, is pinned empty in the managed `.env`; a project other than the pod's belongs in `spec.scope.projects`). It fails soft after a five-second timeout and falls back to `gcloud config get-value project`, a broker call that is on the allowlist. So the cost is the timeout on each tick, provided the broker's configured project is the pod's own. A fallback answer that differs from the previous run's management project is treated as unresolved rather than as a changed management project.

Credentialed `gcloud` and `kubectl`, the version-control verbs, and the `gke` and `developer_knowledge` MCP servers would be unaffected either way: they call the broker, and the broker is on the list.

None of that would be accidental. A headless browser with unrestricted egress is the exfiltration path, so the capabilities this would remove are the same ones that make the control worth having. Weigh it as a trade rather than a regression, when it arrives.

### Restoring a destination

`spec.security.egressAllowlist.extraRules` takes NetworkPolicy egress rules verbatim. Two things to know:

- **NetworkPolicy matches addresses, never DNS names.** Restoring a hosted service means naming its published address ranges and keeping them current.
- **A rule whose `ipBlock` contains a metadata address is dropped, not narrowed.** That includes `0.0.0.0/0` with an `except` clause naming the metadata server — see below for why an `except` clause is not a block. To grant broad egress you have to carve the ranges around `169.254.169.252` and `169.254.169.254` yourself, in the spec, where a reviewer can see it.

`spec.security.egressAllowlist.controlPlaneCIDRs` is separate because there is no NetworkPolicy peer for "the Kubernetes API server". On GKE the control plane is not a Pod and not in the cluster, and the in-cluster `kubernetes` Service address is translated to it before policy is evaluated. Left empty the rule is absent and nothing in the agent Pod can reach the API, which matters to any sidecar or plugin you added that talks to it. Find the range with `gcloud container clusters describe CLUSTER --format='value(privateClusterConfig.masterIpv4CidrBlock,endpoint)'`.

### Why it is default-deny rather than "allow everything except the metadata server"

The obvious shape — one broad rule with the metadata address in an `except` clause — is what this repository shipped once before, and it is unsound twice over on GKE:

- **On GKE Dataplane V2 it is a near-total outage, not a permissive rule.** Google's documentation states that Pod traffic is never covered by an `ipBlock` rule, so a policy whose only peer is `0.0.0.0/0` permits no Pod-to-Pod traffic at all — not kube-dns, not LiteLLM, not the broker.
- **On an iptables dataplane the `except` clause names an address the policy never sees.** A request to `169.254.169.254:80` is translated to the node-local metadata server at `169.254.169.252:988` in NAT PREROUTING, before the filter rules run. This is [kubernetes/kubernetes#68078](https://github.com/kubernetes/kubernetes/issues/68078), open since 2018 and titled "Network policy not properly blocking GKE metadata IP".

Default-deny sidesteps both: it names Pods with selectors rather than CIDRs, and it does not have to predict which address the request was rewritten to, because no rule permits either address on a port the token can be minted over. For the same reason all three metadata addresses — `169.254.169.254`, `169.254.169.252` and the IPv6 `fd20:ce::254` — are refused in `extraRules`, on every port. The DNS rule's port-53 grant to `169.254.169.254` is the operator's alone; `extraRules` cannot widen it. `spec.networkPolicy.additionalEgress` is a separate matter — it appends to the gateway policy over the same Pod and is bounded by prefix width rather than by destination, so it can reach a metadata address. See [Security and IAM](/kube-agents/reference/security-and-iam/#change-control--safety).

It is also why this is one policy object and not two. There is no deny rule in NetworkPolicy, so a separate "everything except metadata" policy would not subtract the metadata server from an allowlist. It would add the internet to it.


## Troubleshooting

**Every brokered CLI reports `credential proxy unavailable`.** The `gcloud` command inside `<name>-shell` and session pods (plus `kubectl` on `AgentProfile` workers) is a wrapper that forwards to the broker Service (`kubectl` in `<name>-shell` and session pods talks directly to `<name>-kube-proxy`). When nothing is listening on the broker, wrapper calls fail the same way:

```text
credential proxy unavailable: [Errno 111] Connection refused
```

This is an availability problem rather than an authentication one — a rejected credential comes back as an HTTP error, not a refused connection. The broker is a Pod of its own, so the message means it has no ready endpoint. Check the endpoint first and the events second:

```bash
kubectl get endpoints -n kubeagents-system platform-agent-credential-proxy
kubectl describe pod -n kubeagents-system -l app=platform-agent-credential-proxy
kubectl logs -n kubeagents-system deploy/platform-agent-credential-proxy
```

If the endpoint is there and the broker is healthy, the sandbox Pod is the next place to look — the shims run there, over SSH from the gateway:

```bash
kubectl get pods -n kubeagents-system -l app=platform-agent-shell
kubectl logs -n kubeagents-system platform-agent-shell-0
```

**A proxied command prints `CREDENTIAL_PROXY_EXEC_URL ignored (…); commands go to the stateful broker`.** The sandbox has an exec-tier URL that the shim cannot use: it is not a valid `http://` URL, it has no host, its port is not a number from 0 to 65535, or it has a query or a fragment. The shim ignores it, and the command runs on the stateful broker as on an install without the exec tier. The operator sets this variable, so check the operator version and the sandbox's environment.

**A proxied command fails with `credential proxy error: the connection dropped after the request was sent …; the command may have run`.** The connection to the broker closed after the command was sent and before its answer came back, for example because the broker Pod restarted. The shim does not send the command again, because the broker may have run it. Check what the command changed before you run it again: a `kubectl get` is safe to repeat, but an `apply` or a `delete` may already have taken effect.

**A `401` from every proxied command** is the other half of the same path, and it is authentication rather than availability. The broker verifies an audience-bound projected token with a `TokenReview`, so a `401` means the token was absent, expired, minted for another audience, or presented by a ServiceAccount that is not in `CREDENTIAL_PROXY_ALLOWED_CALLERS`. The broker's log names the reason; the caller never gets it.

**A proxied command fails with `credential proxy error (HTTP 200): …; the command may have run`.** The broker answered that the command ran, but the shim could not use the answer. It was not JSON, not a JSON object, a field of it was missing or had the wrong type, or its exit code was outside -127 to 255. The line names which, and prints nothing of the answer. The shim does not send the command again. Check what the command changed, as for a dropped connection; if it repeats, look at what sits between the sandbox and the broker. A command that a signal ended is not this case: the shim prints its output and exits with 128 plus the signal's number, as a shell does (137 for `SIGKILL`).

**A proxied command fails with one of the admission messages:** `the credential proxy is at its limit of 8 concurrent commands …`, `the credential proxy is at its child memory budget (… MiB in use of … MiB: …) …`, `the credential proxy's admission queue is held by requests waiting for its child memory budget (…) …`, `the credential proxy keeps … of its … admissions for interactive work …`, `the credential proxy keeps one of its … admissions for background work …` or `the profile role is limited to … concurrent command(s) through the credential proxy (CREDENTIAL_PROXY_PROFILE_SLOTS) …`. The sandbox's wrappers retry these by themselves, as described below. The broker admits a bounded number of commands at once, and the rest of this entry says what bounds them.

The slot cap is `CREDENTIAL_PROXY_MAX_CONCURRENT_COMMANDS` (8 by default). Within that, the broker admits only as many as fit a memory budget it derives from its container's memory limit, because each command is a child process that the limit has to hold. A child is about 100 to 120 MiB for `gcloud`, or `kubectl` with its auth plugin. At the operator's default 2Gi limit the budget admits ten at once, so the slot cap of eight is what binds.

Each request has a class: profile workers' and the scope publisher's are background, and every other caller's are interactive. Background work holds at most the admitted count less two, in slots and in budget room, so on a pod that admits three or more, interactive commands always find two admissions. Interactive work holds at most the admitted count less one, so background work always finds one. Profile workers' calls together also hold at most `CREDENTIAL_PROXY_PROFILE_SLOTS` (4 by default, never more than the background share), and one past that is refused at once.

Inside a class requests are admitted in arrival order, and interactive requests go ahead of queued background ones. A forge credential refresh, which takes no slot, also passes commands waiting only for a slot when it fits the budget. A request still waiting after a minute is refused with a `503` rather than run. Long-running brokered commands hold their admission for as long as they run. At the defaults seven of them from interactive callers hold everything interactive work may take, and an eighth waits for one to finish.

The broker's log shows the queueing (`request waited … for a slot`, `… for memory budget`, or `… for the background share` and `… for the interactive share`) and the refusal (`command queued too long`, or `… credential refresh queued too long` for a refresh), each followed by the refusal's text, which the refresh client also reports after the HTTP code. A refresh refused on the refresh lock says `… waited 60s for another refresh to finish`, and one that stepped aside for a vcs request's refresh says so with the time it spent. The broker's startup line says how many requests the budget admits.

The broker CLI wrappers (`gcloud`, plus `kubectl` on `AgentProfile` workers) retry a refusal at the slot cap, the memory budget, a class share or the profile share by themselves, up to four more times. Each retry follows a jittered wait of about 2, 4, 8 and 16 seconds at most (or a `Retry-After` the reply carries, held between 2 and 30 seconds) and prints one stderr line. A refusal at the slot cap, the memory budget or a class share comes after a 60-second queue, so the wrappers stop after about two minutes rather than outlive the terminal tool's 180-second limit.

The version-control skill's broker calls retry on the same schedule, but only a refusal the broker marks as given before it admitted the request, when nothing has run. A refusal from the forge itself, its rate limit among them, is never retried.

A command still refused when the retries run out fails with `credential proxy throttled: gave up after … attempts`; run it again later. The per-role caps (`the session role is limited to …`, and the scope publisher's) are not retried, because they are the caller's own limit; wait for one of its commands to finish.

The budget follows the container's memory limit, which `spec.deployment.credentialProxy.resources` moves. A limit under 544Mi, at which the budget would admit fewer than two requests at once, turns the budget off: the broker logs a WARNING at startup naming the limit it read and admits by the slot cap alone. On GKE Autopilot without bursting a container's limit equals its memory request. There the proxy's limit is the operator's Autopilot request, 2Gi, so the budget admits the same ten, held to eight by the slot cap; a `requests.memory` override under 544Mi turns it off there.

How often commands queue, for how long and behind which bound, and how many are refused, are series on the broker's metrics listener. `kubeagents_credential_proxy_admission_wait_seconds`, `kubeagents_credential_proxy_admission_refusals_total`, and the slot and budget gauges beside them ([Observability](/kube-agents/concepts/observability/) names them) are where to read the queue before reaching for the log.

**A proxied command fails with `the credential proxy is at its hard resource watermark (memory=… tmp=…) and is admitting interactive sessions only …`, and the broker answered `429` with `Retry-After`.** Beside the budget above, the broker reads what its container holds now: on every admission, the cgroup's working set (usage less inactive file cache) against its limit. Every 30 seconds it sums its state and `/tmp` volumes against the caps in `CREDENTIAL_PROXY_STATE_LIMIT_BYTES` and `CREDENTIAL_PROXY_TMP_LIMIT_BYTES`: each volume's sizeLimit, or its share of an ephemeral-storage limit set under the two together. From 75% of memory or 70% of a volume (`CREDENTIAL_PROXY_MEM_SOFT_PCT`, `CREDENTIAL_PROXY_DISK_SOFT_PCT`) it runs one command at a time and frees idle scratch. From 85% or 80% (`CREDENTIAL_PROXY_MEM_HARD_PCT`, `CREDENTIAL_PROXY_DISK_HARD_PCT`) it refuses background callers at once with `429 CREDENTIAL_PROXY_RESOURCE_PRESSURE`, `Retry-After` (5 to 30 seconds) and `retry_after` in the body.

One slot stays open to chat session pods up to 92% memory or 90% disk, beside the one command the clamp lets background work run. The class is the caller's authenticated role; nothing a command sends changes it. The refusal's text names the interval (`retry in 17 s`); the sandbox's wrappers wait it out and retry, as for the `503` above. The log shows the crossing (`resource watermark normal -> hard (memory=86% …)`), the relief (`resource watermark relief: …`) and each refusal (`command refused under resource pressure`). `kubeagents_credential_proxy_resource_watermark_ratio` carries each resource's fill, and the refusals counter counts these under `bound="pressure"`. A gate that trips at rest means the volumes or the memory limit are undersized for the fleet. Raise `spec.deployment.credentialProxy.resources` (a larger ephemeral-storage limit widens the state volume), or set the percentages through `spec.deployment.env`.

**A proxied command fails with `BROKER_LOOP_BREAKER: identical command failed or was blocked 5 consecutive times in this session; stop retrying this command and report the refusal/error.`** The broker CLI wrappers (`gcloud`, plus `kubectl` on `AgentProfile` workers) send the run's key as the request's `sessionId`: a kanban card, a scheduled job's run, or a session pod's session. In the shell sandbox the first two come from the command's working directory; a chat turn sends no key and is not counted. When one keyed run sends the same command, on the same cluster, and it fails or is refused five times running, the sixth and every later one is refused without running. It counts as `blocked`, rule `session.loop-breaker`, printed as a policy block.

A different command still runs and is counted on its own, so a loop over two failing commands is refused each of them at its sixth call. The broker keeps a run's last 8 failing commands, and any success of the run clears the counts. `BROKER_SESSION_MAX_IDENTICAL_FAILURES` in `spec.deployment.env` moves the count; `0` turns it off.

A kanban card's key is the card id, so its streak carries into the card's next dispatch. A card re-dispatched after five failures of one command is refused that command until another of its commands succeeds, the broker restarts, or the card leaves the broker's last 1024 keys.

**A proxied command fails with `BROKER_SESSION_BUDGET_EXCEEDED: session exceeded 1500 tool invocations; summarize current findings and finish the turn.`** A keyed run of the shell or profile role sent more than `BROKER_SESSION_MAX_TOOL_CALLS` commands (1500 by default). A policy refusal counts as a command. A `busy` answer does not: the wrapper re-sends the command, and the retries are one invocation. A conversation is never held: a chat turn in the shell sandbox carries no key, and the session pod's role is exempt; the scope publisher, a script, sends none.

The refusal counts as `blocked` with rule `session.tool-budget`. Each replica counts alone, so N exec-tier replicas admit about N times the ceiling. A request without a `sessionId`, such as a collector run by hand, is never counted; one a card or scheduled run launches inherits the key. Raise the variable in `spec.deployment.env`, or set `0` to turn the ceiling off.

A scheduled run's key names one execution, so its count ends with the run. A kanban card's key is the card id, so the count spans every dispatch of the card on a replica. A card past the ceiling is refused on its next dispatch too, until the broker restarts or the card leaves the last 1024 keys.

**Cloud diagnostics inside the sandbox fail while the broker is down.** The `gcloud` wrapper is the only `gcloud` the sandbox has, so cloud commands inside `<name>-shell` return the same connection error (`kubectl` talks separately to `<name>-kube-proxy`). Test the broker's cloud identity from a throwaway Pod using the same ServiceAccount:

```bash
kubectl run wi-check -n kubeagents-system --rm -it --restart=Never \
  --image=google/cloud-sdk:slim \
  --overrides='{"spec":{"serviceAccountName":"kubeagents-platform-agent"}}' \
  -- gcloud auth print-access-token
```

**The credential-proxy container restarts and its log ends without an error.** Read the previous container's exit first:

```bash
kubectl get pod -n kubeagents-system -l app=platform-agent-credential-proxy \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[*].lastState.terminated}{"\n"}{end}'
```

`OOMKilled` with exit code 137 is the kernel killing the container for its memory limit. On cgroup v2 the kubelet arms the group kill, so one child over the limit takes the broker, Envoy and every command in flight with it, and the log stops mid-request. The broker's `memory high-water` and `memory limit reached` lines before the stop say what the container held and which process held it; `largest child so far` names the biggest child (the first such line is the startup command, `bootstrap`). The same figures are series on the metrics listener ([Observability](/kube-agents/concepts/observability/)).

A `kubectl` child in the hundreds of MiB is a listing of a large cluster. The tool builds the whole list before it prints. The image's `kubectl` held 432 MiB listing 4,000 pods as JSON and 1.3 GiB as YAML, where the budget charges 128 MiB per request for the child (176 MiB with its output allowance). Size `spec.deployment.credentialProxy.resources.limits.memory` to hold the largest listing the fleet produces for every command that runs at once (eight at the slot cap), or a `spec.deployment.sizingProfile` row that does. Add the 192 MiB reserve for the broker and Envoy. The 2Gi default holds eight requests of 176 MiB, not eight of 500 MiB.

Any other exit is named by the container's PID 1 as `start-services: … exited with status …` or `… was killed by signal …`, the line its PID 1 writes before the container ends. A stop the kubelet sent to the container (a rollout, an eviction, a drain) reads `… stopped by signal 15 …` instead.

**The broker exits during startup.** The credential runtime runs `CREDENTIAL_PROXY_BOOTSTRAP_COMMAND` before it begins serving, and a non-zero exit stops the container, so the Deployment never has a ready endpoint. The command's stdout and stderr go to the container's log. Bootstrap failures usually mean the Pod cannot reach the cluster or mint a token; see [Security & IAM](/kube-agents/reference/security-and-iam/) for the Workload Identity binding it depends on.

Another cause is a universe domain mismatch. The log then ends with `credential proxy failed to start`, and the record says that the universe domain in the broker's environment differs from the domain the metadata server reports. A broker that started before the metadata server answered ends later with `credential proxy stops serving` and the same text. Set `spec.harness.universeDomain` to the reported domain, or omit it.
