---
title: "Inference gateway: Self-hosted & OpenAI-compatible"
description: "Connecting private proxies, vLLM, and self-hosted OpenAI-compatible model servers."
---

Part of [Inference gateway](/kube-agents/concepts/inference-gateway/).

## OpenAI-compatible endpoints (self-hosted or private)

`MODEL_PROVIDER=openai_compatible` routes `model-default` to any server that speaks the OpenAI chat-completions API: vLLM, TGI or an internal gateway, in the cluster or on your own network. LiteLLM stays in front of it, so the agent and Hindsight keep calling `inference-gateway` and their config does not change. The provider has no defaults. The model name and the server's base URL are both required, and the render fails without either.

In the chart values:

```yaml
litellm:
  modelProvider: openai_compatible
  modelDefaultName: google/gemma-3-27b-it # the model name the server serves
  openaiCompatible:
    apiBase: http://llm-service.models.svc.cluster.local/v1
    targetPort: 8000
```

`apiBase` is the server's base URL with its `/v1` path, `http://` or `https://`. `modelDefaultName` is the name the server answers to; vLLM serves the model it loaded under its Hugging Face ID unless it was started with `--served-model-name`.

`install.sh` and the Terraform example carry the same settings. The installer checks them against the chart's rules before it creates anything, and its interactive provider menu and the `--menu` panel offer the provider as a fifth entry:

| `install.env` key                  | Flag                                 | Chart value                                                                                  |
| ---------------------------------- | ------------------------------------ | -------------------------------------------------------------------------------------------- |
| `OPENAI_COMPATIBLE_API_BASE`       | `--openai-compatible-api-base`       | `litellm.openaiCompatible.apiBase`                                                           |
| `OPENAI_COMPATIBLE_TARGET_PORT`    | `--openai-compatible-target-port`    | `litellm.openaiCompatible.targetPort`                                                        |
| `OPENAI_COMPATIBLE_EGRESS_CIDRS`   | `--openai-compatible-egress-cidrs`   | `litellm.openaiCompatible.egressCIDRs` (comma-separated in the installer)                    |
| `OPENAI_COMPATIBLE_CA_SECRET_NAME` | `--openai-compatible-ca-secret-name` | `litellm.openaiCompatible.caBundleSecretRef.name` (the key is always `ca.crt`)               |
| `OPENAI_COMPATIBLE_API_KEY`        | `--openai-compatible-api-key`        | key `OPENAI_COMPATIBLE_API_KEY` in `platform-agent-secrets`                                  |
| `LITELLM_ENV_SECRET_NAME`          | `--litellm-env-secret`               | `litellm.envFromSecret` (the OAuth2 client credentials, [below](#oauth2-client-credentials)) |

The Terraform example's variables are the same names in lower case (`openai_compatible_api_base` and so on), with `model_provider = "openai_compatible"` and `model_default_name`. The install above, through the installer:

```bash
curl -fsSL https://raw.githubusercontent.com/gke-labs/kube-agents/<RELEASE_VERSION>/install.sh | bash -s -- \
  --model-provider=openai_compatible \
  --model-default-name=google/gemma-3-27b-it \
  --openai-compatible-api-base=http://llm-service.models.svc.cluster.local/v1 \
  --openai-compatible-target-port=8000
```

### The API key

The key is optional. The gateway reads it from `OPENAI_COMPATIBLE_API_KEY` in the credentials Secret (`platform-agent-secrets`) and sends it as a bearer token. Without it, requests carry the placeholder `Bearer fake-api-key`, which a server that checks no key ignores. With this provider the gateway pod gets none of the Gemini, OpenAI or Anthropic keys, so no request to your server can carry one of them.

### OAuth2 client credentials

An enterprise AI gateway often takes no static key: it issues a client id and a client secret, which are exchanged at an OAuth2 token endpoint (`client_credentials` grant) for a bearer token that expires after minutes or hours. Put the three values in the [credentials Secret](/kube-agents/concepts/inference-litellm/#a-credentials-secret-for-the-gateway) and name it with `--litellm-env-secret`:

```bash
kubectl create secret generic ai-gateway-oauth -n kubeagents-system \
  --from-literal=OPENAI_COMPATIBLE_OAUTH_TOKEN_URL=https://login.example.com/oauth/token \
  --from-literal=OPENAI_COMPATIBLE_OAUTH_CLIENT_ID=<client id> \
  --from-literal=OPENAI_COMPATIBLE_OAUTH_CLIENT_SECRET=<client secret>

curl -fsSL https://raw.githubusercontent.com/gke-labs/kube-agents/<RELEASE_VERSION>/install.sh | bash -s -- \
  --model-provider=openai_compatible \
  --model-default-name=<model> \
  --openai-compatible-api-base=https://ai-gateway.example.com/v1 \
  --litellm-env-secret=ai-gateway-oauth
```

With that Secret named, the chart ships a pre-call hook into the gateway (`litellm_oauth2_callback.py`, beside `config.yaml`). While `OPENAI_COMPATIBLE_OAUTH_TOKEN_URL` is set, it fetches a token before the first request and sends it as the bearer on every request bound for the server. It renews the token 60 seconds before the expiry the token endpoint stated (a response that states none is treated as 5 minutes, so it renews after 4). It fetches one token at a time, and the gateway's log records each fetch and renewal. A failed exchange fails the request that needed it with the token endpoint's status, and the next request tries again.

Two optional keys: `OPENAI_COMPATIBLE_OAUTH_SCOPE` is sent as `scope`, and `OPENAI_COMPATIBLE_OAUTH_CLIENT_AUTH=post` puts the client id and secret in the form body for a token endpoint that does not take them as HTTP basic authentication, the default. Without the token URL the hook is idle and `OPENAI_COMPATIBLE_API_KEY`, if set, is the bearer as before.

The token request leaves the pod under the same [egress rules](#egress-to-the-server) as the model requests, which open the server's address and port and nothing else private. So the token endpoint has to be reachable where the server is: a public address on 443, an address inside `OPENAI_COMPATIBLE_EGRESS_CIDRS` on the same port as the base URL, or, for an in-cluster server, its namespace on `OPENAI_COMPATIBLE_TARGET_PORT`.

For a server behind a [private CA](#a-server-behind-a-private-ca), the hook trusts that bundle beside the system roots when it calls the token URL, so the token endpoint can sit on the same private CA or on a public one. A gateway that is SAP AI Core itself does not need this: [`MODEL_PROVIDER=sap`](/kube-agents/concepts/inference-litellm/#sap-ai-core) carries the exchange in LiteLLM's own driver.

### How the gateway calls the server

Each alias renders as LiteLLM's `hosted_vllm` provider. Despite the name, that is LiteLLM's handler for any OpenAI-compatible server:

```yaml
model_list:
  - model_name: model-default
    litellm_params:
      model: hosted_vllm/google/gemma-3-27b-it
      api_base: http://llm-service.models.svc.cluster.local/v1
```

LiteLLM's `openai/` handler would fit the API too, but it falls back to the `OPENAI_API_KEY` environment variable when an entry has no key, which either sends an OpenAI key to your server or fails every request. It also ignores a per-entry `ssl_verify`, so a private CA would have to replace the trust store for every provider at once. `hosted_vllm/` reads only `HOSTED_VLLM_API_KEY`, which the chart fills from the Secret key above, and honours `ssl_verify` on its own entries. It also strips `strict` from tool schemas and drops replayed reasoning content from earlier turns before the request leaves.

The gateway pod also sets `LITELLM_LOCAL_MODEL_COST_MAP=True` for this provider, so LiteLLM uses the model-price table bundled in its image instead of fetching one from GitHub at startup.

### A server behind a private CA

`litellm.openaiCompatible.caBundleSecretRef` names a Secret in the release namespace that holds the PEM bundle signing the server's certificate (under `key`, default `ca.crt`). The chart mounts that key read-only into the gateway pod at `/etc/litellm/openai-compatible-ca/` and points `ssl_verify` on this provider's entries at it. The bundle replaces the public roots for those entries, so it must hold every CA the server's chain needs. Nothing else trusts it: no other entry, no other pod, and no global `SSL_CERT_FILE`; the one addition is the [OAuth2 hook](#oauth2-client-credentials), which trusts it beside the system roots for the token URL. Through the installer, create the Secret first and pass its name:

```bash
kubectl create secret generic model-server-ca -n kubeagents-system --from-file=ca.crt=./ca.pem
```

### Egress to the server

The gateway's NetworkPolicy (`litellm-policy`) allows DNS, HTTPS to public addresses, the metadata server and the telemetry collector, and none of the places a private server usually lives. The chart adds one egress rule, derived from `apiBase`:

- **An in-cluster Service** (`<svc>`, `<svc>.<ns>.svc` or `<svc>.<ns>.svc.cluster.local`; a bare `<svc>` means the release namespace). A host with exactly two labels, such as `openrouter.ai`, is a hostname, not `<svc>.<ns>`, and follows the rules below; write an in-cluster Service as `<svc>.<ns>.svc`.

  The rule admits that namespace on `targetPort`, which is required in this form: NetworkPolicy matches traffic after the Service has translated it to the pod's port, so the Service port in the URL is not enough. The rule names the namespace, not the server's pods, so every pod in that namespace becomes reachable from the gateway on `targetPort`. Run the model server in a namespace of its own rather than the release namespace, which holds the agent and the gateway. If the server's namespace has its own ingress policy, that policy has to admit the gateway's namespace.

- **A private address outside the cluster**, such as an internal load balancer or an on-premises server over Interconnect or VPN. List its ranges in `egressCIDRs`; the rule admits those CIDRs on the URL's port, or 443 for `https` and 80 for `http` when the URL names none. NetworkPolicy matches addresses and never DNS names, so a hostname needs the ranges it resolves to. Each entry is a CIDR no wider than `/12` (IPv4) or `/48` (IPv6), at most 50 of them. A range that reaches link-local or metadata addresses (`169.254.0.0/16`, `fe80::/10`, the metadata server's `fd20:ce::/48`) is refused, as is an IPv4-mapped IPv6 block. `egressCIDRs` is ignored for an in-cluster Service.
- **A public HTTPS endpoint on port 443** needs no rule: the gateway's existing 443 rule already reaches public addresses. A hostname on 443 that resolves to a private address does not ride that rule, because it excludes private ranges; give it `egressCIDRs`. The chart's static copy of that rule excludes `10.0.0.0/8`, `172.16.0.0/12` and `192.168.0.0/16`, and the operator's copy also excludes `100.64.0.0/10` and `169.254.0.0/16`.

Any other URL with `egressCIDRs` empty fails the render with a message that names `litellm.openaiCompatible.egressCIDRs`.

Use `https` for a server outside the cluster. Over `http`, prompts, which can carry cluster data, and `OPENAI_COMPATIBLE_API_KEY` cross the network unencrypted; the chart accepts it, and both `install.sh` and the chart's install notes (shown by `helm install` and `helm upgrade`) print a warning.

On a default install the operator owns `litellm-policy`, so the chart hands the rule to it as the `kubeagents.x-k8s.io/litellm-upstream-egress` annotation on the `PlatformAgent` ([PlatformAgent CRD](/kube-agents/operator/platformagent-crd/#reconcile-behavior)). The operator checks the value again, and on an invalid one logs `Ignoring invalid annotation value` and adds no rule rather than failing the reconcile; if the gateway cannot reach the server, look there first. With the operator off, the chart's own copy of the policy carries the same rule.

### Context window

A self-hosted server refuses a request whose prompt and `max_tokens` do not fit its served window. Set `litellm.maxTokens` (`MODEL_MAX_TOKENS`) below that window and serve a window large enough for the agent's prompt; [Setting the output-token budget](/kube-agents/concepts/inference-litellm/#setting-the-output-token-budget) has the details.

### What it does not cover

- The kustomize dev copy (`make -C k8s-operator deploy-litellm`) does not carry the provider, the credentials Secret or the OAuth2 hook, and the admin console's provider catalog does not list it. Install through `install.sh`, the Terraform example or the chart.
- The installer does not deploy a model server. The [vLLM example](/kube-agents/concepts/inference-gateway/#vllm-local-models) is one you apply yourself.
- A self-hosted model does not make the install offline. The agent still needs Google APIs, and some of its tools reach the internet on their own. [Security and IAM](https://github.com/gke-labs/kube-agents/blob/main/docs/designs/internals/security-rbac.md#egress-when-model-data-must-stay-off-hosted-providers) lists each destination, which ones are required, and how to turn off the rest. A fully disconnected cluster is not supported.
