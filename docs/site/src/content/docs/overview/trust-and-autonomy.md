---
title: Trust, security, and autonomy
description: Read-only cluster boundaries, hands-on exams across 13 GKE domains, two-layer memory with a pre-push outage guard, and the earned autonomy ladder.
---

Trusting an operations agent with a production fleet requires enforced boundaries, repeatable testing, and human approval. `kube-agents` builds trust across four layers: enforced security isolation, release-gating exams, curated memory, and graduated autonomy.

## 1. Read-only by design, never acts alone

- **Workload Identity, no static cluster keys.** Runs under Google Cloud IAM Workload Identity using short-lived tokens.
- **Wire-level read-only Kubernetes access.** Configured with read-only cluster roles and fronted by `k8s-api-proxy`, which blocks mutating verbs and redacts `Secret` values before the agent sees them.
- **Credentialless shell sandbox.** Model-authored commands run inside a gVisor-sandboxed pod that holds no API keys or Git tokens. An isolated Envoy credential broker injects short-lived Cloud KMS-signed forge tokens at the network boundary.
- **GitOps-only production changes.** Every fix arrives as a peer-reviewed pull request on GitHub, GitHub Enterprise Server, GitLab, Bitbucket (Cloud or Data Center), or Gitea. The broker exposes no merge operation, so your team merges and your GitOps controller applies.

For the exact enforcement boundary on Kubernetes RBAC, GCP IAM, and GitOps, see [What the agent can and cannot do](/kube-agents/reference/security-and-iam/#what-the-agent-can-and-cannot-do).

## 2. Tested like a certified engineer on every release

Rather than relying on static prompts, `kube-agents` is tested against real GKE failure scenarios planted in test clusters using [`devops-bench`](https://github.com/gke-labs/kube-agents/tree/main/bench), an open-source Kubernetes benchmark.

- **All 13 operational domains gate every code change.** Blocking presubmit exams cover reliability, debugging, incident triage, remediation, upgrades, security, capacity, cost, fleet audits, consistency, observability, source control, and chat routing (`docs/designs/domains.yaml`).
- **Any cluster mutation fails the exam.** Evaluation cases assert that the agent diagnoses and proposes fixes without mutating cluster state directly.
- **Reproducible by your team.** The exam tasks live in the public repository. You can re-run them yourself or add private tasks that mirror your own fleet.

## 3. Earned autonomy over time

:::note
The ladder below describes the **earned autonomy roadmap direction** we are building toward, not all levels shipping today. Today's releases operate at **New hire** (read-only audits and explanations) and **Junior** (GitOps pull requests reviewed and merged by your team).
:::

Like a new member of your platform team, `kube-agents` starts by watching and explaining, and takes on more responsibility only as it passes exams and proves itself in your clusters. You choose the level per workflow and can lower it at any time.

| Level | Status | What `kube-agents` does | What your team still does |
| :--- | :--- | :--- | :--- |
| **New hire** | **Available now** | Watches clusters, runs 25+ upgrade rules and fleet audits, and explains root causes in chat. Changes nothing. | Writes and merges all changes. |
| **Junior** | **Available now** | Drafts manifest and Terraform fixes as GitOps pull requests with reproducible evidence, and checks results after merge. | Reviews and merges every pull request. |
| **Senior** | **Roadmap** | Tests fixes in a staging space you designate, then watches the production rollout with a revert ready. | Approves one merge with staging test results in hand. |
| **Expert** | **Roadmap (admin-granted)** | Hands admin-pre-approved fix classes to your CI/CD with automatic rollback. Never earned by exam; revocable at any time. | Sets policy bounds and audits outcomes. |

## 4. How `kube-agents` remembers

Operations knowledge usually disappears into old tickets and chat threads. `kube-agents` uses a **two-layer memory architecture** (shipping in v0.39.0, opt-in via `--memory=file` or `--memory=hindsight`):

- **Layer 1 — Personal chat memory.** Remembers each engineer's formatting preferences and local context in direct messages, strictly isolated per verified user identity.
- **Layer 2 — Curate-as-Code decisions and lessons.** Stores architectural decisions (`knowledge/decision/DEC-*.md`) and operational lessons (`knowledge/lesson/LES-*.md`) in your GitOps repository via human-reviewed pull requests. Tracks post-merge soak outcomes and closed/rejected PRs so the agent does not repeat rejected proposals.
- **Deterministic pre-push outage guard (`<100ms`).** Before pushing any branch, the credential proxy evaluates active decision-memory assertions deterministically with zero LLM calls, preventing new PRs from undoing protective outage fixes.

## Where to go next

- [Security & IAM](/kube-agents/reference/security-and-iam/) — full RBAC, IAM, and enforcement matrix.
- [Credential isolation](/kube-agents/reference/credential-isolation/) — how the sandbox, Envoy broker, and Minty separate execution from secrets.
- [Skill catalog](/kube-agents/skills/) — all 70+ GKE skills grouped by operational domain.
