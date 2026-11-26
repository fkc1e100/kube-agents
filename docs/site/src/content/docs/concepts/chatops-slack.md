---
title: "ChatOps: Slack integration"
description: "Slack Socket Mode behavior, thread formatting, buttons, and KAGE_SLACK_UX options."
---

Part of [ChatOps](/kube-agents/concepts/chatops/).

## Slack

Slack is opt-in. Enable it in the installer's chat menu, where the installer prompts for the token values below, or pass `--enable-slack` with the tokens as flags.

### How it's wired

- The installer's Slack interview collects `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_ALLOWED_USERS`, `SLACK_HOME_CHANNEL`, and `SLACK_HOME_CHANNEL_NAME`; the chart stores the tokens in the credentials Secret and wires the CR's `slack` section.
- [Slack app setup](/kube-agents/install/slack-app/) covers creating the app, its tokens, the allowlist and how to verify.

Slack terminates at the A2A gateway, on the same app and tokens, over Socket Mode (no public webhook required), with or without Google Chat. The Hermes Slack listener and the credential broker's Socket Mode relay are not rendered, so one app has one Socket Mode consumer. The `slack` field of [`spec.integration`](/kube-agents/operator/platformagent-crd/#specintegration) has the detail.

Who is answered is decided by the same `allowedUsers` list, as on Google Chat: a sender must be on the list (or the list must be empty, which allows all), and one who is not is dropped with a notice. A member of another workspace, posting in a channel shared with yours through Slack Connect, is served only when the list names them as `T…:U…` (their workspace ID, a colon, their member ID); an empty list serves no such member. The gateway's `user_id` principal map (the `a2a-slack-principal-map` Secret) is optional: a sender it names is attributed by the identity it maps them to, and any other admitted sender by their Slack member id.

Proactive alerts and scheduled reports reach the [home channel](#home-channel) through the gateway, and the gateway takes a single bot token. When the agent sends a structured message beside its answer (a report's headline and rows, a question with its choices, the plan of the cards it filed), the gateway lays it out in Slack. That layout is the headline in bold, the rows with their severity, a collapsed section for the detail, buttons, and a coloured side bar; a message Slack cannot show posts as its text instead. A click on a choice button answers as your reply (below); a link button opens its page. The design of record is [`docs/designs/spec-chatops-gateway.md`](https://github.com/gke-labs/kube-agents/blob/main/docs/designs/spec-chatops-gateway.md).

The gateway draws the interactive parts itself, from what the agent's messages carry. Your message gets the reaction for its kind of ask (the emoji listed under [Reactions](#reactions)), ⏸️ while the work waits on you and ❌ if it failed. The kind comes off when the answer posts, on the message that asked for the work. That holds even when its cards finish after you have asked something else, as long as each card sent its first marked message before you asked again. The gateway only ever removes its own reactions.

A button on a question, or the one next step an answer offers, is your reply. Clicking it sends the button's answer as your message in the thread, checked against the allowed-users list like a typed one, so a click from someone the gateway would not answer changes nothing. The question then loses its buttons and shows `✓ <your name>: <the button>`, by your Slack display name, never an @-mention.

A reply you type in the thread instead answers it the same way with your reply's first words. The exceptions are `stop`, a status question or a short question about progress (such as "how is the upgrade doing"), `/session` and a `delegate …` request. A question is answered once, by the first click or reply. A next step an answer offers is not a question, so a reply you type leaves its button in place.

Slack shows Working… on the thread from your message until the work, the agent's cards included, has settled, paused while it waits on you, and the thread is titled after your first ask, up to its first question. Opening a new assistant thread, or the bot's Messages tab on an app using agent view, shows the three suggested prompts listed under [Agent view](#agent-view).

These need the app to hold `reactions:write`, `users:read` and `assistant:write`, to subscribe `assistant_thread_started` (and `app_home_opened` for agent view), and to have interactivity on. The gateway's manifest ([Slack app setup](/kube-agents/install/slack-app/#for-the-a2a-gateway)) has all of them. So does the manifest that `hermes slack manifest` prints, except that with `--no-assistant` it lacks `assistant:write`, the assistant view and `assistant_thread_started`. On an app built with only the scopes the gateway needs to read and answer messages, add them and reinstall the app. Otherwise the reactions, the answered line, Working… and the prompts silently do not appear, while the answers still arrive. A button on a message posted before a gateway restart still answers when clicked, but a reply typed under it leaves its buttons in place.

### Allowed users

Slack ingress is gated by `SLACK_ALLOWED_USERS`, a comma-separated list of Slack member IDs such as `U0123ABCD`, matched exactly: an email or display name matches nobody. [Slack app setup](/kube-agents/install/slack-app/#allowed-users) says how to find a member ID. The A2A gateway answers a message from a member not on the list once, with a notice naming the member's ID, so an admin can add it. Leaving the list empty allows every member of the workspace (the operator sets `SLACK_ALLOW_ALL_USERS=true` in that case), which in a shared workspace lets anyone there drive the agent.

### Slash commands

The gateway answers no registered slash command; it reads its own two, [`/session`](/kube-agents/concepts/chatops-a2a-gateway/#session) and [`/feedback`](/kube-agents/concepts/chatops-a2a-gateway/#feedback), from the message text ([What the gateway changes on Slack](/kube-agents/concepts/chatops-a2a-gateway/#what-the-gateway-changes-on-slack)).

Until you do, a typed `/hermes <subcommand>` arrives as an ordinary channel message rather than a command. The `legacy_slash_commands` plugin on the Planning Agent profile unwraps that form before the gateway resolves it, so `/hermes sethome` behaves as `/sethome` either way — registering the slashes adds Slack's autocomplete, not the behaviour. The plugin's [README](https://github.com/gke-labs/kube-agents/blob/main/agents/chat/defaults/plugins/legacy_slash_commands/README.md) is the design of record.

`/new` (alias `/reset`) starts a fresh session and history, after the gateway asks the user to confirm. Asking the Planning Agent in words to reset the chat gets that command named back: the agent cannot clear a conversation itself and does not claim to. `/undo` is disabled on this profile, because rewinding the chat reverses nothing a specialist has done.

### Agent view

With `KAGE_SLACK_UX` on, the default (see [Reactions](#reactions) for turning it off), the Slack bot offers three suggested prompts: is anything unhealthy in my clusters right now, what's on the board, and which clusters are behind their release channel. Tapping one sends it as the user's message. Slack shows them when a user starts a new assistant thread or, on an app using agent view, opens the bot's Messages tab. An assistant thread that already exists, a channel mention, and an app whose manifest carries neither view (one generated with `--no-assistant`, or built by hand without them) do not show them. No `PlatformAgent` field replaces the three.

Slack's agent view, where the bot's DM opens on a Messages tab, needs a new manifest, and **the switch cannot be undone**. Once Slack applies a manifest carrying agent view, the app cannot go back to the assistant view it has today. The manifest also replaces the whole app definition, so pass the name, description and long description your app already has; left out, the name and description become Hermes's and the long description is dropped. Drop `--long-description` if your app has none; Hermes refuses one under 175 characters or over 4,000. Run it with the flag on, which is what names the agent view after `--name`; with the flag off it reads "Chat with Hermes in Slack Messages.":

```bash
kubectl exec -n kubeagents-system deploy/platform-agent-gateway -c platform-agent -- \
  hermes slack manifest --agent-view --name "<app name>" --description "<app description>" \
  --long-description "<app long description>"
```

Paste the output into your app's **App Manifest** page in the Slack App Console and reinstall the app when Slack asks. Try agent view on an app nobody else depends on first. The manifest does not subscribe `agent_session_stopped`, so Slack offers no Stop button on a running reply. With the flag off the manifest and the DM are Hermes's own; with it on or off, `hermes slack manifest` without `--agent-view` prints the same manifest and never switches the view.

### Home channel

`SLACK_HOME_CHANNEL` designates the channel an unprompted message lands in when no user thread is involved. Set it to a monitoring/oncall channel your team already watches.

It is optional at install time. The home channel is `spec.integration.slack.homeChannel` on the PlatformAgent, or, with the field empty, the channel the gateway learns from the first mention (below). The operator hands it to the A2A gateway, which posts the agent's proactive messages (alerts, scheduled reports, and the fleet audit's report card) into that channel and nowhere else, as new threads or as replies in them. `/sethome` does not reach it: an allowed member moves it from the app's Home tab (below). The field must be a channel ID (`C...`, or `G...` for a private channel), not a name; with it set to something else the agent posts nothing to Slack unprompted.

Until a home channel exists, the gateway keeps the posts it refused, up to fifty for thirty days, and posts one digest into the channel once one is set. It refuses and keeps them only when no platform on the gateway has a home channel. With Google Chat holding one, Slack's home posts go to Chat until Slack has its own.

With it unset and `spec.integration.slack.homeChannelPolicy` `auto` (the default), the first top-level mention of the agent in a channel makes that channel the home channel. The gateway checks the channel first: not a direct message, not archived, not shared through Slack Connect, and the app a member. It then records the channel in the `<agent>-home-channel` ConfigMap beside the gateway and posts one line in the mention's thread. The operator projects the recorded channel into a file it mounts in the agent pod and the gateway pod; both read it within about a minute, and no pod restarts. Until the learn the PlatformAgent carries the [`HomeChannelUnset`](/kube-agents/operator/platformagent-crd/#status) condition and the installer warns before it applies.

`manual` turns the learn off, so `homeChannel` alone decides. A set `homeChannel` wins over a learned channel; the learned one stays in the record, so clearing the field returns to it. To forget it, delete that ConfigMap: the operator re-creates it empty, the file empties within about a minute, and the next mention learns again. A reply a person types in one of those threads starts a new conversation rather than continuing the investigation that raised the alert.

To move it later, pick another channel on the app's Home tab ([the Slack Home tab](/kube-agents/concepts/chatops-a2a-gateway/#the-slack-home-tab)): the gateway checks the channel as it checks a mention and records it. One line in the new channel names who moved it, one in the old channel says it moved, and both pods follow within about two minutes.

A typed `@bot /sethome` or `@bot /hermes sethome` is answered by the Slack adapter with where to move it, the Home tab, and who may; it moves nothing, learns nothing and starts no task. The mention form reaches the agent: a bare `/sethome` is Slack's own slash command, refused by the client when it is not registered and dropped by the gateway when it is ([moving the app](/kube-agents/install/slack-app/#moving-an-app-made-for-the-hermes-listener) removes the block). Google Chat has no picker: its space field, or the space the gateway learned, decides.

A scheduled brief posts flat in that channel, never inside a thread. A job that wants its output in a thread names an explicit `deliver=` target instead.

### Reactions

The `KAGE_SLACK_UX` flag is on by default. It changes how reactions work, turns on the [buttons](#buttons) below, turns the first inventory report and fleet-audit reports into cards, and changes how the harness's own messages read on Slack (below).

To turn the flag off, add `KAGE_SLACK_UX=false` to the chart value `platformAgent.deployment.env`; [Breaking changes in recent releases](/kube-agents/install/upgrade/#breaking-changes-in-recent-releases) shows the `install.env` line. A hand edit of the CR's `spec.deployment.env` can be lost at the next chart apply. An install that never set the flag has it on, and any value other than `1`, `true`, `yes` or `on` turns it off. With it off the agent follows the Hermes Slack adapter, adding 👀 to your message when it starts and ✅ or ❌ when the turn ends, and nothing else on this page that the flag gates changes.

#### What the reaction means

With the flag on, your message gets a reaction for the kind of ask it is as soon as the agent picks it up, chosen from its words:

| Reaction | Kind of ask              |
| -------- | ------------------------ |
| 🔍       | something to investigate |
| 🌐       | the whole fleet          |
| ⬆️       | an upgrade or version    |
| 💰       | cost                     |
| 🛡️       | security                 |
| 🛠️       | a change                 |
| 📋       | the board                |
| 🚨       | an incident              |
| 👀       | anything else            |

That reaction comes off when the answer posts, and work that succeeded is left with no reaction; work that failed is left with ❌. A turn the agent answers itself settles as soon as it ends.

For work the agent hands to the board, the reaction stays on past the acknowledgement until every card the turn opened for your message has finished, along with any follow-up cards those cards' workers filed in the thread. The ❌ goes on if any of them gave up, stopped on something no agent can do (a block of kind `capability`, such as a cluster that does not exist), or the turn itself failed.

While a card the turn opened waits on you, or a follow-up filed by one that has since finished, ⏸️ joins it, and comes off once you answer. A follow-up that had already given up, or stopped on a `capability` block, when the card above it completed is told in the thread on its own and leaves your message without ❌.

A cancelled turn has its reaction taken off. Work still running when the agent restarts, or a card closed by hand rather than finishing, leaves the reaction on; a card archived by hand counts as finished, without ❌. The agent only ever removes its own reactions, and a reaction it cannot remove stays on.

#### The status message

With the flag on, a thread's board work shows as one status message instead of a progress message per card. The message is a plan with a line for each card, including each card a fanned-out card filed (one per cluster checked for a fleet question, up to ten). Each line shows the card's latest notes and whether it is running, waiting on you, done or failed, edited in place as notes arrive. Waiting on you covers a question, work handed to you for review or sent back for changes, and a card stopped for blocking over and over.

A card's row appears, running, as soon as the card starts work, before its first note; a card that finishes, fails or stops to wait on you before its row appears gets its row then.

A row's title is the card's name until its first note, then the card's latest note while it runs, with a step count once it has more than one, and that note alone if it fails. It reads `waiting on you` while the card waits. Once the card is done, the title is the first line of the card's summary (or of its result, when it gave no summary), or the card's name when it finished without either. In a plan of several cards, each title starts with the card's name. A card's line opens to its latest notes.

A card stopped on something no agent can do (a block of kind `capability`) shows as failed rather than waiting on you. A card you unblock shows as running again, a running or waiting card archived by hand shows as failed with an `Archived` note, and a card the dispatcher retries after a crash or a timeout stays running.

The card's report still posts as its own message when it finishes. The exception is a card beneath one that filed several and is still working in the same thread, such as one per cluster for a fleet question, or the card one of those hands on to the cluster's own agent. Its row carries its result, and the filing card's report, which waits for every card it filed, gives the answer. A filed card that fails or asks you something is told as any other card is.

The thread shows Slack's Working… status while the agent answers any message, which needs slack-sdk 3.44 or later in the image. Once the agent hands your message's work to the board, kube-agents also marks the thread's session as working from the acknowledgement on, between the agent's replies. For a message the agent puts no reaction on, such as a thread reply without a mention, that starts when the first card starts instead. The session is marked paused while the only cards left are waiting on you, and closed once every card has settled.

A plan with no new note or settled card for half an hour is set aside. Its cards still update their rows on it, and the status clears unless one of them is waiting on you. Answering one brings Working… back on that plan. A card silent that long can leave the thread without Working… while it still runs; its next note starts a new plan and brings Working… back.

A set-aside plan with no card waiting on you or failed is dropped four hours after it was set aside, or after a card on it was answered or unblocked (a card settling on it does not extend that). A card on it that settles later still posts its report but no longer updates its row.

When the agent restarts, a card's next note, its settling, or the next liveness signal from a card still running starts a new plan. A card that settles there, other than by being archived, closes the thread's session, or pauses it while the card waits on you, so Working… from before the restart does not stay. It can also clear Working… for another card from before the restart that is still running, until that card's next liveness signal or note. Past 20 cards the oldest finished ones leave the plan first.

A channel thread is titled after its first ask, up to the ask's first question, as a DM thread is titled after its ask. A thread that a crash-looping workload's alert or a drift alert started is titled for it instead, such as `payments-api crashloop in prod-east` or `checkout-gateway HPA drift in prod-east`. If Slack refuses the plan, the thread falls back to a rolling progress message per card until those cards settle, or for half an hour after the last of them goes quiet. A card settling still updates its row on the plan, and Working… holds while those cards run and pauses while they wait on you.

#### Collapsed cards and option buttons

With the flag on, work handed to the board also reads more quietly in Slack. When a card completes, blocks or fails, its rolling progress message (the plan's fallback) collapses to its last line. A completed card's message posts the worker's report, or its summary when there is no report or the report adds nothing to it, without the `✔ … done` head line; a card that finished with neither keeps the head line.

That message leads with its first sentence in bold, code kept as code, and folds the rest under **why**, collapsed; a closing question stays below the fold, as written. A first sentence longer than 150 characters is cut at its last comma, semicolon or spaced dash, or before "due to" or "because", that leaves a headline short enough, and the rest of the sentence opens what follows. A comma before "which", "who" or "that" is not used, since what follows it is no sentence.

In a thread, when the answer ends by asking which of two to five listed options to take, each option gets a button labelled with its bold lead (an "Option 2:" prefix dropped). The one marked "(Recommended)" is drawn as the primary button. Such a question is "Which of these would you like?" or "How would you like to proceed?", not a yes/no question such as "Shall I proceed?" or an open one such as "Anything else?". Its opening paragraph, each option's label and first sentence (when every option has one), and the question stay in sight, and the rest folds under **why**. A click answers with the button's label as your reply in the thread.

When there is one obvious next step instead, the agent marks it for the presenters, and in a thread it becomes a single button under the answer, such as **upgrade plan for seeded-c**. Clicking it, even on an older answer, sends those words as your reply, exactly as typing them would. Options the answer asks you to choose from take the step's place.

The mark is never shown as text: on Google Chat, outside a thread, with the flag off, and wherever no button can be drawn, you read the answer alone. The one exception is a reply streamed into Slack as it is written, which happens only with the agent's `streaming.enabled` setting on: it keeps the mark as its last line, with no button.

An answer that posts whole, as below, still gets the button under it. The exceptions are a report with options to act on, one too long to draw in one message, and one sent where the Slack adapter sends Slack's own markdown blocks or no rich blocks. An answer posts whole, as before, when:

- it is a report with options to act on;
- it opens with a heading, a list, a code block, a quote, a table row or a bold label;
- its first sentence holds a link or a mention, or runs onto a second line, or runs past 150 characters with no such place to cut it;
- its first line ends in a colon;
- nothing follows that sentence;
- the rest holds a horizontal rule;
- it runs past 12,000 characters;
- the Slack adapter is set to send Slack's own markdown blocks or no rich blocks.

A card that blocks, crashes, times out or gives up posts no line of its own (except a question, below) once the wake asking its creator to explain it has been queued. The agent that created the card then tells the failure; for work you asked for, that is the Planning Agent. If that wake fails, the card's own failure line posts instead, and a wake that then succeeds on a retry tells the failure a second time. A failure line still waiting on its wake when the same card recovers (it completes, hands off for review or is moved to done) is dropped, so it never lands beneath the recovery.

The agent's reply to that wake opens with its first sentence in bold. When it ends on one short yes/no question, such as "Check it there?", a **Try again** button follows it (an open or either/or question stays text). Clicking it sends "Try again" as your reply in the thread, and the message is rewritten to name who clicked. When the reply marks its next step, that step is the button instead, such as **check seeded-a**, whatever the question. The reply posts as written if the agent restarts between the wake and its reply; outside a thread the question stays text, and a step the reply marks is not shown.

Six gaps remain, each leaving the failure untold, and the last three are logged:

- a queued wake that is lost to a restart or an interrupt before the Planning Agent answers;
- a restart between the card failing and the wake being queued;
- the card's notifications stopping, after repeated failed posts or a sweep of stale subscriptions, before the wake is tried;
- a failure line whose post keeps failing;
- a held line dropped because too many cards are holding lines at once;
- a held line dropped because the card recovered, when the wake after it never succeeds.

The lines a card does post name the agent working it when the card has one, such as `@platform`, without the board name or the card's id. Other platforms are unchanged.

#### Pull-request and blocked-card moments

Two moments get a message of their own with the flag on.

When a card opens a pull request on GitHub, or a merge request on gitlab.com or on the GitLab host of your GitOps repository or one of your managed repositories, the thread gets it beside a green side bar. The message has **Open PR** (**Open MR** for a merge request) and **Files changed** buttons, once per pull or merge request in each thread, until the agent restarts.

It is posted as soon as the card's worker opens it, whatever the card goes on to say about it, under the pull request's title. When the worker's line naming it reaches the thread in the same update, it is posted under that line instead. A pull request opened outside a card's work, such as by a scheduled audit, is posted only when a progress note or report says it was opened.

When a card blocks because it needs something from you, its question posts in place of the blocked line, beside a yellow side bar, with up to 2,000 characters of its detail and a "waiting on you" line. A first line longer than 150 characters shows only its first sentence in bold, and the rest of the line opens the detail. A first sentence too long as well is cut. A statement is cut as an answer's is, or at a word when it has no place to cut. A question is cut at a word, ending in "…" where the detail resumes, so it still reads as a question.

The cut never falls inside a link. Code, bold or italic it falls inside is closed in the bold line and reopened below. When a long code span or link would leave only a few words in bold, the cut moves into the code span or past the link. No part of the question shows twice; a link in the bold line shows its label there, and the link itself opens the detail on a line of its own. The note that wakes the Planning Agent tells it the question is already posted so that it need not ask it again.

A question that ends with two to five short options, right after a line ending in a question mark, gets a button for each. The exception is a line whose last sentence is a recognised go-ahead ask ("Shall I proceed?", "Sound good?") and offers no choice with "which" or "or": that list is the plan and stays as text. A go-ahead ask in other words ("Should I apply it?"), or one after a comma, dash or another question ("Here's the plan, sound good?"), is not recognised, and its list gets buttons. Any other shape of question keeps its options as text, as does a question outside a thread, since a click answers in the thread it was clicked in.

Clicking one answers as if you had typed it as your reply in the thread, with the card's name added while the agent still holds the question (after a restart the click answers with the label alone). It runs as your message and passes the same user and channel checks a typed reply does, so a user the adapter would not answer changes nothing by clicking. A click never needs an @-mention.

A typed reply in the thread needs one only where the Slack adapter is set to require a mention in threads, or, in a channel that requires a mention, to ignore every message without one. Where it is set to ignore a message addressed to someone else, a typed reply that opens by mentioning another person is ignored unless it also mentions the agent.

The Planning Agent still takes your answer back to the card; the question's text also names the card, so a typed reply that starts a new conversation with the agent still finds it. Once the card moves on the buttons and the "waiting on you" line come off the question, however you answered; a restart in between leaves them on it.

In a thread, the question then shows who answered and what (`✓ <name>: <answer>`, your Slack display name, else your real name or handle, in plain text, never an @-mention). A click leaves that line at once, and a typed reply leaves it with your reply's first words, less any mention of the agent it opens with, once the card resumes. One reply answers one question, so where two cards ask in one thread, the reply goes to the first card to resume. A card archived, finished or given up without resuming loses its buttons without the line.

In a thread, the Planning Agent posts nothing after carrying your answer to the card, unless carrying it fails, when it says so. A card stops on a question with options when you ask to choose yourself, such as "give me two or three ways to fix it and ask me which one"; otherwise it answers with the fix it recommends. With the flag off, and on Google Chat, the card's blocked line posts and the agent's reply to it asks the question.

### Buttons

#### Alert buttons

With `KAGE_SLACK_UX` on, the alert for a crash-looping workload reads as one line on Slack, such as "🚨 **payments-api in prod-east keeps crashing.** Looking now."; alerts for other reasons, and alerts on other platforms, read as before. An incident's triage edits its alert in place instead of replying under it. The alert becomes a one-line headline, then a button per proposed option showing its title, with the recommended one highlighted and marked "(recommended)", and a button for each console link on the report's 🔗 line. The report, up to its first horizontal rule, is folded underneath.

A drift alert's triage adds a line under the headline saying what changed, who changed it and when, and marks the recommended button by its highlight alone. Its usual buttons are **Put Git's version back** and **Keep it · update Git**, each of which opens a pull request, and its fold is titled **diff**, since the report opens on the changed field's value before and after.

Clicking an option answers as if you had replied in the thread yourself with `apply Option B: <its title>`, or `apply: <its title>` when there is a single fix. The agent replaces the option buttons with a line such as "✓ <your name>: <its title>", your Slack name in plain text (or, if Slack refuses that edit, posts that line in the thread). Your reply passes the same user and channel checks a typed reply does. A click never needs an @-mention.

A typed reply in the alert's thread needs one only where the Slack adapter is set to require a mention in threads, or, in a channel that requires a mention, to ignore every message without one. Where it is set to ignore a message addressed to someone else, a typed reply that opens by mentioning another person is ignored unless it also mentions the agent.

A later click runs nothing if someone the agent answers has already replied in the thread since the options appeared with `apply`, `apply B` or `apply Option B`. The letter is one the alert offers, when its options are lettered, and a please or thanks after the command does not change that. The same holds for a reply of `apply Option B: ` and that option's title, whole or clipped as the button shows it. The option buttons are then replaced with a line saying the alert was answered in the thread; link buttons stay.

The report arrives as a threaded reply as before when:

- it does not parse into options;
- it is a second report in the same thread;
- it is too long to fold;
- it has a table above its first horizontal rule, or a horizontal rule above its headline, options or links;
- Slack refuses the edit.

#### Stuck-task report buttons

The daily stuck-task report shows a **Retry** and a **Drop** button under each task it names. Retry sends the task back to the board to run again, and Drop archives it. Either acts only on a task that is blocked when you press it. A button on an older post leaves alone a task that has moved on since, but acts on one that has blocked again. Anyone the agent answers may press them. The task's row then reads "✓ Retrying." or "Dropped.", followed by who pressed and when. A press acts on the board directly and never starts an agent turn.

On Google Chat, the report shows the same buttons. Google Chat draws every button under the message, so the report numbers its tasks and labels each button with the task's number: "Retry 1" and "Drop 1". The task's line then ends with "✓ Retrying." or "Dropped.", who pressed, and the time in UTC. A press that did not land keeps the buttons and says so on the line.

### Files a card produced

The gateway does not attach a file the card names in its `artifacts` list ([What the gateway changes on Slack](/kube-agents/concepts/chatops-a2a-gateway/#what-the-gateway-changes-on-slack)); the agent still has to declare the file for it to leave the sandbox. Its terminal and file tools run in a separate sandbox pod, so a file it writes is on a volume the gateway cannot read. Only the paths the `artifacts` list names are copied across to the gateway for delivery, and only for as long as the delivery takes.

Four ceilings apply to that copy: 8 MiB per file, 16 files per card, 16 MiB across the card, and a two-minute deadline for the lot. A file that exceeds one is skipped with a warning in the gateway log while the rest of the card still delivers. Paths under the sandbox's credential and system directories are refused outright. [`agents/platform/scripts/sandbox_artifact_patch.py`](https://github.com/gke-labs/kube-agents/blob/main/agents/platform/scripts/sandbox_artifact_patch.py) holds the limits and the denied prefixes.

### Harness messages

With `KAGE_SLACK_UX` on, the harness's own messages stay out of the way on Slack. Scheduled reports arrive without the `Cronjob Response` header, job ID and footer. The long-turn heartbeat, if it is enabled for Slack, says the agent is still working without naming the tool running. The agent does not announce that it is back after a restart, post the session-database warnings (the error stays in the log), or append Hermes' tip about its queueing setting.

Its replies about restarting, shutting down, stopping, being busy with an earlier message, a command sent while it is working, or a `/steer` it could not take are written plainly in its own voice. They carry no console commands or error text, and its replies about the model provider failing or turning a request down read the same way. That covers the English replies; an install set to another display language gets Hermes' translation of the restart and stop replies. Other chat platforms are unchanged, and with the flag off nothing changes.
