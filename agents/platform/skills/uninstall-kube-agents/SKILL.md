---
name: uninstall-kube-agents
description: Discovers and removes provisioned kube-agents GCP/GKE infrastructure.
---

# Uninstall Kubernetes Agentic Harness (kube-agents)

Use this skill when asked to remove or uninstall `kube-agents` infrastructure from a GCP project or GKE cluster.

## One-Liner Uninstall Command (Non-Interactive)

To run the project teardown and optionally clean fleet namespaces, matching persistent disks, and GitOps manifests:

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

Machine-readable JSON status reports are generated at `/tmp/kube-agents-uninstall-report.json`.
