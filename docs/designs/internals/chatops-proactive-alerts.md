# ChatOps: Proactive alerts

Part of [ChatOps](../../site/src/content/docs/concepts/chatops.md).

## Proactive alerts (both channels)

The harness doesn't only reply to messages. A cluster event posted to the in-pod triage endpoint (`inject_message` in [`agents/platform/scripts/session_kv_server.py`](https://github.com/gke-labs/kube-agents/blob/main/agents/platform/scripts/session_kv_server.py)) opens a thread unprompted: it posts the alert first, then runs the triage turn in the thread that alert created. If the agent gateway cannot start that turn, even after retries, a notice in the thread says that triage did not start, whether the alert comes back, and that you can ask about it there ([details](https://github.com/gke-labs/kube-agents/blob/main/agents/platform/docs/session_management.md#when-a-triage-cannot-start)). On Slack and on Google Chat, the triage then [edits the alert itself](../../site/src/content/docs/concepts/chatops-slack.md#buttons) through the gateway.

The first-run inventory report arrives the same way, into the thread `bootstrap_onboarding` bound, when that first message comes within a day of the sweep. After that the report is an issue in the GitOps repository when it is on GitHub, or else in the install's one managed GitHub repository. One line linking it goes to the home channel, kept for the digest while none is set.

On Slack and on Google Chat, with `KAGE_SLACK_UX` on, the inventory report arrives as the card described under [First-run onboarding](../../site/src/content/docs/concepts/chatops.md#first-run-onboarding), built from the stored findings. The card has a headline counting the things to fix first, one row per listed item with its scored risk and the action to take, and the rest counted. The scan's checks are folded, with a button to fix the first one and, when more items are queued than listed, one to see them all. Clicking one answers as your turn in the thread; a click from someone the agent does not answer changes nothing.

When no card can be built, the report is posted as text, reshaped with a headline, the listed findings as rows with the sentence under each kept, and its closing lines. The same text goes on an install whose onboarding was bound to a chat thread before the upgrade that moved its chat to the gateway, when Slack refuses the card or the post fails. A report that does not parse to that shape is posted as written. The report closes with a short note on the first-run audits (see [First-run onboarding](../../site/src/content/docs/concepts/chatops.md#first-run-onboarding)); beside the card, that note is a separate message after it. Where an unprompted message lands:

- **Google Chat**: to the space that owns the interaction, or the space set via `GOOGLE_CHAT_HOME_CHANNEL` or learned from the first mention.
- **Slack**: to `SLACK_HOME_CHANNEL`.
- **Microsoft Teams**, with the gateway's Teams backend armed: to the conversation `spec.integration.teams.homeChannel` names.

An alert goes to **one** of them, not both: it opens a thread that the triage turn then replies into, and a thread belongs to a single platform. The agent picks one platform for the alert among the platforms that have a home channel: one whose home channel is configured before one whose home the gateway learned, and Google Chat before Slack when both are alike. With none, the gateway keeps it for the digest on the first platform.

A scheduled report has no such constraint. The default jobs' `deliver: chat` relays it to every enabled platform among Google Chat and Slack, and to Microsoft Teams while the gateway's Teams backend is armed. On the Hermes path a job whose `deliver` names `teams` posts to the Teams home channel instead. [The relay design](https://github.com/gke-labs/kube-agents/blob/main/docs/designs/cron-report-relay.md) is canonical for both rules.

A governance watchdog's findings live on its ledger issue and the remediation pull requests that link back to it. Its scheduled report on this path is usually one line of counts ending with the ledger link, so the report to read is the issue — see [Proactive autonomy](../../site/src/content/docs/overview/proactive-autonomy.md) and [Autonomous watchdogs](../../site/src/content/docs/concepts/autonomous-watchdogs.md) for the schedules.

With `KAGE_SLACK_UX` on, Slack gets a card built from the open ledger issue, and so does Google Chat. Its headline carries one number, how many findings of the most severe level the issue lists ("Security & RBAC Posture Audit: 2 critical findings"). Up to ten critical findings are listed under it, each led by its severity and tagged "new" when it was not there on the last run. With none critical listed, the headline counts the most severe level listed and lists the top two.

A line under them counts the rest by severity ("5 more (1 major, 4 minor) are in the ledger issue."), and another names any clusters the run could not check, since a silent gap reads as clean. Then come a "Look at the first one" button and a button that opens the issue.

Clicking "Look at the first one" starts a turn for you in the card's thread, as if you had typed the button's label. The buttons give way to a line naming who chose, only the first click counts, and a click from someone the agent does not answer changes nothing. A clean run closes its ledger, so its card is one line: "Security & RBAC Posture Audit: clean. Ledger closed." A run with no findings that left the ledger open because it could not check everything is posted as the report's own line in bold with the link, since the issue does not show this run's counts. (A ledger that a coverage gap opened shows this run's gaps, but no findings.)

A scheduled run that speaks because an on-demand run changed the findings since the last scheduled run also gets a card, built from the ledger. The card counts "new" against the last run of either kind, so the change since the last scheduled run is not on the card; only the text report says it, on a line of its own. Nothing else is posted in the card's thread: the ledger issue holds the rest.

On an install with no GitOps repository there is no issue, so the card is built from the audit's own summary. It holds:

- a headline that also says what changed ("Security & RBAC Posture Audit: 6 critical findings, 2 resolved.");
- one short line for each of up to three critical findings (or the top two of the most severe level present). Each names its cluster, its namespace when it has one, and what is wrong ("seeded-a: control plane is public", "seeded-a/payments: api runs a privileged container");
- the rest counted by severity;
- the change since the last scheduled run when an on-demand run saw it first ("Changed since the last scheduled run: 1 resolved (…).");
- any clusters it could not check;
- a line saying that no ledger issue or fix pull requests were opened;
- the "Look at the first one" button, with no issue button.

That card is posted only when no repository is registered at all. A summary that names a repository the run could not reach, or several repositories with none chosen, is posted as written, so that the fix it gives is not cut short. The headline is posted as text where Slack refuses the buttons or the message, and also where the report was truncated, too little time is left, or the buttons cannot be posted at all. A reply in the thread is answered with the full report in context either way.

A scheduled audit's report, for an audit the install ships, is the one its `finish` step rendered, not the agent's last message. An audit run that failed posts one plain line saying it didn't run, why, and when it tries again (or that an admin needs to fix it), once until the job runs again. One that stopped before that step without failing posts one line saying it did not finish, with the job to look up in the run log.

A run publishes to one repository, the one with `role: gitops`. Only a run that a person started for several repositories posts more than one report. It posts the report of each repository it finished, then a line naming the rest, and that message is posted whole rather than as a card. The card goes through the A2A gateway, which lays out the same card, on Slack and on Google Chat.

### Daily alert ceiling

Each cluster-event alert and each drift alert spends one unit of a daily budget. When a bucket is spent, the alert does not go to chat, and no triage turn starts. The budget is fleet-wide: one count serves all the clusters that the install watches. It resets at 00:00 UTC. A value of `0` removes the cap for that bucket.

| Bucket        | What it counts                                            | Default | `install.env` key            |
| ------------- | --------------------------------------------------------- | ------- | ---------------------------- |
| `Critical`    | Critical cluster events                                   | `10`    | `ALERT_DAILY_LIMIT_CRITICAL` |
| `Warning`     | Warning cluster events                                    | `5`     | `ALERT_DAILY_LIMIT_WARNING`  |
| `Info`        | Nothing today: the severity gate drops Info events        | `5`     | `ALERT_DAILY_LIMIT_INFO`     |
| `GitOpsDrift` | Drift alerts for cluster changes that people make by hand | `20`    | `ALERT_DAILY_LIMIT_DRIFT`    |

[`agents/platform/docs/session_management.md`](https://github.com/gke-labs/kube-agents/blob/main/agents/platform/docs/session_management.md#daily-alert-ceiling) gives the reasons for these defaults and for each bucket.

Most drift changes that reach the drift detector late do not spend the `GitOpsDrift` budget. A change is late when its audit record was published before the detector started to read, for example most changes that an install or a restart of the agent pod makes, or when the record waited more than 30 minutes. The agent posts one "Drift backlog" message for each group of late changes. The message counts the changes by principal and names some of them. On an install with no chat platform enabled, the message is one card on the task board instead. The card has no assignee and waits on a person; no agent acts on it.

Late changes in the message get no triage turn, and the feed `GET /v1/intercepted-events` lists them with the status `backlog`. Some late changes get a triage card and spend the budget instead: a change made with `kubectl`, and every late change of a principal with fewer than three late changes in the group. When the budget is spent, a late change of such a principal is counted in the message instead. A late `kubectl` change is handled as a live change is, so it is lost from chat and the feed lists it as `suppressed`.

Set a ceiling in one of these places:

- The `ALERT_DAILY_LIMIT_*` keys in `install.env`. An empty key keeps the default. `install.sh`, the Day-2 menu and `upgrade.sh --upgrade-mode=full` apply these keys. The other modes of `upgrade.sh` use the values that the release recorded. But each `upgrade.sh` run examines the keys, and a value that is not a whole number stops the run.
- The chart value `platformAgent.deployment.alertDailyLimits`, with the keys `critical`, `warning`, `info` and `drift`.
- The Terraform variable `alert_daily_limits` in `terraform/examples/full-install`, with the same keys.
- An `ALERT_DAILY_LIMIT_*` entry in the `PlatformAgent` CR's `spec.deployment.env`, on an install that no chart manages.

Each of the first three routes renders the keys that are set into `spec.deployment.env`. Helm replaces the full `spec.deployment.env` list on the CR at each apply that changes the list that the chart renders. This includes the apply that sets the first key, an apply that changes a value, and the apply that removes the last key. Entries that you added to the CR by hand are then lost. Before you set a key, move a ceiling to its key, and move another name to the chart value `platformAgent.deployment.env` (`extra_helm_values` on the Terraform install).

A change to a ceiling restarts the agent pod and the credential-proxy pod. A re-tag with `upgrade.sh --upgrade-mode=operator` or `harness` to a release whose chart does not declare `alertDailyLimits` needs `--drop-undeclared-values`. The ceilings then go back to the defaults.

#### Reading what the ceiling held back

Suppression is silent in chat. No message says that a bucket is spent. To see the counts, read `/v1/alert-quota` from the agent pod:

```bash
kubectl -n kubeagents-system exec deployment/platform-agent-gateway -c platform-agent -- \
  sh -c 'curl -s -H "Authorization: Bearer $SESSION_KV_API_KEY" \
    http://127.0.0.1:8699/v1/alert-quota'
```

Add `?day=YYYY-MM-DD` to the URL for an earlier day. The reply gives `limit`, `sent` and `suppressed` for each bucket that has a cap. `suppressed` counts each offer that the ceiling refused. The event watcher offers a refused workload again on its next sighting, so one workload can add many offers to `suppressed`. The event watcher also counts these refusals in the `k8s_event_watcher_events_quota_suppressed_total` metric.

The daily recap has the line "N alerts from M workloads withheld by the daily ceiling and never reached chat". N counts each pod and reason one time, so it can be lower than `suppressed`. M counts the workloads that sent those alerts. The pods of one Deployment are one workload. N is one count for the `Critical` and `Warning` buckets together. The recap runs at 21:00 UTC on weekdays, and each recap covers the time since the previous recap. Thus the recap period is not the UTC day of `/v1/alert-quota`, and the Monday recap covers the weekend.

Drift refusals never appear in the recap. The `GitOpsDrift` row of `/v1/alert-quota` and the session server log show them. The drift detector does not offer a refused record again, so that alert is lost from chat.

The recap line "N events from M workloads were silenced by alert-exclude rules" counts the events that the [alert-exclude rules](platformagent-harness.md#specharnesseventwatcher) held back, and names the five workloads that sent the most. These events never reached the ceiling, and `GET /v1/intercepted-events` lists them with the status `excluded`.

The recap line "N alerts failed to post to chat" is a different problem. It means that chat refused the post, or did not confirm it. Some of these alerts can be in the channel. A higher ceiling does not change this count. Look in the session server log for the cause.

#### Sizing a bucket

The counter is fleet-wide, so the demand on it increases with the number of clusters. Size each bucket from a week of data. A bucket with a value of `0` counts nothing, and `/v1/alert-quota` does not show it. To measure that bucket, first set a high cap on it for the week.

1. For each of 7 days, read `sent` and `suppressed` for the bucket from `/v1/alert-quota?day=YYYY-MM-DD`. For `Critical` and `Warning`, `suppressed` counts repeat offers, so the sum can be higher than the real demand. For `GitOpsDrift`, `suppressed` has no repeat offers. The recap's withheld line cannot give a count for one bucket or for one UTC day.
2. Add the `sent` and the `suppressed` counts, and divide the sum by the number of clusters. The result is the demand for each cluster.
3. Set the bucket to that demand multiplied by the number of clusters that you will run. Do not set it higher than the number of alerts each day that the on-call can act on.
4. If the demand is higher than that number, reduce the inflow: fix the workloads that alert most. Do not raise the bucket.

### One incident per workload

Without folding, each pod and each reason of a broken workload is its own alert: a Deployment with three replicas that cannot pull its image posts three alerts, starts three triage turns, and spends three units of the `Warning` budget. `INCIDENT_WORKLOAD_DEDUP_SECONDS` folds them into one, and is on by default at `3600`, an hour. Within that many seconds of an alert, a later Warning event for the same workload, or a later Critical one after a Critical alert, posts nothing, starts no triage turn and spends no budget.

The same workload means the same cluster, namespace and kind, and either the same owning workload for a pod or the same name for an object that is not a Pod. The event watcher reads a pod's owner from the pod's metadata, so the pods of one Deployment, StatefulSet, DaemonSet or Job fold into one alert. Two workloads of different kinds stay apart even with the same name. The runs of a CronJob are separate Jobs, so each run is its own alert.

If the watcher cannot read a pod's owner, for example because its identity may not read Pods on that cluster, or the owner is not a Deployment, StatefulSet, DaemonSet or Job, only a Deployment's pods fold. They fold by the ReplicaSet hash in their names (such as `checkout-6cfdb6b98b-zwv24`), and other pods each still alert.

An alert says when a workload broke, once: while the same pods keep retrying a failing image pull, the workload is not announced again. For a Deployment, StatefulSet or DaemonSet that it judges, the daily Workload Reliability audit keeps the standing record. It files a finding on its ledger at each run that finds a pod ten minutes into a failed pull, and the finding leaves at the first run that finds none ([what each SOP checks](../../site/src/content/docs/concepts/governance-sops.md#what-each-sop-checks)).

A Critical event after a Warning alert is announced, so a workload that gets worse is announced again. A restart of the agent pod ends every open window, so the first event after one is announced again, unless its fix is waiting for review (below). The feed `GET /v1/intercepted-events` lists a folded event with the status `folded`. The value is a whole number of seconds; `0` turns folding off, a larger value than `86400` counts as `86400`, a negative value counts as `0`, and a value that is not a number counts as the default.

Change it with the chart value `platformAgent.deployment.incidentWorkloadDedupSeconds`, which renders the entry into the CR's `spec.deployment.env`, or set that entry yourself on an install that no chart manages. On an install made with `install.sh`, put the value in a `TF_VAR_extra_helm_values` line in `install.env`, for example `TF_VAR_extra_helm_values='{platformAgent={deployment={incidentWorkloadDedupSeconds=0}}}'`. `0` turns folding off:

```yaml
platformAgent:
  deployment:
    incidentWorkloadDedupSeconds: 0
```

An entry named `INCIDENT_WORKLOAD_DEDUP_SECONDS` in `platformAgent.deployment.env` wins over the key. A change to the window restarts the agent pod and the credential-proxy pod, and the first apply that renders the entry replaces entries added to the CR's `spec.deployment.env` by hand, as the ceilings paragraph above describes.

With folding on, a workload that breaks again after the window, while the pull request the agent opened automatically to fix one of its recent incidents (`INCIDENT_TRIAGE_OPEN_PULL_REQUEST`) is still open for review, also starts no new triage turn. This covers any object that comes back under the same workload: a new pod of the same owning workload (a Deployment's, StatefulSet's, DaemonSet's or Job's), and a bare pod or other object that comes back under the same name. If the watcher cannot read a pod's owner, any pod that comes back under the same name is held too. A pull request a person opened by hand, or one opened for anything else asked in the incident's thread, does not count.

A fix opened by replying `apply` or clicking an option button in the incident's own thread holds a recurrence the same way. The hold counts the first card for the Platform Agent filed from that thread within 30 minutes of the reply. A later card in the thread does not count, and neither does an `apply` typed in the main space or the first reply in a Google Chat direct message, which is answered at top level. An `apply` on the platform the A2A gateway holds is not recorded and does not hold.

With folding on by default, an install that opens fix pull requests runs this lookup for every new incident. The search is bounded, and a forge that does not answer in time announces the event as a new incident.

The hold covers the same fault only: the event's reason must be one the incident showed, its own or one folded into it, so a workload waiting on a fix for `BackOff` that starts failing `Unhealthy` gets a new incident. For the same fault, the incident's chat thread gets one short reminder per window instead, naming the pull request: the fault is already diagnosed and its fix is waiting on a person. Once that pull request is merged or closed, the next new failure is a new incident again. The feed `GET /v1/intercepted-events` lists such an event as `folded`, with the pull request in its `pull_request` field.

[`session_management.md`](https://github.com/gke-labs/kube-agents/blob/main/agents/platform/docs/session_management.md#folding-a-workloads-repeat-events) describes which earlier alert a later event is folded into, and [holding a recurrence](https://github.com/gke-labs/kube-agents/blob/main/agents/platform/docs/session_management.md#holding-a-recurrence-while-its-fix-waits-for-review) how the open fix is found.

### Opening the pull request without a reply

By default, a triage report proposes GitOps fixes and stops. A human replies `apply` (or `apply Option B`), and the Platform Agent opens that fix as a pull request. Set `INCIDENT_TRIAGE_OPEN_PULL_REQUEST` to `true` to skip the wait. The Planning Agent then files a second card beside the triage card. That card goes to the Platform Agent and names the triage card as its parent, so it waits in `todo` until the diagnosis is `done` or `archived`. If the triage card ends `blocked`, the second card waits too, and the board health check lists it under the blocked card.

Once the report is complete, the second card opens only the option the report marked Recommended, or the single proposed fix, through `submit-suggestion`, changing only the files that option calls for and leaving alternative options and unrelated definitions untouched. Any other value, or no value, keeps the default.

Set it as an entry in the chart value `platformAgent.deployment.env`, or in `spec.deployment.env` on an install that no chart manages:

```yaml
platformAgent:
  deployment:
    env:
      - name: INCIDENT_TRIAGE_OPEN_PULL_REQUEST
        value: "true"
```

A human still reviews and merges the pull request, and nothing is written to the live cluster. The branch is `platform-agent/incident-<incident>`, keyed to the cluster, namespace, kind, workload and reason. The workload is named the way the fold above names it: a pod's owning workload when the watcher could read it, and otherwise a Deployment's pods share their Deployment's name and any other pod keeps its own name. So a retried event for the same workload revises the open pull request instead of opening a second one.

If the watcher cannot read a pod's owner, StatefulSet, DaemonSet, Job and CronJob pods, and bare pods, each get a branch of their own, because the pod name alone cannot prove they belong to one workload. Each CronJob run is a separate Job, so it gets its own branch. With the fold on, a workload's repeat events inside the window start no triage, so they file no pull-request card either. The second card's result, the pull request URL, is posted in the same thread as the report.

The setting has limits. Drift and controller-stall reports are not covered; they still wait for a reply. On Slack with `KAGE_SLACK_UX` on, the report's button for the recommended or single fix is left off when the report says that fix's pull request `is being opened automatically`; buttons for the other options stay. A typed `apply Option B` still works and opens its own pull request. Changing the value rolls the agent pod. The agent ignores the variable in its own `.env` file, so only the install can turn it on. It is an environment variable for now and can move to a `PlatformAgent` field once it has proven itself.

### Limiting the open triage pull requests

A failure that breaks many workloads at once, such as a node or storage fault, starts many triages, and with `INCIDENT_TRIAGE_OPEN_PULL_REQUEST` on each one opens a pull request. Set `platformAgent.deployment.incidentMaxOpenPullRequests` to limit how many are open or being opened at once. The chart renders it as `INCIDENT_TRIAGE_MAX_OPEN_PULL_REQUESTS`. `0`, the default, is no limit.

```yaml
platformAgent:
  deployment:
    incidentMaxOpenPullRequests: 5
```

A triage whose pull request would pass the limit still runs, but its report asks for a reply, as without the setting, and a note in the alert's thread says that the limit held its pull request back. An incident whose branch already has a pull request is not held: its card revises that pull request. If the open pull requests cannot be counted, because the forge fails or does not answer in time, the triage is held the same way, with a note that says so. As with the switch, the agent ignores the variable in its own `.env` file.

The limit counts triage pull requests only: the open pull requests whose branch starts with `platform-agent/incident-`, plus each triage routed to open one whose pull request does not exist yet. The count goes by that branch prefix alone, so a pull request opened by a reply counts only when its branch takes the prefix. A routed triage stops counting when its pull request opens (it then counts as open), when its pull-request card is `done` or `archived`, or after 24 hours. A card that is `blocked`, or waits behind a blocked triage card, keeps counting until then, because it can still open its pull request.
