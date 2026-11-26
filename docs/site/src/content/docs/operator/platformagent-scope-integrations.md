---
title: "PlatformAgent: Scope, networking, and integrations"
description: "Detailed reference for spec.scope, spec.networkPolicy, and spec.integration on PlatformAgent."
---

Part of [PlatformAgent CRD](/kube-agents/operator/platformagent-crd/).

## `spec.scope`

Optional. Which GCP projects, folders, organisations, Shared VPC hosts and Metrics Scopes, beyond
the project the agent runs in, the
hourly Cluster Agent reconcile enumerates for GKE clusters, and which projects and clusters it
leaves unmanaged. The management project is always in scope and cannot be excluded.

The chart renders it from `platformAgent.scope`, and the Terraform composition sets that value from
`scope` in its tfvars, which the installer generates from `SCOPE_PROJECTS`, `SCOPE_FOLDERS`,
`SCOPE_ORGANIZATIONS`, `SCOPE_SHARED_VPC_HOSTS`, `SCOPE_METRICS_SCOPES`, `SCOPE_MAX_PROJECTS`,
`SCOPE_EXCLUDE_PROJECTS` and `SCOPE_EXCLUDE_CLUSTERS` in `install.env`, so on those paths the field
is declared there and never by editing the `PlatformAgent`. The installer refuses a full upgrade
over a `spec.scope` edited by hand until `install.env` records it (it prints the `SCOPE_*` lines
that reproduce it) or the CR is put back. A retag, or a hand-driven composition apply whose rendered
scope is unchanged, leaves the edit in place because Helm sends only the difference between its
rendered manifests.

An empty scope is a present block with empty lists, rendered whenever the chart is given one
(`folders`, `organizations`, `sharedVpcHosts`, `metricsScopes` and `maxProjects` only when the value
carries the key, so a release record from before the chart knew them leaves the CR's lists and cap
alone on a retag; the composition always passes all five). A chart that is given nothing (the value
is `null`, its default) renders no block, which leaves the field as it finds it while no earlier
release rendered the block and removes it once one has, a removal the reconcile reads as no
declaration (the management project alone, nothing retired).

The composition binds the read roles before it writes the CR, which orders creation and not IAM
propagation. A first install's one-shot inventory sweep may still name a scoped project as
`denied`, and the hourly reconcile creates its profiles once the grant has propagated. Absent, the
reconcile lists the management project alone, every cluster there getting a Cluster Agent profile,
keeps the last declaration's exclusions and marks nothing newly `retiring` (a project an earlier
block already marked `retiring` is still pruned on a clean run); an empty `projects` list in a
present block drops the projects an earlier block declared, over two clean runs.

That default reaches every cluster in the management project, the ones nobody deployed the agent
for included. A scope with no membership list is the block absent, or present with every
membership list empty, which is what the installer renders without `SCOPE_*` values. While
that holds and the event watcher registers a cluster in the management project other than the
host, the operator writes the `ScopeUndeclared` condition with the count and names of the
adopted clusters ([Status](/kube-agents/operator/platformagent-crd/#status)). A profile in another project is not counted: nothing
adopted it. To keep the adopted clusters and clear the condition, name the management project in `projects`; to
leave a cluster unmanaged, list it under `exclude.clusters`, and the next reconcile prunes its
profile.

The condition covers a scope that names nothing. The management project stays in scope under any
declaration, so a scope that names other projects silences it without retiring the neighbours. On
an install made with `install.sh`, declare the scope in `install.env` (`SCOPE_PROJECTS`,
`SCOPE_EXCLUDE_CLUSTERS`) and run `upgrade.sh`; a hand edit of the CR is refused at the next full
upgrade, as the paragraphs above say.

```yaml
spec:
  scope:
    projects: # explicit project IDs, in addition to the management project
      - payments-prod
      - payments-staging
    folders: # numeric folder IDs, every project beneath them at any depth
      - "123456789012"
    sharedVpcHosts: # Shared VPC host project IDs, every service project attached to each
      - shared-net-host
    metricsScopes: # Metrics Scope scoping-project IDs, every project each scope monitors
      - observability-hub
    maxProjects: 100 # the most projects a run lists, the management project included
    exclude:
      projects: # project IDs or shell-style globs, dropped after resolution
        - "*-sandbox"
      clusters: # one cluster each, by the full triple
        - projectId: payments-staging
          location: us-central1
          clusterName: scratch-cluster
```

- `projects` — project IDs whose clusters get profiles. The agent's service account needs the
  read roles in each one (`roles/container.clusterViewer`, `roles/container.viewer`,
  `roles/compute.viewer`, `roles/monitoring.viewer`, `roles/logging.viewer`,
  `roles/iam.securityReviewer`, `roles/gkehub.viewer`, the read subset of the `read_only_roles` the Terraform composition binds in the management project). The composition binds the ones the management project holds, through the `kube-agents-iam` module's `scope` input, in every project the same value names; a CR edited by hand needs the same grants made by hand.

  A project it cannot list is reported as `denied`, `api-disabled` or `unreachable` ([Project outcomes](#project-outcomes)) and its existing profiles are kept. Each list is capped at 100
  entries, and the run lists at most `maxProjects` projects in total (100 by default), the management project included; an
  explicit project past that reads `over-cap` and is likewise kept but not listed.

- `folders` and `organizations` — numeric IDs of GCP folders and organisations. Each is resolved on every run with one Cloud Asset Inventory call, which names every GKE cluster in every project beneath it, at any depth. [`spec.scope.folders` and `spec.scope.organizations`](#specscopefolders-and-specscopeorganizations) has the roles it needs, the asset index's lag, and how a container the run cannot read or that crosses the cap is carried.
- `sharedVpcHosts` and `metricsScopes` — project IDs of Shared VPC host projects, and of the scoping projects of Cloud Monitoring Metrics Scopes. Neither is a Resource Manager container: each is resolved on every run to the projects it reaches, and those projects then take the `projects` path above. [`spec.scope.sharedVpcHosts` and `spec.scope.metricsScopes`](#specscopesharedvpchosts-and-specscopemetricsscopes) has the lookups, the roles they need, and how a monitored project the scope names by number reads.
- `maxProjects` — the most projects the reconcile lists per run, the management project included, 1 to 5000, 100 by default: explicit projects, selector members and container members fill it in that fixed order, and a project past it reads `over-cap` (profiles kept, nothing created).

  The reconcile lists with four workers at every cap and sizes its listing budget from it, 300 seconds per default cap's worth of projects, and the bootstrap gate's ceiling on the reconcile follows the budget, so an estate of a few hundred projects declares the number it has rather than reading half of itself `over-cap`; the snapshot records the cap in force under `maxProjects`. Each run creates at most 100 profiles and leaves the rest to the next run, so a wide scope onboards in batches a run apart rather than against that ceiling; `BOOTSTRAP_MAX_CREATES_PER_TICK` under [`spec.deployment.env`](/kube-agents/operator/platformagent-crd/#specdeployment) sets the number.

  The Terraform composition refuses a plan whose explicit projects and selector members exceed it, while a selector is declared or the cap is below its default, and renders the same value here from its `scope.max_projects` (`SCOPE_MAX_PROJECTS` in `install.env`). A CR edited by hand takes the value directly. The 100-entry cap on each declared list is unchanged: a hand-written list past a hundred entries is the shape folders exist for.

- `exclude.projects` — IDs or globs matched against every resolved project ID. An entry that names a number exactly (a glob never matches a number) also matches the number a Metrics Scope named a monitored project by, on whichever route the project is reached, so long as the run can tie the number to the project's ID.

  The run ties them by naming it, which the grant an entry in `projects` or a declared folder carries allows, or from the number an earlier run named it by. The snapshot keeps that number on the project's row and, once the entry has dropped the project and it has no row, in its `numbers` map, so a number entry keeps matching a project the run named before and can no longer name, and a naming call that times out does not admit the project again.

  A number the run cannot tie to an ID matches only the member the Metrics Scope reports under that bare number. An entry that matches the management project, by ID or by the number a Metrics Scope named it by, is ignored and recorded in the snapshot, never applied.

- `exclude.clusters` — single clusters by `projectId`, `location` and `clusterName`, because a
  cluster name is unique only within a project and location. This replaces the
  `RECONCILE_EXCLUDE` environment variable, which matched bare names across every project and keeps
  working for one release alongside it. An excluded cluster gets no Cluster Agent, and fleet answers,
  the onboarding sweep and the fleet-audit collectors that list clusters leave it out.

  The credential broker and `kube-proxy` refuse every route to an excluded cluster's Kubernetes
  API, for every caller, the agents' own commands included. That covers a kubeconfig the broker mints or uses, `gcloud container clusters get-credentials`, `kubectl` through `kube-proxy`,
  the watchers' cluster relay and the `gke` MCP server's in-cluster tools, each refused as `scope.excluded-cluster`. While any cluster is excluded, a target that names its project by
  number is refused too, and so is an in-cluster MCP call whose cluster the broker can't read.
  Spell entries by project ID: an entry spelled by project number refuses its location and cluster
  name in every project. A broker or `kube-proxy` that can't read the scope it was given reaches no
  cluster until it can (`scope.exclude-unreadable`).

  A GCP metadata read that names an excluded cluster is refused too, as `scope.excluded-cluster`:
  `gcloud container clusters describe`, `gcloud container node-pools list` and `describe`, and the
  `gke` MCP server's `get_cluster`, `get_node_pool` and `list_node_pools`.

  A logging read, through
  `gcloud logging read` or the broker's Logging relay, leaves out the cluster's entries. The broker
  adds one clause to the filter that matches the cluster's name, in any project and location, so a
  cluster that shares an excluded cluster's name loses its entries too. It refuses a
  filter it can't add one to safely.

  A session's or profile task's `gcloud container clusters list` and `gcloud container operations
list` leave an excluded cluster out too. The broker adds a `--filter` clause that matches its name,
  in any project and location, so a cluster that shares the name loses its row too. It refuses a
  `--filter` it can't add the clause to safely, and lists nothing while it can't read the scope.

  Other
  project-wide reads, such as an asset search or the instance list, aren't filtered, and every other
  caller's project-wide reads stay allowed, such as the project's cluster list. Exclusion keeps the
  agents out of a cluster's API, workloads, metadata and logs, not out of every caller's view of the
  project's cluster list. These still cover an excluded
  cluster, through project-wide reads only:
  - the daily upgrade-readiness watch and the Saturday `upgrade-readiness-weekly-review`, which
    grade its versions and skip their in-cluster readiness rules;
  - the networking audit's subnet usage, since its pods still hold their IPs;
  - the GCE audit's instance listing;
  - the third-party `gke` MCP server's `list_clusters`.

  The upgrade-readiness watch used to read inside an excluded cluster too. It no longer does,
  because the broker can't tell its reads from an agent's. The broker enforces the exclusion, not
  IAM: the agent's read roles still reach the cluster. Only a project where the agent holds no
  roles, bound there or inherited from a folder or organization, fences the service account off.

### Project outcomes

Each project the reconcile resolves reads one outcome in the run's snapshot:

| Outcome        | Meaning                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `ok`           | The project listed its clusters.                                                                                                                                                                                                                                                                                                                                                                                                           |
| `denied`       | No role left that grants `container.clusters.list`. `roles/iam.securityReviewer` alone keeps a project listable but not manageable, since it carries no `container.clusters.get`: its clusters list and every profile create fails, which is why the composition refuses a scope whose bindings carry neither `roles/container.clusterViewer` nor `roles/container.viewer`. A project reads `denied` only once every listing role is gone. |
| `api-disabled` | GKE API off in that project.                                                                                                                                                                                                                                                                                                                                                                                                               |
| `unreachable`  | Anything else, including a listing that did not finish within the run's listing budget.                                                                                                                                                                                                                                                                                                                                                    |
| `over-cap`     | Past the `maxProjects` cap: profiles kept, nothing created, the project not listed.                                                                                                                                                                                                                                                                                                                                                        |

A project with any outcome but `ok` keeps its existing profiles.

### `spec.scope.folders` and `spec.scope.organizations`

The design recommends folders until the scoped service account pool grants authority. A folder binding reaches every project beneath it, an organisation binding every project in the organisation, including ones nobody meant to manage, and one service account holds the read roles across all of them ([Security & IAM](/kube-agents/reference/security-and-iam/#roles-per-set)).

**Resolution.** Each is resolved on every run with one Cloud Asset Inventory call (`gcloud asset search-all-resources --scope=folders/<id> --asset-types=container.googleapis.com/Cluster`), which names every GKE cluster in every project beneath it, at any depth, including projects created since the last run; no per-project listing follows for them. The asset index is what answers, not Resource Manager: a project moved into or out of a folder appears under its new parent once the index has caught up, which after a move can lag by more than an hour, and until then it reads as absent from the container.

**A project the index dropped.** Because the index and not the declaration dropped it, a project that was reached through a still-declared container and is absent from the index is kept, listed under `unmanaged` with that reason and the time it was first found absent (`absentSince` on its row), and is back in scope the run the index places it again.

That holds whether or not it was also named in `projects`, so dropping the explicit entry while the project moves into the folder costs nothing, and the same holds when the folder is declared in the edit that drops the entry: a container the previous run did not know is what marks that edit, and the same day's grace applies.

It retires sooner when the declaration speaks, by the container leaving the CR or an `exclude.projects` entry naming it, and otherwise once it has been absent for a day, over the ordinary two clean runs. That is what retires a project that was deleted or moved under a parent the CR does not declare, since a deleted project answers 403 to `describe`, never NotFound.

A project dropped from `projects`, or whose folder leaves the CR, in the same edit that declares the folder it moved into is held that day too, since the index may not place it yet. A rollback to an operator that predates these fields renders a declaration without them, which the reconcile likewise reads as saying nothing about containers, so their members are kept.

**Roles.** The agent's service account needs `roles/cloudasset.viewer` and the read roles above on the container, and `cloudasset.googleapis.com` enabled in the management project. The Terraform composition binds both on each container its `scope` value names, through the `kube-agents-iam` module, and enables the API when a container is declared, and the installer checks before the apply that the credentials Terraform applies with can set IAM policy on each container and that no organisation policy forbids the API. A CR edited by hand needs the same grants made by hand, and recording such a container in `install.env` later hands its bindings to Terraform, which then needs that permission too.

**A container the run cannot read** (`denied`, `api-disabled`, `unreachable`) is frozen: the members the previous snapshot reached through it are carried forward under that outcome, nothing is created under them, and the scope prune stays off for the run. A project under two declared containers takes the live listing when either resolves, whichever sorted first, unless the cap is already reached. A member whose per-cluster call answers 403 reads `denied` for the run, unless it is also explicit or the management project, whose own listing decides.

**The snapshot.** The snapshot's `containers` array lists each container with its outcome and a project count: the projects the lookup returned for `ok` and `over-cap`, the members carried forward from the previous snapshot for a failed lookup. A member project's `via` names it (`folders/<id>`), or several sources when more than one produced it.

**Past the cap.** A container whose members would take the run past the `maxProjects` cap reads `over-cap` with nothing created under it. The members the run just resolved are carried reading `over-cap`, and because the run holds the full member list the prune is not held back. Those members are carried but not listed, and do not count against the containers after it, so a small folder declared beside a large one still lists.

What an operator above the cap does: raise `maxProjects` to the size of the estate; `exclude.projects` globs subtract members before the count, so a folder that carries sandboxes or archives is trimmed by pattern; or declare the sub-folders that hold the clusters, each counted on its own.

### `spec.scope.sharedVpcHosts` and `spec.scope.metricsScopes`

**Resolution.** Each is resolved on every run to the projects it reaches: `gcloud compute shared-vpc list-associated-resources <host>` for the service projects attached to a host, the host itself not among them, so name it in `projects` if its own clusters are wanted; `gcloud beta monitoring metrics-scopes describe locations/global/metricsScopes/<id>` for the projects a scope monitors, the scoping project included.

Those projects then take the `projects` path above: each lists its own clusters, needs the read roles in it, and reads `denied`, `api-disabled` or `unreachable` on its own. A project that is not a Shared VPC host resolves to no members. A selector's projects fill the set after the explicit projects and before the containers, each reading `over-cap` on its own past the cap.

**Roles.** Nothing is inherited through a Shared VPC or a Metrics Scope, so the Terraform composition resolves each selector when it plans (its `kube-agents-scope-resolver` module), with the same reads as the run and made as the identity it applies with.

It binds the read roles in every project resolved and in each scoping project, and `roles/compute.viewer` alone in a host not otherwise in scope, through the `kube-agents-iam` module. A read that identity cannot make fails the plan before anything is applied, naming the selector, and a monitored project it cannot name is left out by naming its project number in `exclude.projects`. A project attached or linked after the last apply reads `denied` until the next one binds it; a CR edited by hand needs the same grants made by hand.

The lookups themselves need `compute.projects.get` in the host project (`roles/compute.viewer` carries it) and, for a Metrics Scope, to read the scope in the scoping project: `roles/monitoring.metricsScopesViewer` (`resourcemanager.projects.get` and `resourcemanager.projects.list`) is the narrowest role that grants it, and the read roles above carry both between them, with the Monitoring API enabled in the scoping project (a scope whose API is off reads `api-disabled`).

**Monitored projects named by number.** The Monitoring API names monitored projects by project number, so the run names each with `gcloud projects describe <number>`, which needs `resourcemanager.projects.get` in that project. A monitored project the account cannot read cannot be named either, and is reported by number under the naming call's outcome (`denied` for a 403), or under its ID once an earlier run has named it (every row a scope named by number keeps the number, `retiring` rows included). One that a Shared VPC host, a folder, an explicit entry or the management project names by ID is listed on that route, and its own listing decides its outcome.

A monitored project whose ID the scope cannot carry, a legacy `example.com:name` ID, is reported by number as `denied` with the reason in the log rather than as a failed lookup, so it never holds the prune. Name the number in `exclude.projects` to drop it. A monitored project the account cannot name and no earlier run has named holds the scope prune for the run, as a folder it cannot read does, because the bare number could be any project, including one the same edit dropped from `projects`; granting `resourcemanager.projects.get` there, or excluding the number, releases it.

**A selector the run cannot read** is frozen exactly as a container is: the members the previous snapshot reached through it are carried under that outcome, nothing is created under them, and the scope prune stays off for the run. The `containers` array carries a row for it under its `via` name (`sharedVpcHosts/<host>`, `metricsScopes/<id>`). There is no index and no lag behind either lookup: a project detached from the host or unlinked from the scope leaves the set on that run and retires over the ordinary two clean runs. A rollback to an operator that predates these fields keeps their members, as for containers.

### How the A2A gateway checks a task's target

The A2A gateway checks a profile task's cluster target against this
block before it routes the task. A project named in `projects`, or the agent's own project, is
admitted directly. An excluded project or cluster is refused.

A project that only a folder, organisation, Shared VPC host or Metrics Scope reaches is admitted
only from the resolved scope, which the operator publishes in the `<name>-resolved-scope`
ConfigMap. The project must be listed there as readable. The list must match this `spec.scope`
and be refreshed within two publisher cycles: 40 minutes at the default `maxProjects`, longer at
a higher cap. Otherwise the task is refused as not confirmed in this install's scope, with the
reason: the resolved scope is stale, it reads too large or failed, or the project cannot be read. The `ScopeResolved`
condition on the `PlatformAgent` says whether the resolved scope is current.

### Rolling the release back past the scope fields

Remove the whole `spec.scope` block from the CR first and re-add it after. A `cluster_agent_reconcile.py` from before `folders` and `organizations`, or from before `sharedVpcHosts` and `metricsScopes`, reads the same `scope.json`, ignores those keys, and finds every container or selector member in its previous snapshot but not in its resolved set, which is the ordinary two-run retire; a CR without the block marks nothing newly `retiring`. On a default install the agent image follows the operator's, so an operator rollback is an agent rollback too.

### How the declaration reaches the reconcile

The operator renders the block as `scope.json` in the agent's config ConfigMap, mounted read-only at `/etc/kube-agents/scope.json`, so editing it moves the config hash and rolls the pod. The file records whether the CR carries a `scope` block at all: a CR without one declares nothing, so the reconcile lists the management project alone and marks nothing newly `retiring` (a project an earlier block already marked `retiring` is still pruned on a clean run), keeping the last declaration's exclusions and carrying its projects, because a block goes missing on its own when a CR write passes an older operator's webhook. To drop projects, empty `projects` and keep the block.

### What a reconcile run records

Each reconcile run (other than `--dry-run`) writes what it resolved to `fleet_scope.json` beside the profiles on the data volume:

| Entry             | What it holds                                                                                                                                                                                                                                                      |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `declared`        | The declaration the run applied, or on a run that could not read it the last one read.                                                                                                                                                                             |
| `projects`        | Each project with its outcome: `ok`, `denied`, `api-disabled`, `unreachable` or `over-cap`.                                                                                                                                                                        |
| `unmanaged`       | The profiles whose project the scope never produced or whose prune waits for a clean run. A profile whose identity could not be read is kept but appears under the report's `skipped_no_identity`, and under `profiles` once an earlier run has read its identity. |
| `ignoredExcludes` | Any exclusion it declined to honour.                                                                                                                                                                                                                               |
| `containers`      | Every folder, organisation, Shared VPC host and Metrics Scope with its outcome and member count, with `resolver` reading `asset-inventory` once a folder or organisation is declared and `explicit` otherwise; it says nothing about the two selectors.            |
| `profiles`        | Each profile's project as read this run or, for a profile whose identity could not be read, as last read, which is what keeps such a profile attributed while it stays on the volume.                                                                              |

### When profiles are pruned

A cluster named in `exclude.clusters` loses its profile on the next run, unconditionally, as `RECONCILE_EXCLUDE` always did. A project removed from the scope, or newly matched by an `exclude.projects` entry, has its profiles pruned over two clean runs. A run is clean when no project came back `unreachable`, every folder, organisation, Shared VPC host and Metrics Scope resolved `ok` or `over-cap`, the management project resolved, listed its own clusters and is the one the previous snapshot named, and the scope file was readable.

The first clean run that finds a previously in-scope project absent records it as `retiring` in `fleet_scope.json` and keeps its profiles (listed under `unmanaged`); the next clean run deletes them, so a scope edit reverted before that run costs nothing. A run that cannot read the declaration is not a clean run and prunes nothing.

One that reads a CR without a scope block keeps the exclusions of the last declaration it read and marks nothing newly `retiring`, so a rollback to an operator without the field neither re-onboards an excluded cluster nor, on the roll forward, prunes a project the rollback's own CR write dropped. A profile the scope never produced is kept and listed, which is also what a project dropped while `fleet_scope.json` was lost between the two runs becomes: declare and drop it again to retire it.

**The management project.** A management project that changes identity (`RECONCILE_PROJECT` re-pointed, or the metadata server naming another project) marks the old project `retiring` on the run the change is seen, once the new project has listed its own clusters, and the next clean run prunes, unless `projects` names the old project and no `exclude.projects` entry matches it. An answer from the gcloud config fallback that disagrees with the previous run is treated as unresolved instead. Nothing is created or retired under the management project until an authoritative source, or a fallback answer that matches the previous run, names it.

**The onboarding sweep** names any folder, organisation, Shared VPC host or Metrics Scope the reconcile could not resolve and, on an install whose scope resolved more than one project, any project it could not list, so a partial roster reads as partial; an install with one project and no container renders the sweep prompt it rendered before scopes existed.


## `spec.networkPolicy`

Configures the operator-generated egress `NetworkPolicy`.

- `enabled` (bool, optional) — toggle operator-managed NetworkPolicy generation. Default `true` (unset
  means on). Setting `false` stops generation and deletes the policies the operator manages for this
  agent: `<name>-gateway-netpol`, the `<name>-fqdn-netpol` `FQDNNetworkPolicy`, the shared
  `litellm-policy` (if LiteLLM is present). The gateway policy also carries the audit-report store's rule, which goes with it. Deletions check ownership / managed labels first, so a
  policy that the operator did not create survives. To opt only LiteLLM out of operator NetworkPolicy
  management while keeping the agent pod's policies managed, set the annotation
  `kubeagents.x-k8s.io/enable-litellm-network-policy: "false"` on the `PlatformAgent`. When opted out, the operator deletes any managed copy of `litellm-policy`, leaving LiteLLM unselected (fail-open) unless a replacement policy is provided and managed out-of-band.

  With it off, an install's own policies over the gateway pod should also admit TCP `8700` from the
  credential broker's pods alone: the audit-report store listener's port.

  **Upgrade note:** when upgrading from a chart version that shipped the static `litellm-policy`, Helm
  prunes the static policy on the first upgrade (unless the live object already carries
  `helm.sh/resource-policy: keep`, in which case Helm retains it and the operator adopts it). The operator recreates it once the new operator pod
  rolls out, acquires leader election, and reconciles. LiteLLM is unselected (fail-open) during this
  operator rollout window.

  To eliminate this window on an existing cluster, annotate the live policy before upgrading (`kubectl annotate netpol litellm-policy helm.sh/resource-policy=keep -n <namespace>`); Helm will retain the policy across the upgrade and the operator will adopt it via Server-Side Apply. Alternatively, pre-roll the new operator image before running `helm upgrade` to narrow the window to controller watch latency (~1s), or manage the
  policy out-of-band during the transition via `litellm.networkPolicy=false`. The same window
  opens on a fresh default install, with no live object to annotate; the chart README's
  [upgrade notes](https://github.com/gke-labs/kube-agents/blob/main/charts/kube-agents/README.md#upgrade-notes-static-to-dynamic-networkpolicy)
  say how to cover it. Going the other way,
  from operator-managed back to the static copy, needs a handoff first — see
  [Handing `litellm-policy` back to Helm](https://github.com/gke-labs/kube-agents/blob/main/charts/kube-agents/README.md#handing-litellm-policy-back-to-helm)
  in the chart README.

- `dnsClusterIPs` ([]string, optional, max 8 items) — pins the cluster DNS Service ClusterIPs in
  rule 1 of both the agent gateway policy (`<name>-gateway-netpol`) and the LiteLLM gateway policy
  (`litellm-policy`), suppressing dynamic discovery from `kube-system/kube-dns`. Each entry is a bare IPv4 or
  IPv6 address with no prefix. Admission bounds the IPv4 octets and rejects the leading-zero form
  (`010.96.0.10`) that Go's `net.ParseIP` refuses, so the usual typos are apply-time errors. A malformed
  IPv6 literal can still get past it, in which case the operator drops the entry and falls back to
  discovery, and says so in its log.
- `metadataDaemon` (object, optional) — pins the node-local cloud metadata daemon IP in the
  metadata rule of `litellm-policy` (rule 4); the gateway policy has no metadata rule. Its
  one field, `endpoint`, is required within it, so `metadataDaemon: {}` is rejected; an explicit
  `endpoint: ""` suppresses the post-NAT metadata rule entirely, for datapaths without a post-NAT daemon. Leave it
  unspecified to let the operator discover the container port from the `kube-system/gke-metadata-server`
  DaemonSet on port `metadata-server` (promoting `metadataDaemonIPSource` to `Discovered`). If undiscoverable,
  it falls back to `169.254.169.252` on port `988`. Overriding the endpoint explicitly opts out of port
  discovery and uses port `988`.
- `additionalEgress` ([]EgressRule, optional, max 32 items) — appends custom CIDR and port egress
  rules to the generated agent gateway policy (`<name>-gateway-netpol`). (Does not apply to `litellm-policy`.) A peer CIDR broader than `/12` (IPv4) or `/48` (IPv6) is rejected at
  admission, so that a caller-supplied range cannot be widened into an unrestricted egress bypass.

  One shape gets past that check and is dropped by the operator instead: an IPv4-mapped IPv6 block
  such as `::ffff:0:0/96` is a 128-bit prefix by every textual measure, so it clears the IPv6 floor,
  and the operator re-measures it against the IPv4 floor once it has collapsed it to the IPv4 block
  it means.

  An `except` block that is not a strict subset of its peer's CIDR is dropped too — the API
  server rejects the whole policy for one that is not — and a rule left with no usable peer is
  dropped whole — a rule carrying ports and no peer would otherwise permit egress to every
  destination. All three are logged, so the operator's log is where a rule that did not take effect
  explains itself.

  A rule's `ports` list is optional, and omitting it is not one of those drops. A rule with peers
  and no ports permits **every** port to those peers, which is what a NetworkPolicy egress rule with
  an empty port list means. Nothing is logged, because nothing was dropped. List the ports unless
  that is what you want.

  A peer's `except` entries may be written bare (`10.0.1.5`, meaning a `/32`) as well as with a
  prefix, the same as `cidr`. Unlike `cidr` there is no prefix floor on them, because an `except`
  has to be a strict subset of its peer to be kept at all.

Annotations (`kubeagents.x-k8s.io/dns-cluster-ip` and `kubeagents.x-k8s.io/metadata-daemon-ip`) remain
available as escape hatches and take precedence over `spec.networkPolicy`.


## `spec.integration`

Enables external integrations. Only the enabled ones need to be present.

- **`googleChat`** — `enabled` (default `false`), `projectId`, `topicName`, `subscriptionName`, `allowedUsers`, `homeChannel`, `homeChannelPolicy` (`auto` or `manual`; absent means `auto`), `mode` (`default` or `debug`, default `default`), and `answerFeedback`. `answerFeedback` defaults to `true`; `false` hides the 👍/👎 buttons under answers and keeps no rating ([Answer feedback](/kube-agents/concepts/chatops-a2a-gateway/#answer-feedback)). `homeChannelPolicy` says whether the gateway may learn the home space from the first mention ([`spec.integration.slack` on the A2A gateway](#specintegrationslack-on-the-a2a-gateway) has the rule). When `enabled`, `projectId`, `topicName`, and `subscriptionName` are required (enforced by a CEL validation rule). Populated by the installer when Google Chat is enabled.
- **`slack`** — `enabled` (default `false`), `botTokenSecretRef` and `appTokenSecretRef` (Secret refs, required when enabled), `allowedUsers`, `homeChannel`, `homeChannelName`, `homeChannelPolicy` (`auto` or `manual`; absent means `auto`), and `answerFeedback`. `answerFeedback` defaults to `true`; `false` hides the 👍/👎 buttons under answers and keeps no rating ([Answer feedback](/kube-agents/concepts/chatops-a2a-gateway/#answer-feedback)). `homeChannelPolicy` says whether the gateway may learn the home channel from the first mention ([`spec.integration.slack` on the A2A gateway](#specintegrationslack-on-the-a2a-gateway) has the rule). Populated by the installer when Slack is enabled. This field arms the A2A gateway's Slack backend, with or without `googleChat`; [`spec.integration.slack` on the A2A gateway](#specintegrationslack-on-the-a2a-gateway) says what that changes for the home channel, `allowedUsers`, and a multi-workspace install.
- **`teams`** — `enabled` (default `false`), `appIdSecretRef` and `appPasswordSecretRef` (Secret refs, required when enabled), `tenantId`, `allowedUsers`, `allowAllUsers`, `homeChannel`, `homeChannelName`, `adaptiveCards` (default `true`), and `inbound.enabled` (default `false`; needs `tenantId`, which the CRD enforces). Set when the Microsoft Teams integration is enabled.
- **`forges`** — the forges the agent talks to, up to 16. Each entry has a `name` (required; a DNS label that `repositories` refer to it by, unique in the list), a `provider` (`github`, `gitlab`, `gitea`, `bitbucket` or `bitbucket-datacenter`), and, with rules that depend on the provider, `host`, `scheme`, `port`, `namespace`, `credentialsRef`, `caBundleRef` and `identity`. [`spec.integration.forges`](#specintegrationforges) has each field's rules, the one-GitHub-host rule, and what the credential broker does with the Secrets.
- **`repositories`** — the repositories the operator registers, up to 64. Each entry has a `forge` (required; the `name` of an entry in `forges`), `repository` (required; up to 2048 characters), an optional `namespace` of its own that overrides the forge's, and a `role` (required): `gitops` for the repository the agent publishes its own changes to, at most one; `managed` for another repository it may change; `context` for one it only reads. [`spec.integration.repositories`](#specintegrationrepositories) has the accepted spellings, the refusals, and what the operator writes to the `<agent>-gitops-state` ConfigMap.
- **`repositories[].baseBranch`** — on a `gitops` or `managed` entry, the branch every pull request (a merge request on GitLab) onto that repository must target; absent means the repository's own default branch. [`spec.integration.repositories[].baseBranch`](#specintegrationrepositoriesbasebranch) says what the credential broker does with it and the spellings the schema accepts.
- **`github`** — deprecated alias for one forge with `provider: github`: `org` is its `namespace` and `gitRepo`, when set, is one `gitops` repository on it; the two resolve identically. Set `forges`/`repositories` or `github`, not both; a resource setting both is refused by a CEL rule on the CRD and by the webhook.

  This is still the spelling `install.sh` and the `full-install` Terraform composition write for a github.com install (a GitLab, Bitbucket or GitHub Enterprise Server install writes `forges`/`repositories`; see [GitLab as the GitOps forge](/kube-agents/install/gitlab/) and [Bitbucket as the GitOps forge](/kube-agents/install/bitbucket/)). The Helm chart renders one GitHub forge with no `credentialsRef`, no `caBundleRef`, no host other than a spelling of github.com, and at most one repository, the `gitops` one, with no namespace of its own, this way whichever values key set it, because `helm upgrade` does not update CRDs and an older CRD would prune `forges`.

  It does so only where the forge declares a namespace or the repository, and the repository is one the operator would accept for GitHub: `name`, `owner/name`, or an `http(s)://`, `ssh://` or `git://` URL, a schemeless host or an scp remote on `github.com`, `www.github.com` or `ssh.github.com`, with no port, naming `owner/name`. A repository the operator would refuse renders as the lists, so the refusal names the entry that was written. A repository that sets `baseBranch` renders as the lists too, since the alias has no place for it.

:::caution[Upgrade note: non-GitHub repository rejection]
Upgrading to an operator that accepts `provider: gitlab`, `provider: gitea`, `provider: bitbucket` or `provider: bitbucket-datacenter` needs the CRD from the same release applied first: `helm upgrade` does not update CRDs, an older CRD's enum refuses the newer providers, and the chart fails the render with that message when it can read the installed CRD.

Earlier operator versions passed arbitrary `https://` and `http://` URLs through to `CleanRepoURLWithOrg` without host validation. A repository now has to sit on a host its forge's provider serves — for `provider: github`, `github.com`, `www.github.com` or `ssh.github.com`, or the forge's declared GitHub Enterprise Server host. A forge at a host other than github.com must name its `provider`: the CRD refuses one without it, and the field has no default any more. A CRD of an earlier release stored `provider: github` on a forge written without one, so before you upgrade, check that every forge at a host other than github.com names the provider you mean. A forge written for a GitLab instance that way now reads as a GitHub Enterprise Server forge.

Existing `PlatformAgent` resources pointing at another forge reconcile into `phase: Degraded` with condition `Reason: InvalidGitRepoURL`, and subsequent updates to those resources are rejected at admission by the validating webhook, where it is enabled, until the `spec.integration.repositories` entry — or the deprecated `spec.integration.github.gitRepo` — is corrected or removed. A repository on GitLab, Gitea or Bitbucket needs a forge of that provider with a `credentialsRef`, named in the entry's `forge`. See the `forges` field above, [GitLab as the GitOps forge](/kube-agents/install/gitlab/) and [Bitbucket as the GitOps forge](/kube-agents/install/bitbucket/) for `install.sh`'s way of doing it, and [Gitea as the GitOps forge](/kube-agents/install/gitea/) for self-managed Gitea.
:::

:::caution[Upgrade note: repository spellings no longer rescued]
Earlier operator versions also rewrote four malformed GitHub spellings into a working repository. Each is now refused, with the same `Degraded` condition and admission behaviour as above:

- A single path segment after a host, with the owner taken from `org`: `github.gitRepo: github.com/infra` (or `https://github.com/infra`, `git@github.com:infra`) and `github.org: gke-labs` used to mean `gke-labs/infra`. A URL with one segment names an account, not a repository, so only a bare name is qualified by the namespace. Write `infra` or `gke-labs/infra`.
- A colon in place of the first slash of a URL with a scheme: `https://github.com:owner/repo`, `ssh://git@github.com:owner/repo`. After `://`, what follows the colon can only be a port, and git itself reads `github.com:owner` as the host. Write `https://github.com/owner/repo`, `ssh://git@github.com/owner/repo`, or `git@github.com:owner/repo`.
- An owner containing `_` or `.`, which no GitHub account can have.
- A URL with any bracket in its userinfo, paired or not, or an unpaired one elsewhere in its authority: `https://[TOKEN]@github.com/owner/repo`, `https://[x@github.com/owner/repo`. Earlier versions read the host after the last `@`; the agent's URL parser refuses these (with a bracket in the userinfo it accepts only an address literal as the host), so it reads no repository from the value either. A bracketed IPv6 host after the `@` is unaffected.
- A schemeless remote with a `:` in its userinfo, or an empty one: `user:token@github.com:owner/repo`, `a:b@github.com/owner/repo`, `:x@github.com/owner/repo`, `@github.com:owner/repo`. Earlier versions cut everything up to the first `@`; git reads what comes before the first `:` as the host, so the first names the host `user`, and the agent reads none of them as a GitHub repository. Put a credential in the credential helper, not the value, and write `git@github.com:owner/repo` or `https://github.com/owner/repo`.
  :::

See [`k8s-operator/api/v1alpha1/platformagent_types.go`](https://github.com/gke-labs/kube-agents/blob/main/k8s-operator/api/v1alpha1/platformagent_types.go) for the exact struct definitions.

### `spec.integration.slack` on the A2A gateway

The `slack` field arms the A2A gateway's Slack backend; the credential broker's Socket Mode relay and the Hermes slack platform are not rendered. With `googleChat` enabled too, one gateway serves both platforms. The operator names both in the agent's `A2A_NOTIFY_CONVERSATIONS`, and in `A2A_NOTIFY_PLATFORM` each one whose `homeChannel` is set. The agent adds a platform whose channel the gateway learned. With no home channel anywhere, it sends home posts to both, and the gateway keeps each platform's posts for its digest.

Whichever backend the stack holds, the operator renders an empty ConfigMap `<agent>-home-channel` beside the gateway and a Role rule that lets the gateway read and patch that one object. With Slack or Google Chat on the gateway, it also renders the gateway env `A2A_HOME_CHANNEL_RECORD`, `A2A_SELF_IMAGE` and `A2A_HOME_CHANNEL_LEARN`, and each platform's `homeChannelPolicy` as `A2A_SLACK_HOME_POLICY` or `A2A_GCHAT_HOME_POLICY`.

**The learned home channel.** With `homeChannel` empty and `homeChannelPolicy` `auto`, the gateway makes the channel of the first top-level mention of the agent in a channel the home channel. It checks the channel first: a channel id, not a direct message, not archived, not shared through Slack Connect, and the app a member. It writes the channel to the `<agent>-home-channel` ConfigMap, which the operator renders empty beside the gateway with a Role rule that lets the gateway read and patch that one object. The gateway env `A2A_SLACK_HOME_POLICY`, `A2A_HOME_CHANNEL_RECORD`, `A2A_SELF_IMAGE` and `A2A_HOME_CHANNEL_LEARN` carry the contract.

The operator projects the admitted channel (`homeChannel` when set, else the record) into the `<agent>-chat-home` ConfigMap, one key per platform: `slack_home` and `gchat_home`. It mounts that ConfigMap as a read-only directory in the agent pod and the gateway pod. Both read the file where it is mounted, within about a minute of a change, and no pod restarts for a learn. An agent image older than the operator reads env only and never sees a learned channel: keep the agent image at the operator's release.

It admits a recorded channel under policy `auto` when the value is a channel id and no refusal is recorded beside it, and clears `HomeChannelUnset` then. Otherwise the condition says why: the policy is `manual`, the recorded value is not a channel id, or the gateway refused the channel (archived, shared through Slack Connect, the app not a member, a direct or group direct message). A hand edit of the record carries the same trust as the field, and the gateway checks the channel before each post: one Slack refuses is recorded as refused, the condition names it, and the next mention replaces it.

`manual` turns the learn off. A set `homeChannel` wins; the learned channel stays in the record, so clearing the field returns to it. An allowed member moves the learned channel from the app's Home tab; the record keeps who moved it and when, and picking the previous channel there moves it back. To forget it, delete the ConfigMap: the operator re-creates it empty and the next mention learns again.

**The learned Google Chat home space.** `spec.integration.googleChat` follows the same rule with its own `homeChannelPolicy`, its own keys in the record (`gchat`, `gchat.setBy`, `gchat.setAt`, `gchat.refused`) and its own projected file, so an install with both platforms keeps two home channels. The candidate is the first top-level mention of the agent in a named space; a direct message or a group chat never is. The gateway checks the space with the Chat app's own credentials: a space name, the app a member, and no people outside the organization admitted. A refused space is recorded and `HomeChannelUnset` names the reason.

Google Chat has no Home tab, so a learned space moves only by setting `homeChannel` or by removing its `gchat` keys from the ConfigMap. Both platforms share that ConfigMap, so deleting it forgets both learned homes.

**The home channel.** The gateway also carries `homeChannel` and posts the agent's proactive messages into that channel and nowhere else, as new threads there or as replies on them. Those are the alerts, the scheduled reports, and the fleet audit's Block Kit report card without its buttons. It must be a channel ID (`C...`, or `G...` for a private channel). With it unset and no learned channel admitted, or with it malformed, the agent posts nothing to Slack unprompted; unset with no learned channel admitted, the CR carries the `HomeChannelUnset` condition.

A kanban card's report back to the Slack conversation that asked for it is not a proactive post: the gateway serves it with `homeChannel` unset too, though not with a malformed one, which leaves the gateway's notify route off altogether.

**Who is admitted.** `allowedUsers` applies on the gateway as Google Chat's does: an absent list (or a single empty string) admits every member, any other list admits only the member IDs it names, matched exactly. A plain ID names a member of the install's own workspace. An entry `T…:U…` (a workspace ID, a colon, a member ID) admits that member of another workspace in a Slack Connect channel; nothing else admits one, an absent list included.

The gateway's `user_id` principal map, the `a2a-slack-principal-map` Secret, is optional, mounted when present and read when the gateway starts. It does not admit anyone: a member the list admits and the map names is attributed by the mapped identity, one the map does not name by their Slack member id, and a member the list does not admit is refused whatever the map says. A member of another workspace posting in a Slack Connect channel shared with the install's is served only when the list names them as `T…:U…`. That Secret is the whole map: the `principal-map` ConfigMap is not mounted on a Slack gateway, so adding a Slack user to it admits no one.

**One workspace.** The gateway serves one Slack workspace: install one bot token from one workspace, or turn Slack off. A multi-workspace install, whose bot-token Secret holds the legacy broker's comma-separated list of tokens, cannot keep that list, with or without Google Chat. The operator does not check, because it arms on the CR alone. So an install with a list token loses Slack when it upgrades to an operator that arms the gateway, with nothing in the CR's `.status` to say why (the gateway pod's log carries the cause), and gets it back only by switching the Secret to a single workspace's bot token.

The installer checks before it applies: `install.sh` and a full `upgrade.sh` refuse an apply that hands Slack to the gateway (Slack on, with or without Google Chat) with a token list, an email in `allowedUsers`, or a `homeChannel` that is not a channel ID ([when an upgrade is refused](/kube-agents/install/upgrade/#when-an-upgrade-is-refused)). `upgrade.sh`'s operator and harness re-tags, a full upgrade onto a release that predates the check, and changes made outside the installer skip it.

### `spec.integration.forges`

Each `forges` entry has these fields:

| Field            | Rules                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`           | Required. A DNS label that `repositories` refer to it by, unique in the list.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `provider`       | `github`, `gitlab`, `gitea`, `bitbucket` (Bitbucket Cloud) or `bitbucket-datacenter` (Bitbucket Data Center). Omitted, it is `github`, and it is required for a forge at a host other than github.com.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `host`           | Optional on `github` and `gitlab`, where it defaults to the provider's own (`github.com`, `gitlab.com`) and may name a self-managed instance: a GitLab instance on a `gitlab` forge, or a GitHub Enterprise Server instance on a `github` forge. On `bitbucket` it is `bitbucket.org` only. Required on `gitea`, where hosted SaaS domains are refused, and on `bitbucket-datacenter`, where it names the Data Center instance. The hostname alone, with no port and no path: a provider that supports another port takes it in `port`, and an instance at a context path is not supported. Never a host another provider serves, and never a host at or under a domain where GitHub runs its own services: `github.com`, `githubusercontent.com`, `githubassets.com`, `githubapp.com`, `github.io`, `github.dev` and `ghe.com`. |
| `scheme`         | `https` or `http`, default `https`. `http` is accepted only on `gitea` for in-cluster `.svc` or `.svc.cluster.local` Service DNS names.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `port`           | Optional on `gitea`; `1`–`65535`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `namespace`      | Optional. The organisation, user, or group a bare repository name on this forge belongs to, within the provider's own limit: 39 characters on GitHub, a nested group path on GitLab, 40 characters on Gitea. On Bitbucket it is a workspace ID (Cloud) or a project key (Data Center).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `credentialsRef` | The name of a Secret in the agent's namespace, for a provider whose credential is a token an administrator holds. Ignored on a `github` forge, required on `gitlab`, `gitea`, `bitbucket` and `bitbucket-datacenter` (below).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `caBundleRef`    | `name`, and `key` (default `ca.crt`): a Secret in the agent's namespace holding the PEM CA that signed a self-managed instance's TLS certificate (below).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `identity`       | Optional, on `bitbucket` and `bitbucket-datacenter` only: the login the forge's token acts as, for a token that cannot name its own account (below).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |

**Credentials.** GitHub's credential is the GitHub App, so on a `github` forge `credentialsRef` is ignored and admission returns a warning saying so. On a `gitlab`, `gitea`, `bitbucket` or `bitbucket-datacenter` forge it is required: the Secret holds the access token under the key `token` (a group or project access token, or a dedicated account's personal access token on a tier without them). The operator mounts that key into the credential broker's pod only at `/var/run/kube-agents/forge-credentials/<forge-name>/token` and renders `VCS_FORGES_CONFIG`, and the broker reads it on every call, so rotating the token is updating the Secret.

The same Secret may also hold a read-only token under the key `read-token` (Reporter role, `read_repository` scope only) on a `gitlab` forge, or a token that can only read repositories on a `bitbucket` or `bitbucket-datacenter` forge. The operator mounts it beside `token` when the key is present, and the broker presents it only to clone the forge's `context_repos` entries, never on a write; without the key a context repository clones with no credential. A missing Secret or `token` key does not stop the broker; calls to that forge answer `FORGE_CREDENTIAL_UNAVAILABLE` naming the host until the Secret exists, and the status does not report it.

**One GitHub host per install:** github.com, or one GitHub Enterprise Server. A second `github` forge at another host is refused, and so is one host declared for two providers; two `github` forges at one host still name two organisations. The first `github` forge declared decides the host. While its host can be read, it keeps the host even when another of its fields is refused. The `github_host` key, the broker's configuration and the egress stay on that host, and a later `github` forge at another host stays refused. A change of the declaration that moves the host writes a `GitHubHostChanged` Warning Event, because the repositories registered on the old host are then no longer served.

**GitHub Enterprise Server.** On a GitHub Enterprise Server the operator writes the host into the `<agent>-gitops-state` ConfigMap as the key `github_host`, which the agent reads (a github.com install has no such key). The credential broker calls the instance's REST API at `https://<host>/api/v3`, and keeps the GitHub App token it mints for it in memory. The chart's token minter mints on the instance too: it reads the GitHub forge and sets the instance's API URL and CA on the minter.

`install.sh --gitops-host` writes a GitHub Enterprise Server forge, through the Terraform composition's `gitops_host` and `github_ca_secret_name`; see [GitHub Enterprise Server in INSTALL.md](https://github.com/gke-labs/kube-agents/blob/main/INSTALL.md#github-enterprise-server). The chart owns this resource on such an install, so change the forge there, not with a hand edit of this resource.

**A private CA.** These forges are at a self-managed host: a `gitlab` forge, a `github` forge at a GitHub Enterprise Server host, an `https` `gitea` forge, and a `bitbucket-datacenter` forge. Such a forge may also set `caBundleRef` (`name`, and `key`, which defaults to `ca.crt`): a Secret in the agent's namespace that holds the PEM CA that signed the instance's TLS certificate. A CA certificate is public, but it lives in a Secret for its integrity: changing it chooses which servers the broker sends the token to, so it needs the same rights as changing the token Secret.

The operator mounts that key into the credential broker's pod at `/etc/kube-agents/forge-ca/<forge-name>/ca.crt`, as it mounts the token, and the broker trusts the CA for this forge's host and for no other, beside the system CAs, in its API client and in git; git follows no redirect from that host. On a GitHub Enterprise Server forge, the chart also mounts the CA into the token minter, which trusts it for all of its outbound calls, beside its image's bundle ([token minter guide](/kube-agents/deploy/token-minter/#github-enterprise-server)). For this host only, the broker turns off Python's strict X.509 checks, which refuse a CA certificate without Key Usage; the chain and the hostname are still verified.

The mount is optional: until the Secret exists, calls to the forge answer `FORGE_TLS_UNTRUSTED`, naming the host and "the Secret <name> or its key <key>", and an update needs no restart. The field is refused, in the CRD and in admission, on a forge whose host is empty, gitlab.com, github.com or bitbucket.org in any spelling, because a private CA must never vouch for a host the public CAs sign, and on a `gitea` forge with `scheme: http`. Two `github` forges at one host may not name two different CA bundles.

**Bitbucket.** `bitbucket` is Bitbucket Cloud, at `bitbucket.org` only, and `bitbucket-datacenter` is a Bitbucket Data Center instance at the declared `host`. Both need `credentialsRef`, and the Secret has the keys described above.

**Bitbucket tokens.** On Bitbucket Cloud the token is a workspace access token, or the API token of an account that exists only for this install. A repository access token reaches one repository. The broker holds one credential per host, so such a token serves an install with one repository only. On Bitbucket Data Center it is a project HTTP access token. The broker sends the token as `Authorization: Bearer`. Git gets it with the username `x-token-auth` on Cloud, and as a bearer on Data Center, which needs git 2.46 or later in the broker image.

**Identity.** The optional field `identity` (up to 255 characters of letters, digits and `.`, `_`, `@`, `+`, `-`, `{`, `}`) is for the two Bitbucket providers only, and the CRD and admission refuse it on any other forge. It is the login that the forge's token acts as, for a token that cannot name its own account through the forge's API. On `bitbucket` it is the account UUID, with or without its braces, and any other value is refused. On `bitbucket-datacenter` it is the username; a project or repository token needs none, because the instance names its user (`access-token-user/<project>/<token>`) in every answer.

**GitLab, Gitea and Bitbucket namespaces.** A `gitlab`, `gitea`, `bitbucket` or `bitbucket-datacenter` forge's `namespace` and the groups/owners of the repositories declared on it are also the namespaces (`allowedPaths`) the broker serves with that token. One such forge per host: a second at a host already declared is refused. Such a forge with neither a `namespace` nor a repository is not given to the broker. Admission returns a warning, and the operator writes the same text as a `Warning` Event (reason `IntegrationWarning`) on the PlatformAgent, since the chart ships the webhook off.

A GitLab group may contain a dot, but a `namespace` or repository path whose first segment is a forge host (`gitlab.com/acme`, `github.com/acme/infra`, or the forge's own self-managed host) is refused: name the group alone. A repository whose resolved URL is longer than 256 characters is refused too, because the credential broker reads no longer a reference.

**Naming a repository on a multi-forge install.** On an install that declares a `gitlab`, `gitea` or Bitbucket forge beside GitHub, a bare `owner/name` still names a GitHub repository that the install registered by URL. The sandbox client sends the bare name as the URL of the registration, so crons, skill invocations and `--repo` arguments do not change.

Use `<scheme>://<host>[:<port>]/<path>` or `<host>/<path>` for a GitLab, Gitea or Bitbucket repository. Also use it for a GitHub repository that the install did not register, that an administrator registered without a URL, or that has the same path as a repository on another forge. The broker serves multiple forges, so it refuses a bare `owner/name` in these cases. The declared forges also decide the forge hosts in the gateway's FQDN egress policy (the `enable-fqdn-network-policy` annotation); GitHub's hosts are always included.

### `spec.integration.repositories`

**Accepted spellings.** `repository` accepts HTTPS/HTTP (`https://`, `http://`), SCP-style SSH (`git@...`), SSH/Git protocols (`ssh://`, `git://`), `owner/repo` shorthand (e.g. `gke-labs/kube-agents`), and a bare name qualified by the namespace. On `bitbucket-datacenter`, write `KEY/repository`: a clone URL or web URL of the instance (`/scm/`, `/projects/`, `/users/`) is refused with the form to write. On both Bitbucket providers a repository is exactly two segments: `workspace/slug` on Cloud, `KEY/slug` on Data Center.

**Refusals.** Every refusal names the entry at fault, e.g. `spec.integration.repositories[1].repository`:

| Refused by                       | Shape                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The CRD                          | A repository naming an undeclared forge, and a second `gitops` repository.                                                                                                                                                                                                                                                                                                                                                                                                    |
| The webhook, where it is enabled | Whitespace, control characters, invalid syntax, the same repository declared twice (in any letter case), a GitHub repository name over 100 characters, a name that still ends in `.git` after one is stripped, and a host the forge's provider does not serve, so a repository on another forge is refused rather than rewritten onto the declared one. The chart ships the webhook off, and one enabled through the chart fails open at its default `failurePolicy: Ignore`. |
| Reconciliation                   | The same validation again, since a chart install runs with `ENABLE_WEBHOOKS=false`: an invalid entry is left out of the state ConfigMap, its neighbours are still registered, and the resource surfaces `Ready: False` and `Degraded: True` (`Reason: InvalidGitRepoURL`).                                                                                                                                                                                                    |

**What a refused entry holds back.** Where the refused entry is one the GitHub organisation is read from — a GitHub forge, or a `gitops` or `managed` repository unless every GitHub forge declares the same namespace, or unless the entry names on its own a `gitops` or `managed` repository that was accepted (a second declaration of it) — the operator also leaves the token minter policies as they were, and the agent's `GITHUB_ORG` as the running pod has it (unset on a first install), rather than scoping either to another forge's or another repository's organisation. So a CR upgraded from a release that accepted a spelling this one refuses keeps its organisation, and its pod is not rolled for it.

The same holds for the ConfigMap: while any `github` entry in `managed_repos` or `context_repos` does not parse — a spelling an earlier release accepted, added by hand — the operator adds token minter policies but prunes none, since the entry may be the repository a policy it tracks is for. It reports the hold as `Degraded/MinterPruningHeld` naming each entry by its list and position, such as `managed_repos[1]`, never by its value, which can carry a credential; correcting or removing the entry lets the next reconcile prune.

An entry of another `type` is not the minter's and holds nothing, and on a GitHub Enterprise Server install neither is a `github` entry on github.com or with no host. The minter mints for the install's GitHub host, and the agent skips such an entry, so the minter skips it too and it holds nothing.

**What the operator writes.** The operator appends each valid `gitops` and `managed` repository to `managed_repos`, and each `context` repository to `context_repos`, in the `<agent>-gitops-state` ConfigMap if absent, as `{"type": "<provider>", "url": "https://<host>/<path>"}`: `https://github.com/<owner>/<name>` on GitHub, `https://<host>/<owner>/<name>` on a GitHub Enterprise Server, `https://gitlab.com/<group>/.../<project>` or the self-managed host on GitLab, `<scheme>://<host>[:<port>]/<owner>/<name>` on Gitea, `https://bitbucket.org/<workspace>/<slug>` on Bitbucket Cloud, or `https://<host>/<KEY>/<slug>` on Bitbucket Data Center.

The entries carry no role, so the `gitops` repository is the first `managed_repos` entry, which is the one the agent's token refresh mints for when no repository is named. The skills' resolvers refuse to guess among several entries, so with a `managed` repository declared beside it a caller names its target with `--repo`. A `gitops` repository the list does not yet hold is inserted at the front, and an entry already present is never moved. While a declared `gitops` repository is refused, no `managed` repository is appended either, since it would take the first place.

The fleet audit does not need `--repo`, because the operator also writes the valid `gitops` repository, as one such entry, to the `gitops_repo` key of the same ConfigMap, and the audit puts its ledger issue and fixes there (see [Which repository gets the ledger](/kube-agents/concepts/declarative-workflow/#which-repository-gets-the-ledger)). The operator removes the key when no repository has that role or when two have it, and keeps the key as it is while the declaration does not resolve or the `gitops` repository is refused.

An existing entry counts as present when it names the same repository on `github.com` in another spelling — a `.git` suffix, a remote, a run of `/` after the host — but not in another case, since the agent's `--repo` checks compare the spelling (so the declared spelling is added beside it). Nor does it count on `www.github.com` or `ssh.github.com`, with or without a scheme, nor under a `type` other than the forge's provider, nor in a spelling with two `@`, nor one over 256 characters, since the agent reads none of those. Reconciliation only adds, and keeps every existing entry as written, so removing a repository means removing it from the CR _and_ editing the ConfigMap.

**The two lists.** `managed_repos` is read-write. `context_repos` names repositories the agent reads and never writes to. An audit consults them for declared intent before it reports a posture as a finding. A diagnosis reads them to find the file that defines a value when the fix is not in a managed repository ([Write scope shapes a diagnosis](/kube-agents/concepts/declarative-workflow/#write-scope-shapes-a-diagnosis)). An administrator may also add entries to it by hand.

An entry may add `"ref": "<branch>"` to read a branch other than the remote's default. A `ref` is kept when it is made of letters, digits, `.`, `_`, `/`, `-` and, after the first character, `@`, and passes git's branch-name rules (no `..`, `@{`, `//` or `.lock` component, no leading `-`).

Any other, an empty string, a JSON `null` or a value that is not a string (a number, a boolean) included, is refused with a warning naming it, and the declared-intent search skips that repository rather than reading its default branch in the pin's place, so the ledger names it as not searched until the entry is corrected (omit the key to read the default branch). A `ref` on an entry naming the GitOps repository itself is ignored, because the audit reads that repository at the branch it publishes against. The operator never adds a `ref`, and keeps one an administrator added to a seeded entry.

**What the agent reads.** The agent's skills read every `managed_repos` entry whose `type` is a forge the agent image serves (`github`, or `gitlab`, `gitea`, `bitbucket` and `bitbucket-datacenter` named `host/path`), and only `github` entries with a GitHub URL in `context_repos`. Any other entry is skipped with a warning naming the key. On a GitHub Enterprise Server install, a `github` entry on the instance's host is read too, in both lists, and named `<host>/<owner>/<name>`. A `github` entry on github.com, on no host, or on any other host is skipped with a warning, so a repository registered before a move from github.com is not served on the instance under its old name.

The credential broker's repository gate reads every typed entry, keyed by its `type`, host and path, so an entry counts only for the forge whose provider it names.

Each same-organization `context_repos` entry gets a read-only (`contents: read`) token minter policy, so a private context repository is readable through the credential broker's `snapshot` read, provided the GitHub App is installed on it — see [Read-only tokens for context repositories](/kube-agents/deploy/token-minter/#read-only-tokens-for-context-repositories). On a `gitlab` forge, a private context repository is readable the same way when the forge's Secret holds `read-token` — see [Private context repositories](/kube-agents/install/gitlab/#private-context-repositories). Nothing that writes consults the key: a context repository stays refused by every version-control verb but `capabilities` and `snapshot`.

### `spec.integration.repositories[].baseBranch`

A `context` entry may not set `baseBranch`: the CRD refuses one, because a context repository is never written and its branch pin is the `ref` in the `<agent>-gitops-state` ConfigMap. The deprecated `github` alias has no place for a base, so pinning one takes `forges`/`repositories`.

For each accepted `gitops` or `managed` repository that sets one, the operator adds an entry to `CREDENTIAL_PROXY_PINNED_BASES` in the credential broker's environment: a JSON array of `{"repository": "https://<host>/<path>", "branch": "<baseBranch>"}`, with the forge's canonical host (`github.com` for every GitHub spelling, `gitlab.com` for `www.gitlab.com`) and the path that forge reads, nested groups included on GitLab. With no base set the variable is not rendered.

The broker then refuses a pull request onto that repository that targets any other branch, a clone of it that names no branch checks the base out, and every pinned branch is refused a direct push on every repository. A repository is matched by host and path, so the same path on another host, or on another forge, is not pinned.

The agent container and the shell sandbox get no copy, and `spec.deployment.env` can never set the variable. A `CREDENTIAL_PROXY_BASE_BRANCH` or `GITOPS_BASE_BRANCH` there still passes through: the broker refuses direct pushes to the branch it names but does not hold pull requests to it.

The CRD schema holds the value to the branch names the broker accepts: up to 200 characters of letters, digits, `.`, `_`, `/` and `-`, starting with a letter or digit, not `HEAD`, with no `..`, `/.`, `//`, `@{` or `.lock/`, and no trailing `/`, `.` or `.lock`. A `refs/heads/` prefix is allowed, and what follows it must start with a letter or digit, not be `HEAD`, and not start with `refs/heads/` or `heads/`; a value may not start with `heads/`.

So each base has one spelling, the one the broker targets and protects. Changing a base restarts the broker's pod and no other. The Helm chart key is `platformAgent.integration.repositories[].baseBranch`; because `helm upgrade` does not update CRDs, the chart refuses to render it against an installed CRD that lacks the field.
