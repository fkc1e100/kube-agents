---
title: A day with kube-agents
description: How teams adopt kube-agents from hour one to ongoing delegation, plus three end-to-end operational scenarios and live Web Console demos.
---

## From install to part of the team

At first `kube-agents` talks to you; over time your team talks back and hands it work, the way you onboard a new teammate.

| Stage | What happens |
| :--- | :--- |
| **Hour one — It scans and finds something** | Install with one guided command in read-only mode. Its first scan ranks findings across your fleet so the first thing your team sees is a real issue worth fixing. |
| **Day one — It talks to you** | First-run audits (cost, compliance, capacity, and upgrade history) post a ranked report in chat. If a GitOps repo is connected, fix PRs open automatically for the most severe manifest findings (at most five per run). |
| **First weeks — You talk back** | Engineers ask follow-ups, approve or close PRs, and tell it what matters. Team decisions go into curated Git memory; formatting preferences stay in private personal memory. |
| **Over time — You hand it work** | Developers and operators ask directly in chat or the Web Console to scale a service, add a node pool, or explain a failing pod. Every ask comes back as a grounded answer or a pull request to review. |

Want to watch real cluster walkthroughs? See the six live [Web Console demos](/kube-agents/deploy/web-console/) covering reliability, capacity, security, GKE upgrades, cost right-sizing, and Argo CD fleet drift.

Each scenario below follows one trigger to the chat messages, issues, and pull requests it produces. Names such as `shop`, `checkout`, `redis`, and `prod-east` are placeholders.

## A scheduled audit finds an exposed database

Earlier in the week, someone edits the manifest of the `redis` Service in your GitOps repository to `type: LoadBalancer`, to reach it from a laptop, and your GitOps tool applies it to namespace `shop` on cluster `prod-east`. Nothing objects: the load balancer gets a public address and the Service is healthy. The same namespace also runs a `checkout` Deployment with `securityContext.privileged: true`.

At 06:20 UTC the next day, the `compliance-audit` job (Security & RBAC Posture Audit) runs on the Platform Agent. The audit is read-only and covers every cluster in the install's scope. Two of its checks fire, and both are `critical`. `lb-world-open` flags the Service, because it publishes port 6379 to the internet with no `loadBalancerSourceRanges` and no internal load balancer annotation. `privileged-container` flags the Deployment.

The run publishes to the GitOps repository:

- One ledger issue, `[audit] Security & RBAC Posture Audit (platform-agent-host) — 2 findings (2 critical)`, with the labels `agent:audit`, `audit:compliance-audit`, `audit-scope:platform-agent-host-…` (this install's) and `severity:critical`. Each finding carries the command that produced it, so a reviewer can run it again.
- One remediation pull request for the Service, titled `fix(compliance-audit): <finding title>`, on a branch that starts with `platform-agent/fix-compliance-audit-`. It edits the Service's own declaration. The run opens pull requests unasked, at most five per run, only for findings whose fix is a manifest change. These are `critical` findings, and `major` findings on `unbound-sa-automount`. If a fix can break something the audit does not see, it waits in the ledger for `/remediate`.

The privileged container gets no pull request. Its fix is `manual`, because dropping privilege can break a workload that needs one capability, so the ledger gives the steps and the owner decides. The harness opens pull requests and never merges them ([what the agent can and cannot do](/kube-agents/reference/security-and-iam/#what-the-agent-can-and-cannot-do)).

Chat gets a short report on every enabled platform. The card shows the headline "Security & RBAC Posture Audit: 2 critical findings", lists up to ten critical findings, and links to the ledger issue ([Proactive alerts](/kube-agents/concepts/chatops-proactive-alerts/)). Replying in that thread reaches the Planning Agent with the report attached.

The next morning nothing has changed, so the run rewrites the ledger quietly and stays silent in chat. Once a reviewer merges the PR and your GitOps tool applies it, the next run marks **1 resolved** and updates the ledger title. When both findings clear, it closes the ledger as completed.

On a new install, this audit runs once right after the initial fleet scan without waiting for its schedule. The weekly cost audit (`fleet-wide-cost-analysis`) works the same way, reporting orphaned volumes, unattached disks, idle IPs, and over-requested workloads. See [Reference → Cron jobs](/kube-agents/reference/cron-jobs/) for every schedule.

## A crash loop becomes a root cause and a pull request

A config change rolls out to the `checkout` Deployment in namespace `shop` on cluster `prod-east`, and the new pods start crashing. The event watcher forwards persistent `BackOff` warnings once a pod fails three times over two minutes; transient blips are ignored.

`kube-agents` posts a short alert in chat and files a card for the `prod-east` Cluster Agent. The Cluster Agent verifies its `kubeconfig` targets `prod-east` and runs read-only diagnostics (`describe`, logs, events).

It returns a structured report with three sections — "What's wrong", "Why", and "What to do" — showing, for example, `OOMKilled` against the manifest's memory limit. When multiple fixes exist, it presents lettered options with one recommended, and asks the engineer to reply `apply` (or `apply Option A`).

An engineer replies `apply` or clicks the recommended button. The Platform Agent runs `submit-suggestion`, edits the Deployment manifest on a `platform-agent/` branch, and opens a pull request (or merge request on GitLab). Nothing is written directly to `prod-east`; your team merges and your GitOps controller applies the fix.

If a reviewer wants changes, they comment `/agent ...` on the pull request and the Platform Agent amends the same branch. For full alert triggers, deduplication, and daily rate limits, see [ChatOps: Proactive alerts](/kube-agents/concepts/chatops-proactive-alerts/).

## A developer asks why a deployment is stuck

In a Slack direct message to the bot, a developer writes "why is my checkout deployment stuck in Pending?". The message gets a 🔍 reaction, picked from its words with no model call. Every chat message reaches the Planning Agent first, and it has no cluster tools. It replaces "my" with the cluster the developer stored in personal memory earlier, here `prod-east`. It files a card for the `prod-east` Cluster Agent and replies with one line, such as `checking checkout.`

The Cluster Agent runs its preflight check, then reads the pods, the namespace events and the Deployment. For a Pending pod, its troubleshooting skill goes to the namespace events and their `FailedScheduling` message, for example `Insufficient memory`. Progress shows in the thread while it works. When the card completes, the gateway posts the Cluster Agent's full result in the thread: the cause, the evidence and a proposed manifest change. On Slack, the first sentence usually leads in bold, with the rest in a folded "why" section. No pull request opens, because the developer asked a question.

The developer replies "open a PR with that fix". The Planning Agent files a card for the Platform Agent, which opens the pull request through `submit-suggestion`. On Slack a separate message shows the pull request with Open PR and Files changed buttons. The credential broker refuses kubectl and gcloud commands that change state, for every agent in the pod, so the pull request is the only change ([Security & IAM](/kube-agents/reference/security-and-iam/#what-the-agent-can-and-cannot-do)).

Personal memory works only in a direct message; in a channel, the Planning Agent asks which cluster. On Slack, reactions, buttons, the progress plan message and the folded answer need `KAGE_SLACK_UX` on, the default. On Google Chat the gateway lays out the agent's answer and its cards' plan and report, buttons included, and keeps one status line per task. A cluster with no Cluster Agent yet gets one from the hourly reconcile at minute 11; until then the Platform Agent investigates it itself.

With no chat platform, use the A2A console's chat pane, the Hermes CLI in the agent pod or the [admin console](/kube-agents/reference/admin-console/) ([User interfaces](/kube-agents/reference/user-interfaces/), [ChatOps → When no chat platform is enabled](/kube-agents/concepts/chatops/#when-no-chat-platform-is-enabled)).

Without kube-agents, the developer needs cluster credentials, reads the scheduler events, matches the message to the requests in the manifest, and edits the manifest. A developer without that access waits for someone who has it.

## Where to go next

- [Proactive autonomy](/kube-agents/overview/proactive-autonomy/) — every scheduled audit and what it checks.
- [ChatOps](/kube-agents/concepts/chatops/#proactive-alerts-both-channels) — how alerts and replies work on each chat platform.
- [Declarative workflow](/kube-agents/concepts/declarative-workflow/#the-fleet-audit-skill) — ledger issues and remediation pull requests.
- [Security & IAM](/kube-agents/reference/security-and-iam/#what-the-agent-can-and-cannot-do) — what the agent can and cannot change.
