---
title: ChatOps
description: Google Chat and Slack are the primary interfaces to the harness. Both terminate at the Planning Agent front door, which delegates to the Platform Agent.
sidebar:
  order: 3
---

Chat is the harness's primary interface — for requests from humans and for the unprompted messages the harness raises itself ([Proactive alerts](#proactive-alerts-both-channels)). The interactive channels shipping today are **Google Chat** (the reference channel; enable with the installer's `--enable-google-chat`) and **Slack** (enable it in the installer's chat menu, or with `--enable-slack`). Both are opt-in and default to disabled. An experimental **Microsoft Teams** Bot Framework outbound relay (`spec.integration.teams`, [below](#microsoft-teams)) also ships: it delivers the agent's replies and posts, and an inbound receiver, off by default, takes the messages people type in Teams ([Microsoft Teams app setup](/kube-agents/install/teams-app/)). Proactive alerts and reports reach a Teams home only with the gateway's Teams backend armed.

Both channels terminate at the **Planning Agent** — the `default` Hermes profile in the agent pod, and the only profile that receives chat ingress. It knows which specialists exist because the roster is injected into every turn by the `agent_roster` plugin (its `router` MCP tool `list_agents` re-reads the same list on demand). It files the work as a card on the shared **kanban board** (`kanban_create`), assigned to the specialist that can execute it. Results come back on their own: the gateway posts each completed card's answer into the thread verbatim, and the Planning Agent handles the hand-off and anything that blocks or fails.

The [Platform Agent](/kube-agents/concepts/platform-agent/) does the actual infrastructure work as a delegated kanban worker, and per-cluster [Cluster Agents](/kube-agents/concepts/cluster-agents/) handle single-cluster runtime debugging; neither receives chat directly. A user still sees a single conversational agent regardless of channel — the delegation is visible only as progress updates in the thread. The design of record for this coordination model is [`docs/designs/agent-communication.md`](https://github.com/gke-labs/kube-agents/blob/main/docs/designs/agent-communication.md).

On a large fleet the roster counts the Cluster Agents by project and location instead of naming each, and the Planning Agent looks a named cluster's agent up with `list_agents` before it files the card. The switch is the number of Cluster Agents, above `KUBEAGENTS_ROSTER_SUMMARY_THRESHOLD`, 20 unless set. A fleet of four Cluster Agents never reaches it. Set the variable in the chart value `platformAgent.deployment.env`, or in the `PlatformAgent` CR's `spec.deployment.env` on an install that no chart manages; a value that is not a whole number keeps the default, and changing it rolls the agent pod.

```yaml
platformAgent:
  deployment:
    env:
      - name: KUBEAGENTS_ROSTER_SUMMARY_THRESHOLD
        value: "100"
```

Google Chat terminates at the A2A gateway: the Chat app, topic and subscription, pulled through the credential broker by the gateway, with the `allowedUsers` list deciding who is answered. Proactive alerts and scheduled reports reach the [home channel](/kube-agents/concepts/chatops-slack/#home-channel) through the gateway. The gateway posts them there as new threads or as replies in those threads. A reply a person types in one of those threads starts a new conversation rather than continuing the investigation that raised the alert.

The reports of the cards a triage files reach the alert's thread the same way, and so do the answers of the cards the agent files for a question you asked it in chat. They post in the thread or DM you asked in, whether or not a home channel is configured (a home channel that is set but is not a space name turns this off too). Either way there are two differences from delivery through a Hermes chat platform. A card's progress is one plan message the gateway edits in place with `KAGE_SLACK_UX` on, and a message per note with it off. A file the card produced is not attached. The design of record is [`docs/designs/spec-chatops-gateway.md`](https://github.com/gke-labs/kube-agents/blob/main/docs/designs/spec-chatops-gateway.md).

## Google Chat

Google Chat is the reference channel. Setup is automated by the install: the [`chat-pubsub` Terraform module](https://github.com/gke-labs/kube-agents/tree/main/terraform/modules/chat-pubsub) provisions the backend when Google Chat is enabled (the installer's `--enable-google-chat`, or `enable_google_chat = true` in `terraform.tfvars`). Each question you send the app in a DM is answered in its own thread, and a reply in that thread continues it, as on Slack.

### How it's wired

- A **Pub/Sub topic** and **subscription** are created in the target GCP project.
- Your Google Chat app (configured separately in the [Chat API console](https://console.cloud.google.com/apis/api/chat.googleapis.com)) publishes events to the topic.
  A GCP project holds only one Chat app, so a project already running one cannot also run this — see [Prerequisites](/kube-agents/install/prerequisites/).
- The A2A gateway pulls the subscription through the credential broker and publishes each message as a task on the bus; the Planning Agent answers it through the `hermes-bridge` container in its pod ([How a chat question is answered](#how-a-chat-question-is-answered)).

### Allowed users

Google Chat ingress is gated by `spec.integration.googleChat.allowedUsers` (a list of user emails, collected by the installer as `ALLOWED_USERS`). Leaving it empty allows everyone the Chat app is visible to. A sender not on the list gets one notice and nothing else ([Which messages it answers](/kube-agents/concepts/chatops-a2a-gateway/#which-messages-it-answers)).

### Home channel

`spec.integration.googleChat.homeChannel` on the PlatformAgent is the space an alert-driven report lands in when there is no thread to reply into. Set `GOOGLE_CHAT_HOME_CHANNEL` in `install.env`, pass `--google-chat-home-channel`, or set the field on the `PlatformAgent` resource. Left unset, the gateway learns the home space from the first mention (below). Until it has one, alert-driven reports have nowhere to go until the digest below. The investigation still runs and still opens its remediation PR, so the only visible symptom is silence in chat.

The operator hands the field to the A2A gateway, which posts the agent's proactive messages to that space and nowhere else, and `/sethome` does not reach it. The field must name a space (`spaces/<id>`); a malformed value turns the agent's unprompted Google Chat posts off. With no home space, the PlatformAgent carries the [`HomeChannelUnset`](/kube-agents/operator/platformagent-crd/#status) condition and the installer warns before it applies.

With the field unset and `spec.integration.googleChat.homeChannelPolicy` `auto` (the default), the first top-level mention of the agent in a named space makes that space the home channel. A direct message or a group chat never does, and neither does a reply inside a thread or a command. The gateway checks the space first: the app is a member, and the space does not admit people outside your organization. It then posts one line in that thread saying so, and proactive posts follow within about a minute with no pod restarted.

`manual` turns the learn off, so `homeChannel` alone decides. A set `homeChannel` wins over a learned space. To move a learned space, set the field. To forget it, remove the `gchat` keys from the `<agent>-home-channel` ConfigMap and mention the agent again. Both platforms share that ConfigMap, so deleting it forgets Slack's learned channel too ([the learned home channel](/kube-agents/operator/platformagent-scope-integrations/#specintegrationslack-on-the-a2a-gateway) has the record).

The agent sends home posts to each platform on the gateway that has a home channel. A channel or space the gateway learned counts. When no platform has one, the gateway refuses them and keeps each platform's posts apart, up to fifty for thirty days. It posts one digest once that platform's home channel is set.

### What it looks like end to end

[How a chat question is answered](#how-a-chat-question-is-answered) follows one question from the gateway's `ingress` line to the card's report in the thread. In short:

1. User DMs the app or @-mentions it in a space.
2. Chat sends the message event to the topic; the gateway pulls it from the subscription and publishes it as a task, and the `hermes-bridge` container runs it as a Planning Agent turn.
3. The Planning Agent picks the right specialist from the injected roster and files a kanban card with the full request context (`kanban_create`). The two questions the roster answers itself, which GCP projects are in scope and where the host cluster is, get a direct reply and no card.
4. The gateway's kanban dispatcher spawns the specialist — for infrastructure work, the Platform Agent (`hermes -p platform`) — which runs the tool loop and completes the card with a one-line `summary` and the full answer in `result`. A card filed from chat goes ahead of background triage, and one worker slot is held for it ([Why dispatch is capped by default](/kube-agents/operator/platformagent-harness/#why-dispatch-is-capped-by-default)). If it has to wait anyway, the thread says `⏳ Queued: the system is busy. Your request will start when a worker frees up.` and the specialist's progress joins that message once it starts. The wait is bounded: after `spec.harness.tuning.admission.queueBoundSeconds` (600 s by default) the dispatcher blocks the card with kind `capacity`, the queued line settles as stopped, and the Planning Agent replies in the thread with the reason and the alternatives.
5. The gateway posts the card's progress into the thread (one plan message edited in place with `KAGE_SLACK_UX` on, a message per note with it off) and then its report. The Planning Agent is woken for none of it; it is woken when a card blocks or fails.

A file the card produced is not attached: Chat's `media.upload` refuses app authentication, so an install reaching Chat through the credential proxy can never produce a native attachment, and the gateway posts the report without it.

### Session metadata

Every Chat message carries session context (space, user, thread) that flows through Hermes and out as OpenTelemetry spans. The full trace is documented in [`docs/designs/gchat-session-metadata-data-flow.md`](https://github.com/gke-labs/kube-agents/blob/main/docs/designs/gchat-session-metadata-data-flow.md).

## Slack

This section has its own dedicated reference page: [ChatOps: Slack integration](/kube-agents/concepts/chatops-slack/).

## Sending another message while it works

Through the gateway, a message sent while the Planning Agent is still answering an earlier one in the same conversation is queued as a follow-up behind the running task; see [Follow-ups while a task runs](/kube-agents/concepts/chatops-a2a-gateway/#follow-ups-while-a-task-runs).

## Conversations through the A2A gateway

This section has its own dedicated reference page: [ChatOps: A2A gateway & conversations](/kube-agents/concepts/chatops-a2a-gateway/).

## How a chat question is answered

A message from Google Chat or Slack reaches the A2A gateway rather than a listener in the agent pod. The Planning Agent still answers it, and still hands cluster work to a specialist as a kanban card. What the gateway changes is how the message reaches the Planning Agent, over the message bus, and how the card's answer gets back to the thread, through the gateway. Setting up the Slack app for the gateway is covered in [Slack app setup](/kube-agents/install/slack-app/).

The commands below assume the default resource names (`platform-agent`) and the `kubeagents-system` namespace. The gateway logs one JSON object per line.

1. **The gateway takes the message.** It refuses a sender the channel's allowed-users list does not admit. It posts a status line in the thread that reads `⏳ submitted…` (on Google Chat; Slack shows Working… on the thread instead), and publishes the message as a task for the `platform` addressee. When at least as many requests are already waiting or running as the bridge runs at once (10 by default), the status line says how many are ahead of yours instead: `⏳ queued — 10 requests are ahead of yours; I'll start on it as soon as there's room`. Each message that starts a turn logs an `ingress` line with its `taskId`, `conversation` and `addressee`:

   ```bash
   kubectl logs deployment/platform-agent-a2a-gateway -n kubeagents-system -c gateway | grep '"msg":"ingress"'
   ```

2. **The bridge hands it to the Planning Agent.** The `hermes-bridge` container in the agent pod takes the task from the bus and sends its text to the Hermes API server in the same pod. The server runs it as a turn under the `default` profile: the Planning Agent (on an install that enables the experimental `platformFrontDoor`, the Platform Agent instead). Every message in one thread lands in the same Hermes session, so a turn sees the thread's earlier turns. The status line changes to `⚙️ working`. The bridge logs which executor it runs when it starts, and a `task accepted` line for each task:

   ```bash
   kubectl logs deployment/platform-agent-gateway -n kubeagents-system -c hermes-bridge | grep -E 'hermes bridge consuming|task accepted'
   ```

   The startup line should carry `"executor":"api"`. Its `"profile":"platform"` is the bus address the bridge takes tasks from, not the Hermes profile that runs the turn. With `"executor":"cli"` (the operator setting `A2A_BRIDGE_EXECUTOR=cli`, or a bridge with no API server key), each message runs as a one-off `hermes -p platform` command instead. The Platform Agent answers it directly, with no Planning Agent and no memory of the thread, and a card it files does not report back to the thread.

3. **The Planning Agent files a card and acknowledges.** It routes the request: to the Cluster Agent for a named cluster's live runtime state (or the host cluster's agent for "this cluster") when one is on the roster, otherwise to `platform`. It files a kanban card for that specialist, then replies with one short line naming what is being checked, such as `checking prod-east.` The gateway posts that line as a message (on Google Chat, the status line becomes that line). The turn has ended; the work has not. The gateway logs the end of the turn:

   ```bash
   kubectl logs deployment/platform-agent-a2a-gateway -n kubeagents-system -c gateway | grep '"msg":"task terminal"'
   ```

   A message sent while a turn is still running is queued as the next turn in the same session (`✏️ got it, I'll take that next`); the `cli` executor refuses it instead. One sent after the acknowledgement starts a new turn.

4. **The specialist works the card.** The kanban dispatcher in the agent pod starts the specialist against its own profile, with its own identity, permissions and cluster access ([Security and IAM](/kube-agents/reference/security-and-iam/) is canonical). No setting is needed to let it read a cluster. To inspect the cards and read one:

   ```bash
   kubectl exec deployment/platform-agent-gateway -n kubeagents-system -c platform-agent -- hermes kanban list
   kubectl exec deployment/platform-agent-gateway -n kubeagents-system -c platform-agent -- hermes kanban show <task_id>
   ```

5. **The answer comes back to the thread.** Before a task's first turn the bridge records which conversation its Hermes session answers, so the card is addressed to that conversation. As the specialist works, the gateway posts each progress note into the thread or DM you asked in, and then the card's result. Two things differ from delivery through a Hermes chat platform. A card's progress is one plan message the gateway edits in place with `KAGE_SLACK_UX` on, and a message per note with it off. A file the card produced is not attached.

   If the card blocks or fails, the thread gets the card's own blocked or failed line from the notifier. The Planning Agent's wake for it runs in the bridge's session, and its reply is not posted. The gateway posts only into a conversation it is still holding, the one whose session record carries the card's context, and refuses anything else. It logs each post it makes:

   ```bash
   kubectl logs deployment/platform-agent-a2a-gateway -n kubeagents-system -c gateway | grep -E '"msg":"(chat.notify route armed|notify posted|notify refused)'
   ```

   At startup `chat.notify route armed` should carry `"conversations":true`. Each `notify posted` line names the conversation it posted into in its `thread` field, the same key as the `conversation` field on the question's `ingress` line.

The session pods that [Security and IAM](/kube-agents/reference/security-rbac/#each-a2a-session-pod-is-its-own-bus-identity) describes are a different path. The gateway starts one only for a message that begins with the word `delegate` (`delegate: check prod-east`), which runs that one task in its own pod, or for a conversation moved onto its session route with the `/session` command. Such a pod reads the cluster only under the session pods' [cluster view](/kube-agents/operator/platformagent-harness/#the-session-pods-cluster-view): on by default when the install sets `defaultRoute: session`, or with the operator's `A2A_SESSION_CLUSTER_VIEW=true`. Any other message follows the steps above, which that setting does not affect.

## Microsoft Teams

An experimental Microsoft Teams Bot Framework relay (`spec.integration.teams`) connects the gateway (`agents/platform/scripts/teams_relay_patch.py` and `agents/chat/plugins/platforms/teams/`) to `/v1/chat/teams/*` on the credential broker (`TeamsRelay` in `agents/platform/scripts/credential_proxy.py`). The broker holds `TEAMS_APP_ID` and `TEAMS_APP_PASSWORD`, mints and caches Microsoft Entra OAuth 2.0 `client_credentials` tokens, and enforces optional single-tenant isolation (`TEAMS_TENANT_ID`). Outbound calls on `/v1/chat/teams/api` are restricted to `POST v3/conversations/<id>/activities`, plus `PUT` on one `activities/<id>` for the gateway's status line (excluding `/activities/history`), on official Bot Framework hosts (`smba.trafficmanager.net` and `*.botframework.com`, with query strings, fragments, and HTTP redirects refused).

The in-pod event queue (`/v1/chat/teams/events`, `/ack`, `/nack`) is wired between the Hermes gateway and credential broker, and the gateway adapter, not the broker, applies the user allowlist (`TEAMS_ALLOWED_USERS` / `TEAMS_ALLOW_ALL_USERS`). List users by Entra ID Object ID (`from.aadObjectId`) or `from.id`: an inbound Teams activity carries no UPN or email, so such entries match no one, and display names are never matched.

Proactive alerts and the default scheduled reports ([below](#proactive-alerts-both-channels)) go to Google Chat and Slack, and to the Teams home channel once the gateway's Teams backend is armed. Without that backend, a cron job whose `deliver` names `teams` posts its report to the Teams home channel (`TEAMS_HOME_CHANNEL`, rendered from `homeChannel`).

When the operator runs with `A2A_TEAMS_BACKEND=true`, the A2A chat gateway consumes that queue instead of the Hermes adapter (`a2a/gateway/teams.go`, the `A2A_TEAMS_*` env), the broker admits the gateway pod as a caller, and the Hermes Teams platform is not rendered.

What this means for an evaluator: enabling `spec.integration.teams` alone gives you the outbound half. A cron job whose `deliver` names `teams` posts its report to the Teams home channel, as an Adaptive Card by default. A message typed in Teams reaches the agent only with the inbound receiver on (`spec.integration.teams.inbound.enabled`, with `tenantId`). The operator then runs a pod that accepts the requests Microsoft delivers for the bot, verifies Microsoft's signature on each one, and hands the message to the install. You expose its Service with your own Ingress and TLS certificate and register that address as the bot's messaging endpoint; [Microsoft Teams app setup](/kube-agents/install/teams-app/) walks through it.

## Proactive alerts (both channels)

This section has its own dedicated reference page: [ChatOps: Proactive alerts](/kube-agents/concepts/chatops-proactive-alerts/).

## First-run onboarding

On a fresh install the first chat interaction gets a guided onboarding instead of a cold start. One `no_agent` cron job on the Planning Agent profile (`agents/chat/defaults/cron/jobs.json`), `oobe`, drives it. Every minute it runs four stages: delivery first, then the scan, then the first-run audits, then the lost summaries. The old `bootstrap-inventory-scan` and `bootstrap-inventory-delivery` entries ship disabled.

- **The scan stage** files a kanban card assigned to the Platform Agent, recording the card's id in `/opt/data/.bootstrap_scan_filed` so it never files a second one. That worker runs the environment-discovery SOP ([`agents/platform/governance/inventory.md`](https://github.com/gke-labs/kube-agents/blob/main/agents/platform/governance/inventory.md)): it lists the fleet, audits any cluster the Cluster Agent roster has no agent for or the first-run cap leaves without a card, and completes. The same cron job files one audit card per Cluster Agent on the roster, up to that cap, each pointing that agent at the single-cluster audit SOP ([`agents/platform/governance/cluster_inventory_audit_sop.md`](https://github.com/gke-labs/kube-agents/blob/main/agents/platform/governance/cluster_inventory_audit_sop.md)).

  Once those cards finish, the same cron job's hand-off script merges their structured results (fleet topology, Workload Identity and the workload checks the scan runs) into the complete findings at `/opt/data/INVENTORY.raw.md`. Any cluster that did not report is named as a gap. It then files a second card, which runs the prioritization SOP ([`agents/platform/governance/inventory_prioritize_sop.md`](https://github.com/gke-labs/kube-agents/blob/main/agents/platform/governance/inventory_prioritize_sop.md)) against those findings alone. That card scores each one against a fixed rubric and registers all of them in the findings queue before writing the ranked report the user is sent to `/opt/data/INVENTORY.md`.

  The scan runs a fixed list of checks and reports what else it sees in passing that no first-run audit checks. The report counts those checks in its posture and leaves security and RBAC, reliability, capacity and cost to the first-run audits stage below. The full findings stay on disk.

  The report names the most urgent critical findings, at most `FINDINGS_FIRST_REPORT_CRITICALS` of them, and nothing less severe. It says how many items are queued behind them and how many of those are critical, and the [findings nudge](/kube-agents/reference/cron-jobs/), whose page also covers that limit, brings those to chat a few a day. A scan with no critical finding gets a report that lists none and calls nothing healthy, since the scan does not check what the first-run audits check. If no cluster's audit reached the findings, no second card is filed: the hand-off writes a short report saying no cluster was audited and why, so an empty scan is never presented as a clean environment.

- **The delivery stage** posts that report into the chat once two conditions hold: the ranked report has been written, and a human has connected within a day of the sweep. After that it is filed as an issue instead; see below. On Slack with `KAGE_SLACK_UX` on, and on Google Chat, it goes as a card built from the files the prioritization card left beside the report, never from the report's text. The card has a headline counting the things to fix first, one row per listed item with its scored risk and the action to take, and the rest counted. The scan's checks are folded, with buttons to fix the first one or see them all.

  When the card cannot be built, or an origin-path door cannot post it, the report goes as text, reshaped as described above. The onboarding stage log (`logs/oobe.log` under the agent's data directory) says why. In a recorded conversation a card that did not post is posted again on a later tick. Elsewhere it goes as written.

  It closes the report with a short note on the fleet audits: what the first-run stage did (the audits are running, which started as part of onboarding, named by area, which did not and why, or why it started none). An audit that finished before anyone opened the chat had no home channel to post its summary to. So the note names every shipped fleet audit that ran since the scan began and whose summary was not posted, however its run started, and gives a request you can send to see those reports. With the card, the note is a separate message after it. It claims the delivery atomically first, so overlapping runs can't post the report twice.

- **The first-run audits stage** runs four of the fleet audits and then the upgrade retrospective once, one after another (`fleet-wide-cost-analysis`, `compliance-audit`, `obtainability-audit`, `stockout-prevention`, `upgrade-retrospective`). It starts as soon as the scan's ranking card has finished and none of the four is already running. If that never happens, it starts at a fallback of 90 minutes or more after the sweep was filed (longer for a larger fleet). So their first ledger issues arrive soon after the scan rather than at the next scheduled run. An audit that already completed a scheduled run since the scan began is not run again. It does not wait for a human.

  On an install with no GitOps repository, each audit keeps its report in the report store, and a run that changed something posts a summary that says no GitOps repository is connected. It records what it started in `/opt/data/.oobe_audits_fired`. Once the stage is done, no lost first-run summary is still to re-send, and the report was delivered about a quarter of an hour ago, `oobe` removes itself. The design is [`docs/designs/oobe.md`](https://github.com/gke-labs/kube-agents/blob/main/docs/designs/oobe.md).

- **The lost summaries stage** posts a first-run audit's report whose summary found no home channel, once the operator projects a Slack or Google Chat home channel into the pod. It asks the chat relay to post the report as the scheduled delivery would have, while the run is under 90 minutes old; the relay's record of the post keeps a second copy out. An older run and an audit outside the first-run chain keep the request sentence in the report's note.

The `bootstrap_onboarding` plugin (enabled in `agents/chat/config.yaml`) hooks the first human turn. It greets the user, binds the delivery job to that chat thread and marks that a human is present. For a conversation the gateway holds it records the conversation the message came from, and the report is posted into it through the gateway; it sets no home channel there.

Once the report has been filed as an issue because nobody wrote within a day, the first human turn is greeted once with a link to it and binds nothing. After a retire the first turn gets no onboarding greeting. Once the report is delivered, the flow marks itself complete and the disabled bootstrap entries are removed; `oobe` removes itself about a quarter of an hour after delivery once its audits stage is done. None of them runs again on that data volume.

The job fires every minute (`* * * * *`, see [Autonomous watchdogs](/kube-agents/concepts/autonomous-watchdogs/#what-fires-the-schedule)) while the work it guards takes minutes, so each stage records its own marker the moment it acts rather than inferring from the report or from completion. `oobe`'s design is [`docs/designs/oobe.md`](https://github.com/gke-labs/kube-agents/blob/main/docs/designs/oobe.md); the onboarding stages' design, state markers, and maintenance rules live in the plugin's [README](https://github.com/gke-labs/kube-agents/blob/main/agents/chat/defaults/plugins/bootstrap_onboarding/README.md).

## What's not here

- **One browser page by default.** Chat is the primary surface. Every install serves the [A2A console](/kube-agents/reference/user-interfaces/#a2a-console), a status page over the bus with a chat pane, reached only through `kubectl port-forward`. Two more are off by default. The [web console](/kube-agents/deploy/web-console/) has threads that reach the Planning Agent front door and channels that show event triage and scheduled checks. The Hermes dashboard is a per-pod debugging view the installer offers as `--enable-hermes-dashboard` (the CRD's own default is on) that binds loopback inside the pod. A local [admin console](/kube-agents/reference/admin-console/) runs from a repository checkout on your own machine; the install does not deploy it. [User interfaces](/kube-agents/reference/user-interfaces/) compares them, with the port and the way in for each.
- **No CLI beyond the Hermes CLI inside the pod.** `kubectl exec` into the agent pod and run the Hermes CLI there. The pod hosts several profiles, so a bare `hermes` command talks to the locked-down Planning Agent; use `hermes -p platform` to reach the Platform Agent (or `hermes -p <cluster-profile>` for a Cluster Agent). `kubectl port-forward` is not a way in on a GKE Sandbox (gVisor) node pool, which is the install default: the forward is established in the host-side netns and cannot see a listener inside the sandbox — [PlatformAgent CRD](/kube-agents/operator/platformagent-crd/#specharness) is canonical on that. `kubectl exec` has no such problem, because it enters the sandbox.
- **No email, PagerDuty, or generic webhook ingress.** Chat channels only.

## When no chat platform is enabled

Both channels are opt-in and default to disabled, so an install that enabled neither has no chat to talk to. It also carries the [`NoChatPlatform`](/kube-agents/operator/platformagent-crd/#status) condition, which says where its findings go. The A2A gateway still runs, on its console door alone, so the [A2A console](/kube-agents/reference/user-interfaces/#a2a-console)'s chat pane reaches the Planning Agent with nothing to turn on: `kubectl -n kubeagents-system port-forward svc/platform-agent-a2a-console 8080:8080`, then `http://localhost:8080`. The [web console](/kube-agents/deploy/web-console/) is a browser alternative, turned on with `install.sh --enable-web-console`; its channels also show event triage and scheduled checks. The Hermes CLI above is another way in, and the installer prints these two commands when you choose "None" at its chat prompt and again when it finishes:

```bash
gcloud container clusters get-credentials <cluster> --location <region> --project <project> --dns-endpoint
kubectl exec -it deployment/platform-agent-gateway -n kubeagents-system -c platform-agent -- hermes -p platform
```

Pass `--dns-endpoint` only on a cluster that publishes an externally reachable DNS endpoint; gcloud rejects the flag on one that does not. The installer resolves that per cluster and prints the flag only when it applies ([`scripts/installer/gke_dns_endpoint.sh`](https://github.com/gke-labs/kube-agents/blob/main/scripts/installer/gke_dns_endpoint.sh)). The `-c platform-agent` is the Hermes container; the gateway pod runs three, so omitting it works but makes kubectl warn about which one it picked.

This reaches the Platform Agent directly, bypassing the front door: a request typed here is executed by the profile that receives it rather than being planned and filed as a kanban card. A bare `hermes` reaches the Planning Agent instead, which is where a chat message would have landed and which delegates as described above.

The [admin console](/kube-agents/reference/admin-console/), started from a repository checkout on your own machine, is one more. Its Chat page reaches the Planning Agent through the front door, so a request typed there is planned and delegated the way a chat message would be. [User interfaces](/kube-agents/reference/user-interfaces/) compares the browser pages.

Two things a chat-less install does not exercise. Scheduled reports and alert-driven triage are delivered only to enabled chat platforms (Google Chat, Slack, and Microsoft Teams while the gateway's Teams backend is armed), so neither reaches a person as it happens. The audit reports stay in the report store on the data volume, the triage shows on the board, and other scheduled reports are not kept.

What the alert path did is still readable. Ask the agent through any of these doors `what alerts fired overnight?` and it answers from its event ledger: the alerts it posted, and the events it held back from chat and why.

The onboarding delivery stage waits a day for a human to connect over chat. Then it files the first-run inventory report as an issue labelled `agent:onboarding`, in the GitOps repository when it is on GitHub or else in the install's one managed GitHub repository. A report it could not file is retired a week after the sweep. For that first day the report sits at `/opt/data/INVENTORY.md` on the shell sandbox pod's volume.

Read it there with `kubectl exec -n kubeagents-system platform-agent-shell-0 -c shell -- cat /opt/data/INVENTORY.md`, or in the issue afterwards. The file is renamed `INVENTORY.delivered.md` once filed or retired.

Or ask through any of these doors. `what did onboarding find?` answers from that report, `show me the full inventory` from the sweep's complete findings, and `was the first-run report delivered?` says where it went: the chat where the first person wrote, the issue, or retired after a week with nobody arriving.

## Where to go next

- [Overview → Proactive autonomy](/kube-agents/overview/proactive-autonomy/) — what fires the outbound alerts.
- [Concepts → Observability](/kube-agents/concepts/observability/) — where the traces from chat sessions land.
