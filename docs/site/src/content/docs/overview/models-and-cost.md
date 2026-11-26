---
title: Models, cost, and BYOT
description: Apache 2.0 open source ($0 license), GKE Standard or Autopilot co-existence, Bring Your Own Tokens (BYOT) providers, and built-in cost controls.
---

`kube-agents` is Apache 2.0 open-source software with no license fee, seat charge, or token markup. You pay only your standard GKE compute costs and the model tokens you consume on your own provider account.

## Zero license fee, co-exists on any GKE cluster

- **$0 software license.** Apache 2.0 open source on GitHub.
- **No dedicated cluster required.** Installs into an isolated `kubeagents-system` namespace with NetworkPolicy and least-privilege Workload Identity, and co-exists alongside other workloads on an existing GKE Standard or Autopilot cluster.
- **Bring Your Own Tokens (BYOT).** Every agent calls one in-cluster gateway (`Service/inference-gateway`, backed by LiteLLM). You pick a provider at install time and can switch later in config with no cluster reinstall.
- **Direct billing and guardrails.** Usage bills directly to your Google Cloud, Anthropic, OpenAI, or SAP account. Optional monthly spend caps (`litellm.budget`), sensitive-data redaction, and JSONL audit logs are built in.

## Supported model providers

| Provider | Models & connection | Billing |
| :--- | :--- | :--- |
| **Google Gemini (default)** | Gemini models via Gemini API key or Vertex AI Workload Identity (no static cluster key; optional data-residency region). | Billed to your Google Cloud billing account ([Vertex AI pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing)). |
| **Anthropic Claude** | Anthropic Claude models via Anthropic API key, Vertex Model Garden, or SAP AI Core with automatic prompt caching. | Billed to your Anthropic, Google Cloud, or SAP account. |
| **OpenAI GPT** | OpenAI GPT models via OpenAI API key. | Billed to your OpenAI account. |
| **SAP AI Core & private gateways** | Native `sap` driver (OAuth2 service key), plus Azure, AWS Bedrock, Databricks, vLLM/TGI, or custom OAuth2 proxies with private CA support. | Billed to your enterprise gateway account. |
| **Gemma & open-weight models** | Self-hosted Gemma or other open-weight models on your own GPU nodes via `openai_compatible` (vLLM). | No per-token fee; you pay only GPU compute. |

:::caution
When using a Gemini API key, attach the owning Google Cloud project to a billing account and review the [Gemini API Additional Terms of Service](https://ai.google.dev/gemini-api/terms) for paid versus unpaid tier terms.
:::

## How `kube-agents` manages token efficiency

Actual token consumption depends on your fleet size, model choice, prompt length, and audit frequency. Three built-in mechanisms help keep multi-turn investigations predictable:

- **Automatic prompt caching.** Multi-turn tool loops re-send system instructions and prior cluster observations across turns. Where the selected model provider supports prompt caching, `kube-agents` enables cache breakpoints automatically to reduce repeat input token charges.
- **Adaptive reasoning defaults.** `kube-agents` uses default reasoning settings tuned for operational tool-calling without requiring manual thinking-budget configuration.
- **Spend caps and per-cluster telemetry.** Platform admins can enforce monthly budget ceilings on the inference gateway (`litellm.budget`) and monitor per-cluster usage via exported spend counters (`spendMicrosUSDTotal`).

For current model rates, consult your provider's published pricing page (for example, [Vertex AI Generative AI pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing)).

## Where to go next

- [Inference gateway](/kube-agents/concepts/inference-gateway/) — detailed configuration for Vertex AI Workload Identity, Anthropic, OpenAI, SAP AI Core, and vLLM.
- [Quick start (GKE)](/kube-agents/install/quickstart-gke/) — install with your preferred model provider.
- [Fleet sizing](/kube-agents/deploy/fleet-sizing/) — compute sizing profiles (`small`, `medium`, `fleet`) for your cluster count.
