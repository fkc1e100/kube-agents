---
title: In-Cluster POC Web Console
description: Deploying the zero-configuration Web Console for customer evaluations without chat platform dependencies.
sidebar:
  order: 8
---

Evaluating Kube-Agents in enterprise environments typically requires configuring webhooks, bot registrations, and OAuth manifests for chat platforms such as Slack, Microsoft Teams, or Google Chat. For proof-of-concept (POC) environments and single-cluster evaluations, the **POC Web Console** provides a zero-configuration web interface running directly inside the cluster.

The Web Console serves a responsive browser interface styled in Google Cloud design tokens and proxies user chat queries and incident telemetry directly to the in-cluster agent runtimes.

In accordance with our platform invariants, Kube-Agents proposes GitOps changes as pull requests; it never mutates live cluster resources directly.

---

## Architectural Seam

The Web Console runs as an independent Deployment and Service alongside the Platform Agent:

```
Browser User
     │ (HTTP :8080 or port-forward)
     ▼
Web Console Container (:8080)
     ├──> Hermes Agent Gateway (:8642) [Chat queries & diagnosis turns]
     ├──> Session KV Server (:8699)   [Incident feed & task records]
     └──> LiteLLM Proxy (:4000)        [Model proxy fallback]
```

### Key Operational Guarantees

1. **Zero External Chat Platform Setup:** Operators interact with Kube-Agents immediately upon Helm installation without administrative access to corporate messaging tenants.
2. **Read-Only Telemetry:** The console renders incident alerts and remediation task statuses from Session KV without bypassing Kubernetes RBAC or agent policy gates.
3. **No Chaos Scenarios or Workshop Artifacts:** The console is strictly an operational bridge for chat and status inspection; test injection controls and simulated failure scenarios are excluded.
4. **Lightweight Footprint:** Built as a standalone Go binary on distroless scratch, consuming less than 32MiB memory and under 50 millicores CPU.

---

## Deployment via Helm Preset

To enable the Web Console during Helm installation, supply the `charts/kube-agents/values-poc.yaml` preset:

```bash
helm install kube-agents charts/kube-agents \
  --namespace kube-agents --create-namespace \
  -f charts/kube-agents/values-poc.yaml \
  --set platformAgent.harness.projectId=YOUR_PROJECT \
  --set platformAgent.harness.clusterName=YOUR_CLUSTER \
  --set platformAgent.harness.location=YOUR_LOCATION
```

Alternatively, set `webConsole.enabled: true` in your existing values:

```yaml
webConsole:
  enabled: true
  service:
    type: ClusterIP
    port: 8080
```

---

## Accessing the Interface

Once the deployment reports Ready, establish local access using port-forwarding:

```bash
kubectl port-forward -n kube-agents svc/kube-agents-web-console 8080:8080
```

Open `http://localhost:8080` in your web browser.

For environments requiring direct network reachability without port forwarding, configure `webConsole.service.type: LoadBalancer` or configure an Ingress object targeting port 8080.
