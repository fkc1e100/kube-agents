---
title: "Upgrading to the A2A stack & troubleshooting"
description: "Migrating older installs to the A2A stack, gateway ServiceAccount notes, and diagnosing refused upgrades."
---

Part of [Upgrade](/kube-agents/install/upgrade/).

## Moving to the A2A stack

Every install runs the A2A stack: the NATS bus, the A2A gateway, the auth callout, the capability
verifier, the A2A console and the `hermes-bridge` container in the agent pod. The chart also creates the `<release namespace>-profiles` Namespace for
profile pods, with its ResourceQuota and NetworkPolicy. Earlier releases rendered it only for `spec.mode: next`, and an install made
before `next` became the default ran without it, as `spec.mode: today`. The upgrade moves such an
install with no action of yours.

`spec.mode` is deprecated and ignored. The CRD defaults an absent field to `next`, and the admission
webhook rewrites `today` to `next` on the next write. The operator patches a stored `today` to
`next` on its first pass, and records an Event with reason `ModeMigrated` on the `PlatformAgent`.
`PLATFORM_AGENT_MODE` in `install.env` is read and ignored, with one notice; delete the line. There
is no switch back: the way back is the previous release
([Rolling back a release](/kube-agents/deploy/rollback/)).

[`docs/designs/spec-mode-switch.md`](https://github.com/gke-labs/kube-agents/blob/main/docs/designs/spec-mode-switch.md)
is the design of record for the stack. This section covers what the move does to an install that
ran without the stack: the bus first, then Google Chat, then Slack. An install already on `next`
meets none of it.

### The A2A bus

An install that ran without the stack has no A2A bus, so the upgrade creates one, and a new bus
runs three NATS servers on separate nodes, each with a 40Gi JetStream claim
([Cluster requirements](/kube-agents/install/prerequisites/#cluster-requirements)). On a Standard
cluster that cannot grow to three nodes, set the chart value
`platformAgent.harness.tuning.busReplicas: 1` (through `extra_helm_values`) before the upgrade. Once the
bus exists, changing the count migrates it, keeping its data
([Changing the bus's server count](/kube-agents/operator/platformagent-crd/#changing-the-buss-server-count)).
The chart's quota check counts the whole stack
([Footprint](/kube-agents/install/prerequisites/#footprint)); under a namespace quota sized for the
previous stack, `helm upgrade` is refused until the quota has room.

With Google Chat or Slack on, a full run prints the chat setup checklist after "Upgrade
Complete!", so the app steps the gateway needs are on the screen after the move.

### Google Chat

With Google Chat enabled, the A2A gateway takes Google Chat. Each top-level
message you send the app in a DM is then its own conversation, answered in its own thread, as on
Slack ([ChatOps → Google Chat](/kube-agents/concepts/chatops/#google-chat)). The thing to set for
it is the home channel, where alerts and scheduled reports land. The gateway posts them
to `GOOGLE_CHAT_HOME_CHANNEL` in `install.env` (the `PlatformAgent`'s
`spec.integration.googleChat.homeChannel`), which must be a space name, `spaces/<id>`, or, with
the key unset, to the space it learns from the first mention (below). A home
channel set from chat with `/sethome`, or by the install's first chat message, before the move is
kept in the Planning Agent's profile and does not count.

With the key not a space name, the agent posts nothing to Google Chat unprompted. With it unset,
the gateway makes the space of the first top-level mention of the agent in a named space the home
channel, and the agent posts nothing unprompted until then.

Before the upgrade, set `GOOGLE_CHAT_HOME_CHANNEL` in `install.env`, so the full run applies it
([ChatOps → Home channel](/kube-agents/concepts/chatops-slack/#home-channel)). After it, check that
a scheduled report or an alert reaches that space.

With Slack enabled too, the same gateway takes Slack. The Slack steps below apply as they do
with Google Chat off.

### Before the upgrade

1. Check that Slack answers now, as in [Checking the result](/kube-agents/install/upgrade/#slack).
2. Check the Slack settings the gateway depends on. A full upgrade refuses a run that
   would hand the gateway a setting it cannot use, and names it
   ([When an upgrade is refused](#when-an-upgrade-is-refused)); `--plan` warns of the same
   ones. Checking first saves a refused run:
   - The bot token is one `xoxb-` token, not a comma-separated list: the A2A gateway takes a
     single workspace's token
     ([Get the tokens](/kube-agents/install/slack-app/#get-the-tokens)). This counts the
     `xoxb-` tokens in the installer's Secret without printing them, and should print `1`:

     ```bash
     kubectl get secret platform-agent-secrets -n kubeagents-system \
       -o jsonpath='{.data.SLACK_BOT_TOKEN}' | base64 -d | tr ',' '\n' | grep -c '^xoxb-'
     ```

     `0` means nothing was read: check that the `PlatformAgent`'s
     `spec.integration.slack.botTokenSecretRef`, if set, names this Secret and key.

   - `SLACK_ALLOWED_USERS` in `install.env` holds member IDs such as `U0123ABCD`, not emails
     ([Allowed users](/kube-agents/install/slack-app/#allowed-users)).
   - `SLACK_HOME_CHANNEL` in `install.env` is the ID of the channel for alerts and scheduled
     reports: `C…`, or `G…` for some private channels. The gateway posts the agent's
     proactive messages to this channel, or, with it empty and `homeChannelPolicy` auto (the
     default), to the channel of the first top-level mention of the agent. A `/sethome` home
     channel does not carry over. A DM ID (`D…`) or a channel name turns off the gateway's
     notify route, and with it the reports of board cards
     ([Slack app setup → Home channel](/kube-agents/install/slack-app/#home-channel)). With no home
     channel those posts go to Google Chat's home channel, or are refused when Chat has none either,
     while conversations keep working. The run warns, and the `PlatformAgent` carries
     `HomeChannelUnset`.
   - Keep the agent image at the operator's release, on Slack and on Google Chat. A learned home channel reaches the agent through
     a file the operator mounts; an older agent image reads env only and never sees it, while the CR
     shows no condition.
     An older agent image on an install with no home channel on the CR also sends no proactive
     posts.
   - An allowed member moves the home channel later from the app's Home tab (the Home channel panel);
     the record keeps who moved it and when. On a rollback to a gateway without the panel, a published
     Home view keeps the picker until the member reopens the tab; the old gateway drops a pick and
     writes nothing.

3. Check the board for cards in flight:

   ```bash
   kubectl exec deploy/platform-agent-gateway -c platform-agent -n kubeagents-system -- \
     hermes kanban ls --status running
   kubectl exec deploy/platform-agent-gateway -c platform-agent -n kubeagents-system -- \
     hermes kanban ls --status blocked
   ```

   Wait until neither command lists a card: answer each blocked card in its Slack thread, and let
   running ones finish ([What carries over](#what-carries-over) says why). If scheduled jobs keep
   filing cards, upgrade between their runs.

4. Upgrade when nobody is using the agent, and tell its users that Slack will not answer for a
   while.

Then [run the upgrade](/kube-agents/install/upgrade/#run-the-upgrade) in the default full mode: pass no `--upgrade-mode`. An
operator run moves the install too, since the operator renders the stack whatever the chart says,
but only a full run re-renders `install.env`'s Slack and Google Chat settings onto the resource.

### During the upgrade

The operator moves Slack in three steps:

1. It restarts the credential broker without the Slack tokens, stopping the old broker pod before
   it starts the new one, and restarts the agent's pod without its Slack listener. From here, no
   process holds the app's Socket Mode connection.
   - Messages the broker had taken from Slack but not yet handed to the agent are lost: the
     broker acknowledges each event to Slack when it arrives and holds it in memory.
   - A question the agent was answering stops with its pod and gets no answer.
   - A board card that was running is put back in the queue once the board reclaims its stale
     claim, which can take up to 30 minutes (`kanban.dispatch_stale_timeout_seconds`), and runs
     again from the start.
2. It creates the NATS bus and the auth callout. It creates the A2A gateway once a callout
   replica is ready, which needs the bus to be running. The provisioning Job, started at the same
   point, creates the bus's streams.
3. The gateway joins the bus and waits for the provisioning Job to create the `TASKS` stream;
   until then the pod is running but not ready, and the `PlatformAgent` reads `Provisioning`
   naming it. It then checks the bot token with Slack, logs `slack connected`, and opens the
   Socket Mode connection.

The broker's connection stops when the move starts, and the gateway exists only once the bus is
up, so in practice the two never take the same message. How long Slack goes unanswered depends on
how fast the cluster schedules and pulls the new pods. Slack has no connection to deliver a message
sent in that gap to, and nothing in kube-agents fetches it later: treat it as lost, and ask its
sender to send it again. Wait for the gateway, for up to 15 minutes:

```bash
for i in $(seq 90); do
  kubectl logs deploy/platform-agent-a2a-gateway -c gateway -n kubeagents-system 2>/dev/null \
    | grep -q 'slack connected' && { echo connected; break; }
  sleep 10
done
```

It prints `connected` once the gateway has logged `slack connected`. The operator then restarts
the agent's pod once more, to add the bridge that runs the gateway's tasks, and that can take a few
minutes if the cluster has to add a node for it. Wait for the `PlatformAgent` to report `Ready`,
then check Slack as in [Checking the result](/kube-agents/install/upgrade/#slack):

```bash
kubectl wait platformagent/platform-agent -n kubeagents-system --for=condition=Ready --timeout=15m
```

If the loop prints nothing, the `Ready` condition's message names what the
operator is waiting on, and
[Troubleshooting](https://github.com/gke-labs/kube-agents/blob/main/INSTALL.md#6-tracing-where-a-chat-message-stops)
has the checks for the bus and the gateway. Slack stays unanswered until the gateway connects or
you roll back to the previous release.

```bash
kubectl get platformagent platform-agent -n kubeagents-system \
  -o jsonpath='{.status.conditions[?(@.type=="Ready")].message}{"\n"}'
```

### What carries over

- **The same app, tokens and allowlist.** The gateway reads the tokens from the same Secret.
- **The board and the agent's data volume.** The new pod mounts the same volume.
- **Not the conversations.** The agent starts every Slack conversation with no history from
  before the move. In a channel, a reply without a mention in a thread started before the
  upgrade gets no answer: mention the app.
- **Not the cards in flight, outside the home channel.** A card filed before the upgrade from a
  DM or from any channel other than the home channel posts nothing after it: the gateway refuses
  the post and, with a home channel set, logs `thread "<channel>/<ts>" is not a thread of the home channel`. A card filed
  in a home-channel thread still posts its progress and report there. Either way its buttons stop
  working: the gateway answers only the buttons it drew itself.
- **The home channel only from `install.env`**, as in step 2 above.

Slash commands, buttons, cards and the other Slack features that do not carry over are listed in
[ChatOps → What the gateway changes on Slack](/kube-agents/concepts/chatops-a2a-gateway/#what-the-gateway-changes-on-slack).

### After the upgrade: the Slack app

Once a DM gets an answer as in [Checking the result](/kube-agents/install/upgrade/#slack), edit the app as
[Slack app setup → Moving an app made for the Hermes listener](/kube-agents/install/slack-app/#moving-an-app-made-for-the-hermes-listener)
describes. Delete the slash commands from its manifest and leave interactivity on, since the gateway
answers the buttons it draws. Edit the app rather than pasting the gateway's manifest over it: a
manifest replaces the app's whole configuration, including its name. Do it after the upgrade rather
than before, because the Hermes listener answers slash commands until then. Until you do, a slash
command gets Slack's timeout error.

A rollback to a release before the stack was unconditional keeps the stack: that release's
operator reads `spec.mode: next` on the migrated object ([Rolling back a release](/kube-agents/deploy/rollback/)).
Slack returns to the credential broker and the Hermes listener only after that release's own
switch back. A full run with `PLATFORM_AGENT_MODE=today` alone renders no field and changes
nothing, so patch `spec.mode` to `today` first (the rollback page has the command). They answer
the slash commands again then, so put the `commands` block back in the app's manifest. Conversations and cards started on the gateway do not carry back,
for the same reasons as above. The bus volume and its credentials Secret stay;
[Uninstall](/kube-agents/install/uninstall/#what-the-a2a-stack-leaves-behind) says how to remove
them.


## The gateway's own ServiceAccount

From the release in which the gateway Pod runs as its own ServiceAccount, an upgrade moves the
gateway from the agent ServiceAccount (`spec.security.serviceAccountName`, `kubeagents-platform-agent`
by default) to `<name>-gateway-agent`, which the operator creates with no annotation. The agent
ServiceAccount, its Workload Identity annotation and its IAM binding stay where they are, with the
credential broker, so neither Terraform nor IAM changes. The new ServiceAccount is bound to the same
read-only `kubeagents:minimal` ClusterRole and the `kubeagents:local` and `kubeagents:leader` Roles
the gateway already used.

Two things an install may have added by hand do not follow the gateway:

- **RBAC bound to your own ServiceAccount.** If you set `serviceAccountName` and bound extra roles to
  it expecting the gateway to use them, the gateway no longer runs as it. Bind them to
  `<name>-gateway-agent` if the gateway needs them; the broker keeps whatever is bound to yours.
- **IAM granted to the gateway's Kubernetes identity directly.** A `principal://…/subject/ns/<ns>/sa/<sa>`
  or namespace-wide `principalSet://` grant reaches whichever Pod runs as that ServiceAccount, and the
  gateway's metadata path is closed, so such a grant no longer reaches the gateway. Anything in the
  gateway that needs Google goes through the broker.

To check: `kubectl get deployment platform-agent-gateway -n kubeagents-system -o
jsonpath='{.spec.template.spec.serviceAccountName}'` prints `platform-agent-gateway-agent` for the
chart's default name.


## When an upgrade is refused

Every one of these stops the run before any of the new release is applied. The first four are
settled before the run touches the cluster at all. The last six need the cluster: they are settled
after `kubectl` has been pointed at it, and except for the breaking-change check, after a real run's
pre-flight Secret backfills (a plan skips those). They still run before any CRD, chart or Terraform
change of the new release. One is the exception: the gVisor node-pool refusal comes from the
Terraform apply itself, so a full upgrade it stops has already applied the new release's CRDs.

- **The sources do not match the release.** The checkout's `HEAD` is not the release's commit, the
  tree has uncommitted changes, or an unpacked tree names a release other than the one asked for —
  either in its `.release-bundle` marker or in the version stamped into its root scripts. A release
  script carries its version with it, so standing in an older unpacked tree and running a newer one
  is refused rather than silently applying the older tree. The stamp is read from `install.sh` and
  `uninstall.sh` before `upgrade.sh`, because saving a newer `upgrade.sh` into an older tree
  overwrites the one file that would otherwise be asked. Start again from a clean checkout or from
  the bundle of the release you want.
- **`KUBE_AGENTS_INSTALL_ENV` names a file that is not there.** An explicit pointer is taken
  literally, not fallen back from, so a stale or mistyped value is reported with the path you gave
  rather than searched past. Fix the path or unset the variable.
- **No install configuration.** Neither `KUBE_AGENTS_INSTALL_ENV` nor an `install.env` was found in
  any of the configuration locations described at the top of this page. An install predating 0.4.0,
  which kept its settings in the retired `k8s-operator/scripts/vars.sh` and never gained an
  `install.env`, is refused here: copy those settings into an `install.env` first.
  If the machine that held the file is gone, see
  [Recovering `install.env`](/kube-agents/install/upgrade-recovery/).
- **`GITHUB_APP_ID` is not a number.** The token minter needs the GitHub App's numeric ID, the "App
  ID" on the App's General settings page, not its name or slug. `--dry-run` refuses it too.
- **The move leaves behind a commit marked as a breaking change.** When the target does not
  contain the installed commit — a rollback to an older release, or a commit build moved to a
  release that lacks some of its commits — the run reads the commits the target lacks. It stops
  before the Secret backfills if any has a `type!:` subject or a `BREAKING CHANGE:` footer, and
  names each one. Read them, then re-run with `--allow-breaking-downgrade`, in any mode. `--plan`
  warns instead. A move between two release tags to the newer one is not checked, and neither is a
  run whose tag is read off the install. See [Rolling back a release](/kube-agents/deploy/rollback/).
- **The apply would destroy the gVisor node pool.** A full upgrade whose `ENABLE_GVISOR` resolves
  to `false` on a Standard install that runs the gVisor pool stops before `terraform apply`, after
  the CRDs (see above). With no
  `ENABLE_GVISOR` in `install.env`, the upgrade reads the live install instead: the Terraform state,
  then the cluster's node pools. On Autopilot with no state to read, it keeps the sandbox. To keep
  the pool, set `ENABLE_GVISOR="true"`. To turn the sandbox off on purpose, re-run with
  `--allow-node-pool-destroy` (full mode only).
- **No Helm release.** The target namespace has no `kube-agents` release to upgrade.
- **The memory store cannot be checked and nothing named one.** When the configuration records no
  `MEMORY`, the upgrade asks the cluster whether it runs the Hindsight memory store, so that a store
  that is there is kept rather than planned away. If the cluster cannot be asked — `kubectl` is
  pointed elsewhere, the credentials have expired, the API server times out — the run stops instead
  of guessing. Record `MEMORY=hindsight|file|off` in `install.env`, or restore access to the cluster
  and re-run.
- **The chart does not declare a value the release recorded.** The operator and harness modes
  re-apply the values the release recorded, and name each one the new chart's values schema refuses
  as undeclared. On an upgrade that is usually a setting the new chart renamed or removed: run
  `--upgrade-mode=full`, which renders `install.env` onto the chart instead. On a rollback to a
  release that predates the value, re-run with `--drop-undeclared-values`. A full upgrade refuses
  that flag, since it has no recorded values to drop.
- **A Slack setting the A2A gateway cannot use.** With Slack on, the A2A gateway takes Slack, with or without Google Chat. The run
  refuses three settings it cannot use, naming each one:
  - a `SLACK_ALLOWED_USERS` entry with an `@`: the list matches Slack member IDs exactly, so an
    email matches nobody. Replace it with the person's member ID (in Slack, their profile, then
    **⋮** (More), then **Copy member ID**).
  - a `SLACK_HOME_CHANNEL` that is not a channel ID (`C...` or `G...`): the gateway's notify route
    does not arm, so proactive posts and board-card reports stop. The ID is at the bottom of the
    channel details' About tab.
  - a `SLACK_BOT_TOKEN` that holds several tokens, or one with a comma or space left in it: the
    gateway takes one workspace's token, whole. The run gives the count, never the token. Install
    one bot token from one workspace, or turn Slack off (`SLACK_ENABLED=false`).

  `--plan` warns of the same three without refusing.

- **A `SLACK_HOME_CHANNEL_POLICY` or `GOOGLE_CHAT_HOME_CHANNEL_POLICY` that is not `auto` or
  `manual`.** Each key renders its platform's `homeChannelPolicy` under `spec.integration`, and the
  CRD accepts only those two values (empty means `auto`). The run stops before it writes
  `terraform.tfvars`, in every mode and with the platform on or off, and names the key. `--plan`
  stops the same way.

- **The apply would remove GitOps.** The PlatformAgent opens pull requests through the GitHub token
  minter, but `install.env` does not carry that repository in `GITOPS_ORG`, `GITOPS_REPO` and
  `GITHUB_APP_ID`. The run would therefore render GitOps off and destroy the minter's Cloud KMS
  key, key ring and service account. This is what an install whose GitOps came from `install.sh`'s
  flags looks like when it was set up by a release that did not record them in `install.env`. The
  run prints the lines to set, with the live values filled in where it can read them; set them and
  re-run the same command. To remove GitOps on purpose, re-run with
  `KUBE_AGENTS_REMOVE_GITOPS=true` in the environment. `--plan` warns instead.

  A minter that this install did not make (one made by hand, by `make deploy-github`, or by
  another Helm release) is not removed by the apply, so the run does not ask for `GITHUB_APP_ID`.
  It refuses when `GITOPS_ORG`, `GITOPS_REPO` and `GITOPS_HOST` do not name the PlatformAgent's
  GitOps repository, or when it cannot read the PlatformAgent or the repository it names.

  The run decides that the minter is not this install's only when three things hold. The
  `kube-agents` release record has `githubMinter.enabled` false, the minter's Deployment carries no
  Helm annotations for that release, and the install's Terraform state holds no minter module (its
  service account and Cloud KMS key). With no release (a first install), or a state it cannot
  read, it applies the check above.

- **The chart's minter would land on another minter.** This run renders the chart's own token
  minter, but a minter that this install did not make runs under the same names, and Helm does not
  take over objects it does not own. Remove all of the other minter's objects first: run
  `make -C k8s-operator undeploy-github` with the same `GITHUB_MINTER_KSA_NAME` for the kustomize
  path, or turn the minter off in the Helm release that made it, and delete a
  `github-app-credentials` Secret that you made by hand. Or keep the other minter: set
  `GITHUB_APP_ID` empty in `install.env` (and, with `install.sh`, give no `--github-app-id`).
  `--plan` warns instead.
