---
title: Web Console
description: A browser page for the agent on installs with no chat platform, laid out as channels and threads, reached through kubectl port-forward.
sidebar:
  order: 9
---

The web console is a browser page for the agent that runs inside the cluster. It is for installs where Slack or Google Chat is not set up yet, such as an evaluation cluster, a workshop seat or a demo. It is off by default.

## The layout

The page has a rail on the left, a centre pane, and a right pane you can close. A banner above the two panes shows the model, the token and cost counters, and the cluster.

The rail lists two channels and your threads:

- `# alerts` has one post per Kubernetes warning event the agent triaged. Each post is an event triage session the event watcher opened.
- `# scheduled` has one post per scheduled check the agent ran.
- **Threads** are your own conversations with the agent. **New chat** starts one.
- **Chat** lists Slack and Google Chat sessions by title. It appears only when there are any, and its rows cannot be opened.

A channel shows its 50 most recently active posts, with the most recent at the bottom. Each post shows its subject, the agent's latest reply, the reply count and when it was last active. For an event triage post, the subject is the card title the triage prompt names, such as `Triage shop/Pod/web-7 (BackOff) on prod`. The reply count covers the session's newest 50 messages, so on a longer session it is a lower bound. If you scroll up and a post arrives, a **New posts** button appears instead of moving the feed.

**View thread** opens the post's session in the right pane. You can reply there. The reply goes into that session, and the agent answers in it. **About this agent** opens in the same pane. It shows the model, the cluster, the agent's Kubernetes service account, and the Google Cloud service account and project roles it was granted.

## Threads

Each thread is one agent session. A message you type reaches the Planning Agent, the same front door a Slack or Google Chat message reaches. It answers directly, or it files a kanban card and hands the work to the Platform Agent. A turn that calls tools can take several minutes, and the console waits up to five minutes for a reply. When the agent proposes a change, it opens a pull request, as it does from any other chat surface.

Several threads can run turns at once. You can send in one thread and switch to another while it works. A thread's title is its first message.

Work handed to a card finishes after the turn's reply is already on the page. The card's result lands on the same session as a new message. One loop checks every thread for new messages every ten seconds. A result for the thread on screen appears tagged `update`. A result for another thread gives that thread an unread dot in the rail.

The thread list is kept in the browser's local storage. It survives a reload and is shared by the tabs of that browser. It holds at most 12 threads and drops the least recently used. Removing a thread with its × button removes it from this list only; the agent keeps the session. Threads opened in another browser are not listed.

## Live status

While a turn runs, a single line under it shows what the agent is doing: thinking, running a named tool, or writing the reply. The line appears in the pane where you sent the message. It shows the tool name and a short preview at most. Tool arguments and tool output stay on the server.

The page reads the line from `POST /api/chat/stream`, which relays the agent's event stream. If that route is missing, as on an older console, the page uses `POST /api/chat` and shows a plain "working" line until the reply.

## Unread counts and notifications

The rail shows an unread count for each channel and bolds a thread with news. A post counts as unread when it is new or has more messages than when you last saw it. Seen state is kept per post in local storage. On a first visit, every existing post is marked seen. The page title shows the total, for example `(3) kube-agents`.

The page sends browser notifications for new `# alerts` posts only after you click **Turn on notifications** in the rail. It never asks for permission on its own. It notifies only while the tab is in the background. Each check sends at most three post notifications, plus one that counts the rest.

## The banner

The model and provider come from the chart's LiteLLM settings at install. The token and cost counters are read from LiteLLM's own metrics, so read them with these limits in mind:

- The counters reset when a LiteLLM pod restarts. The banner says "since LiteLLM last restarted".
- They are summed across LiteLLM replicas. The console finds the replicas through a headless Service and reads each one. When a replica does not answer, the banner says how many it read, for example "1 of 2 replicas", and the total is low.
- The cost is LiteLLM's estimate from its own price table, not your bill.
- An install without LiteLLM shows "Not available".

## Agent identity

The identity in **About this agent** is recorded at install. The Terraform composition passes the Google Cloud service account and the project roles it granted into `webConsole.agentIdentity`. The console does not read IAM. A role granted or removed later is not shown until the next install or upgrade updates the values.

## What it does not show

The Hermes gateway API does not expose the kanban board or a session's place in the work queue. The console cannot show which cards are open, who holds them, or how long a turn will wait. Ask the agent in a thread instead.

## Replies into agent sessions

A reply from the right pane names the event triage or scheduled session itself. Before the turn, the console looks the session up in the agent's session store. It accepts it only when the session was created through the gateway API and its title is the one the event watcher or the scheduler gives it. The console never creates or recreates such a session. A session the agent has no record of is refused with a 404. A Slack or Google Chat session is refused with a 403, and so is any other caller's.

## Privacy

The console reads the text of event triage sessions, scheduled checks, and its own threads. An event triage session can include replies people posted in the Slack or Google Chat thread where the alert went, because those replies continue the same session. Anyone who can open the console can read them. The console never reads the messages of a session that started in Slack or Google Chat. It lists those by title only, and Hermes writes most titles from a session's first exchange, so a title can summarize what someone asked.

This does not widen access much. Opening the console takes `pods/portforward` on the install namespace. The built-in `edit` and `admin` roles that grant it also grant `pods/exec`, which reads the agent's session store directly.

## How it is reached

The console is reachable through `kubectl port-forward` and no other way. The chart renders its Service as `ClusterIP`, and a NetworkPolicy refuses every connection to the console pod from the pod network. The policy takes effect only on a cluster that enforces NetworkPolicy, which clusters the installer creates do. A port-forward enters from the node, which NetworkPolicy does not govern. In practice, whoever holds `pods/portforward` on the install namespace can use the console.

The console holds the agent's API key, from the same Secret the agent reads, and attaches it to the requests it sends the agent. The key does not reach the browser. There is no login page and no per-user identity: every turn reaches the agent as the console. A port-forward carries no identity of the person behind it, so the page cannot show who is signed in.

Do not expose the console through a LoadBalancer, an Ingress or a NodePort. Anyone who could reach it would be able to drive the agent. The chart does not offer a way to change the Service type, and apart from its health check the console refuses any request whose `Host` is not `localhost`, `127.0.0.1` or `::1`.

## Turning it on

Pass `--enable-web-console` to the installer, on a new install or a re-run of an existing one:

```bash
./install.sh --enable-web-console
```

On a first install, the installer writes the choice into the `install.env` it creates, as `WEB_CONSOLE_ENABLED=true`, so later runs keep it. The installer never rewrites an existing `install.env`. On a re-run, the flag applies to that run only, and the installer warns you: set `WEB_CONSOLE_ENABLED=true` in `install.env` yourself, or the next `install.sh`, `upgrade.sh` or `--menu` run removes the console again. `--enable-web-console=false` and `WEB_CONSOLE_ENABLED=false` turn it off. If you drive the Terraform composition in `terraform/examples/full-install` directly, set `web_console_enabled = true`.

The console needs the Platform Agent; the chart refuses to render it on an install with `platformAgent.enabled: false`. Its image follows the agent's image tag and the install's image registry, so a mirrored install pulls it from the mirror.

When the install finishes, the installer prints the command to reach the console. Its Service is `kube-agents-web-console` in the install namespace, `kubeagents-system` by default:

```bash
kubectl port-forward -n kubeagents-system svc/kube-agents-web-console 8080:8080
```

Then open `http://localhost:8080`. Both commands assume the chart's default `webConsole.service.port`, 8080. The console pod does not run under gVisor, so this works on a sandboxed install as well.

## Routes

The page uses these routes. All of them answer only a loopback `Host`.

| Route                                | What it returns                                                                                                                        |
| :----------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /api/channels/{name}/posts`     | The 50 most recently active posts of `alerts` (event triage) or `scheduled` (scheduled checks), with summaries. Any other name is 404. |
| `GET /api/sessions/{id}/transcript`  | The newest 200 text messages of an event triage, scheduled or console session. Any other session is 403.                               |
| `GET /api/sessions/{id}/messages`    | New messages on one of the console's own sessions, after a given message ID.                                                           |
| `GET /api/sessions/recent`           | The agent's 20 most recent sessions with their kind. The rail's Chat section reads it.                                                 |
| `GET /api/status`                    | Whether the console can reach the agent gateway. The top bar's badge reads it.                                                         |
| `GET /api/insights`                  | The model, the LiteLLM counters, the identity recorded at install, and the cluster.                                                    |
| `POST /api/chat`, `/api/chat/stream` | One turn, as a single reply or as a stream of status lines then the reply.                                                             |

## What to expect when something is wrong

The badge in the top bar shows whether the console can reach the agent. It reads "Agent unreachable" while the agent pod is starting. A failed turn shows its error in the pane that sent it, including the agent's own message when the agent returned one. The console does not fall back to answering from the model directly, so every reply in the page came from the agent: the Planning Agent's answer, or the result of a card it handed to the Platform Agent.

Each session takes one turn at a time. If you send a second message in a thread before the first has been answered, the console refuses it. Wait for the reply, or use another thread.
