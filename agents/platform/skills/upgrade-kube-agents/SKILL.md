---
name: upgrade-kube-agents
description: Perform non-interactive or interactive Day-2 upgrades of the Kubernetes Agentic Harness and operator on GKE clusters.
---

# Upgrade Kubernetes Agentic Harness (kube-agents)

Use this skill when asked to upgrade the `kube-agents` Platform Agent or operator on an active GKE cluster.

## One-Liner Execution Mode (Non-Interactive)

To non-interactively upgrade `kube-agents` on a GKE cluster:

```bash
curl -fsSL https://gke-labs.github.io/kube-agents/upgrade.sh | bash -s -- \
  --upgrade-mode="full" \
  --non-interactive \
  --project-id="<PROJECT_ID>" \
  --cluster-name="<CLUSTER_NAME>" \
  --region="<REGION>" \
  --image-tag="<VALIDATED_RELEASE_TAG_OR_COMMIT_SHA>"
```

## Upgrade Modes

- `--upgrade-mode=harness`: Upgrades Platform Agent deployment and controller container images.
- `--upgrade-mode=operator`: Upgrades Kubernetes Operator CRDs and controller manager.
- `--upgrade-mode=full` (Default): Performs full atomic upgrade across operator, harness, and skills.

## Dry-Run Mode

To preview the upgrade plan and output a JSON status report without modifying cloud resources:

```bash
./upgrade.sh --dry-run --upgrade-mode=full
```

Machine-readable JSON status reports are generated at `/tmp/kube-agents-upgrade-report.json`.
