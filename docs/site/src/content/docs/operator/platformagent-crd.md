---
title: PlatformAgent CRD
description: The single custom resource the operator reconciles.
sidebar:
  order: 1
---

The `PlatformAgent` resource declares everything the operator needs to run one Platform Agent instance: which Hermes image, which service account, which chat integrations, and which framework-level toggles.

- **API group / version**: `kubeagents.x-k8s.io/v1alpha1`
- **Kind**: `PlatformAgent`
- **Source**: [`k8s-operator/api/v1alpha1/platformagent_types.go`](https://github.com/gke-labs/kube-agents/blob/main/k8s-operator/api/v1alpha1/platformagent_types.go)
- **Sample**: [`k8s-operator/examples/platformagent.yaml`](https://github.com/gke-labs/kube-agents/blob/main/k8s-operator/examples/platformagent.yaml)
- **Fields**: [PlatformAgent fields](/kube-agents/operator/platformagent-fields/), every `spec` and `status` field with its type, default and constraints, generated from the Go API types. This page covers what the fields do.

## Top-level shape

```yaml
apiVersion: kubeagents.x-k8s.io/v1alpha1
kind: PlatformAgent
metadata:
  name: platformagent
  namespace: kubeagents-system
spec:
  harness: { ... } # execution environment + framework
  deployment: { ... } # container image, pull policy, containers, volumes
  security: { ... } # service account + Workload Identity
  telemetry: { ... } # OTLP collector endpoint and the people switch (optional)
  networkPolicy: { ... } # generated egress NetworkPolicy (optional)
  integration: { ... } # Google Chat, Slack, Teams, git forge
  scope: { ... } # projects beyond the management project, and exclusions (optional)
  hold: { ... } # clusters an operator has paused the agents' access to (optional)
  storage: { size: 80Gi } # data volume size (optional; absent means 50Gi)
  mode: next # deprecated and ignored; every install runs the A2A stack (optional; absent reads next)
```

`spec.deployment`, `spec.security`, `spec.telemetry`, and `spec.networkPolicy` are inlined from the shared `AgentSpec`, so they are common to every agent type. `spec.harness` is required; `spec.integration`, `spec.telemetry`, `spec.networkPolicy`, `spec.scope`, and `spec.hold` are optional.

`spec.mode` is deprecated and ignored: every install runs the A2A stack. The enum still accepts `today` and `next`, so a stored object that carries `today` stays valid, and the schema defaults an absent field to `next`. The mutating webhook rewrites `today` to `next` on create and update. The operator patches a stored `today` to `next` once and records an Event with reason `ModeMigrated`. A later release removes the field.

The operator renders the A2A stack:

| Component                                                                | What is rendered                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | Notes                                                                                                                                                                                                                                                                                                                                                                                                                       |
| ------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Bus                                                                      | the NATS/JetStream component and its provisioning Job, an ingress NetworkPolicy fencing the bus, an egress NetworkPolicy fencing the session pods, and a session-pod ResourceQuota                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |                                                                                                                                                                                                                                                                                                                                                                                                                             |
| A2A gateway                                                              | its Deployment, with session-pod spawning armed and the console door always on (`A2A_CONSOLE_DOOR=true`). Its election Lease `<agent>-a2a-gateway`, which the gateway may only read and renew (the operator's `A2A_GATEWAY_ELECTION=false` turns the election off). A PodDisruptionBudget of `maxUnavailable: 1` while more than one replica is Ready, and a zone topology spread. It runs `availability.a2aGateway.replicas` replicas once a gateway on its image holds the Lease, and one before that. Once `ProfileSupervisorForm` is True, the ConfigMap `<agent>-a2a-profile-names`, listing the bound and draining AgentProfiles, which the gateway and the MCP server mount | runs on the console alone when no chat backend is configured                                                                                                                                                                                                                                                                                                                                                                |
| Capability verifier                                                      | a Deployment of two replicas, with its own ServiceAccount, a NetworkPolicy fencing it to DNS and the bus, a PodDisruptionBudget of `maxUnavailable: 1` and a `kubernetes.io/hostname` topology spread                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | the only bus principal permitted to read the `cap` KV bucket, and it needs nothing else; a submission arriving while no verifier is ready is refused terminally, so a node drain must not take both replicas at once                                                                                                                                                                                                        |
| Auth callout                                                             | the Deployment that authenticates bus clients, its Service, ServiceAccount, Role and RoleBinding, a cluster-scoped ClusterRoleBinding to `system:auth-delegator`, the identity-map ConfigMaps `<agent>-a2a-authmap-<n>`, and the keys Secret `<agent>-a2a-callout-keys`; its two replicas also carry a PodDisruptionBudget of `maxUnavailable: 1` and a `kubernetes.io/hostname` topology spread                                                                                                                                                                                                                                                                                   | while no callout is ready the bus refuses every new connection, so a node drain evicts one callout at a time and waits for its replacement to be ready before taking the other                                                                                                                                                                                                                                              |
| Console server                                                           | the Deployment and Service `<agent>-a2a-console`, which serve the A2A console page and proxy its websocket to the bus, and a deny-all ingress NetworkPolicy, `<agent>-a2a-console-netpol`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | reachable only through `kubectl port-forward`, and that port-forward is also what hands out the console credential                                                                                                                                                                                                                                                                                                          |
| MCP server                                                               | the Deployment, Service, and ServiceAccount `<agent>-a2a-mcp`, a deny-all ingress NetworkPolicy `<agent>-a2a-mcp-netpol`, and the bearer-token Secret `<agent>-a2a-mcp-token`. Once `ProfileSupervisorForm` is True it also mounts `<agent>-a2a-profile-names`                                                                                                                                                                                                                                                                                                                                                                                                                     | rendered by default unless `A2A_MCP_DOOR=false` (`operator.mcpServer.enabled: false` in the chart); reachable only through `kubectl port-forward` with the bearer token from `<agent>-a2a-mcp-token`                                                                                                                                                                                                                        |
| Profile dispatcher                                                       | the Deployment `<agent>-a2a-dispatcher`, its ServiceAccount, Role and RoleBinding, and the dispatch ConfigMap, whose profiles are the ones `<agent>-a2a-profile-names` lists                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | rendered by default unless `A2A_PROFILE_DISPATCHER=false` (`operator.profileDispatcher.enabled: false` in the chart)                                                                                                                                                                                                                                                                                                        |
| Teams inbound receiver, when `spec.integration.teams.inbound` is enabled | the Deployment, ServiceAccount and ClusterIP Service `<agent>-teams-inbound` (port 8100) and the NetworkPolicy `<agent>-teams-inbound-netpol`; no Ingress, which you provide                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | the one pod the internet reaches; it holds no credential of the install's own, and the broker admits it to `POST /v1/chat/teams/events` alone                                                                                                                                                                                                                                                                               |
| ServiceAccounts                                                          | one for the provisioning Job and one for the spawned session pods (beside the verifier's, callout's, MCP server's, and dispatcher's above)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | so the callout has an identity to resolve each by                                                                                                                                                                                                                                                                                                                                                                           |
| Google Chat, when that is the chat backend                               | the A2A gateway consumes the install's Chat subscription in place of the Planning Agent, whose Google Chat platform is then not rendered, and carries `spec.integration.googleChat.homeChannel`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | the agent's proactive messages reach that space through the gateway, which posts them as new threads there or as replies on its threads and nowhere else. With `homeChannel` not a `spaces/<id>` name, the agent posts nothing to Google Chat unprompted. Unset, the gateway learns the space from the first mention under `homeChannelPolicy` `auto`, and the CR carries the `HomeChannelUnset` condition until it has one |
| Teams inbound receiver, when `spec.integration.teams.inbound` is enabled | the Deployment, ServiceAccount and ClusterIP Service `<agent>-teams-inbound` (port 8100) and the NetworkPolicy `<agent>-teams-inbound-netpol`; no Ingress, which you provide                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |

The operator also renders the task-signing key Secret `<agent>-a2a-task-signing-key`. Only its public half reaches the callout, and only the dispatcher will mount its seed.

The bus runs [`harness.tuning.busReplicas`](/kube-agents/operator/platformagent-fields/#spec) NATS servers, three by default. They spread one per node with `DoNotSchedule`, so one drain takes one server. At three, the bus also has a routes Service and a PodDisruptionBudget of `maxUnavailable: 1`.

One server isn't highly available. A node drain or an upgrade that moves its pod takes the bus down while the pod restarts, typically for about two minutes, and longer after a node scale-down (below). The operator says so once each time a new bus pod comes up, in a Normal `A2ABusSingleServer` Event on the PlatformAgent that links [Changing the bus's server count](#changing-the-buss-server-count). It writes the Event once more after an operator restart. Ready and Degraded don't change. A one-server bus has no PodDisruptionBudget and no `safe-to-evict` annotation, since on Autopilot either can hold node upgrades.

After a node scale-down, GCE can keep a NATS disk attached to the node being deleted for tens of minutes. The bus pod's replacement then waits in `ContainerCreating`, with `FailedAttachVolume` (`RESOURCE_IN_USE_BY_ANOTHER_RESOURCE`) in the pod's Events only, until the old node is gone. On three servers the bus serves on two meanwhile.

The verifier's and the callout's topology spreads are `ScheduleAnyway`, so a single-node install still comes up. There the bus needs `busReplicas: 1`. On a cluster with no other schedulable node, such as a single-node install, a drain that evicts a callout waits until the node is uncordoned or the drain overrides the budget.

### Changing the bus's server count

On a bus that already runs, changing `busReplicas` between 1 and 3 starts a migration that keeps the bus's data. The operator runs it in phases, shown in `status.busMigration` and reported by the `A2ABusMigrating` condition. The admission webhook refuses another change to `busReplicas` while one runs. A run has two hours going forward; a phase still running then counts as failed, and the way back gets two hours of its own. Objects under a run's names that the PlatformAgent does not own are never used: a phase that finds one fails and names it.

A migration starts only on a bus whose provisioning has completed (`BusProvisioned`). A bus never provisioned, with no migration behind it, takes a changed count as asked, since it holds no data yet. That is how the count comes down on a cluster that can't schedule three servers. After a migration, the next one waits for the provisioning that follows it.

The operator runs the migration's work in pods of its own image, so it needs `OPERATOR_IMAGE` set, as the chart does. Without it a `busReplicas` change starts no migration: the bus keeps its count, and an `A2ABusMigrationUnavailable` Warning Event says why. The same holds, with the same Event, when the installed CRD is older than the operator and drops `status.busMigration`. The operator sees its first run's record dropped, and starts no other until the CRD is applied and the operator restarted.

**Three servers to one** happens in place. A Job of the operator's moves each stream's leader to server 0 and scales the stream to one replica while the bus is still a cluster; then the bus renders one server. Writes keep flowing, with brief stalls as leaders move and while server 0 restarts on its own.

A one-server bus starts its server with a `stale-cluster-meta` init step. A server that ran in a cluster keeps the cluster's metadata (`/data/jetstream/SYS/_js_`) while it runs alone, and a later move back to three servers would bring back, from it, streams that no longer exist. The step removes exactly that directory, and only on `<agent>-a2a-nats-0`, logging the path and size. It refuses a symbolic link on that path, failing the pod rather than following it: `kubectl logs <agent>-a2a-nats-0 -c stale-cluster-meta` says what it did.

**One server to three** copies the streams, behind a write freeze:

1. **The freeze.** The callout is rolled so that every replica authenticates only the migration. Then the bus restarts without its static application users. From then on, until the freeze lifts, connections drop and are refused: the console and web logins fail, the gateway and the bridge cannot publish, and tasks wait.
2. **The copy.** The operator's pod snapshots every stream to a staging claim. A pod with no bus access digests the snapshots, and the operator keeps the digests.
3. **The clear.** With the snapshot pinned, the operator's pod deletes the streams from the single server, so it joins the cluster with nothing on disk; the conversion would have dropped them anyway.
4. **The conversion.** The bus renders three servers. On a cluster that provisions nodes on demand, such as Autopilot, that includes the nodes for servers 1 and 2. The conversion has 15 minutes of its own (`status.busMigration.phaseDeadline`) to get all three Ready, so a cluster that cannot schedule servers 1 and 2 turns the run back then, not at the run's two-hour deadline.
5. **The restore.** The operator's restore pod restores each stream, with its consumers, and raises it to three replicas. Before it restores a stream, it checks the snapshot against the operator's digests and against the operator's policy for that stream: its subjects, limits and retention. The stream comes back with the limits the install renders now. A snapshot that does not fit them is refused, which turns the run back: more bytes than the rendered `max_bytes`, or an oldest message older than the rendered `max_age`. After, it checks the restored stream against the same policy and deletes one that fails.

   The one exception to the rendered limits is `max_consumers`. It is raised to the rendered value when the snapshot's is lower, and never lowered. A wider stream, or one with no limit, keeps its own, because its consumers must still fit.

6. **The settle.** Once every stream is raised, the restore pod waits, up to 5 minutes for all of them together, until each stream's replicas are current and each restored durable consumer answers from its leader. A stream that doesn't settle in that time turns the run back, like any failed restore.
7. **The release.** The bus restarts with its static users and the callout serves the install's identities again.

The freeze lasts as long as the copy, the conversion and the restore together, which is expected to be minutes; the restore's settle wait adds up to 5 of them. The staging claim is `ReadWriteOncePod`, on the default StorageClass, sized for every stream full to its cap plus 10% (15Gi today), so the default StorageClass must support that access mode.

Before a one to three run starts, the operator reads each stream's size from the bus's monitoring endpoint. If a stream holds more than the cap the restore puts on it, keeps a message older than its max age (a stream an earlier install kept longer), or the sizes can't be read, no run starts and nothing freezes. The bus keeps its one server, and an `A2ABusMigrationStreamsOverCap` Warning Event names each stream and the limit it is over. The operator checks again on later passes and starts the run once every stream is under its cap.

A stream the restore put back that differs from a fresh install of it, on a field outside its policy, is listed in `status.busMigration.warnings` and reported once as a `BusMigrationDrift` Warning Event. How long the streams took to settle is in `status.busMigration.settleTime`, and in a `BusMigrationSettled` Normal Event.

#### When a migration fails

Most failures turn the run back on its own. Three to one, before the bus has gone to one server, raises the streams back to three replicas. One to three, from the conversion on, renders one server again and restores the same snapshot into it, each stream as it was, its own limits included. A failed restore first deletes the cluster's partial copies; a failed conversion has none, since nothing was restored, and goes straight back to one server, whose `stale-cluster-meta` step removes the cluster's metadata.

In both directions the run then ends `Abandoned`: the bus runs as before, with its data, and the condition says why. To try the same count again, annotate the PlatformAgent `kubeagents.x-k8s.io/bus-migration-start=<run>`, naming the abandoned run. Spec changes to other fields, and syncs that change nothing, do not start a new run.

A failed way back stops for a person, and so does a failure with no way back (below). The run is then `Failed`, `status.busMigration.failedIn` names where, and the condition names the step to take. A `Failed` run blocks any other migration, and spec changes leave the bus as it is, until a person acts with an annotation on the PlatformAgent that names the run:

- **Retry:** `kubectl annotate platformagent <name> -n <namespace> kubeagents.x-k8s.io/bus-migration-retry=<run>-<attempt>`, with the value the condition gives. It runs the failed step again with a fresh deadline: the clear (from `Clearing`, keeping what it already deleted), the rollback (from `RollingBack` or `RollbackRestoring`) or the unpin (from `Unpinning`). A run may be retried three times; each attempt is recorded in `status.busMigration.retries`.
- **Give up:** `kubectl annotate platformagent <name> -n <namespace> kubeagents.x-k8s.io/bus-migration-abandon=<run>`. For a run that failed during the freeze, this lifts the freeze and runs the provision Job again at once, which recreates, empty, every stream the run did not put back. Ready waits for it. It deletes the staging claim and its snapshot, unless the claim holds the streams' only copy ([below](#recovering-a-given-up-runs-staging-claim)).

A rollback that failed keeps the write freeze, the staging claim and the operator's digests until then, so a retry restores the same snapshot. Before retrying, check the `<agent>-a2a-nats-0` pod, and the restore pod's termination message (`kubectl get pod <agent>-bus-rollback-<run> -o jsonpath='{.status.containerStatuses[0].state.terminated.message}'`), which names the stream and the check that failed.

#### Recreating TASKS wider

JetStream fixes a stream's `max_consumers` when the stream is created, and refuses to change it after. A TASKS stream created narrower than the PlatformAgent now renders, for example before `maxSessions` was raised, keeps its old width, and the provision Job refuses it. A one to three migration widens it on the way. On a bus that keeps its count, a person can ask for a reshape:

```sh
kubectl annotate platformagent <name> -n <namespace> --overwrite kubeagents.x-k8s.io/bus-reshape=<any new value>
```

A reshape is a migration run of leg `Reshape`, at the count the bus runs. It freezes writes as one to three does, snapshots TASKS alone, deletes it, and restores it at the rendered width, never narrower, with its messages, sequences and consumers. Then it lifts the freeze. Nothing else on the bus is touched. The freeze lasts as long as the bus's restart into it, the snapshot and restore of TASKS, and the restart out of it, which is expected to be a few minutes. The failure paths, the retry and the give-up are as for one to three. A failed restore puts TASKS back as it was.

It starts only when all of these hold. Otherwise a Normal `A2ABusReshapeNotStarted` Event says why:

- no migration is under way, and the last one isn't a `Failed` run waiting for a person;
- the bus is provisioned (`BusProvisioned`), or its provision Job refused only TASKS's width, as it does after a reshape given up with TASKS still narrow;
- the operator has its own image (`OPERATOR_IMAGE`);
- the installed PlatformAgent CRD keeps `status.busMigration`. An older CRD drops the run's record, so the request is refused, naming the CRD; once this release's CRD is applied and the operator restarted, the same request starts;
- the live TASKS is narrower than the width this PlatformAgent renders. A TASKS with no limit is never narrower;
- TASKS fits the limits the restore puts on it, as for one to three.

A value already acted on never starts a second reshape: the operator records it on the bus StatefulSet (`kubeagents.x-k8s.io/a2a-reshape-consumed`), where later migrations don't replace it. An annotation left in place is therefore inert. To ask again, after a reshape that was undone, set a new value. An operator rolled back to a release before reshapes holds a reshape under way ([below](#a-run-this-operator-does-not-run)), so roll back only to 0.35.0 or later, the first release with that hold.

#### A run this operator does not run

A later release may run a migration of a kind this one doesn't, and a rollback can find one under way. `status.busMigration.leg` then names a leg this operator does not run. Such a run is held, in whatever phase it is in. Nothing advances and no pod or Job is made. The run's deadline does not apply. The bus keeps its server count and the write freeze, and the provision Job waits. The `A2ABusMigrating` condition reads `LegUnknown`, and one `A2ABusMigrationLegUnknown` Warning Event names the leg.

There are two ways out. Either upgrade back to the operator that started the run, which carries it on where it is, or turns it back if the run's deadline passed during the hold, or give it up with `kubeagents.x-k8s.io/bus-migration-abandon=<run>`. Giving up works as it does for a `Failed` run: the freeze lifts, and the provision Job recreates, empty, every stream the run did not put back. It is never retried, since only the operator that started it knows its way back. Once such a run has ended, any `busReplicas` change starts a new migration as usual, since this operator can't read the ended run's target.

A run that failed in `Shrinking` (server 0 did not come up on its own) or in `Releasing` (the servers did not come back with their static users) has no way back to retry. The bus stays at the count it reached. Fix the `<agent>-a2a-nats` pods, then give the run up to allow the next migration.

#### Recovering a given-up run's staging claim

A one to three run that failed at or after its clear, which emptied the single server, may have the streams' only full copy on its staging claim. Its `failedIn` is then any phase from `Clearing` on: `Clearing`, `Converting`, `Restoring`, `RollingBack`, `RollbackRestoring` or `Releasing`. Retry such a run rather than give it up while retries are left: a retry restores the snapshot into one server on its own.

If it is given up anyway, the operator lifts the freeze, the bus runs one server, and the provision Job recreates every stream empty. It keeps the staging claim `<agent>-bus-stage-<run>` and the run Secret `<agent>-bus-run-<run>`, which holds each snapshot file's SHA-256, and the `A2ABusMigrating` condition names both. It does not restore the snapshot, and it does not delete either object; both are owned by the PlatformAgent, so deleting the PlatformAgent deletes them. A run's object name that would pass 63 characters ends in a hash in place of the run. Find them by their labels (the instance label is `<namespace>-<name>`, cut to 63 characters):

```bash
kubectl get platformagent <name> -n <namespace> \
  -o jsonpath='{.status.busMigration.runID} {.status.busMigration.failedIn} givenUp={.status.busMigration.givenUp}{"\n"}'
kubectl get pvc,secret -n <namespace> \
  -l kubeagents.x-k8s.io/a2a-component=bus-migration,app.kubernetes.io/instance=<namespace>-<name>
```

To keep the data past the PlatformAgent, keep the volume when its claim is deleted, and take the claim out of the PlatformAgent's ownership:

```bash
PV=$(kubectl get pvc <claim> -n <namespace> -o jsonpath='{.spec.volumeName}')
kubectl patch pv "$PV" -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
kubectl patch pvc <claim> -n <namespace> --type=json -p '[{"op":"remove","path":"/metadata/ownerReferences"}]'
kubectl get secret <agent>-bus-run-<run> -n <namespace> -o jsonpath='{.data.run\.json}' | base64 -d > run.json
```

The claim holds one directory per stream, each with `stream.tar.s2` (the server's snapshot of the stream) and `meta.json` (its config and state when snapshotted). To copy it out, mount it read-only in a pod of your own (the claim is `ReadWriteOncePod`, so nothing else may hold it):

```bash
kubectl apply -n <namespace> -f - <<'YAML'
apiVersion: v1
kind: Pod
metadata:
  name: bus-stage-reader
spec:
  securityContext: { runAsNonRoot: true, runAsUser: 65532, fsGroup: 65532, seccompProfile: { type: RuntimeDefault } }
  containers:
    - name: reader
      image: busybox:1.37
      command: ["sleep", "3600"]
      securityContext: { allowPrivilegeEscalation: false, readOnlyRootFilesystem: true, capabilities: { drop: ["ALL"] } }
      volumeMounts: [{ name: stage, mountPath: /stage, readOnly: true }]
  volumes:
    - name: stage
      persistentVolumeClaim: { claimName: <claim>, readOnly: true }
YAML
kubectl exec -n <namespace> bus-stage-reader -- sh -c 'cd /stage && sha256sum */stream.tar.s2 */meta.json'
kubectl cp <namespace>/bus-stage-reader:/stage ./bus-stage-<run>
kubectl delete pod bus-stage-reader -n <namespace>
```

The checksums should match the `data` and `meta` digests in `run.json`. The bus already runs one server, so set `busReplicas: 1` to match it. While the field asks for three, no new run starts unless the `bus-migration-start` annotation names the given-up run. A new run would snapshot the empty streams onto a claim of its own. Putting the old data back is manual: the operator has no command for it, and restoring a stream takes a bus client allowed `$JS.API.STREAM.RESTORE` on it, which only a migration's own identity holds, and only during its restore. Delete the claim once the data is safe or not needed.

The operator keeps the claim on every such give-up, including one where a restore or a rollback restore had already put every stream back. A claim left over then is the accepted cost of never deleting a copy that might be the only one. To tell whether it's safe to delete, compare each stream's `state.messages` and `state.last_seq` in its `meta.json` on the claim with the same stream on the bus. If every stream on the bus has at least as many messages, and the same last sequence or a later one, the bus holds everything the claim does.

Disabling Google Chat afterwards, with no other backend configured, leaves the gateway running on the console door alone.
The A2A gateway serves Prometheus counters on a metrics-only port, 9096 (container port `a2a-metrics`, set by `A2A_METRICS_PORT`), which the chart's `<name>-a2a-gateway-monitoring` `PodMonitoring` scrapes behind `platformAgent.podMonitoring`; the metrics are listed on [Observability](/kube-agents/concepts/observability/). The gateway's NetworkPolicy, `<name>-a2a-gateway-netpol`, renders wherever the gateway does, eval door or no door. It admits the `gke-gmp-system` namespace and the operator's own pods to that port and nothing else, the operator because its usage poller reads the gateway's inbound-message counter into `status.usage.chatMessagesInboundTotal`.

The same port answers `/readyz`, which the gateway Deployment's readinessProbe reads every 5 seconds: 503, with the reason, until the gateway has bound its event relay, which on a fresh install waits for the provisioning Job's `TASKS` stream. The kubelet's probe comes from the node, which the policy does not govern.

The gateway's egress is governed by a second policy, `<name>-a2a-gateway-egress`, which renders and goes with that one. It admits cluster DNS, the bus, the credential broker and the Kubernetes API server on their ports. It also admits TCP 443 except to private, link-local and shared addresses, for the chat platforms the gateway dials directly. Where the CNI enforces NetworkPolicy, everything else the gateway sends is denied.

## `spec.harness`

This section has its own dedicated reference page: [PlatformAgent: Harness configuration](/kube-agents/operator/platformagent-harness/).

## `spec.deployment`

Abstracts the pod/deployment configuration. The controller synthesises a `Deployment` from these plus the workspace ConfigMaps. Available fields:

- `image` — container image repository.
- `tag` — image tag. Applies only when `image` is set without a tag or digest, falling back to `latest` there; when `image` is omitted, the operator's default platform-agent version applies instead. The credential broker's image is derived from the same repository and tag unless `CREDENTIAL_PROXY_IMAGE` (the chart's `credentialProxy.image`) pins it, and a pinned one must be at least as new as the operator. The operator reads the broker's readiness on a health listener (port 8768) that older broker images do not open, so a broker Pod running one never becomes Ready.
- `imagePullPolicy` — one of `Always`, `Never`, `IfNotPresent`. Default `IfNotPresent`.
- `imagePullSecrets` — Secrets in the agent's namespace holding registry credentials, as
  `- name: <secret>` entries. Referenced, not created: each must exist before the pod is
  scheduled. Pod-scoped, so it covers the agent, both injected sidecars, anything in
  `initContainers`/`sidecars`, and the OCI image volumes `AgentPlugin`s mount.
- `browserArgs` — extra command-line args for the agent's browser (e.g. `--no-sandbox`).
- `availability.replicas` — the gateway's replica count, default 1. The operator runs the gateway
  as a single replica: a value above 1 renders exactly what 1 renders (one replica, `Recreate`, no
  leader election, ReadWriteOnce default claims), and the `ReplicasLimited` condition
  ([`status`](#status) below) says so. High availability is not supported yet.

  Above one replica the gateway container would run `leader_elect.py`, which needs an in-cluster
  ServiceAccount token that container deliberately does not have, so it exits at startup; and the
  data volumes an install creates at one replica are ReadWriteOnce, so a replica scheduled on
  another node cannot attach them. The field is not refused at admission, so a CR that already asks
  for more keeps reconciling. On such an install, claims created earlier keep their access mode,
  since claims are created once; and a gateway that ran as a StatefulSet (more than one replica over
  ReadWriteOnce `storages`) is replaced by the Deployment, which mounts new claims.

  Set it to 1, or remove it, to clear the condition. That can leave the ReplicaSet from the higher
  count behind, still running pods that crash-loop: if gateway pods keep failing after the condition
  clears, find it with `kubectl get rs -n <namespace> -l app=platform-agent-gateway` (a ReplicaSet
  that isn't the current one but still has replicas) and run
  `kubectl scale rs <name> -n <namespace> --replicas=0`.

- `availability.a2aGateway.replicas` — the A2A gateway's replica count, default
  2, minimum 1, maximum 5. One replica holds the gateway's Lease and does the work; the others stand by and
  take over within the lease's 20s if it stops. The operator renders more than one only once a
  gateway pod on the image it renders holds the Lease (the `GatewayElected` condition), and one
  with `Recreate` until then. Two or more roll with a surge pod, so the namespace's ResourceQuota
  needs room for one more gateway pod during a rollout; set 1 where it has none. An install upgrading from one gateway pod
  goes to two once its new gateway holds the Lease.

  The chart's quota check and the operator's own session pod quota both count the standby and
  the surge pod.

  The elected gateway depends on the API server. A leader whose renewals fail stops about 12s
  after its last good renewal, and no replica leads until the API server answers again. Chat, the
  console and the relay stop for the length of a control-plane outage, and a zonal cluster's
  control-plane upgrade is several minutes of that. Run a regional control plane where the gateway
  must stay up through one.

- `availability.runtimeClassName` — pod runtime class (e.g. `gvisor`) for the agent Pod. Nested under `availability` alongside `replicas`, `nodeSelector`, `tolerations` and `affinity`. When set, the managed config also carries `database.journal_mode: delete`, and the entrypoint converts Hermes' existing databases out of WAL once at start-up — `state.db`, `kanban.db` and the cron, project, evidence, response, memory and Discord stores Hermes opens through the same journal-mode helper. A sandboxed runtime serves the data volume over a gofer mount that accepts SQLite's WAL mode and then corrupts it. The Session KV store (`session_kv.db` on the `system-metadata` volume) sets WAL itself and is not covered by either. Clearing the field drops the pin, and the databases return to WAL on their next open.
- `env` — additional container environment variables.
- `resources` — requests and limits for the agent container, replacing the operator's defaults as a block. The memory request is also the dispatcher's default admission budget ([`tuning.admission`](/kube-agents/operator/platformagent-harness/#specharnesstuning)), so raising it admits more workers at once. Setting it below `workerRssCapMiB` without raising `admission.memoryBudgetMiB` or lowering `workerRssCapMiB` is rejected where the validating webhook is enabled, or reported as `Degraded` (`InvalidKanbanAdmission`).
- `credentialProxy.resources` — requests and limits for the credential-proxy container, the broker that runs every credentialed command in a pod of its own. Merged over the operator's defaults per key, unlike `resources`; [`spec.deployment.credentialProxy.resources`](#specdeploymentcredentialproxyresources) has the defaults it keeps, what the operator refuses, and what admission warns about.
- `credentialProxy.exec.replicas` — the number of exec-tier broker pods, 0 to 32: stateless replicas beside the broker pod that answer `/v1/exec` and `/v1/gcp/` only. 0, the default, renders none. A positive count renders the `<name>-credential-proxy-exec-tier` Deployment, Service, count ConfigMap, NetworkPolicy and (from two replicas) PodDisruptionBudget, and gives the sandbox, the profile workers and the session pods its address. Each replica requests and is limited to 2 CPU and 2Gi, so each one needs a node with that much free, and the pods that turning the tier on restarts (below) need room to start again.

  Turning it on or off restarts the shell sandbox and the profile warm pools, and the A2A gateway under the cluster view; changing between two positive counts restarts nothing. With a positive count the agent's name must be at most 36 characters, or it is refused and `Degraded` reports `InvalidCredentialProxyExec`. The operator does not size the tier from the fleet; [`CredentialProxyExecReady`](#status) reports its Ready replicas, and `Unschedulable` with the scheduler's message for a replica that has no room.

- `agentAPIAuth.resources` — requests and limits for the `agent-api-auth` sidecar in the gateway pod, the native container that authenticates the agent's API-server calls and also runs the event watcher and the drift detector, and the audit-report store listener on 8700. Merged per key over the operator's defaults, or over the [`sizingProfile`](#specdeployment) row when one is set, like `credentialProxy.resources`: a CR that sets only `limits.memory` keeps the default 150m CPU request, 384Mi memory request, 1 CPU limit and 2Gi ephemeral-storage limit.

  The event watcher reads the memory limit through the Downward API and sets its Go soft memory limit to half of it, so raise `limits.memory` when the watcher is OOM-killed under a large fleet of watched clusters. Overriding `limits.cpu` also changes the watcher's `GOMAXPROCS`, which the Go runtime derives from the container's CPU limit, so leave `limits.cpu` at the default unless you mean to. Only `cpu`, `memory` and `ephemeral-storage` are accepted.

  The startup peak depends on the control plane. With the `WatchList` feature gate, on at Kubernetes 1.32 and from 1.34, the watcher holds a cluster's whole initial stream until its end, so up to four of the largest backlogs are resident at once. Without the gate the watcher reads the backlog in pages of 500 Events and holds one page per cluster. Steady state scales with the number of watched clusters and their open incidents.

  The operator refuses a request above its limit, a negative quantity, a zero limit, `claims`, and any other resource name, whether or not the webhook is on. It ignores the override, renders the sidecar at the profile's row (the operator's defaults under `small`), and reports `Degraded` with reason `InvalidAgentAPIAuthResources` when no higher-ranked `Degraded` cause is present, the agent staying Ready. There is no memory floor, unlike the credential proxy, because the watcher derives no admission count from the limit. Where the [validating webhook](/kube-agents/operator/#admission-webhooks) is enabled, admission refuses the same override at apply, and warns on the GKE Autopilot memory-per-vCPU band and on a `cpu` or `memory` limit set without the same key under `requests`, for the reasons `credentialProxy.resources` gives.

- `initContainers` / `sidecars` — standard init and sidecar containers. A `volumeMounts` entry naming a reserved volume is refused at admission, the same as `extraVolumeMounts`. That is the route that needs no user-authored volume at all, and so the one the name reservation exists for; see [Reconcile behavior](#reconcile-behavior).

  The render also writes two environment variables onto every `sidecars` entry — `POD_NAMESPACE` (downward API) and `A2A_CAPABILITY_REQUIRED` — with different precedence. The operator's `A2A_CAPABILITY_REQUIRED` wins, so a value set for that name in the CR is discarded on every reconcile, while `POD_NAMESPACE` is supplied only as a default and a CR value for it survives. Both are inputs to the A2A capability check the sidecar executor performs, not container configuration; nothing else in the container is rewritten.

- `extraVolumes` — custom volumes for the main container. Both halves of the reservation apply: a reserved name, and a source that would carry the A2A bus credential or watcher token, are each refused at admission; see [Reconcile behavior](#reconcile-behavior).
- `extraVolumeMounts` — custom mounts for the main container. A mount has no source, so only the name half applies: an entry naming a reserved volume is refused at admission.
- `sidecarVolumes` — custom volumes for the sidecar containers. Same reservations as `extraVolumes`.
- The watchers' broker token is reserved on all five surfaces. The webhook refuses the volume name
  `watcher-credential-proxy-token` on `sidecars`, `initContainers`, `sidecarVolumes`, `extraVolumes`
  and `extraVolumeMounts`, and any volume projecting the `kubeagents-credential-proxy-watcher`
  audience under another name. Where the webhook did not run, the controller leaves out of the Pod
  template any user volume under that name or projecting that audience, together with every
  `volumeMount` naming one across all five surfaces. The `VolumesDropped` condition names the
  dropped volumes and bare `watcher-credential-proxy-token` mounts with reason
  `WatcherTokenVolumeDropped` (or `HostPathVolumeDropped` when a `hostPath` volume is dropped too).
  The token belongs to the gateway's `agent-api-auth` container alone.
- A `hostPath` entry on either volume list is refused at admission, and on an install where the
  webhook did not run (the Helm chart ships it off, and one enabled through the chart fails open at
  its default `failurePolicy: Ignore`) the controller leaves it out of the Pod template at render,
  together with every `volumeMount` naming it on the agent container, the dashboard container, and
  the CR's own `sidecars`/`initContainers`. The rest of the template renders as written, and the
  `VolumesDropped` condition ([`status`](#status) below) names what was left out — as many entries
  as fit in 4096 bytes, then a count of the rest, and an entry longer than that on its own cut with
  `...`.

  The budget is the controller's, not the schema's: a condition message may hold 32768 characters,
  and the list stops well short of it because `kubectl describe` is where it is read and the first
  few entries are what anyone acts on. Volume names and host paths are the author's, and nothing
  bounds their length or their number, so an unbounded list would be one spec away from failing
  the whole status write — `Ready`, the phase and every other condition with it.

- `podAnnotations` — annotations applied to the generated pod template.
- `scaleToZero` — when `true`, scales the gateway Deployment to 0 replicas (idle cost saving). The shell sandbox, the credential broker and the A2A stack keep running. Once the gateway has no ready replica the `PlatformAgent` reads `phase: Paused`, with `Ready` `False` and reason `ScaledToZero`. That tells a paused install from one whose rollout never finishes. Set the field to `false` or remove it, and the normal phases return: `Provisioning` while the gateway starts, then `Ready`. [What `Ready` reports](#what-ready-reports) has the detail. On the way back the Platform Agent's scheduled audits do not all start at once: [Catch-ups after a pause](/kube-agents/concepts/autonomous-watchdogs/#catch-ups-after-a-pause).
- `sizingProfile` — the preset row the credential-proxy container, the `agent-api-auth` sidecar and the shell container start from, before the per-key overrides above and under [`shellSandbox`](/kube-agents/operator/platformagent-harness/#shellsandbox) are applied over it; an explicit key always wins. One of `small` (the default, and what an absent field means: the operator's defaults as documented above), `medium`, `fleet` or `auto`. The agent container's own `resources` are not part of a profile.

  | Tier     | Credential proxy                                                                                     | `agent-api-auth`   | Shell            |
  | -------- | ---------------------------------------------------------------------------------------------------- | ------------------ | ---------------- |
  | `small`  | the defaults above                                                                                   | the defaults above | the defaults     |
  | `medium` | 1 CPU and 4Gi requests (2 CPU and 4Gi on GKE Autopilot), 2 CPU and 4Gi limits, 8Gi ephemeral-storage | 4Gi memory limit   | the defaults     |
  | `fleet`  | 4 CPU and 8Gi requests, 8 CPU and 8Gi limits, 8Gi ephemeral-storage                                  | 8Gi memory limit   | 4Gi memory limit |

  Figures a row does not name keep the small row's. `auto` promotes the tier from the cluster count the operator polls into `status.usage`, the larger of `clustersRegistered` and `clustersMonitored`: `medium` at 10 clusters, `fleet` at 25. It continues from the tier `status.effectiveSizingTier` holds: `small` on a CR that never named a tier, and the explicit tier on one that did. A CR moved from `fleet` to `auto` therefore stays at `fleet`; set `small` first to restart it from `small`. A promotion is upward only, latched in that status field, so a count that falls never lowers the tier, and a recreated CR starts again at `small`.

  Before each step up the operator reads every ResourceQuota in the namespace. On each constrained `cpu`, `memory` and `ephemeral-storage` key, requests and limits sides alike, it compares the free quantity with what the step adds across the three containers. The difference is what admission has to find room for, because each of the three pods is replaced rather than surged. It tries the earned tier first, then each tier between it and the running one, every step measured from the running tier, and takes the highest step the quotas admit. A count that earns `fleet` with room for the `medium` step alone reaches `medium`; when every step is short the running tier stays.

  With a quota or a LimitRange in the namespace, a step is measured only once the running tier's workloads have settled: each carries the tier's resources, its rollout is complete and every replica is available. A quota's used total charges a step only when admission has created its pods. So the pass after a promotion, while the broker recreates, measures nothing and leaves the tier and the condition as they are. Each such pass logs the hold and the workload it waits on.

  A workload that is not there has not settled either. The quota charges nothing of it while the step is measured from its row, and a `Pod`-type LimitRange item is read against its template. So the pass that recreates it is the one that lifts the hold.

  On GKE Autopilot without Pod bursting admission sets every limit equal to its request. The operator reads that clamp from Autopilot's own record, the `autopilot.gke.io/resource-adjustment` annotation on the running templates. A limit the record shows lowered to its request is read through the requests side when the settled check compares a template with the tier's figures. When any record shows the cluster clamps, every `limits.*` key of a step is compared with the requests' movement, the figure admission charges there, rather than with the rows' limits. With no such record (GKE Standard, Autopilot with bursting) limits are compared and counted as written.

  Any refused step sets the `SizingCappedByQuota` condition ([`status`](#status) below) naming the quota and the key, rather than rolling out pods the quota would refuse. The message names the tier earned, the running tier the refused step was measured from, and the tier that stays. A count that earns `fleet` with room for the `medium` step therefore reads as the step up from `small` until the `medium` pods settle. The step from `medium` is then measured, the message changes once, and the Warning event carries that step's figures.

  A quota whose scopes cannot select these pods is not read, as admission would not read it: `Terminating`, `BestEffort`, `CrossNamespacePodAffinity`, `VolumeAttributesClass`, or a `PriorityClass` requirement that does not match the class admission gives these pods. `NotTerminating` and `NotBestEffort` quotas bind them and are read. An explicit tier is applied as written, without the check.

  That class is the one admission gives the pod a step recreates. The operator asks for it with a server-side dry-run create of a Pod built from the broker Deployment's template, which runs the API server's Priority plugin and persists nothing. The answer is none on a cluster with no `globalDefault` PriorityClass, and the default's name on one that has it, created before or after the install. A quota scoped `In` that default then binds the pods and is read. Admission is asked only when a `PriorityClass`-scoped quota constrains a cpu, memory or ephemeral-storage key. One that counts `pods` or `count/*` alone cannot refuse a step, so it asks nothing.

  When the dry run is refused, the step is held: nothing is measured, the tier and any standing condition stay as written, and the pass logs the hold until admission answers. A broker Deployment that does not exist yet holds the step the same way, before admission is asked.

  The check reads the quotas once, and the broker's Recreate asks admission for its new pod only after the old one has drained, so a pod the namespace admits in between can take the room the check found. When the proxy or the gateway Deployment then carries `ReplicaFailure` with admission's `exceeded quota` message, the next pass steps the latch back one tier and sets `SizingCappedByQuota` naming the quota and that message.

  The refusal is read only when a key it names is one the step up to the latched tier raised on that pod, and the figure it asked for is under the row above's. A `pods` count at its cap, a key no row moves, or the old ReplicaSet's refusal lingering after a step back is left to the settled hold instead.

  The lower row is rendered, and once its pods settle the step up is measured again, after a hold of ten minutes from the step back; a pod refused at the lower row too is stepped back from in turn. The shell StatefulSet carries no such condition, so its refused pod shows as the settled hold in the operator log.

  The check also reads the namespace's LimitRanges, before the quotas, as admission does. Each `Container`-type item's `max`, `min` and `maxLimitRequestRatio` are compared with the three sized containers' requests and limits at the candidate row. Each `Pod`-type item's are compared with the sums of the pods those containers run in, read off the running templates with the sized container's figures swapped for the candidate row's. The limits are read through the Autopilot clamp where the running templates show one. A row that crosses a bound is refused and the condition names the LimitRange, the item's scope, the bound, the resource and the container, with reason `LimitRangeShort` and the figures in a `SizingCappedByLimitRange` Warning event.

  Neither check reads node capacity. On GKE Standard the `medium` and `fleet` rows' broker requests (1 and 4 CPU) have to fit on one node before the recreated broker can start. A Standard pool therefore needs nodes that fit the `fleet` row's 4 CPU request (`e2-standard-8` or larger) before the count reaches 25 under `auto` ([the sizing guide](/kube-agents/deploy/fleet-sizing/#option-b-gke-standard)).

  A change of tier recreates the proxy pod once and rolls the gateway and the shell pod, as a `resources` change does. The usage poller takes its first reading 30 seconds after the operator is elected and every five minutes after. An operator restart on a running install therefore re-reads the count within a minute; a fresh install is sized on the first poll that reads the gateway.

  Admission and the reconciler validate an override against the row the CR renders: the explicit profile's, or under `auto` the tier `status.effectiveSizingTier` holds, `small` before the first pass writes one. A CR run at an explicit `fleet` with an override the fleet row admits, a 3 CPU request on the proxy, say, keeps it when switched to `auto`, since the latch stays at `fleet`. A higher row never refuses an override a lower one admitted; a step back to a lower row that refuses one renders that row and reports `Degraded` until the override is corrected, as an override that was never valid does.

Default image: derived dynamically from the operator's container image at runtime via the `OPERATOR_IMAGE` env var on the controller manager (e.g. `ghcr.io/gke-labs/kube-agents/platform-agent:<version>`), overridable operator-wide via the `PLATFORM_AGENT_IMAGE` env var on the controller manager (see [Docker images § Private / custom registry](/kube-agents/deploy/docker-images/#private--custom-registry)), and falling back to `ghcr.io/gke-labs/kube-agents/platform-agent:latest` if neither is set. Rebuild with `make dev-rebuild-agent ARGS="platform"` for local iteration.

`imagePullSecrets` has the same operator-wide form, `IMAGE_PULL_SECRETS` on the controller manager, taking comma-separated Secret names. It differs from the image overrides in one way: a CR that sets `imagePullSecrets` **replaces** the operator's list rather than merging with it, so an agent that names its own registry identity is stating it completely. See [Docker images § Registry authentication](/kube-agents/deploy/docker-images/#registry-authentication).

### `spec.deployment.credentialProxy.resources`

`credentialProxy.resources` is merged over the operator's defaults per key, unlike `resources`: a CR that sets only `limits.memory`, at or above the default memory request, keeps the default requests, the 2 CPU limit and the 8Gi ephemeral-storage limit, which bounds the broker's scratch clones. The proxy's state emptyDir (size limit 5Gi) grows by whatever that limit is raised above the 8Gi default, and its `/tmp` emptyDir keeps its 2Gi, so the kubelet does not evict the pod at the smaller figure.

The default requests are 500m CPU and 1Gi of memory, and on GKE Autopilot 2 CPU and 2Gi, because Autopilot without bursting clamps the limits to the requests. A `cpu` or `memory` limit set without its request, below the default request, lowers that request to the limit. On Autopilot a CPU request the CR does not set is held to at most one CPU per GiB of the memory request, so the pair does not fall under the band's 1 GiB per vCPU floor.

The broker sizes how many commands it admits at once from the memory limit, so that is the key to raise when the proxy is OOM-killed under a large fleet, or pick a [`sizingProfile`](#specdeployment) row that raises it. Only `cpu`, `memory` and `ephemeral-storage` are accepted, the quantities the container declares.

**What the operator refuses.** A memory limit below 544Mi (two commands at once), a request above its limit, a negative quantity, a zero limit and `claims`, which the proxy pod has no use for. A refused override, including an edit of one that was valid, renders the proxy Deployment at the sizing profile's row (the operator's defaults under `small`) rather than at the last accepted override until it is corrected, which restarts the proxy once (its Deployment is `Recreate`), and the agent stays Ready whether or not the webhook is on. The `Degraded` condition carries one reason, and reports `InvalidCredentialProxyResources` when no higher-ranked `Degraded` cause is present.

**What admission adds.** Where the [validating webhook](/kube-agents/operator/#admission-webhooks) is enabled, admission refuses the same override at apply and the running proxy is untouched. Admission also warns, using the Autopilot default requests on every cluster type, when memory per CPU on the requests pair leaves the 1 to 6.5 GiB per vCPU band GKE Autopilot admits unchanged, because Autopilot then raises the smaller request and the chart's quota preflight is short by the difference; Autopilot applies the band to requests only.

It warns too for each of `cpu` and `memory` set under `limits` without the same key under `requests`, unless the limit equals the request it would be replaced by: Autopilot without bursting sets the limits equal to the requests, so a CR that sets only `limits.memory: 3Gi` runs at the 2Gi request there. Set the request to the same value, or enable bursting, under which the declared limits stand.

## `spec.security`

- `serviceAccountName` — the KSA the credential broker Pod runs as, with its Workload Identity binding. `kubeagents-platform-agent` by convention. The gateway Pod runs as its own `<name>-gateway-agent`, which the operator creates; a value naming that or another operator-created ServiceAccount is refused.
- `serviceAccountAnnotations` — passed through to the KSA. Typically holds `iam.gke.io/gcp-service-account` for Workload Identity binding.
- `workloadIdentityFederation` — `audience` (the pool provider's full resource name) and `serviceAccountEmail` (the GSA to impersonate). Set both, or neither: a half-filled block is read as absent. Optional hardening: with it set, the credential broker takes its GCP identity from a projected token file in its own Pod rather than from the metadata server. Without it the broker uses the Workload Identity annotation on its own ServiceAccount; the gateway runs as a separate ServiceAccount with no annotation either way. The chart sets both from `platformAgent.security.workloadIdentityFederation`; nothing creates the pool, and those commands are in [`designs/agent-shell-sandboxing.md`](https://github.com/gke-labs/kube-agents/blob/main/docs/designs/agent-shell-sandboxing.md#setting-up-the-pool).

- `egressPolicy` — `None` (default) or `Allowlist`. `Allowlist` renders a default-deny egress NetworkPolicy on the agent Pod, with the link-local metadata server's credential API left off the allowlist (the address is permitted on port 53 alone, where it is the Cloud DNS for GKE resolver). **It blocks nothing today, and cannot — unless `networkPolicy.enabled: false` has withheld the gateway policy, in which case this becomes the Pod's only policy and default-denies for real on an enforcing CNI.**

  Everywhere else: adding a policy is monotone — policies selecting one Pod are unioned and the API has no deny rule — and the same Pod is already selected by `<name>-gateway-netpol`, which names `169.254.169.254/32` on port 53 only (the resolver; it opens no metadata path) and permits TCP 443 to `0.0.0.0/0` minus the private and link-local ranges. So enabling this widens the Pod's permitted egress (by the broker on 8765, and by the managed collector namespace on 4317/4318 when the agent is not exporting telemetry) and narrows nothing; what you get is an auditable object, not enforcement.

  The gateway no longer holds a cloud identity and its policy opens no metadata path; narrowing `<name>-gateway-netpol`'s internet rule is what turns this field into a control, and the capability cost lands then. It will also do nothing on a cluster whose CNI does not enforce NetworkPolicy, which the operator cannot detect. See [Credential isolation § Denying the sandbox the metadata server](/kube-agents/reference/credential-isolation/#denying-the-sandbox-the-metadata-server).

- `egressAllowlist` — tunes `egressPolicy: Allowlist`. `controlPlaneCIDRs` permits the Kubernetes API server on 443 (absent by default, which costs the agent container its API-server connection; a bare address — what the documented `gcloud` command emits for a public endpoint — is widened to a single-host prefix). `extraRules` are NetworkPolicy egress rules appended verbatim, except that a rule the operator will not render is refused loudly rather than silently dropped. The agent goes `Degraded`/`EgressAllowlistRefused`, the workload stops being reconciled, and the policy keeps being rendered minus the refused destinations. The refused shapes:
  - an `ipBlock` reaching a metadata address, including in IPv4-mapped form;
  - a rule with no `to` peers;
  - a peer naming no `ipBlock`, `podSelector` or `namespaceSelector`;
  - an invalid CIDR, in `cidr` or `except`;
  - an `except` outside its `cidr`, which the API server would reject in a way that wedges the whole reconcile;
  - `controlPlaneCIDRs` wider than /16 IPv4 or /32 IPv6.
- `scopedServiceAccountPool` — the [scoped service account pool](/kube-agents/reference/security-and-iam/#the-scoped-service-account-pool): the switch that arms it and the project→service-account mapping it serves. Absent (the default) the pool is disarmed and the broker runs on the agent's own identity, with `CREDENTIAL_PROXY_SCOPED_SA_POOL=0` on its container. **Leave it off for now**: pool members currently hold no IAM grant, so an armed pool turns every mapped-project read into a `Forbidden` — see the caution on the pool section.
  - `enabled` — arms the broker, and is the only thing that does: a populated `serviceAccounts` list with `enabled: false` renders nothing, and a project declared in `spec.scope` arms nothing either. With it true the operator renders the mapping into the credential-proxy ConfigMap (`scoped-sa-pool.json`, version 2, sorted by `projectId`), mounts it read-only, and sets `CREDENTIAL_PROXY_SCOPED_SA_POOL=1`. The broker then mints a short-lived token for the account a request's project maps to and refuses a project with no entry (`403`, rule `gcp.scoped-sa.unmapped-scope`) rather than falling back to the ambient credential. `enabled: true` with an empty list is rejected at `kubectl apply`, since the broker refuses to start on an empty pool.
  - `serviceAccounts` — one `{projectId, serviceAccountEmail}` entry per GCP project the agent may read, each account provisioned by Terraform in the host project (the composition's `scoped_service_accounts` output is the source). Keyed on the project rather than the cluster: the project is the IAM unit a scope declaration is written in, and two clusters in one project share an account by design.

    The list is keyed on `projectId` so a duplicate project is rejected at `kubectl apply` rather than crashlooping the broker at startup; both fields are pattern-validated, and there is no entry cap — the Terraform module's `scoped_pool_max_accounts` is the bound declared on the pool from the host project's free service-account quota, and the plan holds the derived set to it before any entry reaches this list.

The Workload Identity target GSA (`kubeagents-platform-gsa@<project>.iam.gserviceaccount.com`) is created and bound by the [`kube-agents-iam` Terraform module](https://github.com/gke-labs/kube-agents/tree/main/terraform/modules/kube-agents-iam) with one of these permission sets:

- `read-only` (default)
- `custom` (roles supplied via the installer's `--custom-roles`, the composition's `project_roles`)

## `spec.scope`

This section has its own dedicated reference page: [PlatformAgent: Scope, networking, and integrations](/kube-agents/operator/platformagent-scope-integrations/).

## `spec.hold`

Optional. An operator's pause for one cluster, several, or all of them. The credential broker and
`kube-proxy` refuse a held cluster's Kubernetes API to every caller, on the same routes as
[`spec.scope.exclude.clusters`](#specscope), usually within a minute or two of the edit and without
restarting any pod. Unlike an exclusion, a held cluster keeps its Cluster Agent profile and its
place in fleet answers and audits; those runs meet the same refusal.

- `clusters` — single clusters by `projectId`, `location` and `clusterName`, matched as
  `exclude.clusters` entries are.
- `all` — `true` holds every cluster, the one the harness runs in included.
- `reason` — up to 256 characters, quoted in every refusal.

A held cluster is refused as `scope.held-cluster` (a rule of the `scope.*` family it shares with
[exclusions](#specscope)), with a message that names the hold and its reason
and tells the agent to report it and stop. A Cluster Agent task that targets a held cluster is
refused for every command, metadata reads included. The Platform Agent's own reads of the GKE
control plane for it (the project's cluster list, a cluster's describe) stay allowed. A broker or
`kube-proxy` that can't read the hold file it was given reaches no cluster until it can
(`scope.hold-unreadable`).

A hold, like an exclusion, is checked when a request starts. A watch, a followed `kubectl logs -f`,
an exec, attach, port-forward or proxy stream, or a watcher stream the broker relays that was opened before
the hold reached the component keeps running until it ends.

The operator renders the hold into the `<agent>-hold` ConfigMap (`hold.json`), which no pod
template hashes, so the edit rolls nothing: the kubelet updates the mounted file and both components
read it again on their next request. `install.env` has no key for it, the chart never renders it,
and an upgrade leaves it on the CR. Set it with a patch, and lift it by removing it:

```bash
kubectl patch platformagent platform-agent -n kubeagents-system --type merge -p \
  '{"spec":{"hold":{"clusters":[{"projectId":"payments-prod","location":"us-central1","clusterName":"prod-1"}],"reason":"INC-1234: rollback in progress"}}}'

# Every cluster:
kubectl patch platformagent platform-agent -n kubeagents-system --type merge -p \
  '{"spec":{"hold":{"all":true,"reason":"change freeze"}}}'

# Lift:
kubectl patch platformagent platform-agent -n kubeagents-system --type json -p \
  '[{"op":"remove","path":"/spec/hold"}]'
```

## `spec.storage`

Optional. `size` is the request of the agent's `<name>-data` claim, mounted at `/opt/data`, and of
the shell sandbox's data claim at the same path. The operator requests the same size for both claims
and grows the sandbox's claim first, so the copy the sandbox takes of the agent's working
directories fits. A StorageClass or a quota that refuses the growth of one claim can leave the two
claims at different sizes. Absent, or with no `size`, the
operator default of `50Gi` applies; the CRD declares no default, so a later raise of the operator
default reaches every CR that does not set the field.

Raising it expands both existing claims online, with no pod restart, where the claim's
StorageClass sets `allowVolumeExpansion: true`. The shell sandbox's StatefulSet is recreated once,
because its claim template cannot change in place; the sandbox pod keeps running. Each GiB added
counts twice against a namespace `requests.storage` quota and against the project's disk quota,
once for each claim, except on the agent's claim while `expectedClusterProfiles` holds it above
`size`.

Where the class cannot expand the claim (`allowVolumeExpansion` false or unset, a claim with no
StorageClass, or a class that does not exist), the operator leaves the claim at its size and sets
the `DataVolumeNotExpanded` condition ([`status`](#status) below). A namespace quota that refuses
the growth, or a claim not yet bound, is logged by the operator and does not set the condition.

The admission webhook refuses a `spec.storage.size` lower than the size the stored object resolves
to (the `50Gi` default when it sets none), because a claim cannot shrink. It also refuses a size of
zero or less, and a size above `64Ti`, the largest persistent disk, unless the stored object already
carries that value; a stored size above `64Ti` compares as `64Ti`. Removing the field is allowed,
and the size then resolves to the default.

Where the stored size is above the default, the existing claims keep their size, only a new claim
gets the default, and the webhook warns about the removal. Where the stored size is below the
default, the operator grows both claims to the default, with no warning. The webhook compares with
the stored object, not with the claims: after a raise and a removal, it admits a size between the
default and the claims' size, and the claims keep the larger size. The chart ships the webhook off;
without it, the operator still never shrinks a claim, and it treats a size of zero or less as
absent.

The chart sets it from `platformAgent.storage.size`, the Terraform composition from
`platform_agent_storage_size` and `install.sh` from `PLATFORM_AGENT_STORAGE_SIZE` in `install.env`.
While the value is the default, the composition passes the chart nothing, so the CR carries no field.

`expectedClusterProfiles` (1 to 20000) is how many Cluster Agent profiles the install is expected
to hold, one per cluster in scope. It raises the agent's `<name>-data` claim, and not the sandbox's,
to at least `8Gi` plus `400Mi` per profile, rounded up to whole GiB. That's the size the session
stores settle at under the default 90-day retention
([Fleet sizing → The data volume](/kube-agents/deploy/fleet-sizing/#the-data-volume)). The claim
takes the larger of that and `size` (or the default), so the field only raises it, and the formula
passes the `50Gi` default above 107 profiles.

Raising it grows the existing claim online, as a
raised `size` does, and the `DataVolumeNotExpanded` condition covers a class that can't expand it.
The sandbox's claim holds no session stores; the copy it takes of the agent's working directories
leaves them out. The chart sets it from `platformAgent.storage.expectedClusterProfiles`.

## `spec.telemetry`

- `otlpEndpoint` — the OTLP/HTTP collector **base** URL (no `/v1/traces` suffix; the exporters append their own per-signal path). Up to 2048 characters, `http://` or `https://`.
- `peopleSeen` — whether the A2A gateway keeps its [people record](/kube-agents/concepts/chatops-a2a-gateway/#people-seen): one hashed key and a last-active time per person who writes on Google Chat, Slack or Discord, kept 30 days after their last turn. Defaults to `true`. `false` writes no key, deletes every key the record holds at the gateway's next start, and the gateway serves no `kubeagents_a2a_gateway_people_seen` sample. The chart sets it from `platformAgent.telemetry.peopleSeen`, and refuses to render `false` against a served CRD that lacks the field, because `helm upgrade` does not update CRDs.

Optional, and omitting it is the point: with the field absent the operator discovers an in-cluster collector, falls back to GKE Managed OpenTelemetry when it cannot establish what the cluster has, and disables export altogether when discovery finds no collector (`otlpEndpointSource: None`). Setting it pins the endpoint and suppresses discovery. The full precedence ladder, the discovery order, and the Helm value that drives LiteLLM and the NetworkPolicy alongside this field are on [Deploy → Telemetry](/kube-agents/deploy/telemetry/#pointing-at-your-own-collector).

## `spec.networkPolicy`

This section has its own dedicated reference page: [PlatformAgent: Scope, networking, and integrations](/kube-agents/operator/platformagent-scope-integrations/).

## `spec.integration`

This section has its own dedicated reference page: [PlatformAgent: Scope, networking, and integrations](/kube-agents/operator/platformagent-scope-integrations/).

## `status`

The operator writes observed state to the `status` subresource; [PlatformAgent fields → Status](/kube-agents/operator/platformagent-fields/#status) lists every field with its type. How the `usage` counters are produced, where `inference` comes from, and what each condition reports, follows.

`usage.toolExecutionsTotal`, `usage.toolExecutionsBlockedTotal`, `usage.eventsIngestedTotal`, `usage.sessionsTotal`, `usage.chatSessionsTotal`, `usage.remediationsProposedTotal`,
`usage.chatMessagesInboundTotal`, `usage.brokerFailuresTotal`, `usage.chatTurnsErroredTotal`, `usage.backgroundTasksGaveUpTotal`, `usage.negativeFeedbackTotal`, `usage.positiveFeedbackTotal`, `usage.autonomousNegativeFeedbackTotal`, `usage.autonomousPositiveFeedbackTotal`,
`usage.lastActiveTime`, `usage.lastHumanActiveTime`, the two cluster gauges and the proposal, people and origin readings are produced by the operator, on the leader and off the reconcile path. So are the three inference totals, `usage.inputTokensTotal`, `usage.outputTokensTotal` and `usage.spendMicrosUSDTotal`. Every five
minutes it reads the credential broker's, the event watcher's, the chat plugin's, LiteLLM's and the A2A gateway's metrics listeners over the pod network, folds the counter series into totals it keeps with their per-pod baseline in the
`<name>-usage-counters` ConfigMap, so the counters stay monotonic across pod, process and operator
restarts, and patches the status only when it is behind.

The gauges are the latest poll's reading of the watcher's body, written whenever they change in
either direction, and they do not move `lastActiveTime`. The counters under-count rather than
over-count: a listener that cannot be read keeps its baseline and its backlog is added when it is
read again, but a backlog past the per-poll ceiling, an honest burst past it, or what a process
counted after its last read and before it restarted, is lost once.

A `lastActiveTime` that stops advancing while commands plainly run is the symptom of a listener the
operator cannot reach; the CR's events name the pod. It advances on any brokered command, including
those a scheduled job runs -- the Controller Stall Watch cron issues some every 30 minutes by
default -- so a recent `lastActiveTime` is not evidence that a person used the agent; `lastHumanActiveTime` is.

The six proposal fields, the two people fields and the nine origin fields are readings, not totals. A reading's source is the credential broker, the A2A gateway or the chat plugin. Every 240 seconds the credential broker asks the forge (on GitHub with a read-only token of its own) for the proposals the install authored in each managed
repository and the human events on them. The operator projects the latest poll's values as they
stand, outside the ConfigMap.

The outcomes reading (`remediationsMergedTotal`, `remediationsOpen`, `proposalsAuthored`) and the
details reading (the other three) each have their own miss streak. One poll that cannot read the
broker, or reads it without a reading, leaves that reading's fields as they were; the second in a
row clears them to absent. The broker stops serving a reading more than an hour old. A 0 is a
reading.

A broker restart leaves the details fields (`remediationsClosedUnmergedTotal`,
`proposalHumanTouches`, `proposalsMergedUntouched`) as they were for one operator poll, and clears
them when a second poll in a row finds no details reading. The broker keeps what it read of each
proposal in memory, and after a restart it reads every proposal again within an hourly budget of
forge calls. A small install is done within the first sweep. An install with a thousand proposals
takes some hours, and the fields are absent in between. The outcomes fields return on the first
sweep.

The people reading (`peopleSeen7d`, `peopleSeen30d`) comes from the A2A gateway: the distinct
people who wrote on a chat platform it serves in the last 7 and 30 days, the largest count across
gateway pods. The operator reads it only while no chat
platform the install enables is served through Hermes, that is, Microsoft Teams on the
Hermes path. With the gateway's Teams backend armed (`A2A_TEAMS_BACKEND`) every enabled
platform is the gateway's, and the reading is present. Otherwise both fields are absent.

A poll that reads no gateway body carrying both
windows is a miss, and so is a poll that finds no running gateway pod. The second miss in a row
clears both. With `spec.telemetry.peopleSeen: false` the gateway serves no sample, so both fields
clear the same way. A 0 is a reading, and neither field moves `lastActiveTime` or
`lastHumanActiveTime`.

`topTools` is the credential broker's five most-invoked tool and subcommand pairs since its pod
last started, summed across the broker pods. Each row carries the pair's total and its outcomes
(`success`, `error`, `blocked`, `busy`, `abandoned`); the rows sort by total, then by tool and
subcommand. Every word is from the broker's own closed vocabularies, so the list carries no
command line. A broker restart starts it over, a broker that has run nothing leaves it absent,
and the second poll in a row that cannot read the broker clears it. It moves neither time. The
summary script and the chat gateway's `/feedback summary` print it as the
`tools (top 5, since broker start)` block.

The origins reading (`proposalsFromChat`, `proposalsFromConsole`, `proposalsFromApi`,
`proposalsFromEvent`, `proposalsFromDrift`, `proposalsFromAudit`, `proposalsFromScheduled`,
`proposalsFromIssue`, `proposalsFromOther`) comes from the chat plugin's proposals ledger: the pull
requests the agent opened and the forge confirmed, counted by the origin of the work that started
each. The operator reads it on the gateway pod's chat metrics listener, summed over the chat
platform. The reading is present when all nine origins resolve and the plugin's read age, when the body
carries it, is not above two poll intervals; the plugin serves every origin, zero included, from its
first ledger read. Until then, and while the served CRD predates them, the nine fields are absent. A
ledger that stops answering therefore clears them about twenty minutes later.

A poll that reads no body with all nine is a miss, and the second miss in a row clears them. A 0 is
a reading, and none of the nine moves `lastActiveTime` or `lastHumanActiveTime`. A proposal the
agent did not see itself open is not counted, so the nine usually sum to at most
`remediationsProposedTotal`.

The operator also serves every counter, cluster gauge, scalar reading and time of this block (the two lists, `activeInterfaces` and `topTools`, aside), and `status.phase`, as Prometheus gauges on its own metrics port. A collector reads them without a query against the status; the series are on [Observability](/kube-agents/concepts/observability-exports/#prometheus-metrics).

`inference.provider` and `inference.model` are the install's default model, the one LiteLLM serves
under `model-default`. The operator reads the LiteLLM config ConfigMap the `litellm` Deployment
mounts, or, with no such Deployment, the newest `litellm-config` or `litellm-config-*` ConfigMap
that carries `config.yaml`. It takes the `litellm_params.model` of the `model_list` entry named
`model-default`, or the first provider-qualified entry when no entry has that name, and splits it at
its first `/`. A Vertex AI endpoint path (`projects/…`) or a Bedrock ARN keeps its resource id only,
so no project id, region or account id is written; every other name is kept as typed, an
organisation prefix such as `meta-llama/` included.

`inference.reasoningEffort` is the `reasoning_effort` on the same entry, as typed (the chart writes
`litellm.reasoningEffort` there). It is absent when the entry states none, so the model thinks at
its own default.

The pair is written whole or not at all. Both fields are absent when the namespace has no LiteLLM
config, when the `litellm` Deployment mounts none, or when the default model has no provider or no
name. A Deployment that mounts none leaves any remaining `litellm-config*` ConfigMaps unread, and a
`model-default` entry with a malformed model does not fall back to another entry. A read that fails keeps the last pair. The
Ready status update writes the block, and a change to the ConfigMap or to the `litellm`
Deployment's pod template re-reads it within a reconcile.

`usage.activeInterfaces` is `dashboard` unless `harness.hermes.dashboardEnabled` is `false`, plus
`googlechat`, `slack` and `teams` for each `integration` entry with `enabled: true`. It is resolved
from the spec on every reconcile and written by the Ready status update when it changes; a pass that
parks the CR `Degraded` before that update leaves the previous value, so read it alongside the Ready
condition.

On an install whose served CRD predates the field, the API server drops it from every write; the
operator notices from the write's echo, stops treating the missing field as a change for five
minutes at a time, and lands it once this release's CRD is applied: within five minutes on a quiet
install, at once when the Ready status update next writes for any other reason. The other status
writers carry the field through as they read it, so a pass that ends `Degraded` lands nothing new.
`inference`, `resolvedUniverseDomain` and `universeDomainSource` follow the same Ready-writer and
five-minute reprobe rule under a served CRD that predates them.

A served CRD from before `inference.reasoningEffort` keeps the provider and model and drops the
effort until it is applied.

`profileSubmitMaxAgeSeconds` is the live `PROFILE_SUBMITS` stream's max age, as the A2A
provision Job last read it, when it is longer than this release creates the stream with (`0` is no
age limit). Provisioning never changes an existing stream's max age, so a stream created by an older release
with a longer max age, or edited by hand, keeps its own. The dispatch config's submit retention is
the longer of the two, so a finished task's tombstone outlives its submission, up to a year: a
stream with no age limit, or one longer than a year, gets a year.

The value is read once per provision Job run, and the Job runs again a day after it finishes, so
a stream edited by hand is picked up within a day. A Job that fails records nothing. The field is
absent when the stream is no longer than this release's, and before the first report. Only a report
the operator can read changes it. Under a served CRD that predates the field the write is dropped
and the retention stays this release's own until the CRD is applied.

The counters and the two times land through the poller above, which consults the same five-minute
record. Under a served CRD that predates `status.usage` they accumulate in the
`<name>-usage-counters` ConfigMap and land with the first patch after this release's CRD is
applied.

Under a served CRD at a previous schema, which has `status.usage` without the fields added
later (the two cluster gauges, the proposal readings, the people readings, the origin readings, `chatMessagesInboundTotal`,
`toolExecutionsBlockedTotal`, `brokerFailuresTotal`, `chatTurnsErroredTotal`,
`backgroundTasksGaveUpTotal`, `negativeFeedbackTotal`, `positiveFeedbackTotal`, the two autonomous feedback totals, `chatSessionsTotal`, the three inference totals and `lastHumanActiveTime`), the first-schema
counters keep landing and the newer fields are probed again every five minutes until this
release's CRD is applied. `storageStatus.capacityBytes` and `freeBytes` follow the same rule under
a served CRD that predates them.

`effectiveSizingTier` is the tier the operator last rendered the three sized containers at,
`small`, `medium` or `fleet`, written before the render on every pass that reaches it, whatever
status the pass ends on. Under [`spec.deployment.sizingProfile`](#specdeployment) `auto` it is also
the latch: the tier rises from it with the cluster count. It is stepped back one tier when
admission refuses the pod a step recreated, and the `SizingCappedByQuota` condition then names the
quota. Under an explicit profile it repeats that profile.

Under a served CRD that predates the field, the five-minute rule above applies. The operator
notices the pruning from the write's echo, and writes and logs the tier once per interval rather
than on every pass. It renders `auto` at `small`, since the latch cannot be stored, and lands the
field with the first probe after this release's CRD is applied.

`effectiveSessionCap` is the session cap the operator renders on the session route, fitted to the
live `TASKS` stream as [`spec.harness.tuning`](/kube-agents/operator/platformagent-harness/#specharnesstuning) describes. A pass that cannot
read the bus keeps the stored value, and a stored value's reading is reused for five minutes. It is
written only on `defaultRoute: session`; on `platform`, the default, a value an earlier opt-in left
is cleared.

These condition types appear in `conditions`; only `Ready` is always present. The table is
generated from `k8s-operator/internal/controller/condition_docs.go`, and the controller's tests
fail when it writes a condition type that has no row there:

<!-- BEGIN GENERATED: crd-conditions-platformagent -->
<!-- Regenerate with: make docs-generate -- do not edit by hand. -->
<!-- prettier-ignore-start -->

| Type | Written | Meaning |
| ---- | ------- | ------- |
| `Ready` | Always | Tracks `phase`; its `reason` and `message` carry whatever the reconcile is waiting on, including the reasons that park `phase: Degraded` (`ReservedServiceAccountName`, `RuntimeClassNotFound`, `ShellSandboxCannotBeDisabled`, `UniverseDomainMismatch`, `ForbiddenVolumeMount`, `EgressAllowlistRefused`, `ShellSandboxKeysMissing`, and `A2AProvisionFailed`). [What `Ready` reports](#what-ready-reports) says what `UniverseDomainMismatch`, `ShellSandboxKeysMissing`, and `A2AProvisionFailed` mean and how a failed provisioning Job is cleared. Under `spec.deployment.scaleToZero: true` it reads `False` with reason `ScaledToZero` beside `phase: Paused` once the gateway has no ready replica; the same section says when. With the A2A gateway's election on, the gateway counts as ready only while its elected leader is, after a 30-second grace from the leader's election; with no current leader (no holder, its pod gone, or a holder that stopped renewing) it counts its ready replicas. |
| `Degraded` | Only while degraded | Something in the spec, cluster state, or operator install cannot be honoured. `Reason` is one of `InvalidGitRepoURL`, `CorruptManagedRepos`, `MinterPruningHeld`, `A2ABusStreamsMissing`, `A2AGatewayWaitingForTasks`, `InvalidCredentialProxyResources`, `InvalidAgentAPIAuthResources`, `InvalidShellSandboxResources`, `InvalidCredentialProxyExec`, `InvalidKanbanAdmission` or `RBACIncomplete`; [What `Degraded` reports](#what-degraded-reports) says what each means. The refusals above ride the `Ready` condition instead of this one. |
| `BusCredentialsReady` | While a callout Deployment exists | Whether every replica the callout Deployment asks for is ready, and therefore both serving an identity map and attached to the bus. `Reason: CalloutServing` (`True`), `CalloutUnavailable`, or `CalloutAbsent`. The operator's own gates do not read it, and it reads `False` with `1 of 2 replicas ready` while the gateway exists and dispatches; [What `BusCredentialsReady` reports](#what-buscredentialsready-reports) has the gate it differs from. |
| `DispatcherJobMode` | While the operator runs the profile dispatcher (on by default; `operator.profileDispatcher.enabled`) with the chart's `A2A_DISPATCHER_JOB_POLICY` signal set, from the first pass that reaches the dispatcher | Whether the dispatcher runs profile tasks as Jobs: unattended ones, and permit-carrying ones at any tier. `Reason: InPlace` (`True`), `PolicyMissing`, `NamespaceNotSelected`, `NamespaceNotReady`, `ForeignJobTemplate`, or `GrantFailed`; [What `DispatcherJobMode` reports](#what-dispatcherjobmode-reports) has each. |
| `SessionHarness` | While spec.harness.sessionWorker.type names a harness this operator doesn't render | `status: False`, `Reason: SessionHarnessNotSupported`, with a Warning event: the CRD admitted a session harness this operator doesn't know (after a rollback, for example), so the operator doesn't pass it to the gateway and session pods run the default harness, `claude-code`. Removed once the value is supported or unset. |
| `DispatcherCeiling` | While the profile dispatcher is switched on | How the dispatcher's identity-map entry and its config compare with what one shard and one ConfigMap can hold. `WithinBudget` (`True`); `NearBudget` (`True`), past four fifths of either, with a Warning event; `ProfilesRefused` (`False`), with a Warning event: the newest profiles aren't bound and the dispatcher serves the rest; `OverBudget` (`False`), with a Warning event, only from draining profiles: no dispatcher until their drains run out. About 650 profiles at two tiers; the config fills first only for profiles that declare many parameters. |
| `A2AIdentityMapApplied` | Once the operator renders an identity map | Whether the auth callout took the identity map this operator rendered, read from every Ready callout pod's `/status` by pod IP, again every 30 seconds while unsettled. `True`, `Serving`: every Ready pod answered and serves it. `False`, `Refused`: a pod refused it and serves its previous map, which can be wider; the message quotes the refusal. `False`, `Pending`: a pod is still on an older map or mid-way through its shards. `Unknown`, `StatusUnreadable`: a Ready pod didn't answer and may hold a refusal, so turning to it is a Warning event (a NetworkPolicy on the callout must admit the operator). `Unknown`, `NoReadyCallout`: no pod is Ready. Removed when the A2A stack is off. |
| `InferenceKeysServed` | While the namespace runs the inference gateway (the `litellm` Deployment) | Whether every Ready inference gateway pod has loaded the caller keys the operator mints, one per caller class: `agent`, `a2a-session`, `curator`, and `tier-<tier>` for each AgentProfile tier in use. Each key is in Secret `<name>-inference-key-<class>`, a tier's in the profile namespace, and the `litellm-caller-keys` Secret lists their SHA-256 digests. These names are reserved for the operator: it records the UID of each Secret it creates in `status.inferenceKeys`, and replaces any other Secret it finds at one of them, with an `InferenceKeySecretReplaced` Warning event naming it, so its key never reaches the map. After a rollback to a release that drops that record, every key is replaced once and the condition comes back on a later pass. A pass that finds the condition `True` marks each class's key Secret with the annotation `kubeagents.x-k8s.io/inference-key-served-sha256`, and from the next pass the class's callers send their key ([which key each caller sends](/kube-agents/concepts/inference-litellm/#which-key-each-caller-sends)). The operator also mints a probe key, class `gateway-probe` in Secret `<name>-inference-key-gateway-probe`, which no caller is given and the gateway admits on `GET /v1/models` alone. Every map the operator writes carries a fresh probe key, its digest in the same update and the previous one dropped, so a pod still on an older map refuses it. It sends only the probe key, as `GET /v1/models` by pod IP, to each Ready pod the `litellm` Deployment owns through its ReplicaSet, skipping pods on the host network. `True`, `Served`: every pod answered 200. `False`, `NotServed`: a pod answered something else; the message names the pod and the status, and the operator looks again every 15 seconds, since a pod loads a new map when the kubelet refreshes its mounted Secret. `Unknown`, `ProbeIncomplete`: a pod didn't answer, and the operator looks again every minute. `Unknown`, `NoReadyGatewayPod`: no gateway pod is Ready, and the operator looks again every minute. `False`, `CRDOutdated`: the served PlatformAgent CRD's `status.inferenceKeys` schema isn't current (it lacks the field or its `tierUnboundAt`), so the operator writes no key Secret and no map until the current CRD is applied (Helm doesn't upgrade CRDs on `helm upgrade`); it looks again on its steady interval. `False`, `NotWritten`: the keys or the map weren't written, because another PlatformAgent shares the namespace, the CRD couldn't be read (nothing is written on that pass), a Secret at one of those names is being deleted (the operator creates its own once it's gone), a Secret to replace couldn't be checked against the record as the API server holds it (nothing is replaced on that pass), or an API call failed; the message says which. |
| `A2ACalloutRolloutStalled` | While the auth callout Deployment's rollout is past its progress deadline | `status: True`, `Reason: ProgressDeadlineExceeded`. The bus applies a config change without waiting for every callout replica to load the current identity map, so until the rollout finishes some connections may be placed by the previous map. Check the `<agent>-a2a-callout` Deployment's rollout (`kubectl rollout status`) and its pods' events. Removed once the rollout completes. |
| `A2AProvisionRetrying` | While the current A2A provision Job has failed pods and has neither completed nor failed | `status: True`, `Reason: ProvisionJobPodsFailing`. The message names the Job, how many of its pods have failed, and the `kubectl logs` command that shows why. The Job retries up to its `backoffLimit`, which can take over an hour, before it fails and `A2AProvisionFailed` takes over. Not `Degraded`; `BusProvisioned`, `Ready` and the phase are unaffected, because the Job also re-runs on a bus that is already provisioned and a retry can clear by itself (NATS briefly unreachable). A Warning Event is recorded each time the operator sees the failed-pod count rise; it checks every 30 seconds while the Job runs, so pods that fail between two checks share one Event. Removed once the Job is replaced, or once the Job controller decides it has completed or failed, which can be a few seconds before `Complete` or `Failed` appears while its pods terminate. Written and cleared by every pass that renders the stack and reaches a status write, whichever phase it ends on; a pass that stops before then leaves it as it stands. |
| `A2AGateway` | Only on an install upgraded from an operator that ran the A2A gateway at zero replicas for want of a chat backend: from the pass that scales it back to one replica until that replica is ready. Written and cleared by every pass that renders the stack, whichever phase it ends on (`Ready`, `Provisioning`, or `Degraded` for `A2AProvisionFailed` and `ShellSandboxKeysMissing`), so only a pass that stops before rendering leaves it as it was | `status: False`, `Reason: WaitingForReplica`. Every install runs the A2A gateway, on the console door alone when no chat backend is configured. After the upgrade the next pass renders it at one replica, `Ready` waits on it, and the condition clears once a replica is ready. [What `A2AGateway` reports](#what-a2agateway-reports) covers the older `NoChatBackend` reason and the `discord-bot` Secret. |
| `BusProvisioned` | From the first pass that sees the bus provisioning Job complete, whichever phase that pass ends on; kept through the Job's later re-runs | `status: True`, `Reason: ProvisionJobComplete`. The record that lets `Ready` stop counting the Job: the finished Job is removed by its 24 h TTL and rendered again, and a spec edit renders a new one under a new digest, and neither re-run should flip a Ready install to `Provisioning` for the minute it takes. Until this condition exists the Job counts, so an install upgraded from an operator that never counted the Job (one that could read `Ready` over an unprovisioned bus) does not inherit a completion nobody saw. The message names the Job that first provisioned the bus. A re-run that fails is still reported as `A2AProvisionFailed`. |
| `ProfileSupervisorForm` | `True` once, from the first pass that finds every profile-task reader (the A2A gateway, the agent pod and, with its door on, the MCP server) on this release's image and fully rolled out and the bus provisioning Job that adds the gateway relay's third filter complete; never removed. `False` while this install renders a reader on an image other than this release's (a pinned `spec.deployment.image`) | `status: True`, `Reason: SixTokenSupervisorSubject`. The dispatcher writes a profile task's terminal on the six-token supervisor subject (`a2a.tasks.p.<profile>.<task>.supervisor`) instead of the five-token one, and the gateway relay filters both. It is a latch: a later upgrade that rolls a reader again keeps the dispatcher on the six-token form rather than moving it back for the length of the roll. One pass after it is written, the operator renders `A2A_PROFILE_SUPERVISOR_CUTOFF` on the A2A gateway and the MCP server, set to this condition's `lastTransitionTime` plus ten minutes (on an install that latched earlier, that time may already be in the past at the upgrade), and mounts the `<agent>-a2a-profile-names` ConfigMap on both, which rolls each once: past that time they no longer take a five-token terminal as the end of a task addressed to a profile that ConfigMap lists. From the latch the dispatcher no longer falls back to the five-token form when the six-token one is refused, and settles the task without a terminal after its retry bound (`terminal-unpublished`). Until it is written, the dispatcher writes the five-token form, which every reader watches. `status: False`, `Reason: ReaderNotOnReleaseImage`: the operator renders the reader the message names on an image other than this release's, the hermes-bridge of a pinned `spec.deployment.image`, so the install stays on the five-token form. A later release that drops that form keeps it for this install while this holds. Setting the pin to this release's tag, or removing it, clears it. A reader still on an older release's image, before or during its rollout, writes nothing. |
| `BusStreamsPresent` | Once `BusProvisioned` is True | Whether the streams and KV buckets the provisioning Job creates are still on the bus, read every five minutes from the bus's metrics exporter on port 7777. `True`, `AllPresent`: every one was seen. `False`, `StreamsMissing`: three polls in a row found the ones the message names missing, and the operator deletes the completed provisioning Job so it runs again and recreates them (`Reprovisioning` while it runs); once `TASKS` is back after a loss, however it came back, the operator restarts the A2A gateway and the agent pod whose client container has been running since before the loss, because their `TASKS` consumers don't come back on their own (`A2ABusClientsRestarted`); one that started since binds by itself, and a restart that fails is retried on every poll, with `Reprovisioning` saying so. A loss of `TASKS` counts once three polls in a row saw it, or once the operator re-runs the Job while it's missing. It's kept in the `kubeagents.x-k8s.io/a2a-bus-tasks-lost` annotation, so removing the re-run record doesn't clear an owed restart; removing that annotation does. Re-runs are at most one per 15 minutes and three per 6 hours, recorded in the `kubeagents.x-k8s.io/a2a-bus-reprovision` annotation. A re-run that completed without bringing some of them back stops the re-runs for exactly those names (`ReprovisionDidNotRestore`), each lifted on its own once seen back or all of them when the annotation is removed. A loss of any other stream is still confirmed and re-run while a stop holds, and its message names the stopped ones. A failed Job is not re-run. While `False`, `Degraded` reads `A2ABusStreamsMissing`. `Unknown`, `DetectionUnavailable`: the bus runs without its exporter ([`A2A_NATS_EXPORTER_IMAGE`](/kube-agents/deploy/docker-images/)). `Unknown`, `ExporterUnreachable`: three polls in a row had no usable answer. No verdict is taken while the bus rolls, converts or provisions, and the condition keeps its last one meanwhile, however long that lasts; the bus's own conditions report the rollout. |
| `A2AVerifier` | While the capability verifier's Deployment exists and has no ready replica. A pass that cannot read the Deployment leaves it as it stands | `status: False`, `Reason: VerifierNotReady`. A capability check that gets no answer is refused, so every submission is refused terminally while this holds. The CR stays `Ready`: the verifier is on the request path, not the readiness path. Check the `<agent>-a2a-verifier` Deployment's pods and their logs, including the previous container's: a verifier that cannot bind its capability bucket exits, and its log says why. Removed once a replica is ready. |
| `A2ABusMetaGroup` | On a multi-server bus, on a pass that checks the JetStream meta group before creating the provision Job: present while the group isn't formed, a server isn't running, or a server's view can't be read, and removed on the pass that sees it formed. Also removed on any pass where the provision Job already exists, on a one-server bus, on a pass where another hold (the callout, or the bus rolling out) keeps the check from running, and when the mode flips to `today` | `status: False`. `Reason: ServerOutsideMetaGroup` names the server or servers that don't report the meta leader a quorum agrees on, or that the leader doesn't list as current. The provision Job waits, so no stream is created, and the CR isn't `Ready`. A server still outside 3 minutes later is restarted once, with an `A2ABusServerRestarted` Warning, when it is the only one outside, the rest are a quorum, the bus hasn't been provisioned yet with no server holding a stream or consumer, and its own meta node has started. A server already restarted once and still outside is named as left for a person: delete its pod, or wipe the bus. When no leader is agreed at all, on a fresh bus under the same guards (never provisioned, no server holding a stream or consumer, every meta node started, none restarted before), every server is restarted once after the same 3 minutes, with an `A2ABusMetaGroupRestarted` Warning; a bus still without a leader after that, or one where a server was already restarted, is named as left for a person (wipe the bus). `Reason: ServerNotRunning` names a server whose pod is absent, being deleted, or not Running while the others run, such as the one just restarted: the Job waits for it, and nothing is restarted on that account. `Reason: MetaGroupUnknown` names a running server whose view couldn't be read, or says no server is running; nothing is held or restarted on its account. The check also runs when the Job is re-created on a running bus, where it can hold the re-run and set this condition; it never restarts anything on a bus that has been provisioned, so it doesn't repair a server that drops out of a running bus. |
| `GatewayElected` | With the election on, from the first pass that reads a gateway pod holding the Lease. Kept while the gateway runs that image or the operator's own release. Removed on a roll to another image, or with the election off | `status: True`, `Reason: LeaseHeld`. The message is the image the Lease holder runs. The operator renders `availability.a2aGateway.replicas` gateway replicas only while it is set, since a gateway from before the election would act beside an elected one. A status condition doesn't survive most restores, so a restored install runs one replica until a gateway takes the Lease again. |
| `EventWatcher` | Only while `eventWatcher.enabled` is `false` | `status: False`, `Reason: DisabledBySpec`. The emergency stop is still pressed and no cluster events are reaching the agent. |
| `DataVolumeNearlyFull` | While the operator has a reading of the data volume | `True` (`NearlyFull`) from 90% used, back to `False` (`HasSpace`) only below 85%, so a volume at the line does not flap. A full volume fails every task-board and session write with a bare `disk I/O error`, so this is the early warning. It does not change `phase` or `Ready`, since the agent still answers. The message holds no figure and points to `storageStatus` and the `kubeagents_data_volume_bytes` metric; `freeBytes` is current to within a hundredth of the volume, and exact when the status changes. The reading comes from the event watcher, so it clears at once while the watcher is disabled or answers ready without the volume series. With no fleet reading (unreachable or `k8s_event_watcher_watch_set_ready` below `1`), it holds for one poll and clears after two in a row. The Session KV server in the agent container makes the same check and posts to the home channel when usage crosses 90% and when it is back below 85%. |
| `KanbanDispatcherFailing` | From the first time the task-board dispatcher fails for a whole poll, or a tick on a board runs past 300 s or fails on a database lock after a busy timeout | `True` with reason `TicksFailing` once a board's dispatcher fails 60 ticks in a row (about one five-minute poll), or 3 in a streak at least a poll old. `True` with reason `TickStuck` once a board's tick runs past 300 s or fails on a database lock after waiting the busy timeout (120 s by default), as on a locked board; a stuck board takes precedence over a streak, and a good tick that runs past 300 s can set it for one poll. The message names the board with the last error class, or the stuck board, and no tick count or duration; it is written again when the reason, the board, the error class or the count of failing boards changes. Cards on that board are not dispatched; a full data volume is a common cause. `False` (`Ticking`) at the first poll where no board meets any rule. A good tick resets a streak and a stuck board, and a quick failure of another kind ends a stuck board; a board the dispatcher stops trying drops out after ten minutes. It does not change `phase` or `Ready`. A poll that cannot read the gateway's chat metrics listener leaves it as it is. A board quarantined as corrupt drops out after ten minutes too. |
| `ScopeUndeclared` | While `spec.scope` names no project, folder, organization, Shared VPC host or Metrics Scope, `spec.harness` names the host cluster, and the event watcher registers a cluster in the management project other than the host | `status: True`, `Reason: ClustersAdoptedFromProject`. Without a membership list the reconcile adopts every GKE cluster in the management project. The message counts them, names the first eight as `name (project/location)`, and points at the remedy: name the management project in `spec.scope.projects` to keep them, or list each under `spec.scope.exclude.clusters` ([`spec.scope`](#specscope)); on an installer-made install, set `SCOPE_PROJECTS` or `SCOPE_EXCLUDE_CLUSTERS` in `install.env`. The management project stays in scope under any declaration, so a scope that names other projects silences the condition without retiring the neighbours. Written by the usage poll from the watcher's `k8s_event_watcher_cluster_up` series. Absent with the watcher disabled or after two polls in a row without a fleet reading, and removed once that project registers no cluster beyond the host or a scope is declared. Not `Degraded`; `Ready` is unaffected. |
| `HomeChannelUnset` | While the A2A gateway holds a chat backend whose `homeChannel` is empty (Google Chat, Slack, or Microsoft Teams with the operator's `A2A_TEAMS_BACKEND` switch on, any of them) and no learned channel or space is admitted for it | `status: True`, `Reason: NoHomeChannel`. Conversation replies still arrive. When another platform has a home channel, proactive posts go there meanwhile (Chat's first, then Slack's, then Teams'). When no platform has one, the gateway refuses them and keeps them for one digest once a channel is set. The message names each platform; the `install.env` key beside the field only for the platforms the installer configures. Not `Degraded`; `Ready` is unaffected. Written and cleared on a pass that ends `Ready` or `Provisioning`, and on one that renders the A2A stack and then parks `Degraded` (`ShellSandboxKeysMissing`, `A2AProvisionFailed`); a refusal that returns before the render leaves it as it stands. Set `homeChannel`, or under `homeChannelPolicy` `auto` mention the agent in a channel or a space, or on Slack pick one on the Home tab ([`spec.integration`](#specintegration) has the admission rule). |
| `A2ABusMigrating` | While a bus migration runs (True), and after one ended without converting the bus (False, `Abandoned`) or stopped for a person (False, `Failed`); absent once one converted the bus, or when none has run | `status: True`, `Reason: InProgress` while a run is under way; the message names its phase, which `status.busMigration` also carries. `False`, `Abandoned`: the run ended and the bus runs on as before, data kept. `False`, `Failed`: the run stopped where a person has to act, and the message names the step. A reshape (leg `Reshape`, [recreating TASKS wider](#recreating-tasks-wider)) reads the same way, its message naming TASKS rather than a server count. `True`, `LegUnknown`: the run's leg is one this operator does not run, a later release's found after a rollback; it is held where it is, with the freeze, until that release is back or a person abandons it ([a run this operator does not run](#a-run-this-operator-does-not-run)). An install upgraded from an operator that refused bus conversions loses that operator's `A2ABusConversionRefused` condition on its first status write. [Changing the bus's server count](#changing-the-buss-server-count) has the phases. |
| `NoChatPlatform` | While neither Google Chat nor Slack is enabled, and the gateway's Microsoft Teams backend is not armed | `status: True`, `Reason: NoChatPlatform`. Nothing the agent raises unprompted reaches chat. Its audit findings stay in the report store on the data volume and reach the GitOps repository (ledger issues, fix pull requests) when one is registered; alerts are still triaged on the board; other scheduled reports are not delivered. Ask the agent for the audits in the console's chat pane, or read the volume with `kubectl exec`. Not `Degraded`; `Ready` is unaffected. A Discord-backed gateway carries it too, since no notifier posts to Discord. Written and cleared on the same passes as `HomeChannelUnset`. Enable one platform (`spec.integration.slack` or `spec.integration.googleChat` with `enabled: true`, or `spec.integration.teams` on an operator running with `A2A_TEAMS_BACKEND=true`) to clear it. |
| `ShellSandboxPinned` | While `spec.harness.experimental.shellSandbox.image` names an image other than the one the operator would run without it | `status: True`, `Reason: ImageDiffersFromOperator`. The message names both images. A pin survives operator and agent upgrades, and a sandbox older than the agent fails every `kubectl` call at the credential proxy with a policy refusal. Not `Degraded`; `Ready` is unaffected, since a pin to a mirror or a test build can be deliberate. Written and cleared on a pass that ends `Ready` or `Provisioning`, and on one that parks `Degraded` on `ShellSandboxKeysMissing` or `A2AProvisionFailed`. Clear the field, or set it to the operator's image, to clear it. |
| `A2AMCPServer` | While the operator runs the MCP server (on by default; `operator.mcpServer.enabled`) and a ServiceAccount named `<agent>-a2a-mcp` or a Secret named `<agent>-a2a-mcp-token` exists that this PlatformAgent does not control | `status: True`, `Reason: UnownedServiceAccount` or `UnownedTokenSecret`. Both names are reserved: an account somebody else created would run the MCP server as whatever Workload Identity it carries, and a foreign Secret would arm it with their credential. So the server is not rendered; a server and Service rendered earlier are removed, while the fence and the operator's own token stay. For an unowned account the broker's caller list and `CREDENTIAL_PROXY_MCP_CALLERS` do not name it. `Ready` is unaffected. The message names the object. Delete it; the condition clears on the next periodic pass, within 15 minutes. A controller reference is not a remedy: the operator would adopt the object as it is, annotations and contents included. |
| `ScopeResolved` | While `spec.scope` declares a folder, organization, Shared VPC host or Metrics Scope | A Job named `<agent>-scope-publisher-<suffix>` (shortened for long names) resolves those members into the `<agent>-resolved-scope` ConfigMap 15 minutes after each start, or at once for a new membership when no run is active. `True`, `Resolved`: a lookup answered within twice the sum of 15 minutes and 5 minutes per started 100 of `maxProjects` (40 minutes at the default). `False` reasons: `Missing`, no readable result yet. `Stale`, no lookup answered within that bound. `HashMismatch`, the result predates the membership. `TooLarge`, the members did not fit. `Error`, read the Job's log. `UnownedServiceAccount`, somebody else owns `<agent>-scope-publisher`; delete it; it clears within 15 minutes. `ScopeRoleNotConferred`, the install has no `kube-agents-a2a-gateway-pod` admission policy from the chart, which the broker's scope role needs. `Ready` is unaffected. |
| `BuiltinSchedules` | While something about the built-in AgentSchedules needs saying | `status: False`, one of `OverrideUnknown`, `OverrideRefused`, `ReplacedUnownedSchedule` or `WritesForbidden`. `OverrideUnknown`: an entry in `spec.schedules.overrides` names no built-in schedule, and is ignored; overrides key on the rendered name, so a canary's entry is `<name>-canary`. `OverrideRefused`: an override sets `suspend: false` on a run-now-only schedule such as `onboarding`, which would put it on its nominal cron; only `suspend: true` is taken there. `WritesForbidden`: a write the renderer needs was refused with a 403; the message names the verb, the schedule and the API's reason. If RBAC refused it, as an operator image ahead of its RBAC sees, apply the chart's RBAC: the writes are on the operator's namespaced Role in the install namespace. `ReplacedUnownedSchedule`: an AgentSchedule sat on a reserved built-in name without the operator's marks, and was deleted to be created again as the built-in (an Event says so too). Built-in names are reserved; don't create a schedule under one. Fix the override, or let the replacement finish, to clear it. |
| `VolumesDropped` | Only after a pass that rendered the Pod template around a `hostPath` on `spec.deployment.extraVolumes` or `.sidecarVolumes`, or a volume or mount that would hand a container the credential proxy's watcher token | `status: True`, `Reason: HostPathVolumeDropped` or `WatcherTokenVolumeDropped`. The render leaves the named `hostPath` or watcher-token entries and every mount naming them out of the Pod template the operator applies, and the message lists them by field and index. Not `Degraded`: the Pod runs without them. [What `VolumesDropped` reports](#what-volumesdropped-reports) says which passes write it and which leave it as it stands. Remove the entries to clear it. |
| `ReplicasLimited` | Only while `spec.deployment.availability.replicas` is above 1, after a pass that rendered the gateway | `status: True`, `Reason: HighAvailabilityNotSupported`. The operator runs the gateway as a single replica, whatever the field asks for; the message names the requested count and why a second replica does not start. Not `Degraded`: the single replica runs. Written on whichever status the pass ends on, on the same terms as `VolumesDropped`: a refusal that returns before the render neither writes nor clears it. Set the field to 1, or remove it, to clear it. |
| `CredentialProxyExecReady` | Only while `credentialProxy.exec.replicas` is above 0 and the agent's name is accepted for the tier | `status: True`, `Reason: AllReplicasReady` when every exec-tier replica is Ready. `status: False` otherwise: `Reason: Unschedulable` when the scheduler cannot place a replica, with the pod's name and the scheduler's message (often `Insufficient cpu`); `Reason: ReplicasUnavailable` for any other shortfall. The message counts the Ready replicas against the field. Re-read every 30 s while short; a failed read leaves it as it stands. Not `Degraded`: a caller that cannot reach the tier falls back to the stateful broker. Each replica needs a node with 2 free CPU. Removed when the field is 0 or unset, or when the name is refused (`InvalidCredentialProxyExec`). A park that returns before the broker is reconciled (`ReservedServiceAccountName`, `ForbiddenVolumeMount`, `ShellSandboxCannotBeDisabled`, `RuntimeClassNotFound`, `UniverseDomainMismatch`) leaves it as it stands, count included, until the park clears. |
| `SizingCappedByQuota` | Only while `spec.deployment.sizingProfile` is `auto` and the cluster count earns a higher tier than the namespace's ResourceQuota has room for, or than a LimitRange bound admits, or after a quota refused the pod a step recreated | `status: True`, `Reason: ResourceQuotaShort` or `LimitRangeShort`. The message names the tier earned, the tier the step was measured from, the tier that stays, and the short quota and key or the LimitRange, bound, resource and container; the figures go in the Warning event. Not `Degraded`: the running tier keeps running. Written before the render, so an earlier refusal neither writes nor clears it. Cleared by the pass that finds room or whose count no longer earns the step; a pass with no reading leaves it, so a gateway outage neither clears nor re-records it. The event watcher switched off by spec clears it. Raise the quota or the bound, or name the tier in `sizingProfile`. |
| `SessionCapFitted` | Only while the session cap is fitted below `maxSessions` on an install that sets `spec.harness.tuning.defaultRoute: session`, the install fell back to `platform`, its cap waits on its first reading of the bus, or the served CRD drops the cap. Never on `platform`, which an unset field resolves to | `status: True`, `Reason: TasksStreamNarrow`: the live `TASKS` stream has room for fewer sessions than `maxSessions`, so `status.effectiveSessionCap` holds the fitted cap, which the gateway's cap, the session quota and the provision Job follow. `Reason: NoRoomForASession`: not one session fits, so plain conversations go to `platform`. The cap stays fitted until `TASKS` is widened: on a one-server bus, setting `busReplicas` to 3 widens it and keeps its history; on any bus, a new value on the `kubeagents.x-k8s.io/bus-reshape` annotation recreates it at the rendered width, keeping its messages. `status: Unknown`, `Reason: WaitingOnBusWidth`: on a provisioned bus the width can't be read yet, so plain conversations go to session pods at `maxSessions` and the provision Job waits until it is read. `status: True`, `Reason: StatusFieldPruned`: the served PlatformAgent CRD is older than the operator and drops `status.effectiveSessionCap`, so plain conversations stay with `platform` until the chart's `crds/` is applied; the operator checks again every five minutes. The message carries no figures; the Warning event names the live width, what `maxSessions` needs and the fitted cap. Removed once none of these holds, and on `platform`. |
| `DataVolumeNotExpanded` | Only while a data claim is smaller than `spec.storage.size` (or the 50Gi default, raised by `expectedClusterProfiles` for the agent's claim) and its StorageClass cannot expand it | `status: True`, `Reason: StorageClassCannotExpand`. The message names each blocked claim, its current request, the size asked for, and why the class cannot expand it. Not `Degraded`: the agent runs on the smaller volume. Written on whichever status the pass ends on, `Ready` or `Degraded`, and removed once the claims can grow or the size no longer asks for more. After an operator restart it is left as it stands until the next pass reads the claims. Set `allowVolumeExpansion: true` on the class to clear it. The agent's claim, when it is below that size and will not grow (its class cannot expand it, or this PlatformAgent does not control it), also gets one `DataVolumeUndersized` Warning Event per state. |
| `ExternalModelEgress` | Only while the resolved Google Cloud universe domain is not `googleapis.com` and `status.inference.provider` is an external SaaS provider (any provider other than `openai_compatible`, `vertex_ai`, `hosted_vllm`, `vllm`, `ollama`, or `custom`) | `status: True`, `Reason: ExternalSaaSProviderInCustomUniverse`. Prompts, cluster telemetry excerpts, and tool results leave the sovereign or partner universe boundary to reach the external model provider. Not `Degraded`: `Ready` is unaffected, since an operator may authorize external model egress deliberately. Switch LiteLLM to an in-universe endpoint (`openai_compatible` or `vertex_ai` with `platformAgent.harness.universeDomain` set on the chart) to clear it. |

<!-- prettier-ignore-end -->
<!-- END GENERATED: crd-conditions-platformagent -->

Not everything the operator learns is a condition. One thing the bus
provisioning Job finds about a stream it could not change is recorded as an Event on the
`PlatformAgent` instead: a `TASKS` stream created before the render carried a per-subject cap keeps
running unbounded, and the pass that first sees the Job complete records a `Warning` Event, reason
`TasksSubjectCapMissing`, naming the Job, the live and rendered caps, and the `nats stream edit` that
closes the gap with what that edit costs. A stream carrying some other finite cap is drift, not that
gap, and stays in the Job's pod log.

The byte caps of `TASKS` (8 GiB) and `TOPICS-JOURNAL` (1 GiB) apply to streams this release
creates. An existing stream above its cap keeps it, since provisioning does not edit a stream. The
operator then records a `Warning` Event on the `PlatformAgent`, reason `A2ABusStreamCapAboveRender`.
It names the stream, its live and new `max_bytes`, what it holds, and the `nats stream edit` that
lowers it. It also says whether applying the edit now is safe: a stream holding under half the new
cap evicts nothing when lowered.

The Event is recorded once per Job run, so roughly daily while the gap stands, because the finished
Job is removed by its TTL and run again; Events themselves expire on the cluster's event TTL (an hour
by default), so between runs it can be gone, and the next run records it again. Read it with
`kubectl describe platformagent` or
`kubectl get events -n kubeagents-system --field-selector involvedObject.kind=PlatformAgent`.

`EventWatcher` is absent on a healthy install rather than `True`, deliberately. The operator can say
it asked for a watcher, but nothing here checks that one is alive, and a permanently-`True`
condition would read as a health signal it is not. Disabling the watcher is also not a `Degraded`
state — it is a decision somebody made, and `phase` stays `Ready`. `VolumesDropped` follows the
same shape: it exists while the spec carries a `hostPath` or watcher-token entry and a pass has
rendered around it, and it is the render-side half of the `hostPath` and watcher-token refusals,
which the admission webhook makes at admission on installs where it runs.

It is a claim about the Pod **template** the operator rendered, not about the Pod that is running.
The controller server-side-applies the template and returns as soon as the API server accepts it;
nothing waits on the rollout. So on the first pass of an operator carrying this behaviour over a CR
that a previous one rendered with real `hostPath` mounts, the condition reads `True` while Pods from
the previous revision still mount them — until the roll replaces them, or indefinitely if it stalls
at `progressDeadlineSeconds`.

`Ready` does not close that window either: `readyReplicas` counts ready Pods across every ReplicaSet
the Deployment owns, so one still-ready old Pod is enough for `phase: Ready`. The operator runs the
gateway as a single replica (see `availability.replicas` above), so the strategy is always
`Recreate` and the window is only as long as the replacement itself.

While the operator can see the roll is unfinished — the workload has not observed the applied
template, or it counts Pods that are not on it — the message says so in a sentence of its own. A CR
parked `Degraded` by `A2AProvisionFailed` or `ShellSandboxKeysMissing` carries
it on the same terms: those two refusals render before they park, so that status write reads the
gateway workload back to see whether the roll has finished.

```console
$ kubectl describe platformagent platform-agent -n kubeagents-system
...
  Conditions:
    Type:                 EventWatcher
    Status:               False
    Observed Generation:  3
    Reason:               DisabledBySpec
    Message:              Cluster event ingestion is disabled by spec.harness.eventWatcher.enabled=false. …
```

### What `Ready` reports

A deliberate pause is not a failure, and the condition says which it is. While `spec.deployment.scaleToZero` is `true` and the gateway Deployment has no ready replica, the phase reads `Paused`. `Ready` then reads `False` with reason `ScaledToZero`, and the message names the field and says how to resume. The pause is reported once the scale-down has converged: a replica still serving keeps the install `Ready` for the seconds the Deployment controller takes to remove it.

The pod scan still runs first. A crash loop or an unpullable image in the shell sandbox, the credential broker, the A2A gateway or the verifier parks `Degraded`, as on a running install, since those workloads are not scaled with the gateway. A workload the scan names no fault in but that has no ready replica (a failing readiness probe, a StatefulSet that is gone) keeps the phase `Paused`, and the message names it after the pause. Clearing the field returns the normal phases: `Provisioning` while the gateway starts, `Ready` once it is up. A gateway at zero replicas with the field unset is the start-up wait it always was, `Provisioning` with `Waiting for deployment replicas to be ready`.

With the A2A gateway's election on, `Ready` follows the elected leader. That is the `<agent>-a2a-gateway` Lease holder, which alone binds the event relay. A standby reads Ready while the leader may not. So when some replicas are ready and the leader is not, the gateway counts as not ready. `Ready` reads `False` with reason `Provisioning`, naming the gateway Deployment and the leader pod.

- **Grace:** a leader elected less than 30 seconds ago gets that long to bind, so a normal failover does not flip `Ready`. `Ready` can lag a stuck leader by up to 30 seconds.
- **No current leader:** with no holder, a holder whose pod is gone, a holder that stopped renewing, or a failed read, the gateway counts by its ready replicas.
- **Unchanged:** at one replica, or with the election off (the operator's `A2A_GATEWAY_ELECTION=false`), the gateway counts by its ready replicas.

`UniverseDomainMismatch` returns before rendering workloads whenever `spec.harness.universeDomain` is malformed, is under `googleapis.com`, or disagrees with the host cluster's GKE metadata server. Of the reasons that park `phase: Degraded`, `ShellSandboxKeysMissing` renders the stack in full and reports at the end rather than returning early, because the objects are wanted in place so the Pod starts by itself once the Secret appears.

A failed A2A provisioning Job parks the phase the same way with `A2AProvisionFailed`, naming the Job to inspect. That signal is prompt where the refusal is deterministic. The script exits 2 for a refusal a re-run cannot clear, the Job's `podFailurePolicy` matches exit 2 with `FailJob`, and the Job fails from its first pod, so the condition is written in seconds. Any other failure (NATS unreachable, an unexpected command failure) matches no rule and still spends the `backoffLimit: 20` retry budget, which is the slow path it used to take. While it retries, `A2AProvisionRetrying` names the Job and its failed-pod count, without changing the phase.

Two installs reach `A2AProvisionFailed` from opposite ends:

- **A fresh install** looks healthy first: NATS `1/1`, clients authenticating, while every stream read returns `stream not found` (`err_code=10059`). A fresh install with no streams and no `Degraded` condition is this, not a render fault.
- **An install that already has a bus**, with every stream and bucket present, is refused by the script's closing check when `TASKS` holds fewer consumers than `tuning.maxSessions` needs plus a reserve. The reserve is sized from the `BRIDGE_CONCURRENCY` a declared bridge sidecar sets, or, where the operator renders the bridge, from the operator's `A2A_BRIDGE_CONCURRENCY` (10 when unset), up to 1024 workers, the bridge's own queue capacity. So declaring a bridge sidecar with more workers, or raising `A2A_BRIDGE_CONCURRENCY`, on an install whose bus already exists reaches it too, and there the symptom is a working bus.

The script's refusal quotes both numbers, the rule it read the count by, and whether it capped it. Where a sidecar's entry took the bridge's default because the render could not read it as a count (a `valueFrom`, or a reference to one), the condition's message says the count is what the render read rather than what the CR declares, and states that rule. The script also prints a `NOTE:` on every run, refused or not, when an entry took the default or a sidecar carries `envFrom` with no `BRIDGE_CONCURRENCY` in `env`, a key the render does not read, since the budget may then be short for the real count.

A stream edit does not clear it: `max_consumers` is the one limit nats-server will not change on a stream that exists, answering an update that carries a different one with `stream configuration update can not change MaxConsumers`, and the rendered bus is pinned to `nats:2.10`. The message names the ways out that do work, and splits them by how they finish:

| Way out                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | How it finishes                                                                                                                         | What it costs                                   |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| Lower `tuning.maxSessions` until the budget fits the stream                                                                                                                                                                                                                                                                                                                                                                                                                          | By itself: the edit re-renders the provision Job, whose name digests that render, so a new Job appears and runs with nothing else to do | Fewer concurrent sessions                       |
| Where the CR declares a bridge sidecar with more workers than the bridge's default of 2, declare it with fewer (a lower `BRIDGE_CONCURRENCY`, or none); or, where the operator renders the bridge, set the operator's `A2A_BRIDGE_CONCURRENCY` to fewer workers (unset, the rendered bridge runs 10). The message offers this lever only above the default, and attributes the need to it alongside `maxSessions` wherever the declared count moved the reserve, one worker included | By itself, the same way                                                                                                                 | Fewer bridge workers                            |
| Delete the `TASKS` stream and let provisioning recreate it at the width the CR asks for                                                                                                                                                                                                                                                                                                                                                                                              | Not by itself: nothing re-reads the bus until the Job runs again, so delete the Job to re-run it, or leave it and the 24h TTL will      | The 72h of task history that stream was holding |

Deleting the Job before one of those ways out is taken (the two, or the three where the fewer-workers lever is offered) helps nothing: the same script refuses again against the same stream.

Recreating the stream costs one more step, and the order matters. Once `TASKS` is back, restart the A2A gateway (`kubectl rollout restart deployment/<agent>-a2a-gateway`), and the agent workload `<agent>-gateway` with it where a Hermes bridge sidecar runs. Deleting a stream deletes every consumer on it, and neither of those two durable readers re-creates one, so a gateway left running keeps accepting delegations and spawning session pods while relaying no events, the bridge dispatches nothing, and the CR reads `Ready` over both; session pods recover by themselves, which hides it.

A gateway restarted before the stream is back waits for it, not ready, and for its durable, which provisioning creates with the stream, then binds once both exist. Past five minutes of that wait, with `BusProvisioned` already `True`, the CR also reads `Degraded` with reason `A2AGatewayWaitingForTasks` until it binds. A bridge restarted early is less tidy: it waits for its durable but reports ready meanwhile, and if a task was in flight when the stream went, its startup sweep fails and the pod restarts until the stream is back. So restart the bridge's workload after the stream is back.

The operator takes that step itself once `TASKS` is back after a loss it saw (`BusStreamsPresent`), whether a re-run or a fix by hand brought it back. It restarts whichever of the two has been running since before the loss, and the `A2ABusClientsRestarted` event names them. After a loss the operator didn't see, such as one fixed between two polls, restart the two yourself.

### What `Degraded` reports

The `Degraded` condition carries one reason at a time:

| Reason                            | What it means                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `InvalidGitRepoURL`               | An invalid entry in `spec.integration.forges` or `spec.integration.repositories`, such as a namespace outside the provider's grammar or a repository on a host its forge's provider does not serve. Subsequent updates are rejected at admission until corrected.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `CorruptManagedRepos`             | Unparseable `managed_repos` JSON in the `<agent>-gitops-state` ConfigMap; GitOps disabled.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `MinterPruningHeld`               | A `github` entry in that ConfigMap's `managed_repos` or `context_repos` that this release cannot read. The operator prunes no minter policy while it is listed, so a repository removed from the lists keeps its write policy until the entry is corrected or removed. `Ready` and the phase are left as the workload reports them.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `A2ABusStreamsMissing`            | `BusStreamsPresent` is `False`: streams or KV buckets the provisioning Job created are missing from the bus. The message is the condition's, naming them and what the operator is doing about it. It follows `BusStreamsPresent` while `Ready` is parked on a refusal too, such as `A2AProvisionFailed` or `ShellSandboxKeysMissing`, and when the streams are back it gives way to the resource, exec-tier, or admission refusal it outranked, or clears.                                                                                                                                                                                                                                                                                                                                                            |
| `A2AGatewayWaitingForTasks`       | With NATS up, the A2A gateway's elected leader (the `<agent>-a2a-gateway` Lease holder, which binds the event relay) has not turned ready for 5 minutes since the latest of its start, its election and `BusProvisioned` turning `True`. A standby can read Ready meanwhile. Provisioning created `TASKS`, so the leader most likely cannot see it: a different NATS account, wrong credentials, or a mismatched JetStream domain. Its `/readyz` body on the metrics port names what it waits on. The phase is not changed for it. `Ready` follows the leader ([What `Ready` reports](#what-ready-reports)), so it reads `False` while the leader waits. Cleared once the leader binds.                                                                                                                               |
| `InvalidCredentialProxyResources` | A refused `credentialProxy.resources` override under [`spec.deployment`](#specdeployment); the proxy renders at the sizing profile's row (the operator's defaults under `small`) until it is corrected. Written when no higher-ranked `Degraded` cause is present.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `InvalidAgentAPIAuthResources`    | A refused `agentAPIAuth.resources` override under [`spec.deployment`](#specdeployment); the sidecar renders at the sizing profile's row (the operator's defaults under `small`) until it is corrected. Written when no higher-ranked `Degraded` cause is present.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `InvalidShellSandboxResources`    | A refused `shellSandbox.resources` override under [`spec.harness.experimental`](/kube-agents/operator/platformagent-harness/#shellsandbox); the shell renders at the sizing profile's row (the operator's defaults under `small`) until it is corrected. Written when no higher-ranked `Degraded` cause is present.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `InvalidCredentialProxyExec`      | A positive `credentialProxy.exec.replicas` under [`spec.deployment`](#specdeployment) on an agent whose name is longer than 36 characters; the exec tier is not rendered, and every command goes to the stateful broker until it is corrected. Written when no higher-ranked `Degraded` cause is present.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `InvalidKanbanAdmission`          | Effective `kanban.admission` `memoryBudgetMiB` (from `spec.harness.tuning.admission.memoryBudgetMiB`, or derived from `spec.deployment.resources`) is below `workerRssCapMiB`, so a single worker's RSS cap exceeds the pod's admission budget (and at sub-1536MiB budgets leaves zero spawn headroom once the gateway idles). The operator still renders the resolved values into `managed-config.yaml` and emits a `Warning` Event, leaving `Ready` and `status.phase` to workloads. Raise `memoryBudgetMiB` (or container memory request when `memoryBudgetMiB` is unset) to at least `workerRssCapMiB`, or lower `workerRssCapMiB`. Written when no higher-ranked `Degraded` cause is present.                                                                                                                    |
| `RBACIncomplete`                  | Install skew, not a spec fault: the ClusterRole or namespaced Role bound to the operator denies a permission its RBAC markers declare, the shape of an image deployed ahead of its manifests. The message names the denied verbs and the fix. A denial marked `(in namespace ...)` is written on this agent alone: that namespace, the agent's own or its profile namespace, lacks the operator's namespaced Role and a RoleBinding to it. For the install's profile namespace, delete any hand-made copy and run `helm upgrade` or `make deploy`; a namespace neither path renders into gets both by hand. While any other `Degraded` reason holds the condition the RBAC reason is not written; the operator's log (`RBAC self-check failed` at startup, `RBAC self-check result changed` after) is the only trace. |

### What `BusCredentialsReady` reports

`BusCredentialsReady` says whether every replica the callout Deployment asks for is ready, and therefore both serving an identity map and attached to the bus: its readiness probe answers 503 unless both hold. It is the claim about the callout as a whole, not the rule a dispatcher waits on. A workload dispatched before the callout can authenticate it is refused with an error indistinguishable from a bad credential, and one callout replica serving on the current spec is enough to prevent that. The operator's own gates do not read it.

**The gate the operator reads instead.** The bus provisioning Job is not **created** until the callout Deployment's status shows one ready replica on any template (its principal is authenticated by every replica, all of which serve the current map). The A2A gateway Deployment is not **created** until the callout Deployment's status shows at least one replica that is both ready and on the current pod template (`ReadyReplicas + UpdatedReplicas - Replicas >= 1`). That count is read once the Deployment controller has observed the current generation, from a copy of the Deployment whose generation has reached the one the operator's own apply of the callout returned in that pass. Once the gateway exists it is reconciled normally.

That gate is narrower than this condition on purpose. The callout's replicas form a NATS queue group, so one serving replica answers every authorization request, and a callout whose second pod cannot schedule would otherwise withhold a first gateway indefinitely. The lower bound cannot read true while no current-template replica is serving, so a gateway created while this condition is `False` still has a serving replica to authenticate its sessions. Expect the two to differ: this condition reads `False` with `1 of 2 replicas ready` while the gateway exists and dispatches.

The hold is not silent: the A2A gateway is one of the workloads `Ready` is a claim about, so while it is withheld by this gate the phase reads `Provisioning` and the `Ready` message names the Deployment.

**Why the gateway's creation is what waits.** What waits on the callout is not the gateway's own connection. The gateway is a static principal, `NATS_USER=gateway` with a rendered password, listed in `auth_users` and so exempt from the callout exactly as the Hermes bridge sidecar is. It is what the gateway _spawns_: a session pod authenticates with a projected token that only the callout can turn into a bus identity, so a gateway created while the callout is unready accepts delegations and spawns sessions that cannot connect.

That is the ordering this condition exists to enforce, and the gateway's creation is the last moment the operator can enforce it. Creation only, so a callout that goes unready later does not freeze a running gateway's spec, and does not orphan the session pods that carry an `ownerReference` to it.

The gate's error directions are both false negatives, and each holds the gateway one more pass before the held reconcile's requeue clears it. While a terminated callout pod is still counted, one ready replica on the current template reads as none. On the pass that changed the callout's pod template, the operator's cached copy of the Deployment may still be the one from before that change, which the gate refuses rather than trusting counts that describe the previous template.

**Reasons and messages.** `Reason: CalloutServing` (`True`), `CalloutUnavailable`, or `CalloutAbsent`. The messages differ in what they can name: `CalloutServing` gives the identity map version being served, the two `CalloutUnavailable` messages give the ready count against the count asked for, and `CalloutAbsent` gives neither, because there is no Deployment to read either from.

Ready is counted against `spec.replicas`, not against the pods that exist. The callout rolls at `maxSurge: 1` over `maxUnavailable: 0`, so a healthy roll spends its whole duration with more pods than it wants, and a callout coming up spends its window with fewer. A condition comparing the two numbers to each other would call the first an outage and the second serving.

`CalloutUnavailable` also covers a spec change the Deployment controller has not observed yet, where the reported counts describe the spec before the roll; the message says so rather than reporting those counts as current. It does **not** assert that a named replica has observed a named map version, so a sub-second window after a re-render can report ready while a replica still serves the previous map.

**When it is removed.** Removed, not set false, only once the callout Deployment is gone, so the condition never describes a callout that is still running. It is re-derived from the callout Deployment on every exit from the reconcile, not at a point in its sequence. So a pass that parks `Ready=False` for an unrelated reason (a missing shell sandbox keypair, a refused `spec.deployment`, say) still reports it, rather than leaving it absent or, worse, leaving the last value standing while the callout it named goes away.

### What `DispatcherJobMode` reports

`DispatcherJobMode` says whether the profile dispatcher runs profile tasks as Jobs: unattended tasks, and confirmed changes at any tier. Job mode needs the dispatcher Job admission policy and its binding in the cluster as the chart renders them, the profile namespace selected by that binding, and the dispatcher holding its Jobs Role there. That Role grants create, read and delete on Jobs, and `get` on the `DispatchJobTemplate` objects it builds each Job from. Without it, the dispatcher refuses unattended tasks at admission (`no-worker`) and confirmed changes (`change-needs-job`). The operator also records a `DispatcherJobPolicyMissing` Warning Event on each pass the policy or the namespace selection fails, but Events expire; the condition stays.

**Reasons.**

| Reason                 | Status  | Meaning                                                                                                                                                                                                   |
| ---------------------- | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `InPlace`              | `True`  | The last pass that settled Job mode found the policy and binding in place and granted the dispatcher its Jobs Role in the profile namespace.                                                              |
| `PolicyMissing`        | `False` | The policy or its binding is missing, unreadable to the operator (`Forbidden`), or loosened. The message is the `DispatcherJobPolicyMissing` Event's and names which.                                     |
| `NamespaceNotSelected` | `False` | The profile namespace lacks a label the binding selects it by, so the policy does not hold there. The message is the Event's.                                                                             |
| `NamespaceNotReady`    | `False` | The profile namespace is absent or lacks the chart's markers, or the pass did not apply its network fence, which includes a failed fence write or a failed read of the namespace.                         |
| `ForeignJobTemplate`   | `False` | A `DispatchJobTemplate` under one of the operator's names in the profile namespace lacks this agent's labels. The operator leaves it alone, and Job mode stays off for every profile until it is removed. |
| `GrantFailed`          | `False` | Granting Job mode failed this pass (copying the CA bundle, writing the templates, applying the Jobs Role, or reading the profile namespace). The message carries the error.                               |

Every `False` reason means the pass left the Job templates out of the dispatch config and revoked the dispatcher's Jobs Role. If the revoke itself fails, the Role can still stand; the operator logs that error, and the condition keeps the reason that triggered the revoke. Jobs already running are left to finish.

**When it changes.** It follows what each pass does to the Jobs Role, written on the way out of the reconcile like `BusCredentialsReady`, so a pass that ends `Degraded` still writes it. A pass that changes nothing about the Role leaves it as it was: a read of the policy that fails for a reason other than `NotFound` or `Forbidden` (a timeout, throttling), or a pass that stops before the dispatcher step. So `True` describes the last pass that settled Job mode, not the cluster now: the operator does not watch the policy or its binding, so a policy removed since then shows on the next pass that reaches the dispatcher.

**When it is removed.** Removed, not set `False`, only by a pass that tore Job mode down or found nothing of it left. With the chart's signal off, that is once the dispatcher's Jobs, Job templates and Jobs Role are deleted. With no dispatcher image, it is once the dispatcher is removed. A pass that stops before that teardown (a refused `spec`, say) or whose teardown fails leaves the condition as it was, because the Jobs Role and the templates are still live.

### What `A2AGateway` reports

Every install runs the A2A gateway. With no chat backend configured (neither `spec.integration.googleChat` nor `spec.integration.slack` enabled, no `discord-bot` Secret with a `token` key in the namespace, and no door armed on the operator) it runs on the console door alone (`A2A_CONSOLE_DOOR=true`, rendered on every gateway), so the web console's chat pane has a gateway behind it, and taking a backend away leaves the same gateway running on the console.

Older operators withheld the gateway instead, or scaled an existing one to zero replicas, and wrote this condition with `Reason: NoChatBackend`. After the upgrade the next pass renders the gateway at one replica. A gateway that was at zero is scaled back on the same Deployment, the condition becomes `WaitingForReplica`, and `Ready` waits on the gateway; once a replica is ready the condition clears. Where the older operator never created the gateway, the condition clears on that first pass and `Ready` waits on the new gateway. `Ready`'s message, not this one, says what the replica is waiting on. A `NoChatBackend` condition on a gateway that is already ready clears on the next pass.

A `discord-bot` Secret created on a running install is not watched, so the gateway takes it on the next pass, within 15 minutes; `kubectl rollout restart deployment/<agent>-a2a-gateway` makes it immediate. Rotate the `discord-bot` token by updating the Secret in place, since deleting and recreating it can roll the gateway onto the console door alone if a reconcile lands in between. The running gateway picks the new token up by itself: `DISCORD_TOKEN` is in its secret-env digest, so a pass that reads the changed Secret rolls the pod (see [Rotating a Secret rolls the pod](/kube-agents/operator/platformagent-profile-config/#rotating-a-secret-rolls-the-pod)), and `kubectl rollout restart deployment/<agent>-a2a-gateway` makes it immediate.

### What `VolumesDropped` reports

The render leaves the named `hostPath` or watcher-token entries and every mount naming them out of the Pod template the operator applies. `Reason` is `HostPathVolumeDropped` when a `hostPath` volume is dropped, and `WatcherTokenVolumeDropped` when only watcher-token entries are dropped. The message lists them by field and index, and on a spec carrying more of them than the controller's 4096-byte list budget holds it lists as many as fit and counts the rest. Not `Degraded`: the Pod runs without them. It is a claim about that template and not about the Pod that is running, because nothing here waits on the rollout (the note under the conditions table).

It is written on whichever status the pass ends on, `Ready` or `Degraded`, because the drop happens at render and three of the reasons that park `phase: Degraded` render first. `ShellSandboxKeysMissing` is among them, which is where a chart-default install sits, and a chart-default install is one with no webhook in front of it.

The refusals that return **before** the render (`ReservedServiceAccountName`, `ForbiddenVolumeMount`, `ShellSandboxCannotBeDisabled`, `UniverseDomainMismatch`, `RuntimeClassNotFound`, `EgressAllowlistRefused`) neither write it nor clear it. No Pod is rendered on those passes, so the workload still running is whatever the previous pass left, and a condition written there would report the entries out of a Pod this operator never wrote. On an install rolled forward over a CR a pre-fix operator gave real `hostPath` mounts, that reads as the security property being satisfied while the live Pod still mounts them.

One already present is left exactly as it stands, because the pass that wrote it did render and that Pod is the one running. So while such a refusal holds, the message and the condition's `observedGeneration` can both lag the spec until a pass reaches the render again. Remove the entries to clear it.

### Telling a current status from a stale one

`status.observedGeneration` is the `metadata.generation` the status was last computed from, and the
`Ready` condition, with any `Degraded`, `EventWatcher` or `VolumesDropped` condition written in the
same pass, carries it in its own `observedGeneration`.

`Degraded`/`RBACIncomplete` is the exception: it is written when the set of denied permissions
changes and left in place otherwise, so its `observedGeneration` is the generation at which that set
last changed. `VolumesDropped` is the other: a refusal taken before the render leaves it untouched,
so while one holds its `observedGeneration` is that of the last pass which did render.

A spec edit bumps `metadata.generation` at admission and leaves both behind until the next
reconcile, so a `Ready` condition whose `observedGeneration` is below `metadata.generation`
describes the previous spec, and `kubectl wait --for=condition=Ready` on its own can return on it.
The field says the operator has processed that generation; it does not say the rollout it triggered
has finished. `Ready` is still derived from replica counts, and during a rollout the replica
satisfying it can be the previous one.

`Ready` is a claim about three workloads (the gateway, the shell sandbox and the credential broker),
and about the whole A2A stack as well: the NATS StatefulSet, the auth
callout Deployment, the provisioning Job's first completion (recorded as `BusProvisioned`, after
which the Job's re-runs do not hold `Ready`), and the A2A gateway. An install without any of
them serves no A2A request, and the message names whichever is missing.

That is also how the callout
ordering gate becomes visible: while the operator holds a first gateway creation back for a callout
replica to serve, the phase reads `Provisioning` and names the Deployment it is waiting on. The
gateway runs on every install, on the console door alone when no chat backend is configured, so
`Ready` always waits on it.

So to gate on a change, wait for the generation to be observed, then for the rollout of each
workload, then for the condition:

```bash
gen=$(kubectl get platformagent platform-agent -n kubeagents-system -o jsonpath='{.metadata.generation}')
kubectl wait platformagent/platform-agent -n kubeagents-system --for=jsonpath='{.status.observedGeneration}'="$gen"
kubectl rollout status deployment/platform-agent-gateway -n kubeagents-system
kubectl rollout status statefulset/platform-agent-shell -n kubeagents-system
kubectl rollout status deployment/platform-agent-credential-proxy -n kubeagents-system
# the gateway runs on every install, on the
# console door alone when no chat backend is configured. The verifier is not
# part of `Ready` — a rollout of it should not flip a serving install to
# Provisioning — but a submission arriving while no verifier is ready is
# refused terminally, so an install that stays down reports it as the
# `A2AVerifier` condition, which a Ready CR can carry.
kubectl rollout status deployment/platform-agent-a2a-gateway -n kubeagents-system
kubectl rollout status deployment/platform-agent-a2a-verifier -n kubeagents-system
kubectl wait platformagent/platform-agent -n kubeagents-system --for=condition=Ready
```

## How config reaches each profile

This section has its own dedicated reference page: [PlatformAgent: Profile config propagation](/kube-agents/operator/platformagent-profile-config/).

## Reconcile behavior

- On create/update, the controller ensures the Deployment, Service, ServiceAccount, and ConfigMaps match the spec.
- On delete, it garbage-collects owned resources (note that `litellm-policy` is owned by `Deployment/litellm` rather than `PlatformAgent`, so deleting `PlatformAgent` preserves `litellm-policy` while LiteLLM is still running to prevent fail-open egress).
- The admission webhook (behind cert-manager) validates the spec before it's persisted. It enforces at most one `PlatformAgent` per cluster, forbids sensitive environment variable overrides (`API_SERVER_KEY`, `HERMES_HOME`) and privileged containers/volumes (`hostPath`), and requires each `imagePullSecrets` entry to name a Secret. It refuses a `spec.storage.size` lower than the size the stored object resolves to (the `50Gi` default when it sets none), not above zero or above `64Ti`. It also acts as a name-based tripwire against obvious privileged service account names (`cluster-admin`, `system:admin`).

  The `hostPath` and watcher-token refusals have a second layer in the controller: a `hostPath` or watcher-token entry that reaches the reconcile anyway — the Helm chart ships the webhook off, and one enabled through the chart fails open at its default `failurePolicy: Ignore` — is left out of the Pod template at render with every mount naming it, and the `VolumesDropped` condition reports it. Note that full RBAC least-privilege enforcement is handled by controller- and pipeline-level policies rather than the admission webhook.

- The webhook admits that one `PlatformAgent` in the operator's own namespace only. A `PlatformAgent` created in any other namespace is refused on `metadata.namespace`: the Role that carries the operator's write verbs is bound in the operator's namespace and its profile namespace only ([Security and IAM](/kube-agents/reference/security-rbac/#the-operator-controller-is-a-separate-identity)). One that already exists elsewhere, created while the webhook was off, is updated with a warning naming the two namespaces that need the Role. It reports [`RBACIncomplete`](#what-degraded-reports) until they hold it.

- The webhook also refuses a user volume or mount on `spec.deployment` that would carry the A2A bus credential or the credential proxy's watcher token by a route other than the operator's own projection. The refused shapes are the reserved volume names `a2a-bus-token` and `watcher-credential-proxy-token`, a `serviceAccountToken` projection for the bus audience (`a2a-bus`) or watcher audience (`kubeagents-credential-proxy-watcher`) under any name, and a `secret` volume or projected `secret` source naming one of the Secrets the operator renders with bus credentials or keys in them (`<name>-a2a-nats-creds`, `<name>-a2a-nats-config`, `<name>-a2a-callout-keys`, `<name>-a2a-nats-tls`, `<name>-a2a-nats-ca`, `<name>-a2a-task-signing-key`).

  The render also leaves the same entries, and every mount naming them, out of the Pod (reporting the watcher-token ones on `VolumesDropped`). That happens whether or not admission ran; it is not a fallback for a skipped webhook, though a skipped webhook is when it is the only thing left. `env` references to those Secrets are not checked. This is a guard against misconfiguration rather than a boundary between the containers of one Pod, since a ServiceAccount token is pod-scoped.

- The `kubeagents.x-k8s.io/prevent-deletion: "true"` annotation on a `PlatformAgent` blocks deletion of the resource via the validating webhook (`ValidateDelete`). This serves as an accidental-deletion guardrail rather than an authorization control — `ValidateUpdate` does not block removing the annotation, so any principal with update permissions can patch the annotation off before deleting.
- The `kubeagents.x-k8s.io/enable-litellm-network-policy: "false"` annotation on a `PlatformAgent` opts the shared `litellm-policy` out of operator reconciliation and deletes any managed copy without affecting the agent pod's own NetworkPolicy. Note that deleting the managed policy leaves LiteLLM unselected (fail-open) unless a replacement NetworkPolicy is managed out-of-band.
- The `kubeagents.x-k8s.io/otlp-collector-namespace` annotation sets the collector namespace for `litellm-policy` when LiteLLM exports to an in-cluster collector whose namespace cannot be derived from `spec.telemetry.otlpEndpoint`.
- The `kubeagents.x-k8s.io/litellm-upstream-egress` annotation adds one egress rule to `litellm-policy`, to the model server an `openai_compatible` gateway calls. Its value is compact JSON in one of two forms: `{"namespace":"models","port":8000}` admits that namespace on that TCP port (for an in-cluster Service, the server pod's port), and `{"cidrs":["10.20.0.0/24"],"port":443}` admits those ranges on that port.

  `port` is 1 to 65535, `namespace` a DNS-1123 label, and `cidrs` holds 1 to 50 entries, each no wider than `/12` (IPv4) or `/48` (IPv6) and none reaching `169.254.0.0/16`, `fe80::/10` or a metadata address. A value that breaks any of these, sets both forms or neither, or carries an unknown field is ignored: the operator logs `Ignoring invalid annotation value` with the reason, adds no rule, and the reconcile carries on. [Inference gateway](/kube-agents/concepts/inference-self-hosted/#egress-to-the-server) covers how the chart derives the value from `litellm.openaiCompatible`.

- The `kubeagents.x-k8s.io/network-policy-enforcement: absent-accepted` annotation is a record, not a control: the Terraform composition stamps it when an install onto an existing cluster chose to proceed without NetworkPolicy enforcement, and the operator does not read it. [Installing without NetworkPolicy enforcement](/kube-agents/install/prerequisites/#installing-without-networkpolicy-enforcement) says what it means.
- Under the Helm chart, `platformAgent.annotations` is the route to these annotations. The chart stamps three of them itself: `enable-litellm-network-policy` from `litellm.networkPolicy=false`, `otlp-collector-namespace` from a non-empty `telemetry.collectorNamespace`, and `litellm-upstream-egress` from `litellm.openaiCompatible` when the provider is `openai_compatible` and the server needs a rule. When it does, an entry that disagrees with the value fails the render — see [PlatformAgent annotations](https://github.com/gke-labs/kube-agents/blob/main/charts/kube-agents/README.md#platformagent-annotations) in the chart README.
- The Helm chart renders and applies the CR (the install engine drives it through `terraform apply`); you can also edit it directly with `kubectl edit`.

## Where to go next

- [PlatformAgent fields](/kube-agents/operator/platformagent-fields/) — every `spec` and `status` field, generated from the Go API types.
- [`k8s-operator/README.md`](https://github.com/gke-labs/kube-agents/blob/main/k8s-operator/README.md) — build and test the controller locally.
- [Quick start (GKE)](/kube-agents/install/quickstart-gke/) — how the CR gets applied in a fresh install.
