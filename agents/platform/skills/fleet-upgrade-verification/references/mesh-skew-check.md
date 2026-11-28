# Check in-cluster service-mesh sidecar skew and Envoy xDS NACKs

Before proposing a release-channel change on a cluster that runs Istio or managed Cloud Service Mesh — or when diagnosing `istio-proxy` `OOMKilled` restarts with Envoy xDS NACK rejections (`LDS`/`RDS`/`CDS`/`EDS`, including `istio_authn`) and ingress `503 UH no_healthy_upstream` — run `scripts/mesh_skew_check.py` against a per-target kubeconfig fetched under `${HERMES_HOME:-/opt/data}/.kubeconfigs/`:

```bash
KUBECONFIG="${HERMES_HOME:-/opt/data}/.kubeconfigs/kubeconfig_<project>_<cluster>_<location>.yaml" \
  gcloud container clusters get-credentials <cluster> --location <location> --project <project>
python3 /opt/data/profiles/platform/skills/fleet-upgrade-verification/scripts/mesh_skew_check.py \
  --kubeconfig "${HERMES_HOME:-/opt/data}/.kubeconfigs/kubeconfig_<project>_<cluster>_<location>.yaml" \
  [--context <context>] [--timeout 30] [--skip-logs] [--format text|json]
```

## What it reads

- `istiod` Deployments and `ControlPlaneRevision` objects (`controlplanerevisions.mesh.cloud.google.com`) in `istio-system` and `asm-system` (namespaced reads).
- `mutatingwebhookconfigurations` (`istio-sidecar-injector*`, used as fallback only when no active `istiod` or `ControlPlaneRevision` exists) and `pods` (`istio-proxy` containers and native-sidecar initContainers, `istio.io/rev`, `proxy.istio.io/config`, and `OOMKilled` / exit code `137` status) paged through `collector_run.paged_list`.
- Bounded `--tail=200` logs (unless `--skip-logs` is set) for sampled `istio-proxy` containers (including `--previous` when restarted), `istiod`, and ingress gateway pods.

## Exit codes

- `0` (`ok` or `no-mesh-detected`): no skew or Envoy xDS NACK findings and no unread errors.
- `1` (`findings`): control-plane-older-than-sidecar skew, Envoy xDS NACK loop, sidecar-lag skew (`> 1` minor behind), or mixed sidecar revisions within a namespace.
- `2` (`partial-unread`): no findings, and one or more reads failed or were truncated by the credential proxy.
