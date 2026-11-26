---
title: Why kube-agents
description: What platform teams are measured on, why home-built SRE agents stall, and how always-on fleet care complements coding agents.
---

Platform teams run more clusters every year with the same headcount. `kube-agents` is an open-source GKE operations teammate that runs inside your environment around the clock, audits your fleet against Google-maintained skills, and proposes every fix as a pull request your team reviews.

## Three goals platform teams are measured on

1. **Keep production healthy.** Reliability, security, and cost problems are often found after they reach users or the bill. `kube-agents` checks every cluster against 25+ upgrade-readiness rules and watches drift, stalled controllers, crash loops, security posture, and capacity continuously.
2. **Developer velocity.** Developers normally file tickets and wait on the platform team for routine requests. With `kube-agents`, they ask in chat — why a pod is failing, how to scale a service, or how to right-size requests — and get a grounded answer or a pull request to approve. Larger changes, such as a new node pool, come back as Terraform pull requests for the platform team.
3. **Team efficiency.** Skilled engineers spend hours on entry-level toil: security patches, routine checks, and repeat questions. `kube-agents` takes on the repetitive inspection and PR drafting so each engineer can cover more clusters.

Underneath all three goals is a single foundation: your team stays in control. `kube-agents` is read-only in your clusters, keeps credentials in an isolated broker, and routes every production change through your GitOps review process.

## Why home-built SRE agents stall

Connecting an LLM to Slack or Google Chat is easy. Keeping an operations agent safe and useful in production is hard for three reasons:

- **Production safety.** One bad command can take down a cluster, and an automated agent can run it fast. `kube-agents` enforces wire-level read-only Kubernetes access (with Secrets redacted), runs commands in a credentialless shell sandbox, and proposes every fix as a reviewed pull request.
- **Keeping know-how current.** GKE APIs, release channels, and best practices change constantly. A home-built agent's prompts go stale unless a team maintains and tests them. `kube-agents` ships 70+ GKE skills kept current in the open and gated by hands-on failure exams (`devops-bench`) on every release.
- **Accountability.** Engineers are accountable for production uptime. `kube-agents` never applies changes behind your back and attaches the exact reproducible read commands to every finding so your team can verify every claim.

## Urgent care vs. preventive fleet care

Teams often ask why an always-on cluster agent matters when engineers already use IDE or CLI coding agents (such as Antigravity or Claude Code). Think of the two as **urgent care** and **preventive care**: they solve different halves of operations and work best together.

| Dimension | Coding agents (urgent care) | `kube-agents` (preventive fleet care) |
| :--- | :--- | :--- |
| **When it runs** | On-demand sessions triggered by an engineer for an incident, ticket, or feature; stops when the session closes. | 24/7 inside your cluster across 10 scheduled watchdogs, 30-minute stall sweeps, and live event triage. |
| **State and memory** | Scoped to the active branch, pasted logs, and current window. | Longitudinal fleet record: standing audit ledgers, peer-cluster drift baselines, upgrade retros, and curated team decisions in Git. |
| **Security boundary** | Usually runs with the engineer's workstation shell, local `kubeconfig`, and personal Git tokens. | Isolated read-only Kubernetes proxy (Secrets redacted), credentialless sandbox, short-lived KMS tokens, PR-only writes. |
| **Primary strength** | Inner-loop code authoring, refactoring, and acute break-fix. | Continuous GKE fleet checks tested across 70+ skills and 13 operational benchmark domains. |

**Better together via MCP:** Engineers can keep using their preferred IDE or CLI coding agent and connect it to `kube-agents`'s opt-in read-only A2A MCP endpoint (`A2A_MCP_DOOR=true`, over port-forward with no forge credentials). Local tools can request fleet diagnostics and inspect PRs without standing cluster write access. See [Using kube-agents over MCP](/kube-agents/install/mcp/).

## What installs on your cluster

`kube-agents` installs into a single `kubeagents-system` namespace and co-exists alongside other workloads on an existing GKE Standard or Autopilot cluster (no dedicated cluster required):

- **Kubernetes operator (`k8s-operator/`)** — reconciles `PlatformAgent`, `AgentProfile`, `AgentPlugin`, `AgentSchedule`, and `Tier` custom resources.
- **Agent runtime** — hosts the **Planning Agent** (chat front door and router), the **Platform Agent** (fleet audits, GitOps PRs, and skills), and per-cluster read-only **Cluster Agents** (single-cluster runtime debugging).
- **Inference gateway (`LiteLLM`)** — one in-cluster OpenAI-compatible endpoint so you can switch models (Gemini, Claude, GPT, SAP AI Core, or self-hosted Gemma) in config without changing agent code.
- **Security and A2A stack** — NATS JetStream message bus, A2A chat gateway (Google Chat, Slack, Microsoft Teams, Web Console), `k8s-api-proxy` (read-only enforcement), Envoy credential broker, and Minty (Cloud KMS short-lived GitHub App token minter).

## Where to go next

- [Architecture](/kube-agents/overview/architecture/) — request flows, pod topology, and deployment footprint.
- [Models, cost, and BYOT](/kube-agents/overview/models-and-cost/) — supported model providers and typical token spend per task.
- [Trust, security, and autonomy](/kube-agents/overview/trust-and-autonomy/) — read-only boundaries, 13-domain exams, earned autonomy ladder, and two-layer memory.
- [A day with kube-agents](/kube-agents/overview/day-in-the-life/) — from hour-one scan to day-one audits and pull requests.
