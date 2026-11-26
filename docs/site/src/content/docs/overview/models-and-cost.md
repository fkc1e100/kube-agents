---
title: Models, cost, and BYOT
description: Apache 2.0 open source ($0 license), GKE Standard or Autopilot co-existence, Bring Your Own Tokens (BYOT) providers, and modeled token spend per task.
---

`kube-agents` is free, Apache 2.0 open-source software with no license fee, seat charge, or token markup. You pay only your normal GKE compute costs and the model tokens you consume on your own provider account.

## Zero license fee, co-exists on any GKE cluster

- **$0 software license.** Apache 2.0 open source on GitHub.
- **No dedicated cluster required.** Installs into an isolated `kubeagents-system` namespace with NetworkPolicy and least-privilege Workload Identity, and co-exists alongside your workloads on an existing GKE Standard or Autopilot cluster.
- **Bring Your Own Tokens (BYOT).** Every agent calls one in-cluster gateway (`Service/inference-gateway`, backed by LiteLLM). You pick a provider at install time and can switch later in config with no cluster reinstall.
- **Direct billing and guardrails.** Usage bills directly to your Google Cloud, Anthropic, OpenAI, or SAP account. Optional monthly spend caps (`litellm.budget`), sensitive-data redaction, and JSONL audit logs are built in.

## Supported model providers

| Provider | Models & connection | Billing & status |
| :--- | :--- | :--- |
| **Google Gemini (default)** | `gemini-3.8-flash` (default) or `gemini-3.1-pro` via Gemini API key or Vertex AI Workload Identity (no static cluster key; optional data-residency region). | Billed to your GCP billing account. **Available now.** |
| **Anthropic Claude** | `claude-opus-5`, `claude-sonnet-4-5`, and Claude models via Anthropic API, Vertex Model Garden, or SAP AI Core with automatic prompt caching. | Billed to your Anthropic, GCP, or SAP account. **Available now.** |
| **OpenAI GPT** | `gpt-5.4` and GPT models via OpenAI API key (plus an OAuth relay option for non-production prototyping). | Billed to your OpenAI account. **Available now.** |
| **SAP AI Core & private gateways** | Native `sap` driver (OAuth2 service key), plus Azure, Bedrock, Databricks, vLLM/TGI, or custom OAuth2 proxies with private CA support. | Billed to your enterprise gateway account. **Available now.** |
| **Gemma & open-weight models** | Self-hosted Gemma 4 on your own GPU nodes works today via `openai_compatible` (vLLM). Native built-in GKE Gemma serving and domain profiles are on the roadmap. | No per-token fee; you pay only GPU compute. **Self-hosted now / native upcoming.** |

:::caution
When using a Gemini API key, attach the owning Google Cloud project to a billing account. Without linked billing, Gemini API falls back to the unpaid free tier.
:::

## Typical token usage and modeled cost per task

:::note
The figures below are **modeled, not a billing guarantee**. They apply public Vertex AI list rates (Gemini 3.8 Flash `$0.75/1M` input intro rate through Dec 2026, `$1.50/1M` standard 2027+; Gemini 3.1 Pro `$2.00/1M` input) to measured token counts. Those counts come from 669 multi-turn `devops-bench` runs across 223 GKE failure scenarios using default adaptive reasoning.
:::

| Task type | Typical workload | Tokens & cache hit | Modeled Gemini 3.8 Flash | Modeled Gemini 3.1 Pro |
| :--- | :--- | :--- | ---: | ---: |
| **Quick alert check** | CrashLoopBackOff, warning event, or stalled rollout triage | ~285k tokens (81% cached) | ~$0.06 | ~$0.17 |
| **Deep troubleshooting** | Multi-step outage investigation, upgrade check, or fleet audit (~21 steps) | ~1.1M tokens (81% cached) | ~$0.25 | ~$0.68 |
| **End-to-end fix & PR** | Root-cause trace, manifest or Terraform patch, and PR (~34 steps) | ~2.4M tokens (84% cached) | ~$0.47 | ~$1.28 |

### Why multi-step tasks stay under a dollar

- **Automatic prompt caching cuts repeat input cost by ~70%.** Across 20–34 tool turns inspecting cluster state, 81–84% of input tokens hit automatic prompt caching at a 90% discount. Without caching, the same troubleshooting run rises from `$0.25` to `$0.86` on Flash (`$2.30` on Pro), and a full PR fix rises from `$0.47` to `$1.81` (`$4.84` on Pro).
- **Adaptive reasoning by default.** `kube-agents` scales thinking depth automatically per step (~350–420 reasoning tokens per run, under 5% of output) with no manual tuning required.
- **Optional spend caps.** Platform admins can set hard monthly gateway budgets and inspect per-cluster USD spend counters (`spendMicrosUSDTotal`) at any time.

## Where to go next

- [Inference gateway](/kube-agents/concepts/inference-gateway/) — detailed configuration for Vertex AI Workload Identity, Anthropic, OpenAI, SAP AI Core, and vLLM.
- [Quick start (GKE)](/kube-agents/install/quickstart-gke/) — install with your preferred model provider.
- [Fleet sizing](/kube-agents/deploy/fleet-sizing/) — compute sizing profiles (`small`, `medium`, `fleet`) for your cluster count.
