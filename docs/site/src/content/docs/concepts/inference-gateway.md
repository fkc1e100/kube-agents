---
title: Inference gateway
description: LiteLLM for hosted models, vLLM for local models. Plus optional replay caching for demos.
sidebar:
  order: 8
---

The Platform Agent talks to an LLM through a **Completions API** proxy so provider choice is a config toggle. There are shipping options for both hosted and local models, plus a replay layer.

## Choosing a provider

| You want                                                           | Use                                                               | Why                                                                                                                                                                                                            |
| ------------------------------------------------------------------ | ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Fastest path with a hosted frontier model                          | **LiteLLM → Gemini** (default)                                    | One API key, no GPU node pool, no cluster egress beyond the LiteLLM pod.                                                                                                                                       |
| Provider redundancy or A/B                                         | **LiteLLM → Gemini + Anthropic + OpenAI**                         | LiteLLM handles the router config; agent config is unchanged.                                                                                                                                                  |
| Inference billed to your own GCP project                           | **LiteLLM → Vertex AI / Model Garden**                            | Workload Identity by default instead of an API key (or a SA key Secret); Gemini plus Model Garden publishers. See [below](/kube-agents/concepts/inference-litellm/#vertex-ai-and-model-garden).                                                        |
| Free local prototyping with a consumer subscription                | **LiteLLM → ChatGPT subscription** (OAuth device flow)            | See [`examples/litellm-chatgpt-subscription/`](https://github.com/gke-labs/kube-agents/tree/main/examples/litellm-chatgpt-subscription).                                                                       |
| Model traffic kept off hosted model providers                      | **LiteLLM → your OpenAI-compatible server** (`openai_compatible`) | vLLM, TGI or an internal gateway, in the cluster or on your network. Google APIs stay required. See [below](#openai-compatible-endpoints-self-hosted-or-private).                                              |
| Model traffic through your SAP tenant, or another LiteLLM provider | **LiteLLM → SAP AI Core** (`sap`), or the provider's slug         | Credentials in a Secret you create, named with `--litellm-env-secret`; an OpenAI-compatible gateway behind OAuth2 client credentials uses the same Secret. See [below](/kube-agents/concepts/inference-litellm/#a-credentials-secret-for-the-gateway). |
| Deterministic demos / cheap tests                                  | **Any of the above + inference-replay proxy**                     | Caches responses in a PVC; replays on cache hit.                                                                                                                                                               |

## LiteLLM (hosted models)

This section has its own dedicated reference page: [Inference gateway: LiteLLM hosted providers](/kube-agents/concepts/inference-litellm/).

## OpenAI-compatible endpoints (self-hosted or private)

This section has its own dedicated reference page: [Inference gateway: Self-hosted & OpenAI-compatible](/kube-agents/concepts/inference-self-hosted/).

## vLLM (local models)

[vLLM](https://vllm.ai) serves open models with continuous batching, chunked prefill, and prefix caching for high throughput on GPU node pools.

### What ships

- [`examples/vllm-gemma/`](https://github.com/gke-labs/kube-agents/tree/main/examples/vllm-gemma) — Gemma 4 26B-A4B through vLLM's OpenAI-compatible server on two L4 GPUs, with a 128k-token context. Requires an accelerator node pool; the README gives the command. It runs in the release namespace, unlike the advice above; its README says what that means for the gateway's egress rule.

To put the gateway in front of it, point `litellm.openaiCompatible.apiBase` at its Service, as [OpenAI-compatible endpoints](#openai-compatible-endpoints-self-hosted-or-private) describes; the example's README gives the values.

## Inference replay

[`examples/inference-replay/`](https://github.com/gke-labs/kube-agents/tree/main/examples/inference-replay) is a small proxy that sits between the Platform Agent and LiteLLM. Requests are keyed by a SHA-256 hash of the canonicalized request body (messages plus params); hits return the cached response, misses forward to LiteLLM and cache the reply.

### Modes

- `mode: off` (default) — passthrough. Every request forwards.
- `mode: on` — cache hits return; misses forward and cache.
- Toggle at runtime:

  ```bash
  kubectl patch configmap inference-replay-config -n <ns> --type merge \
    -p '{"data":{"mode":"on"}}'
  ```

The proxy uses a `PersistentVolumeClaim` for the cache so replays survive pod restarts.

### When to use it

- Demos where you want repeatable output for the same inputs.
- CI tests against the agent's tool loop where LLM cost or non-determinism would be a problem.
- Cost containment during development.

Deploy it with `make -C k8s-operator deploy-inference-replay` — it is a development tool, never part of the installer.

## What the agent doesn't care about

The Platform Agent's config (`agents/platform/config.yaml`) doesn't mention the LLM provider. Provider selection is entirely at the LiteLLM / vLLM layer — the agent always talks to the `inference-gateway` Service, and the install decides what that Service resolves to. When the replay proxy is deployed, the `inference-gateway` Service is repointed at the replay proxy and the original gateway pods are re-exposed through a new `inference-gateway-upstream` Service that the proxy forwards cache misses to. That means:

- Swapping Gemini for Anthropic is a LiteLLM `ConfigMap` change.
- So is [prompt caching](/kube-agents/concepts/inference-litellm/#prompt-caching) — the breakpoints are injected gateway-side, because only the gateway knows which model they are for.
- Turning on replay is a `make -C k8s-operator deploy-inference-replay` on a dev cluster.
- Neither touches the agent's persona, skills, or governance layer.

## Where to go next

- [Reference → Examples](/kube-agents/reference/examples/) — the inference example bundles walked through.
- [Deploy → Network policies and Service](/kube-agents/deploy/kustomize/#kustomize-for-operator-integrations) — where the LiteLLM Deployment's dev copy lives on disk.
- [Concepts → Observability](/kube-agents/concepts/observability/) — LLM telemetry export.
