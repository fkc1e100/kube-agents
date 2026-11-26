---
title: "PlatformAgent: Profile config propagation"
description: "How PlatformAgent configuration reaches the Planning, Platform, and Cluster Agent profiles."
---

Part of [PlatformAgent CRD](/kube-agents/operator/platformagent-crd/).

## How config reaches each profile

A deployment runs several Hermes **profiles** from one pod: `default` (the Planning Agent front door),
`platform`, and one `cluster-*` profile per managed cluster. The named profiles are each configured
by an overlay merged into an image-built base at startup. The `default` profile is the exception: it
takes the operator's settings by _two_ routes at once — an overlay merged into its config, and a
read-only **managed scope** pinned over it.

| Profile                                                       | Delivery                                                                                                                                                                   | Who owns the file                                      |
| ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| `default`                                                     | Image-built base, writable on the PVC + `profile-default.overlay.yaml` merged at startup + a narrow set of keys pinned read-only at `/etc/hermes`                          | Agent owns the file, operator the pins                 |
| `platform`                                                    | Image-built base + `profile-platform.overlay.yaml` merged at startup                                                                                                       | Image owns the base, operator the overlay              |
| `platform`, with [`platformFrontDoor`](/kube-agents/operator/platformagent-harness/#platformfrontdoor) on | The same two inputs, but the base is back-filled rather than force-synced — and the `/etc/hermes` pins land here too, because that mount is machine-global                 | Agent owns the file, operator the overlay and the pins |
| `cluster-*`                                                   | Image-built base, copied when the profile is scaffolded and back-filled at startup + `profileclass-cluster.overlay.yaml`, plus `profile-<name>.overlay.yaml` if one exists | Image owns the base, operator the overlay              |
| `tse` (optional, when enabled)                                | Image-built base at `/opt/tse-template`, force-synced at startup when `KUBE_AGENTS_ENABLED_PROFILES` contains `tse` + `profile-tse.overlay.yaml` if one exists             | Image owns the base, operator the overlay              |

A cluster profile is the only one that can take two overlays: the class overlay carries
`tuning.cluster`, which applies to all of them, and a plugin targeting one specific cluster produces
a `profile-<name>` overlay for it as well. The class overlay merges first, so the per-profile file
wins any conflict.

**Why `default` is also pinned.** The pins are the one change-control boundary the front door has:
the agent's own config file is writable, so without them a bad runtime edit survives a restart. (It
is _not_ a security sandbox — see the
[AgentPlugin trust boundary](/kube-agents/reference/security-and-iam/#change-control--safety).)

**What is pinned is narrow, on purpose.** `/etc/hermes` is machine-global — one file for every
profile in the pod, not just `default` — so it carries only what is identical for every profile
_and_ beyond the agent's own repair:

- `model.*`, `platforms.*`, `approvals.cron_mode` and `display.platforms`;
- `kanban.max_in_progress`: the board is shared by every profile, and a burst of workers past it is
  lost to the OOM killer without a restart or an event;
- `kanban.admission`: the dispatcher's memory budget, worker cap, queue bound and fail-closed
  switch, from `spec.harness.tuning.admission`; the board is shared and an eviction is pod-wide, so
  no profile may admit past the pod's request;
- `terminal.*`: where the shell runs, one sandbox per Pod, reached the same way by every profile;
- `database.journal_mode`, when the agent Pod has a runtime class: one data volume per Pod, and a
  corrupted database is found only after the sessions in it are unreadable;
- `sessions.auto_prune` and `sessions.retention_days`, from `spec.harness.retention`: one period for
  every profile, which no profile can lengthen;
- one `hooks.outbound` entry that posts tool calls and model requests to the bridge's loopback
  activity endpoint, when the A2A bridge is in the Pod, rendered by the operator or declared, and
  runs the `api` executor: one endpoint per Pod, signed with a key from the A2A credentials Secret.
  A list is one leaf, so while that entry is rendered it replaces any `hooks.outbound` list a
  profile sets in its own `config.yaml`: those hooks do not fire.

The reasoning is that as long as a human can reach the agent (`platforms`) and the agent can reason
(`model`), anything else it breaks it can be talked into fixing.

Everything else the operator owns for the front door goes in `profile-default.overlay.yaml`
instead: `plugins.enabled` for AgentPlugins with no `targetProfile`, those plugins' non-gateway
config subtrees, and `spec.harness.tuning`'s `default` limits. Those are
profile-shaped — pinning them machine-globally would hand the front door's settings to every
specialist — and they are all recoverable by an agent that can still talk and still reason.
Nothing the operator renders appears on both routes. What appears on neither, and so stays the
image's alone, is each profile's toolsets, `mcp_servers` and `memory`.

It is also the only profile whose config the _running agent_ writes to: `/sethome` records the home
channel there, the monitoring policy mints `monitoring.install_id`, and slash commands save
preferences. Those two facts pulled in opposite directions, and the managed scope is what resolves
them.

The rendering is published as the `managed-config.yaml` key of the `<agent>-config` ConfigMap and
mounted read-only at `/etc/hermes/config.yaml`. Hermes treats that directory as an administrator
layer and overlays it, **per leaf key**, on top of `$HERMES_HOME/config.yaml` at every load. Three
things enforce it (`hermes_cli/managed_scope.py`):

- `load_config` deep-merges the managed dict on top of the agent's own;
- `save_config` strips every managed leaf before writing, so a save cannot persist one;
- `hermes config set` rejects a managed key by name.

So `$HERMES_HOME/config.yaml` stays an ordinary writable file — `/sethome` and the install id work —
while every leaf the operator renders is authoritative and immutable at runtime. Whatever ends up in
the PVC file, the operator's value is what loads, so a restart always heals. Earlier shapes did not
manage both: mounting the render over `$HERMES_HOME/config.yaml` made the path read-only and failed
every runtime write (`/sethome` with a permission error, the rest silently), and
merging it into the file at startup left every merged key mutable, so an agent that repointed
`model.base_url` at nothing kept that across restarts.

Hermes builds the terminal for some turns, among them a scheduled run and the turn a kanban wake
starts, from the profile's own `.env` and `config.yaml`, so the managed `terminal.*` leaves do not
reach them on their own. The entrypoint copies them into every profile's `.env` at
start-up and refuses to start while a profile still resolves something else — see
[Container entrypoint](/kube-agents/deploy/docker-images/#container-entrypoint).

`platforms.<platform>.home_channel` is deliberately **not** pinned, so `/sethome` can still set it
from chat. The platform credentials and endpoints that have no `config.yaml` equivalent are pinned
through a companion `/etc/hermes/.env`, which Hermes applies last with `override=True` and refuses to
let the agent overwrite — without that, a container env var would beat the pinned `platforms.*` leaf.

That file also pins values that are not credentials at all. The first is `API_SERVER_KEY=cluster-internal-trusted`,
the non-secret loopback sentinel the Hermes API server on `127.0.0.1:8642` validates. It is pinned here
because Hermes' stage2 hook generates a random `API_SERVER_KEY` into `$HERMES_HOME/.env` whenever that
file carries none, and the PVC `.env` is applied with `override=True` too — ahead of the container env,
behind `/etc/hermes`. Unpinned, the gateway ends up validating against a value no caller has, and the
credential proxy, the startup probe and every in-pod loopback call get `401 Invalid gateway API key`.
The container entrypoint warns at boot when this pin and the container env disagree.

The credential that guards the API from _outside_ is `API_SERVER_EXTERNAL_KEY`, set from
`hermes.apiServerSecretRef`; the sidecar authenticates the caller against it and swaps in the sentinel.

The second is `HERMES_HOME_MODE=2770`, the mode Hermes re-applies to `$HERMES_HOME` at every process
start. The container env carries it too, but that is the lowest-precedence of the three layers, so a
`HERMES_HOME_MODE=0777` line the agent writes into the PVC `.env` outranks it and widens every
directory Hermes secures on the shared volume.

The third is `KUBEAGENTS_MODE`, pinned to `next` until no supported agent image predates the
removal of `today`, for an agent image older than the operator that still reads it. It is pinned because an absent key is a key the agent may write.

The fourth is `KUBEAGENTS_SCOPE_FILE=/etc/kube-agents/scope.json`, where the reconcile finds the
[`spec.scope`](/kube-agents/operator/platformagent-scope-integrations/#specscope) declaration. The container env carries it too, for the same reason as
`HERMES_HOME_MODE`: a line the agent writes into the PVC `.env` would otherwise outrank it and hand
the reconcile a declaration the agent authored. Its readers are `agents/platform/scripts/cluster_agent_reconcile.py`, which resolves it every hour, and `fleet_scope_targets.py`, which reads it when no reconcile snapshot answers, or when the last snapshot recorded no boundary, for these callers:

- the front door's roster (`agents/chat/scripts/agent_roster.py`), which reads the declared scope when it lists the agents;
- the platform MCP server's `fleet_scope` tool;
- the Platform Agent's `upgrade-readiness-watch` and `upgrade-readiness-weekly-review` jobs, which learn from it whether the install declares a scope before handing the readiness report script the resolved scope beside each project it reads;
- the `sa-role-watch` job, which reads the IAM policy of each project in the resolved scope;
- the onboarding inventory scan (`agents/chat/scripts/bootstrap_scan_gate.py`), which leaves the declaration's excluded clusters out of the sweep it files.

The fifth is `RECONCILE_PROJECT=`, pinned empty. The reconcile reads that variable as the management
project ahead of the metadata server, and a management project that changes identity retires the
old one's profiles, so a line the agent wrote into the PVC `.env` could otherwise re-point it and
have two clean runs delete every profile of the real management project. Nothing in the operator
or the chart sets the variable; the script treats the empty value as unset.

`KUBEAGENTS_RESOLVED_SCOPE_FILE` is pinned too, to
`/etc/kube-agents-resolved/resolved-scope.json`: the scope publisher's `<name>-resolved-scope`
ConfigMap, mounted read-only into the agent container, which is where the helper scripts' cluster
lists come from. The container env carries it too.

On GKE, `GKE_PROJECT_ID` is also pinned, to `spec.harness.projectID`. The reconcile reads it as the
management project when `RECONCILE_PROJECT` is empty, so it is pinned for the same reason. A kind
install does not pin it, because the container env there carries no project.

`KUBEAGENTS_DIAL_ADMINS` names the Slack members who may change the autonomy dial on the Slack Home
tab. It is pinned on every install from `spec.deployment.env`, keeping only the comma-separated entries
shaped like a Slack member ID. Unset, it is pinned empty, which lets nobody change the dial. A value
none of whose entries is a member ID is pinned as `none`, which also matches nobody. Session KV checks
a dial change against it before it records one. Unpinned, a line the agent wrote into the PVC `.env`
could name who may change what the agent may change. It is not in the container env.

The stall watch's three knobs from [`spec.harness.stallWatch`](/kube-agents/operator/platformagent-harness/#specharnessstallwatch) are pinned too:
`STALL_WATCH_EXCLUDE_NAMESPACES` (a comma list), `STALL_WATCH_MIN_AGE_MINUTES` and
`STALL_WATCH_KINDS` (a comma list, or `all`). They are pinned on every install, empty when the CR
does not set them, and the watch reads an empty value as its default. Each one changes what the
watch reads or when it alerts, so a line the agent wrote into the PVC `.env` could otherwise silence
alerts for a namespace nobody excluded. They are not in the container env.

The earned-autonomy switches `KUBEAGENTS_POST_MERGE_CHECK`, `KUBEAGENTS_AUTOMERGE` and
`KUBEAGENTS_DIAL` are pinned the same way, on every install, from `spec.deployment.env`, each
normalised to a value it knows or `off`. They are not in the container env; the
[credential isolation reference](/kube-agents/reference/credential-isolation/) describes them.

One consequence of the render is worth knowing: the managed overlay is a
leaf-level merge, and a list is a leaf, so a list rendered here **replaces** the image's rather than
unioning with it — for every profile at once. That is why the render emits no lists at all today,
and why adding one is the change to think hardest about.

**Why the others get overlays.** Their `config.yaml` is assembled at image build time by merging the
shared defaults with that profile's own overlay, content the operator does not have. A `cluster-*`
config additionally carries a runtime `cluster_identity` stamp that the reconciler matches profiles
to clusters by. Rendering either file in full would fork the source of truth and, for cluster
profiles, strip that identity record.

Every overlay is a key in the one `<agent>-config` ConfigMap, so a change to any of them moves the
config hash and rolls the pod. That restart is required, not incidental: the merge happens once at
startup, so a live ConfigMap update without a restart would be a no-op. The managed key shares the
ConfigMap and so rolls the pod too, though for it the restart is belt-and-braces rather than
required — it is mounted as a directory, not a `subPath`, so the kubelet propagates updates and
Hermes re-reads the file when its mtime or size changes.

Startup is not the only moment a merge happens. Onboarding a cluster scaffolds a new profile without
changing the ConfigMap, so nothing rolls the pod; that profile applies the overlays itself as it is
created. Without it a Cluster Agent created between two pod starts would run on Hermes' own defaults
however the CR is tuned.

**Ordering.** The entrypoint force-syncs each profile's image-owned files first, then merges the
overlays. The reverse order would silently erase every overlay on each restart. The `default`
profile's `config.yaml` is the exception to the force-sync: it is the agent's own file, and a
force-sync is exactly what would throw the runtime's edits away. It is instead seeded from the image
on a fresh volume, and thereafter only back-filled — keys the image declares and the live file has
lost are restored, keys it already holds are left alone, and the `plugins.enabled` list gains the
names the image's list has and it lacks (below). Its overlay is merged after that
back-fill, so the operator's settings are not undone by it.

The platform profile's `config.yaml` becomes a second exception under
[`platformFrontDoor`](/kube-agents/operator/platformagent-harness/#platformfrontdoor), and for the same reason: the gateway is homed there, so
that file is now the one `/sethome` and the monitoring policy write to. It leaves the force-sync
list and is back-filled from the image template instead, on exactly the terms `default` gets — keys
the template declares and the live file has lost are restored, keys it already holds are left
alone. Its overlay merges after that back-fill as it always did. Everything else the image owns in
that profile — the persona files, `cron/`, `skills/`, `governance/`, `hindsight/` — still
force-syncs either way.

A `cluster-*` profile's `config.yaml` is never force-synced: it carries the `cluster_identity`
stamp the cluster reconciler matches the profile to its cluster by, and an overwrite would strip
it. It is back-filled from the cluster template instead, on the same fill-only terms — keys the
template declares and the live file has lost are restored on a pass, and `cluster_identity`
and every value the file already holds are left alone, except the retired `memory.provider` key,
which the entrypoint drops.

A cluster profile takes these steps, the persona copy, the `skills/` replace, the shared plugin
refresh, the back-fill and the repairs below, on a pass. A pass runs only when the profile's
`.scaffold-stamp` does not match the image: the first start on a new image, a start after a pass
that warned, or one after the stamp was deleted.

The entrypoint hashes what a pass reads from the image once per start and stamps each cluster
profile it refreshed without a warning. On a same-image restart a stamped profile is left as it
is, hand edits included. Delete `profiles/cluster-*/.scaffold-stamp` to send a profile through
the pass on the next start. Without the stamp script every profile is refreshed and none is
stamped.

The remote MCP server entries inside both of these files do follow the image (see
[the config reference](/kube-agents/reference/config/)). The back-fill recurses only through
mappings and a server's `args` is a list, so it would otherwise stay as the image that scaffolded
the profile spelled it for the life of the volume.

The entrypoint repairs it in each cluster profile's `config.yaml` on a pass through the profile,
and in the platform profile's at every start when it is the front door: for a server the template
routes through the credential proxy's MCP relay (`gke` and `developer_knowledge`), the whole
`args` list and the `MCP_REMOTE_BEARER_FILE` entry in its `env` become the template's, so a hand
edit to either is reverted at the next pass or start; for any other remote server the image
ships, only the `User-Agent` header value is set. Nothing else in the file is changed.

The `plugins.enabled` list follows the image for the same reason: it is a list, so the back-fill
never enters it. In the `default`, `platform` and every cluster profile it gains the names the
image template's list has and the live list lacks, appended after the agent's own. Nothing is
removed, so a name the agent dropped on purpose comes back, which is the price of a plugin that
ships enabled. Without it a volume scaffolded before a plugin existed would carry the plugin into
every image and never load it.

**Merge semantics.** These differ between the two mechanisms, which is the easiest thing to get
wrong here. In a startup **overlay** — every profile including `default` — maps merge recursively,
lists union, and scalars are replaced by the overlay; precedence, lowest to highest, is Hermes
built-in default → the value committed in `agents/<persona>/config.yaml` → the operator overlay from
the CR. In the **managed scope** the merge is per leaf key, so a list replaces rather than unions,
and it wins over everything else because it is applied at every load rather than once at startup.

**Two writers, two authorities.** Both `spec.harness.tuning` (operator policy) and an
`AgentPlugin`'s `spec.config` (plugin-supplied) land in the same overlay file, but not with equal
rights. A plugin's config is restricted to `approvals`, `platforms`, and `platform_toolsets`, and
for an untargeted plugin only `platforms` reaches the machine-global managed scope — the rest goes
to the front door's overlay. The `agent` subtree holding the execution limits is dropped from plugin
config and writable only by the operator. That is a coordination boundary rather than a security one — plugin code executes
in-process and could change these at runtime — but it keeps limits with board-wide consequences in
one reviewable place.

### Rotating a Secret rolls the pod

Credentials reach the agent pod as environment, through `SecretKeyRef`, and a container's
environment is fixed for the life of the pod: editing the Secret changes nothing a running container
can see. So the operator does for Secrets what the config hash does for ConfigMaps. It reads the
Secret keys the rendered pod spec consumes as environment, digests them with an HMAC-SHA256 keyed by
the UID of each Secret they come from, and stamps the result on the pod template as
`kubeagents.x-k8s.io/secret-env-hash`. Rotating one of those keys moves the digest, which changes the
template, which rolls the pod onto the new value.

Three pods are stamped: the gateway, the credential proxy, and the A2A gateway,
which on a Slack-armed install is the pod that reads the Slack tokens. The A2A auth
callout also reads Secrets as environment (its bus password and its issuer and encryption seeds) but
is not stamped, so after rotating one of those, run
`kubectl rollout restart deployment/<agent>-a2a-callout`.

The digest is keyed because the annotation is readable by anyone who can read pods. An unkeyed hash
would let that reader verify guesses at a low-entropy value offline, whereas the UID is on the Secret
object, and reading it takes the same `get` on the Secret that reads the values. (A UID also travels
on Events and owner references that point at the Secret; the operator creates neither.)

Five details decide whether you will see it happen.

- **Within fifteen minutes, not immediately.** The operator does not watch Secrets — it holds no
  `list` or `watch` on them, deliberately — so nothing wakes a reconcile when one changes. A healthy
  pass instead asks to be requeued after `secretEnvReprobeInterval`, and the re-read happens then.
  `kubectl rollout restart deployment/<agent>-gateway` still works and is immediate.
- **Only what the pod reads as environment.** A key no container references is not in the digest, and
  editing it rolls nothing. Neither does a key the pod _mounts_: the kubelet refreshes a mounted
  Secret file in place, so hashing one would roll a pod over a change it was going to see anyway.

  The gateway mounts exactly one item of `platform-agent-secrets` that way, `SANDBOX_SSH_PRIVATE_KEY`,
  and because an init container copies it into an `emptyDir` at pod start, rotating that one key
  still needs a restart — as it did before this change. The shell sandbox mounts its own
  `<agent>-shell-authorized-keys`, and deliberately never names `platform-agent-secrets` at all.

  The A2A gateway has a second such mount: on a Slack-armed install it mounts the
  `a2a-slack-principal-map` Secret, and the gateway reads that map once, when it starts, so an edit
  to it needs `kubectl rollout restart deployment/<agent>-a2a-gateway`.

- **Whichever Secret the pod actually names.** The refs are read off the rendered pod spec, so a CR
  that supplies its own `SecretKeyRef` pointing at a different Secret is covered without naming it
  anywhere.
- **A missing Secret is not an error.** It digests to a marker, so creating the Secret later moves the
  digest and rolls the pod, and an install whose credentials arrive after the agent behaves the way
  you would expect. A Secret the operator cannot read for any other reason — an API error rather than
  a `NotFound` — keeps the digest the last good pass computed, so a blip neither rolls the pod nor
  stops the rest of the reconcile.
- **Recreating a Secret rolls the pod once, even with the same values.** The digest's key is built
  from the UID of every Secret it reads, which an in-place edit, `kubectl apply`, or a patch keeps
  and a delete-and-create (including `kubectl replace --force`) replaces. A metadata-only write — a new label or annotation —
  changes neither the UID nor the values and rolls nothing.

**The roll is a stop-start.** At the default single replica the gateway's update strategy is
`Recreate`, so the old pod is terminated before the new one starts and the agent is unreachable
across the gap — up to the startup budget of roughly fifteen minutes on a cold image pull. Expect one
such restart per agent the first time an operator carrying this change reconciles: the annotation is
new, so the first pass adds it and the template changes once, whether or not anything was rotated.

The A2A gateway joined the stamped pods later, so the first operator that stamps it restarts each
A2A gateway once in the same way. An operator upgrade that changes how the digest is
computed restarts each stamped pod once in the same way.
