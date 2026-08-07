---
name: uninstall-kube-agents
description: Discovers and removes provisioned kube-agents GCP/GKE infrastructure.
---

# Uninstall Kubernetes Agentic Harness (kube-agents)

Use this skill when asked to remove or uninstall `kube-agents` infrastructure from a GCP project or GKE cluster.

## One-Liner Uninstall Command (Non-Interactive)

To safely discover and delete all `kube-agents` elements (GKE cluster, IAM service accounts, Pub/Sub topics, Secret Manager secrets, operator CRDs, and namespaces):

```bash
curl -fsSL https://gke-labs.github.io/kube-agents/uninstall.sh | bash -s -- \
  --non-interactive \
  --fleet \
  --purge-storage \
  --clean-gitops \
  --project-id="<PROJECT_ID>" \
  --cluster-name="<CLUSTER_NAME>" \
  --region="<REGION>"
```

## Teardown Validation & Success Criteria Tiers

When validating an uninstallation test run, evaluate teardown using the following criteria:

| Tier                    | Evaluation Criteria                    | Description                                                                                                                                                                                                                 |
| :---------------------- | :------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **🏆 Perfect Teardown** | **Zero Residual Fleet & Cloud Sweep**  | All `kubeagents-system` namespaces, CRDs, RBAC, webhooks, retained GCP Persistent Disks, GCS buckets, Pub/Sub topics, Secrets, and GitOps manifests across all fleet clusters are 100% purged with zero residual artifacts. |
| **🥇 Good Teardown**    | **Clean Fleet Namespace & RBAC Purge** | All namespaces, workloads, CRDs, and RBAC bindings across all fleet clusters are cleanly deleted.                                                                                                                           |
| **🥈 OK Teardown**      | **Host Cluster Teardown**              | The central host cluster objects are cleanly removed.                                                                                                                                                                       |

Machine-readable JSON status reports are generated at `/tmp/kube-agents-uninstall-report.json`.
