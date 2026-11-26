# PlatformAgent: Harness configuration

Part of [PlatformAgent CRD](../../site/src/content/docs/operator/platformagent-crd.md).

## `spec.harness`

Framework-level settings passed to Hermes. `clusterName`, `location`, and `projectId` are all
required — the API server rejects a `PlatformAgent` that omits any of them. The credential proxy
only renders its kubeconfig bootstrap (the `gcloud container clusters get-credentials` that gives
the agent a usable kubectl context) when it has the complete triple; with one missing, every
`kubectl` the agent runs resolves to `localhost:8080` instead of a cluster.

`universeDomain` names the Google Cloud API universe domain (`googleapis.com` in standard Google
Cloud, or a sovereign or partner domain in Google Cloud Dedicated). When omitted on GKE, the
operator reads `/computeMetadata/v1/universe/universe-domain` from the node metadata server and
records the result in `status.resolvedUniverseDomain` (`status.universeDomainSource: Discovered`).
When set explicitly (`status.universeDomainSource: Spec`), the operator checks the value against
the metadata server; a mismatch parks `phase: Degraded` (`UniverseDomainMismatch`) before workloads
render. On a Helm install (`platformAgent.harness.universeDomain`), setting the value fails
`helm upgrade` if the served `PlatformAgent` CRD predates `spec.harness.universeDomain`, and sets
`GOOGLE_CLOUD_UNIVERSE_DOMAIN` on chart-rendered `litellm` (`vertex_ai`) and `githubMinter` (plus
`githubMinter`'s `ISSUER_ALLOWLIST`) when non-default.

A value under `googleapis.com`, such as `mtls.googleapis.com`, names hosts of standard Google
Cloud and no other universe. The operator refuses it with `phase: Degraded`
(`UniverseDomainMismatch`) and a message that says what to set, and `helm upgrade` fails on it.
Set `googleapis.com` or omit the field.

[PlatformAgent fields → Spec](../../site/src/content/docs/operator/platformagent-fields.md#spec) lists every `spec.harness` field with its type, default and constraints. The sections below cover what each block does.

`dashboardEnabled` publishes port `9119` on the agent Service, but nothing answers there: `hermes
dashboard` binds `127.0.0.1`, so a request arriving over the pod network gets connection refused.
Reaching it means getting inside the pod's network namespace — `kubectl port-forward svc/<agent>
9119:9119` on an ordinary node pool, and
[`scripts/hermes-dashboard-tunnel.py`](https://github.com/gke-labs/kube-agents/blob/main/scripts/hermes-dashboard-tunnel.py)
on a GKE Sandbox (gVisor) one, where port-forward is set up in the host-side netns and cannot see
the sandbox's listener.

That script is canonical on the dashboard's access path and on why the loopback bind is deliberate.
The exec relay it uses to get inside the sandbox lives in
[`scripts/exec_tunnel.py`](https://github.com/gke-labs/kube-agents/blob/main/scripts/exec_tunnel.py),
shared with the E2E suite, which reaches the agent API the same way and for the same reason. The
container's readiness probe runs `curl` against loopback for the same reason a `tcpSocket` probe
cannot work here: kubelet dials the pod IP, and nothing is listening on it.

`sessionKVApiKeySecretRef` is optional in the API but not in practice, and the `503` above is the
milder half of what its absence costs. The `k8s-event-watcher` in the `agent-api-auth` sidecar
authenticates to that same server, treats an empty `SESSION_KV_API_KEY` as fatal, and exits on every
start — so no cluster events are watched at all, while the container stays Ready and the CR
`.status` says nothing. An installation upgraded from before the key existed is the case that lands
here; add the key to the agent Secret and restart the pod.

### `spec.harness.sessionWorker`

`type` names the harness the session pods' worker image runs. Absent is `claude-code`, which is also the only value the CRD accepts today. Leave it out for Claude Code.

The operator passes a set value to the gateway as `A2A_SESSION_HARNESS`, so an install without it keeps the gateway it had. Setting or removing a supported value rolls the A2A gateway once. The gateway passes it to each session pod it spawns as `A2A_HARNESS`.

If the CRD admits a value this operator or gateway doesn't know, as it can after a rollback that leaves the CRD newer, the gateway keeps serving and session pods run the default harness. That is said loudly. The PlatformAgent's `SessionHarness` condition is `False` with reason `SessionHarnessNotSupported`, a Warning event is written, and a gateway that receives such a value logs an error. The condition clears once the value is supported or removed. The gateway is shared by every conversation, so it falls back instead of stopping, unlike an AgentProfile with an unsupported type, which only loses its own pool.

The type is pod configuration only: no route, bus subject or permission depends on it. Every session pod also carries `A2A_HARNESS_UNISOLATED` set empty, so a worker image can't turn on the worker's isolation waiver through its own environment.

### `spec.harness.memory`

`provider` picks which long-term memory implementation the agents load. Two ship in this repository,
and the difference between them is the whole choice:

| Value                          | Fits                       | What it costs to run                                      | What it gives                                            |
| ------------------------------ | -------------------------- | --------------------------------------------------------- | -------------------------------------------------------- |
| `multiuser_memory` _(default)_ | small or personal installs | nothing — a per-user Markdown file inside the pod         | verbatim recall of everything, no ranking or search      |
| `kube_agents_memory`           | enterprise deployments     | a Hindsight API server and a Postgres database in-cluster | ranked recall, per-user and shared scopes, consolidation |
| `none`                         | —                          | nothing                                                   | no provider; Hermes' built-in store only                 |

The split is about how the store is read, not about how good it is. The file provider concatenates
everything into the system prompt on every turn, so it is bounded by the context window; Hindsight
retrieves only what a question needs, so its cost per turn barely moves as the store grows. A fleet
of a few clusters and a handful of people will not reach the bound, and paying for a database there
buys nothing.

Anything else is passed through to Hermes untouched, so its own external providers (`hindsight`,
`mem0`, `openviking`, …) work if you bring their configuration. `none` is this API's spelling of
Hermes' empty string, which cannot be expressed here: an absent field takes the CRD default.

Only a Hindsight-backed provider reaches the specialist profiles, because only that one can be made
read-only and scoped by tag. Under any other value the specialists get no provider at all and the
Planning Agent keeps the store to itself.

`memoryEnabled` and `userProfileEnabled` are a **different** mechanism — Hermes' built-in
`MEMORY.md` / `USER.md` files, which have no per-user scoping. Both providers above replace that
store rather than supplement it, so both run with `memoryEnabled: false`.

The installer's `MEMORY_ENABLED` variable is that same built-in store and nothing more; the install
copies it into this field unchanged. It is not a master switch — whether the agent remembers
anything is `provider`'s question, and `none` is how that answers no.

The install reads only the provider: the chart's `hindsight.*` values deploy the Hindsight store
when the provider is Hindsight-backed (`--memory=hindsight`), and nothing when it is
`multiuser_memory` or `none`. See
[`docs/designs/memory.md`](https://github.com/gke-labs/kube-agents/blob/main/docs/designs/memory.md).

### `spec.harness.eventWatcher`

The `k8s-event-watcher` runs in the gateway pod's `agent-api-auth` sidecar, streams warning events
from every managed cluster, and posts each surviving incident to the pod-local Session KV server,
which opens an autonomous triage session for it. `enabled: false` stops it from starting at all.
Its Prometheus metrics are served on that sidecar's port 9095 and scraped by the chart's `<name>-gateway-monitoring` `PodMonitoring` on every replica; the `chat_metrics` plugin's port 9097 on the `platform-agent` container has its own, `<name>-gateway-chat-monitoring`, which selects the pod carrying the leader label; see [Concepts → Observability](../../site/src/content/docs/concepts/observability.md).

```bash
kubectl patch platformagent platform-agent -n kubeagents-system --type merge \
  -p '{"spec":{"harness":{"eventWatcher":{"enabled":false}}}}'
```

The field has to exist in the installed CRD for that patch to mean anything, and
[Helm installs CRDs on first install but never upgrades them](https://github.com/gke-labs/kube-agents/blob/main/charts/kube-agents/README.md).
A chart-upgraded install therefore needs the CRDs applied first — worth doing ahead of the incident
rather than during it, since a client that does not send strict field validation gets the unknown
field pruned and an emergency stop that reports success and does nothing.

```bash
kubectl apply --server-side -f k8s-operator/config/crd/bases/
```

`--server-side` is not optional here. Client-side apply stores the whole object in the
`kubectl.kubernetes.io/last-applied-configuration` annotation, and this CRD is far past the 262144-byte
annotation cap, so a plain `kubectl apply` fails with `metadata.annotations: Too long` and leaves the
CRD unchanged. `make install` in `k8s-operator/` applies them the same way.

**This is an emergency stop, not a tuning knob.** It exists for the case where events arrive faster
than the agent can triage them — a fleet-wide rollout gone wrong, a node pool flapping — and the
cheapest way to get the agent back is to cut the inflow rather than chase the cards it has already
been handed. It is all-or-nothing across every watched cluster. To silence one noisy namespace,
cluster, reason or workload while the rest still alerts, use `alertExclude` below.

If the board is merely busy rather than swamped, [`tuning.maxInProgress`](#specharnesstuning) is the
knob for that — it throttles how many cards run at once without losing the events.

Three consequences before you press it:

- **It rolls the pod.** The value reaches the sidecar as an environment variable, so changing it
  rewrites the pod template. During a storm that restart is usually wanted anyway — it is also what
  ends the sessions already running.
- **It stops the inflow only.** Kanban cards and sessions created from events already delivered keep
  running and still have to be dealt with on the board. It reclaims nothing either: the watcher's
  kubeconfig, token projection, and mounts stay in place, and the sidecar keeps the memory request
  sized for the caches it is no longer running.
- **Nothing turns it back on.** An install left with the watcher off has no incident detection at
  all, and the container stays Ready throughout — the readiness probe covers the credential proxy,
  not the watcher. Two things say otherwise: a line in the sidecar log naming the consequence, and
  the `EventWatcher` condition on the CR ([`status`](../../site/src/content/docs/operator/platformagent-crd.md#status) below). Set `enabled: true`, or remove
  the field, to start watching again.

Unset means enabled. The watcher is how a fleet notices its own incidents, so an install that never
mentions the field — which is every install today — keeps watching, and only an explicit `false`
turns it off.

`alertExclude` is the narrow tool: a list of rules for events that open no incident — no alert, no
triage card, no share of the daily alert ceiling. Their clusters stay in scope, so the agent still
reads them when asked; [`spec.scope.exclude`](platformagent-scope-integrations.md#specscope) is what hides a cluster. Each rule sets one
or more of `cluster`, `namespace`, `reason`, `kind` and `name`, and matches an event when every part
it sets matches. `reason` and `kind` are matched without regard to case, and `reason` also matches
the family the watcher groups a reason in, so
`CrashLoopBackOff` covers kubelet's `BackOff` events for a restarting container. `name` takes a
trailing `*` as a prefix, since pod names carry generated suffixes.

```yaml
spec:
  harness:
    eventWatcher:
      alertExclude:
        - namespace: payments # every alert from this namespace, on every cluster
        - cluster: { clusterName: staging-a } # every alert from this cluster
        - reason: FailedScheduling
          cluster:
            projectId: my-project
            location: us-central1
            clusterName: batch
        - namespace: shop
          kind: Pod
          name: inventory-api-*
```

A change is in force within about two minutes, without a pod restart: the operator writes the list
to a ConfigMap, and the watcher reads it again every minute. If the agent image is older than the
operator, a change applies at the next pod restart.

What the rules hold back is counted in the watcher's
`k8s_event_watcher_events_filtered_total{gate="alert_excluded"}`, and the end-of-day recap says how
many events and workloads they held back and names the five noisiest workloads. While
the list is set, it replaces a `WATCHER_ALERT_EXCLUDE` entry in `spec.deployment.env`, and a move
between the two rolls the pod once. The chart
renders the list from `platformAgent.harness.eventWatcher.alertExclude`; a `helm upgrade` that
removes the last rule removes the whole `eventWatcher` block from the CR, `enabled: false` with it,
so set the emergency stop again after one.

### `spec.harness.driftDetector`

The `drift-detector` runs beside the watcher in the gateway pod's `agent-api-auth` sidecar. It pulls
GKE admin-activity audit records from a Pub/Sub subscription, drops every call that a person did not
make or that changed nothing, and posts what is left to the same pod-local Session KV server the
watcher posts to — so a change someone made to a cluster by hand arrives on the board as a card. The
control plane, CI, and every service account are dropped alike; on a busy cluster that is the
overwhelming majority of the stream.

A change on another cluster in the project that no readable Cluster Agent profile names is logged
in the sidecar and not reported, while the sidecar can read its profiles directory. The install's
scope ends at its profiles, so profile the cluster, exclude it under `spec.scope.exclude.clusters`,
or fix the profile the sidecar's log names. The management cluster is always reported, profile or
not, and a cluster the sidecar had already joined when it started stays reported after its
exclusion until the gateway pod restarts.

**Through `install.sh` it is on unless you turn it off; the field itself still defaults to
`false`.** The two layers differ on purpose — the field is what a hand-written CR or a Helm-only
install sets, and neither of those creates a subscription for the detector to read, so the API
default stays off and the installer is what turns it on.

It is not free either, and what it costs is GCP resources rather than cluster resources. The
subscription it reads comes with an audit log sink and a Pub/Sub topic, all three from the
`drift-pubsub` Terraform module, and the sink exports the admin-activity audit records of every GKE
cluster in the project. On an install with a declared [`spec.scope`](platformagent-scope-integrations.md#specscope), each project the
scope lists gets a sink of its own into the same topic, and a change on a cluster there is enriched
through that cluster's Cluster Agent profile and reported like one on the management cluster.

The
[`terraform/examples/full-install`](https://github.com/gke-labs/kube-agents/tree/main/terraform/examples/full-install)
composition instantiates the module when you set `enable_drift_pubsub = true`, and writes the field
below when you set `enable_drift_detector = true` alongside it. Asking for the second without the
first is refused by a precondition rather than applied.

If you installed with `install.sh`, one key covers both: `ENABLE_DRIFT_DETECTOR` in `install.env`
writes the two variables together, and it defaults to `true`, so an install that says nothing gets
the sink, topic, subscription and detector. To go without them, set `ENABLE_DRIFT_DETECTOR=false`
in `install.env`.

Put it in the file rather than relying on `install.sh --enable-drift-detector=false`: the run that
creates `install.env` records that flag into it, but `install.sh` never rewrites that key
afterwards, so on every later run the flag applies to the run you pass it to and is recorded
nowhere — the next run resolves the default and provisions the three resources again, and
`upgrade.sh` takes no such flag at all. The front doors regenerate `terraform.tfvars` on every run,
so a value written into that file by hand does not survive the next one either.

This reaches an install created before the key existed. Its `install.env` records no choice, so the
next `install.sh` or `upgrade.sh` run resolves the default and provisions the three resources —
`upgrade.sh --plan` shows them as additions before you apply.

An install that has neither provisioned the ingress nor applied the module by hand has nothing for
the detector to pull. Setting this field there anyway — which now takes a hand-edited CR or chart
value, not the composition — gives a process that retries a failing pull for the life of the pod
without ever reporting a change, and the pod stays Ready throughout, so an install you switched on
by mistake looks exactly like a fleet nobody has touched.

```yaml
spec:
  harness:
    driftDetector:
      enabled: true
```

Enabling is necessary and not sufficient. Outside the gateway the detector verifies the cluster name
it was given against the cluster its credentials actually reach and exits on a mismatch. Inside it,
where the metadata server is closed, that probe times out and the triple is taken on trust (see the
detector's README). So the operator starts it only when `projectId`, `location`, and `clusterName` are all set on `spec.harness` as well. The API
server already rejects a `PlatformAgent` that omits any of the three, so the case to watch for is one
present but empty — that stays off however `enabled` reads, and unlike the watcher, nothing
substitutes a placeholder name for it.

`projectId` has to be the project ID, not the project number. The detector matches it against the
project on each audit record, which is always the ID, so a value that is nothing but digits can
match nothing. The operator reports the detector as off rather than starting a sidecar that exits on
every launch. `ScopeUndeclared` names the project only in a form `spec.scope.projects` accepts: on
a number it reads the ID off the host cluster's own series, and otherwise it says nothing.
Everything else reading `spec.harness` accepts a number, so an install can be healthy in every
other respect and still be refused here.

`subscription` and `gitopsManagers` are the two knobs worth moving from a CR. Leave `subscription`
unset unless you renamed the one the module creates.

`gitopsManagers` is not what separates automation from people — the detector already does that by
principal, and a controller's writes never reach a card. It names the **field managers** your GitOps
controller writes under, as they appear in an object's `managedFields`: `argocd-controller`, `flux`,
whatever your own controller sets. That is a field-manager string, not a service-account email, and
the two are rarely the same.

Matching one changes what a card says rather than whether it exists. When the detector finds a
configured manager wrote the drifted fields after the change it is reporting, it marks the card as
possibly already reconciled and names the manager. Unset is supported and only loses that hint:
ownership is still read and reported, and you get the same cards without the annotation.

Nothing else about the detector is exposed here. Which principals count as human, and which calls
are dropped as failed or non-declarative, are compiled into the binary; what reaches it at all is
set by the Terraform module's log sinks, not by the CR.

### `spec.harness.stallWatch`

The controller stall watch is the `stall-watch` cron job on the Platform Agent's roster. Every 30
minutes it runs `stall_report.py` over the namespaces of each cluster that has a Cluster Agent
profile, and raises one alert for each namespace with a new stall
([autonomous watchdogs](../../site/src/content/docs/concepts/autonomous-watchdogs.md)). This block tunes what it
reads and when it alerts. Absent, the watch skips the system namespaces and annotated namespaces,
alerts on the first sweep that sees a stall, and scans its default list of kinds.

```yaml
spec:
  harness:
    stallWatch:
      excludeNamespaces: [load-test, payments-canary]
      minStallAgeMinutes: 30
      kinds: [deployments, statefulsets, gateways.gateway.networking.k8s.io]
```

`excludeNamespaces` names namespaces the watch never reads, on every cluster. Each item is an exact
namespace name; there is no wildcard. If a namespace has an open alert when you exclude it, the
watch completes the alert's card with a note that the namespace was excluded, and the chat line says
the same. Up to 100 names.

`minStallAgeMinutes` holds a new alert until at least one stall in the namespace has lasted that
long. A stall's age is the longer of two values: the age `stall_report.py` measures on the object
(from its condition, its last spec write, or its warning events), and the time since the watch first
saw the object stall. A spec write does not restart that second value, as long as the watch saw
the object stall on one of its last two sweeps.

A younger stall is not dropped: the watch keeps it in its ledger and checks it again on each
sweep, so the alert follows on the first sweep after the stall is old enough. An object that starts
to stall in a namespace with an open alert is added to that alert's card at once. The range is 0 to
1440; unset or `0` alerts on the first sweep that sees the stall.

`kinds` replaces the default list of resources the watch scans: Deployments, StatefulSets,
DaemonSets, Jobs, Gateway API Gateways and HTTPRoutes, cert-manager Certificates, and
`*.cnrm.cloud.google.com`, the Config Connector kinds. Write each item as kubectl names the
resource, in lower case: `deployments`, `gateways.gateway.networking.k8s.io`. An item of the
form `*.<suffix>` is a group wildcard for every namespaced kind whose API group ends in the
suffix. A list you set replaces the wildcard too: name `*.cnrm.cloud.google.com` in it to keep
the Config Connector kinds.

The single item `all` scans every namespaced kind the cluster serves, with one read per kind per
cluster, which is slow on a large fleet. The API server refuses `all` next to another
item, and refuses Secrets, ConfigMaps, Events, Endpoints, EndpointSlices, ControllerRevisions and
Leases, which the scan reports nothing from. Up to 20 items. A kind a cluster does not serve is
left out on that cluster.

The Config Connector wildcard is in the default list because a managed resource that Config
Connector cannot apply shows it in two places only. The controller does not crash and logs only on
the object. It records at most a Warning event there, which the event watcher forwards
([a day in the life](../../site/src/content/docs/overview/day-in-the-life.md) lists the reasons), and it sets the
object's own `Ready` condition. The `ConfigConnector` object's status reports the controller's
health, not the health of the resources it manages. `stall_report.py` reads the `Ready` condition
as a stale condition once it has been false for longer than the stall threshold, so a `SQLInstance`
stuck on `UpdateFailed` is a stall like a Deployment past its progress deadline, event or no event.

Two reasons are in progress, not stalled, at any age: `Updating` (a create or update under way) and
`Deleting`. `DependencyNotReady`, which lasts as long as the referenced resource's own create, is a
stall after 60 minutes rather than after the usual 15.

The add-on serves about three hundred kinds, so the watch does not read each one in each
namespace. On each cluster that serves them, it discovers once which kinds have objects and in
which namespaces, with one `kubectl get` over every namespace for each batch of 10 kinds. It
keeps the result in its ledger and reads in a namespace only the kinds it found there, 20 per
sweep.

A namespace with more is read in turns, the next 20 on the next sweep, so every kind is
read within a few sweeps. The ledger says which kinds wait. Objects in the system namespaces, in
`excludeNamespaces` and in exempt namespaces do not reach the record.

It discovers again after 6 hours, or after 1 hour when a batch failed, on at most 2
clusters per sweep, so a fleet's refreshes spread out.

A kind that gained its first object between two discoveries is read from the next one. A kind a
discovery could not read, or one the cluster started to serve since the last discovery, holds its
ledger rows as unread rather than clearing them. A cluster that serves no Config Connector kind
runs no discovery.

Separate from this block, the annotation `kubeagents.x-k8s.io/stall-watch: exempt` opts out
without a CR change. On a namespace, the watch does not read the namespace, as if
`excludeNamespaces` named it. On an object that `stall_report.py` reports (a Deployment, a Gateway,
or any other kind the watch scans), the watch leaves that object's rows out of its alerts. If that
leaves an open alert with no stall, the watch completes the alert's card with a note that names the
annotation. The annotation is checked on each object alone: an exempt Deployment does not exempt the Gateway or the
HTTPRoute in front of it. A Cluster Agent that runs the `gke-stall-detection` skill by hand still
reports an exempt object.

The operator delivers the three values through the agent's managed `.env` (see
[How config reaches each profile](platformagent-profile-config.md)), so a change rolls the agent
pod, and the agent cannot override a value from its own `.env`.

The chart sets this block from `platformAgent.harness.stallWatch`. On an install made with
`install.sh`, put the block in the `TF_VAR_extra_helm_values` line in `install.env`, which a
full-mode `install.sh` or `upgrade.sh` run applies; a `helm upgrade --set` value is dropped by the
next full-mode run, and the watch then goes back to its defaults. `install.env` holds one such
line, so if it already has a `platformAgent` key, put `harness={stallWatch={...}}` inside that key
([Operator settings](../../site/src/content/docs/install/quickstart-gke.mdx#operator-settings) says how the line
works):

```bash
TF_VAR_extra_helm_values='{platformAgent={harness={stallWatch={excludeNamespaces=["load-test"],minStallAgeMinutes=30}}}}'
```

On a hand-driven Terraform apply, set `extra_helm_values` in `terraform.tfvars` instead; on a bare
Helm install, set the block in your values file.

### `spec.harness.tuning`

Execution limits per agent persona, where `<persona>` is one of `default` (the Planning Agent front
door), `platform` (the Platform Agent), or `cluster` (**every** Cluster Agent), plus the board-wide
`maxInProgress` and the dispatcher's memory `admission`, the session-pod cap `maxSessions`, the gateway's
`defaultRoute`, the session pods' idle times `sessionIdleMinutes` and `dmSessionIdleMinutes`, and the AgentProfile knobs under
`profiles` (the ceiling and its child reserve, `warmReplicas`, and the dispatcher's intervals; see [AgentProfile](../../site/src/content/docs/operator/agentprofile-crd.md)). Unset,
`maxSessions` renders `10`, `defaultRoute` renders `platform`, the gateway reaps an idle session pod after 30 minutes (5 for a DM conversation with one message so far), `profiles.ceiling` follows `maxInProgress` (`6` unless set) and `profiles.warmReplicas` `1`.

`defaultRoute` is where the A2A gateway sends a plain conversation's first message: `platform` to the
Platform Agent, `session` to a session pod of the conversation's own. Unset means `platform`, today's
behaviour; making `session` the default is a later change, gated on evidence. The operator renders it
as `A2A_DEFAULT_ADDRESSEE` on the gateway and on the Platform Agent container, which the hermes-bridge
sidecar copies. Changing it rolls the gateway and the Platform Agent pod. On either route the Platform
Agent stays reachable by handle and `delegate:` opens a session pod.

`defaultRoute: session` opts an install into the session route. It widens the `TASKS` consumer
budget, because each session counts the replays of its task too (7 consumers rather than 3). A stream
cannot be widened once it exists, so on the session route the operator reads `TASKS`' live
`max_consumers` from the bus's monitoring endpoint and fits the session cap to it.
`status.effectiveSessionCap` is `maxSessions`, or the sessions the stream has room for when that is
fewer, and the `SessionCapFitted` condition and a Warning event say so.

The gateway's cap, the session quota and the provision Job's check follow the fitted cap; a new
`TASKS` is still created wide enough for `maxSessions`. A stream with no room for one session sends
plain conversations to `platform`. The cap stays fitted until `TASKS` is widened. On a one-server bus,
setting `busReplicas` to 3 widens it and keeps its history. On any bus, a new value on the
`kubeagents.x-k8s.io/bus-reshape` annotation recreates it at the rendered width, keeping its messages
([Recreating TASKS wider](../../site/src/content/docs/operator/platformagent-crd.md#recreating-tasks-wider)). On an existing install, until the operator has read the width once, the
provision Job waits; a new install starts at `maxSessions`. On `platform` none of this runs.

#### The session pods' cluster view

On the session route, session pods get the read-only cluster view by default: `kubectl` through
`<name>-kube-proxy` and read-only `gcloud` through the credential broker's `session` role ([Security
and IAM](security-rbac.md#each-a2a-session-pod-is-its-own-bus-identity)).
The view follows the route the operator resolved, so an install held on `platform` (no room for a
session, or a CRD that prunes the cap) gets none. The operator's `A2A_SESSION_CLUSTER_VIEW` overrides
it, set as [Operator settings](../../site/src/content/docs/install/quickstart-gke.mdx#operator-settings) describes:
`"true"` turns the view on on any route, and `"false"` turns it off on the session route too. Unset or empty, it follows the route, and any other value is off. The flag doesn't change the route itself.

Whoever can set `spec.harness.tuning.defaultRoute` on the PlatformAgent turns the view on with it; whoever runs the operator can turn it off for every install with `"false"`. On a `fleet`-tier install, a session
pod's cluster-wide `kubectl` lists need more than the default session memory limit ([What each pod
needs](../../site/src/content/docs/deploy/fleet-sizing.md#what-each-pod-needs)).

**The per-run limits are opt-in.** The operator pins nothing of its own there: what a fleet needs
depends on its model quota and on what its agents actually do, so a deployment doing short
interactive work should not inherit limits raised for long-running batch work. Unset therefore means
whatever the profile's own `config.yaml` carries, and the `default` and `cluster` configs set no
execution limit of their own — Hermes' defaults apply there: 3 retries, and for the turn budget two
different defaults on the pinned release: a gateway turn runs with no cap, and a kanban worker,
which is a `hermes chat` process, with the chat CLI's own 500.

The `platform` profile is the exception: the image ships `agent.max_turns: 150` in
`agents/platform/config.yaml`, the budget its kanban workers run under, and the fleet audits
([Cron jobs](../../site/src/content/docs/reference/cron-jobs.md#the-shipping-jobs)) carry their own `max_turns: 250`
on their roster entries, which the scheduler reads ahead of the profile value;
[Config reference](../../site/src/content/docs/reference/config.md#agent) is canonical for why.

Setting `tuning.platform.maxTurns` here still wins over the profile value — the overlay is merged
after the image force-sync — and a roster entry's own `max_turns` only ever raises its job above
whichever of the two is in force, never lowers it, so a value above 250 raises the audits too;
removing it restores the image's value rather than Hermes'.

**`maxInProgress` is not.** Unset renders `6`, because the untuned case is the one that cannot
absorb the alternative — see [Why dispatch is capped by default](#why-dispatch-is-capped-by-default)
below. Set it on the CR to raise or lower that. Either way the value is pinned in the managed scope
at `/etc/hermes`, so it applies over whatever the agent's own `config.yaml` says, and removing the
field puts the default back.

**`admission` is pinned the same way.** On every tick the dispatcher reads `kanban.admission` from
the managed scope and counts the container's working set, its cgroup memory usage less the inactive
file cache, against a budget. Past it the dispatcher refuses a card rather than spawn a worker: the
card is blocked with kind `capacity` and a reason that names the figures, so the thread that filed
it is told it is throttled. The budget is the request, not the limit, because the kubelet evicts the
pod under node pressure once its working set passes the request. Under GKE Sandbox the limit the container can read is the sandbox's, not the
cgroup's, so Hermes' own `/proc/meminfo` guard never fires there.

Unset, `memoryBudgetMiB` is the agent container's memory request in MiB (`spec.deployment.resources`,
`4096` at the default `4Gi`), so raising the request raises the budget. `workerRssCapMiB` (`1536`)
stops a running worker whose process tree passes it and blocks its card the same way.
`queueBoundSeconds` (`600`) refuses a ready card that memory pressure or a full board has held for
that long. `failClosed` (`true`) makes a tick that cannot read the memory counters spawn nothing.
Effective `memoryBudgetMiB` must be at least `workerRssCapMiB` regardless of `failClosed`. Helm
renders setting `platformAgent.harness.tuning.admission` refuse a smaller budget against the
`4096` / `1536` defaults, while webhook admission (where enabled) and operator `Degraded`
(`InvalidKanbanAdmission`) evaluate both `tuning.admission` and `spec.deployment.resources`.
[PlatformAgent fields](../../site/src/content/docs/operator/platformagent-fields.md) lists the bounds.

```yaml
spec:
  harness:
    tuning:
      maxInProgress: 8 # board-wide; raises the operator's default of 6
      admission:
        memoryBudgetMiB: 3072 # the dispatcher's budget; defaults to the container's memory request
      platform:
        apiMaxRetries: 8
        maxTurns: 200
      cluster:
        apiMaxRetries: 8
        maxTurns: 150
```

Raised limits belong with the workload that needs them, not with the platform. A long-running,
quota-hungry agent plugin should ship its own tuning — as a patch its installer applies — so that a
deployment without it stays on Hermes defaults, and installing the plugin brings the limits it
requires along with it.

The GKE Stockout Investigator is the worked example:
[`agentplugins/gke-stockout-investigator/tuning.yaml`](https://github.com/gke-labs/kube-agents/blob/main/agentplugins/gke-stockout-investigator/tuning.yaml)
records the reasoning behind each number, and its `install.sh` applies it.

The keys are personas rather than profile names because the profiles are not all known when the CR
is written: Cluster Agent profiles are scaffolded at runtime, one per managed cluster, with
generated names like `cluster-<project>-<cluster>-<region>`. `cluster` therefore applies to all of
them at once — including ones onboarded after the pod last started, which pick the limits up as they
are scaffolded.

Both limits matter because they fail the same way, and it is not an obvious way. A run that
exhausts either stops mid-task without ever calling a terminal kanban tool. The card is charged a
`timed_out` failure whose error text names how the turn ended — `Iteration budget exhausted (N/M)`
for `maxTurns`, `turn_exit_reason=all_retries_exhausted_no_response` for an `apiMaxRetries`
exhaustion that ends with no response — and retrying re-runs into the same wall, so read that text
and the upstream error rate before suspecting the worker.

A `maxTurns` exhaustion keeps what the run found. At the cap the runtime asks the model for a
closing summary and discards any tool call in the answer, and the worker saves the summary as the
run's hand-off. `hermes kanban show <id>` prints it as the card's latest summary, the card carries
it as a comment that names the budget used, and the next attempt reads it in its prompt under the
prior attempt. The card's own `result` stays empty, as for every run that does not complete.

The text is the model's, cut on a word at 4000 characters. When the summary call fails, the
worker's last written answer is saved instead, and the comment says so. A summary that names a
GitHub pull request URL is saved on the run only, with no comment: the dispatcher holds a card whose
recent comments name one, and the retry is what the hand-off is for.

One `apiMaxRetries` exhaustion is handled differently: when the retries were spent on provider rate
limits (429s), the worker blocks its own card instead, kind `transient`, with the provider's error
text as the reason; `kanban_unblock` it once the quota window has passed. A second rate-limit block
after an unblock sends the card to `triage`.

A turn that fails outright, because the provider refused the call (an HTTP 401, a billing wall, a
safety block) or the last retry ended on an error, is recorded by the worker itself. So is a worker
whose `chat()` returns before any turn runs, such as on agent init or runtime credential failure.

The error Hermes reported (or the no-turn notice) goes on the card as a comment. The run is charged
as `crashed` and counted, and the card goes back to `ready` until it reaches its retry limit. The
chat thread shows the generic "worker crashed" line for it, so read the card's comment for the cause.
The charge's own error text names no provider error, so the dispatcher retries the card rather than
parking it as an auth or quota failure.

Goal-mode cards, which the dispatcher runs as a loop of turns judged against the card's goal, get
none of this: their failures exit through the dispatcher's reaper as before, with exit 1, or exit 75
and a `rate_limited` run for a rate limit or a billing wall. A run that stops without a terminal
call and reaches the dispatcher unexplained surfaces instead as a **protocol violation**, which
describes the symptom and hides the cause; the image narrows that window in
[`deploy/docker/patches/kanban_guardrail_exit.py`](https://github.com/gke-labs/kube-agents/blob/main/deploy/docker/patches/kanban_guardrail_exit.py).

Sizing notes: `maxTurns` is consumed mostly by repository exploration, so scale it against how much
the agent has to read rather than how complex the request is. `apiMaxRetries` exists because
Hermes' default of `3` assumes an interactive session where a human retries; a background worker
has nobody to retry it, so a transient burst of upstream 503s ends the run. A 429 retry
waits out the delay Google states in the error body (up to 600 s) rather than a few seconds, so a
burst shorter than that window is survived; see
[`deploy/docker/patches/rate_limit_retry_delay.py`](https://github.com/gke-labs/kube-agents/blob/main/deploy/docker/patches/rate_limit_retry_delay.py).

A 429 that states no delay at all, as a shared-quota 429 does, waits a jittered 30 to 60 s per
retry instead, so the three retries outlast a quota minute; the retry count does not change. See
[`deploy/docker/patches/rate_limit_backoff_floor.py`](https://github.com/gke-labs/kube-agents/blob/main/deploy/docker/patches/rate_limit_backoff_floor.py).

Raising `maxTurns` interacts with `maxInProgress`: a worker doing the work holds its slot for the
whole task and there are only `maxInProgress` of them, so raising one is a reason to reconsider the
other. A coordinator waiting on work it fanned out is the exception — see
[why dispatch is capped](#why-dispatch-is-capped-by-default).

#### Why dispatch is capped by default

A kanban worker is not a coroutine. It is a full `hermes … kanban task` process — a few hundred MiB
resident once its MCP proxies are up, and alive for as long as the task takes, which for an incident
triage is minutes rather than seconds. Uncapped, the dispatcher starts one per queued card, and a
burst of cluster events queues them faster than they retire.

What follows is invisible in the places you would look. The cgroup OOM killer takes a worker, not
PID 1, so there is no container restart and no Kubernetes event; the pod stays `Running` and the
only trace is `pid not alive` in the kanban ledger. The dispatcher's retry budget is 1, so the card
is stranded rather than re-dispatched, and the work it stood for is never done — a triage report
that never arrives, with nothing anywhere reporting a failure.

`6` is a floor for a deployment that has not measured itself, not a recommendation. It assumes the
operator's default 8Gi memory limit on the agent container, and the cost of being wrong is
asymmetric: too low delays a delegated task, too high loses it silently. An install that lowered the
agent's memory limit through `spec.deployment.resources` (which replaces the defaults as a block)
should set `maxInProgress` to fit: about 430 MiB per worker over the 1.8 GiB the pod holds idle, so
a 4Gi limit fits about five. Raise it once you know your worker footprint and your model quota —
that quota is the other shared resource, and for most deployments it binds before memory does.

At the operator's defaults the budget and this cap are close. The budget is the container's memory
request, 4Gi unless `spec.deployment.resources` changes it, and it counts the agent container alone.
A tick admits one new worker per 512 MiB of headroom under the budget: from an idle set of about
800 MiB that is six, from the 1.5 GiB a gateway idles at, five. Six workers at
430 MiB add about 2.6 GiB, inside the request from the smaller idle set and one worker short from
the larger. To admit more, raise the request, not the limit: under node pressure the kubelet evicts
the pod once its working set passes the request ([`admission`](#specharnesstuning)).

[`docs/designs/safe-throttling.md`](https://github.com/gke-labs/kube-agents/blob/main/docs/designs/safe-throttling.md)
is the design for admission by memory beside this count: a pressure guard on the container's own
memory counters, a resident cap per worker, and a `capacity` refusal that names the alternatives.

The cap comes from the operator, not from the image or the agent's own `config.yaml`. The operator
pins `kanban.max_in_progress` in the managed scope at `/etc/hermes`: the CR's value, or `6` when it
says nothing. Hermes applies that file over the agent's config on every load, so a value an existing
volume was first seeded with, a removed override, or an edit the agent made to its own file has no
effect.

An install upgraded onto an operator that changes the default takes the new number on its first
reconcile and the pod roll that follows. The dispatcher logs
`kanban dispatcher: max_in_progress=<n>` at startup (Hermes' `_positive_int_setting` in
`gateway/kanban_watchers_common.py`, which logs each configured kanban cap as it reads it). The
`max_in_progress` line in `agents/chat/config.yaml` applies only to an image run without the
operator.

One slot is guaranteed to each class of card. A card is classed when an agent files it with
`kanban_create`: one filed from an event-triage or cron-relay session is background, and one filed
in a chat turn or through the inject and A2A doors is a user card. A card filed by hand, with
`hermes kanban create` or from the dashboard, never passes through that step and is background
unless it is given priority 100 or more (`--priority 100`); the dashboard can change a card's
priority afterwards. So are the children Hermes' auto-decompose files for a card created with
`triage: true`: they are written at priority 0, so a user card filed that way runs its decomposed
work as background.

At a cap of 2 or more, background cards may hold every slot but one, so a question asked in chat
starts at once even while triage is running, and user cards may hold every slot but one, so a
door's fan-out cannot silence alerts. The slots between go to whoever is first, and user cards
sort first. At the default of 6 that is one slot for each class and four shared. The price is that
a burst of alerts drains more slowly than it would with every slot open to it, and a burst of user
work likewise.

At a cap of 2 each class gets exactly one. At a cap of 1 nothing is held: a user card still goes
ahead of waiting triage, but it waits for the running card to finish. A top-level user card that
waits, because every slot is busy or the only free one is triage's, gets one line in its thread:
`⏳ Queued: the system is busy. Your request will start when a worker frees up.` A card filed as
part of a request already running (a worker's child, or a card with a parent link) waits without
one.

The wait is bounded. A card that memory pressure or a full board has held past
`tuning.admission.queueBoundSeconds` (600 s by default) is blocked with kind `capacity`. The queued
line settles as stopped, and the Planning Agent answers the thread with the reason and the
alternatives ([`admission`](#specharnesstuning)).

A full board is logged as what it is. When every slot is busy for six ticks in a row the gateway
logs, at most every five minutes:

```text
kanban dispatcher saturated: 6/6 worker slots busy (5 background, 1 user: t_ab12 @cluster-prod 14m [k8s-evt-], t_cd34 @cluster-prod 9m [k8s-evt-]); 1 user card(s) and 2 background card(s) waiting
```

The card list is shortened here. The real line names up to five cards that hold slots, oldest first
within each board, boards in turn; a coordinator only waiting on its own children is left out,
because it is not counted as running.
The line gets `; N background card(s) held back because one slot is reserved for user cards` or
`; N user card(s) held back because one slot is reserved for background triage` added when a held
slot is what stopped them. When the only free slot is the one held for the other class, the line
starts `kanban dispatcher holding background cards:` or `kanban dispatcher holding user cards:`
instead. That line is load, not a fault. The older
`kanban dispatcher stuck: … Check profile health` warning now means what it says: slots were free
and still nothing started.

That warning waits for six ticks, so a short saturation would leave no trace. Each user card that
waits therefore also writes one `kanban priority: <id> queued …` line to the gateway log on the tick
it is queued. The line says how many user cards are ahead of it, names the cards that held the
slots and ends with the same held-back clause, so the wait is readable back afterwards. The card's
`queued` event on the board carries the holders' ids as well.

The arithmetic behind `6`:

- **Gateway memory.** One worker measured about 430 MiB on a live install: `hermes chat` 207 MiB,
  two Node MCP proxies about 100 MiB each, a supervisor and an ssh. Six of them are about 2.6 GiB
  over the gateway's 1.8 GiB idle set, about 4.4 GiB under the container's 8Gi limit. A coordinator
  waiting on its own children gives its slot back but stays resident, so the process count can sit
  above six; the 8Gi limit leaves room for about fourteen workers at that size. That is the limit's
  room; the room a default install uses is the request's, because the admission budget follows the
  request (above).
- **Credential proxy.** Every worker's `kubectl` and `gcloud` runs through the proxy, which admits a
  request only when its children fit the proxy's memory limit: 176 MiB per request after a 192 MiB
  reserve for the broker and Envoy. At its default 2Gi limit that is 10 at once
  (`credentialProxyAdmittedRequests` in
  `k8s-operator/internal/controller/credential_proxy_manifests.go`), held to 8 by its slot cap. At
  the old 1Gi it was 4.

  The 8 slots are shared. The stall watch runs four commands at a time for the whole of its tick,
  the listing and then the cluster reads, up to 25 minutes of every 30; the cluster-agent
  reconcile lists four projects at a time. With neither running, all 8 are free for the six
  workers; while one runs, 4 are; while both run at once, none, and a worker command waits up to
  60 s for a slot and is then refused busy.

- **Model quota.** Per-install model rate limits are not measured. A small quota may see 429s at 6;
  if worker logs show them, lower `maxInProgress`.

If you raise `maxInProgress`, check your model quota, and know where the credential proxy stops it.
The proxy's default 2Gi already admits more than its slot cap of 8, so up to about eight workers'
worth of commands fit, fewer while the stall watch's tick or a listing runs. Past that the slot cap binds, and the operator
owns it. No CR field moves it, so raising the proxy's memory in
`spec.deployment.credentialProxy.resources` does not help, and a command beyond eight waits up to
60 s for a slot and is then refused busy. Keep that limit at 2Gi or more, because below it the
memory budget binds first.

The cap counts running cards, not resident processes, and one case makes those differ: a coordinator
waiting on work it fanned out is discounted, or it would hold the slot its own children need
([`kanban_scheduling.py`](https://github.com/gke-labs/kube-agents/blob/main/deploy/docker/patches/kanban_scheduling.py)).
Peak memory is therefore the cap plus however many coordinators are waiting, held down by the
dispatcher's memory admission ([`tuning.admission`](#specharnesstuning)) rather than by this number.

### `spec.harness.experimental`

Opt-in switches with no compatibility promise. A field here may change meaning, change its default,
or be removed outright in any release; an install that depends on one is expected to re-check it at
every upgrade. Fields live here while the question they answer is still open — once it is settled
the switch either graduates into a supported block or goes away.

#### `platformFrontDoor`

Makes the **Platform Agent** the profile the Hermes gateway runs as, so a chat message is handled by
the agent that has the tools instead of arriving at the Planning Agent, which delegates through the
router MCP server and the kanban board.

```bash
kubectl patch platformagent platform-agent -n kubeagents-system --type merge \
  -p '{"spec":{"harness":{"experimental":{"platformFrontDoor":true}}}}'
```

Three things change while it is on:

- The gateway container runs `hermes --profile platform gateway run`.
- `profile-platform.overlay.yaml` gains the three profile-shaped things only the `default` profile
  carried before: the toolsets each chat platform key resolves, the ingress plugins, and the
  `kanban` block. The adapters themselves are not copied — the managed scope at `/etc/hermes` is
  machine-global, so `platforms.*`, `display.platforms`, the board's worker cap
  ([`tuning.maxInProgress`](#specharnesstuning)) and the dispatcher's memory admission
  ([`tuning.admission`](#specharnesstuning)) already land on this profile. The rest of `kanban`
  does have to follow the gateway, because the dispatcher and the notifier run in the gateway
  process and read their settings from its own home. The board itself does not move — Hermes
  anchors `kanban.db` at the shared root rather than the active profile, deliberately, so the
  dispatcher/worker handoff survives — so cards in flight are unaffected by the flip.
- The entrypoint stops force-syncing `profiles/platform/config.yaml` from the image and back-fills
  it instead, on the same terms as the `default` profile's own file (except the remote MCP server
  entries and the `plugins.enabled` list, which follow the image), so `/sethome` and `monitoring.install_id` survive a restart — see
  [How config reaches each profile](platformagent-profile-config.md).

Setting the field back to `false` reverses all three. The overlay records what it applied, so the
keys are unapplied rather than left behind, and the force-sync resumes.

**What it costs.** The Planning Agent's lockdown is its whole reason for existing: a front door
with three toolsets, so an inbound message cannot reach the full Platform Agent tool surface before a
card and a worker turn have framed it. With this on, an inbound message reaches that surface
directly. The lockdown is deliberately **not** copied onto the platform profile — copying it would
leave the Platform Agent unable to do the work the flag exists to let it do.

**Known limits.**

- One gateway means one profile, so this is not additive. While it is on, the Planning Agent persona sees
  no chat at all and the router MCP path is unused. Kanban delegation is not: the front door
  keeps `dispatch_in_gateway`, so it can still hand a card to a spawned worker — it just does so as
  the agent that could also have done the work itself.
- `gateway.multiplex_profiles` is still off, so a `/p/<profile>/` prefix on an API request is
  ignored. Those requests now land on the Platform Agent rather than the Planning Agent.
- The `hermes dashboard` sidecar is deliberately left on the `default` profile, so the dashboard
  shows that profile's sessions while the front door is the platform one.
- **An [`AgentPlugin`](../../site/src/content/docs/operator/agentplugin-crd.md) without a `spec.targetProfile` does not follow the
  gateway.** The two halves that decide whether it loads at all stay on the `default` profile: the
  image volume is mounted at `$HERMES_HOME/plugins/<name>`, and the name is added to that profile's
  `plugins.enabled`. With the flag on, the gateway is homed at `profiles/platform` and reads
  neither, so the plugin never registers — silently, since nothing errors, and its `platforms:`
  block does arrive here through the machine-global managed scope, configuring an adapter that has
  nothing to configure. The `pubsub-platform` adapter and the `gke-stockout-investigator` alert
  route that depends on it are both affected. Setting `spec.targetProfile: platform` moves the
  plugin and its `platform_toolsets` across.
- **The `default` profile's cron roster stops ticking.** Hermes binds its cron ticker to one
  `HERMES_HOME` — the job store, the execution ledger and `.tick.lock` all resolve from the gateway
  process's own home — so the one roster that ticks becomes `profiles/platform/cron/jobs.json`. The
  Platform Agent's own watchdogs therefore tick natively, which is the upside; the cost is that the
  three jobs on the `default` roster never come due.

  Those are `cluster-agent-reconcile`, which scaffolds a profile for a newly onboarded cluster and
  prunes one for a deleted cluster; `oobe`, which runs first-run onboarding (the
  `bootstrap-inventory-*` entries ship disabled); and `profile-cron-tick`, the only thing that ticks
  a **named** profile's own store — so every `cluster-*` roster goes quiet with it, and so do the [idle-install hold](../../site/src/content/docs/concepts/autonomous-watchdogs.md#idle-installs) on the Platform Agent's model-run jobs and the [catch-up policy](../../site/src/content/docs/concepts/autonomous-watchdogs.md#catch-ups-after-a-pause) that thins them after a pause, which run inside that job. Nothing errors
  and nothing is logged: a job that is never ticked stays `scheduled` with a `next_run_at` in the
  past.

- **Per-user memory does not follow the gateway either.** The front door's provider is
  `multiuser_memory`, committed in `agents/chat/config.yaml` and reaching the `default` profile
  alone. The platform profile is configured as a specialist instead: `read_only: true` from the
  image, and a `memory.provider` its overlay blanks unless
  [`spec.harness.memory`](#specharnessmemory) names a Hindsight-backed store. With the flag on the
  front door is that profile, so chat has no recall, no per-user profile and no retention — while
  `memory` stays in the profile's toolsets advertising all three.

  The keys cannot be copied as they are across, because `profiles/platform/config.yaml` is shared:
  it is also the home of every kanban-spawned specialist and every job on the platform cron roster.
  Lifting `read_only` there would let a specialist write the shared corpus, and un-blanking the
  provider would collapse those writes into one anonymous bucket, since a specialist carries no
  gateway identity to scope a per-user store by. Carrying memory to the front door needs those
  settings to be per-process rather than per-profile.

- **First-run onboarding does not follow the gateway.** Its job, `oobe`, is on the `default` roster the
  bullet above stops ticking, and its greeting hook — the `bootstrap_onboarding` plugin — resolves
  its once-per-deployment markers from the gateway's home, so on the platform profile it would greet
  an already-onboarded install and promise a report nothing can deliver. The operator therefore
  leaves that plugin off the front door deliberately. Bring an install up with the flag off, let
  onboarding finish, then turn it on.
- **A home channel set with `/sethome`, or by the first chat message, stays on the profile it was set on.** The operator renders no
  `home_channel` of its own, so on an install that did not populate the CR's Google Chat or Slack
  `homeChannel` the value lives only in the config file the gateway last wrote. Flipping the flag
  changes which file that is, and nothing carries it across. The Platform Agent's own `deliver: all`
  watchdogs then tick in-process, where the delivery target is read from the environment alone —
  so every scheduled report posts nowhere while chat replies stay healthy and the install looks
  fine. Either populate `homeChannel` on the CR before flipping, or re-run `/sethome` after.
- **`chat_message_audit` stops recording.** It is a hook rather than a plugin, and hooks are only
  ever copied into the root home — nothing puts them on a named profile, and Hermes reads
  `$HERMES_HOME/hooks` and returns silently when the directory is absent. `tool_call_audit` is a
  plugin, is enabled on this profile and still records the inbound message with its session and
  pseudonymised user id, so what is actually lost is the record carrying the agent's **response**
  text. Response content remains in the session store.
- **The platform profile's `config.yaml` stops being restored from the image on every restart.**
  Handing the file to the agent is the point — that is what lets `/sethome` and
  `monitoring.install_id` survive — but the same change means a key the running agent writes there
  is not reverted at boot. Keys the image adds still arrive through the back-fill; keys already in
  the file stay as they were last written, except the remote MCP server entries, which follow the
  image ([below](platformagent-profile-config.md)). Operator-owned settings are unaffected: they
  come from the overlay and the `/etc/hermes` pins, both re-applied every boot.
- Cluster profiles that already exist are otherwise unaffected — their config, skills and
  scaffolding on disk are unchanged and they keep working. What stops is the scheduled work above,
  which includes `cluster-agent-reconcile`, so a cluster onboarded while the flag is on gets no
  profile until the flag goes back off.

#### `shellSandbox`

- `enabled` — the agent's shell runs in a StatefulSet of its own, reached over SSH with the keypair in the agent's credential Secret (`SANDBOX_SSH_PRIVATE_KEY` and its public half in `<name>-shell-authorized-keys`). **This is not a toggle: `false` is refused** with `Degraded`/`ShellSandboxCannotBeDisabled`, which changes nothing about the running workload. Absent or `true` are the same thing. With no keypair the sandbox Pod cannot start at all — the Secret it mounts is not optional — so the operator reports `Degraded`/`ShellSandboxKeysMissing` rather than leaving the Pod in `ContainerCreating` with the reason only in a Pod event. `install.sh`, `upgrade.sh` and the Terraform composition generate the pair; a bare `helm install` that passes none, or a kustomize install (INSTALL.md Method 2) that skipped its Step 2, reaches that state.
- `image` — overrides the sandbox image. Empty takes the operator's default. A pinned image must be at least as new as the operator. The operator runs the image's entrypoint in an init container that stages the image-shipped trees, and an older image does not have that mode, so the sandbox Pod never starts. A pin also survives every upgrade, and a sandbox older than the agent fails its `kubectl` calls at the credential proxy, so the operator reports the [`ShellSandboxPinned`](../../site/src/content/docs/operator/platformagent-crd.md#status) condition while the pin differs from its own image.
- `runtimeClassName` — runs the sandbox Pod under a sandboxed container runtime, `gvisor` being the one GKE offers. Unset by default. Separate from [`spec.deployment.availability.runtimeClassName`](../../site/src/content/docs/operator/platformagent-crd.md#specdeployment), which governs the agent Pod: that Pod holds SQLite databases whose WAL mode gVisor corrupts on the gofer-backed mount, and setting the agent Pod's field pins Hermes' own databases to the DELETE journal mode (the Session KV store is not covered; see `availability.runtimeClassName` under [`spec.deployment`](../../site/src/content/docs/operator/platformagent-crd.md#specdeployment)), while the sandbox Pod holds none — so an install can sandbox the untrusted Pod without sandboxing, or slowing, the trusted one.

  On GKE Standard the cluster needs a node pool created with `--sandbox type=gvisor`; Autopilot ships the RuntimeClass natively. A RuntimeClass the cluster does not have leaves the CR `Degraded` naming it, rather than a Pod sitting `Pending`.

- `resources` — requests and limits for the shell container. Merged per key over the operator's defaults, or over the [`sizingProfile`](../../site/src/content/docs/operator/platformagent-crd.md#specdeployment) row when one is set, like `credentialProxy.resources` under [`spec.deployment`](../../site/src/content/docs/operator/platformagent-crd.md#specdeployment): a CR that sets only the memory pair keeps the default 200m CPU request and 2 CPU limit. The defaults are a 512Mi memory request and a 2Gi memory limit. Only `cpu`, `memory` and `ephemeral-storage` are accepted.

  The shell is where every model-authored command runs, so a fleet sweep that fans out many `kubectl` calls at once is bounded by this container's memory. On GKE Autopilot without bursting the limits are set equal to the requests, so there `requests.memory` is the figure that counts, with `limits.memory` to match. A change rolls the shell Pod, as an image change does; the image-trees init container and the gateway's sandbox sidecars keep their own figures.

  The sandbox's memory guard stops the largest command before the container reaches its limit. The sign to raise the limit is a `shell-memory-guard` `killed` line in the shell Pod's log, or a `no-candidate` line when many small commands fill it ([fleet sizing](../../site/src/content/docs/deploy/fleet-sizing.md)). Where the guard logs itself `disabled`, the sign is an OOMKill.

  The operator refuses a request above its limit, a negative quantity, a zero limit, `claims`, and any other resource name, whether or not the webhook is on. It ignores the override, renders the shell at the profile's row (the operator's defaults under `small`), and reports `Degraded` with reason `InvalidShellSandboxResources` when no higher-ranked `Degraded` cause is present, the agent staying Ready. There is no memory floor. Where the [validating webhook](../../site/src/content/docs/operator/index.md#admission-webhooks) is enabled, admission refuses the same override at apply, and warns on the GKE Autopilot memory-per-vCPU band and on a `cpu` or `memory` limit set without the same key under `requests`, for the reasons `credentialProxy.resources` gives.

The GitHub-writing skills hand the credential broker file content and a commit message rather than a directory both sides mount, so the agent never holds a `.git`. There is no field for it: the broker keeps the checkout on its own state volume, which closes git's config-driven exec surface — a hook, a pager, a `filter.*.clean`, an `ext::` transport — and an install that could turn that off would be choosing to keep it open.

The credential broker is a Deployment of its own, never a container of this Pod, so a proxied command reaches it over a ClusterIP Service and nothing crosses as a path. A document travels on stdin, a kubeconfig as a GKE context name, a commit as file content. [`spec.security.workloadIdentityFederation`](../../site/src/content/docs/operator/platformagent-crd.md#specsecurity) is optional hardening on top of that, not what places it.
