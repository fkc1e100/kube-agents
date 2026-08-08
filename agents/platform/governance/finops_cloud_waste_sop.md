# SOP: FinOps and Cloud Resource Waste Audit (Daily Governance)

**Purpose:** Sweep all managed GCP projects for unattached external IP reservations, orphaned PersistentVolumes with `persistentVolumeReclaimPolicy: Retain`, high-volume un-filtered Cloud Logging sinks, idle Cloud Load Balancing backend services, and multi-node workload resource overrequests. The question this audit answers for a platform admin is: _which cloud assets are generating ongoing waste without serving traffic, and where can resource footprint be safely rightsized?_ Output is this stream's single GitHub ledger issue, rewritten in place on every run, plus narrow remediation Pull Requests carrying Terraform or manifest fixes for the findings that get promoted.

**Cron:** id `finops-cloud-waste-audit`, schedule `30 8 * * *` (daily 08:30 UTC).

**Data sources:** `gcloud compute addresses ...`, `gcloud compute backend-services ...`, `gcloud logging sinks ...`, and `kubectl` read verbs across all managed fleet projects (`GCP_PROJECT_ID` and `MONITORED_PROJECT_IDS`).

---

## Execution Checklist

### 0. Open the audit run

```bash
./skills/fleet-audit/scripts/audit_report.py start --audit finops-cloud-waste-audit
```

Returns `{"issue": <int|null>, "repo":"org/repo", "workspace":"/opt/data/gitops/finops-cloud-waste-audit/org__repo", "findings_path":"/opt/data/scratch/findings_finops-cloud-waste-audit.json"}`.

### 1. Enumerate the target fleet

```bash
gcloud projects list --format=json
```

- Target every configured fleet project and GKE cluster. Record `{name, location, project, checks_run}` into `scope.clusters`.
- **`checks_run` is mandatory on every scope entry:** Each entry is an object `{"check": "<slug>", "command": "<literal command>"}` naming the exact inspection command executed on that target.
- A project or target you cannot reach goes in `scope.skipped` with a reason string. If a target is partially readable, record the refusal in its `limitations` string. Declare structurally inapplicable checks in `checks_not_applicable`.

### 2. Diagnostic checks roster

#### 2.1 Multi-node workload request over-allocation (`massive-overrequest`)

- **Severity**: `major`
- **Command**: `kubectl --context=$CLUSTER get deployments,statefulsets -A -o json`
- **Condition**: Workload requests > 32 vCPU or > 128GiB memory without historical utilization evidence, risking bin-packing waste.
- **Do NOT flag**: Workloads in system namespaces, DaemonSets, batch/Job workloads, or single-replica development sandbox workloads.
- **Remediation**: Rightsize resource requests in workload deployment manifest.

#### 2.2 Orphaned retained PersistentVolumes (`orphan-retained-pvs`)

- **Severity**: `major`
- **Command**: `kubectl --context=$CLUSTER get pv -o json`
- **Condition**: PersistentVolume with `reclaimPolicy: Retain` is in `Released` status without an active PVC binding for > 14 days.
- **Do NOT flag**: PVs with `claimRef` updated within the last 14 days, or PVs with explicit `finops.kube-agents.io/keep="true"` retention labels.
- **Remediation**: Clean up released persistent storage or archive disk snapshot via `kind: manual` or `kind: gcloud`.

#### 2.3 Unattached external static IP address reservations (`unattached-static-ips`)

- **Severity**: `minor`
- **Command**: `gcloud compute addresses list --filter="status=RESERVED AND addressType=EXTERNAL" --project=$PROJECT --format=json`
- **Condition**: External static IP address is reserved but not bound to any running VM or forwarding rule for > 14 days.
- **Do NOT flag**: Internal IP addresses (`addressType: INTERNAL`), addresses reserved < 14 days ago, or addresses referenced in GitOps Ingress/Gateway manifests.
- **Remediation**: Release unused static IP reservation via `kind: gcloud`.

#### 2.4 Unfiltered high-throughput Cloud Logging export sinks (`cloud-logging-cost-runaway`)

- **Severity**: `minor`
- **Command**: `gcloud logging sinks list --project=$PROJECT --format=json`
- **Condition**: Log sink exports unfiltered noisy container stdout/stderr logs directly to BigQuery or Cloud Storage without exclusion filters.
- **Do NOT flag**: Compliance audit log sinks or sinks with existing explicit exclusion filters.
- **Remediation**: Add exclusion filters for health check and debug log streams in Terraform logging sink definition.

#### 2.5 Idle Cloud Load Balancing backend services (`idle-backend-services`)

- **Severity**: `minor`
- **Command**: `gcloud compute backend-services list --project=$PROJECT --format=json`
- **Condition**: Backend service has no attached backends or receives 0 requests over a sustained billing period.
- **Do NOT flag**: Backend services associated with active Kubernetes GKE Ingress/Gateway resources undergoing rolling deployments.
- **Remediation**: Remove unused backend service in Terraform configuration.

### 3. Generate remediation artifacts

For promoted findings requiring `kind: manifest` remediation, write the updated Terraform or manifest file to `remediation.path` resolved within the `workspace` GitOps repository:

- Discover the target configuration from existing repository paths (e.g., `terraform/modules/networking/sinks.tf`).
- Never invent phantom paths or write manifests to directories outside the reconciled GitOps hierarchy.

### 4. Emit findings.json

Write the whole document to `findings_path` in one shot, with `audit: "finops-cloud-waste-audit"`, `scope.clusters` listing every target you queried — each carrying the `checks_run` list §1 required and, where §1 recorded them, that target's `checks_not_applicable` entries and `limitations` string — and `scope.skipped` listing only the targets you could not read.

`command` in `checks_run` is the literal inspection command executed, and anything under eight characters is rejected.

Every finding must conform to the full findings schema:

```json
{
  "audit": "finops-cloud-waste-audit",
  "scope": {
    "clusters": [
      {
        "name": "finops-fleet-prod",
        "location": "global",
        "project": "proj-1",
        "checks_run": [
          {
            "check": "unattached-static-ips",
            "command": "gcloud compute addresses list --project=proj-1 --format=json"
          }
        ]
      }
    ],
    "skipped": []
  },
  "findings": [
    {
      "check": "unattached-static-ips",
      "severity": "minor",
      "title": "Unattached static IP address ip-prod-unused in us-central1",
      "cluster": "finops-fleet-prod",
      "namespace": "default",
      "object": "Address/ip-prod-unused",
      "impact": "Unattached reserved IP address incurs ongoing idle reservation cost.",
      "evidence": {
        "command": "gcloud compute addresses describe ip-prod-unused --region=us-central1 --project=proj-1 --format=json",
        "excerpt": "status: RESERVED, users: null"
      },
      "recommendation": {
        "action": "Release static IP reservation ip-prod-unused.",
        "rationale": "Reserved static IP has had no active bindings for > 30 days.",
        "risk": "Ensure DNS records do not reference this IP address."
      },
      "remediation": {
        "kind": "gcloud",
        "path": ""
      }
    }
  ]
}
```

### 5. Close the audit run

```bash
./skills/fleet-audit/scripts/audit_report.py finish --audit finops-cloud-waste-audit   --findings-file /opt/data/scratch/findings_finops-cloud-waste-audit.json
# -> {"status":"CLEAN"|"OPENED"|"UPDATED","issue_url":...,"new":n,"resolved":m,
#     "prs_opened":[...],"prs_closed":[...],"partial":false,"coverage_gaps":[],
#     "silent_ok":true}
```

- On a **scheduled** run, `silent_ok: true` -> your final response is exactly `[SILENT]`.
- **An on-demand run is never silent.** If a person dispatched this job, report the outcome and the ledger URL whatever `silent_ok` says.
- Repo writers can trigger remediation by commenting `/remediate <finding-id>` or `/remediate all` on the ledger issue.

---

## Red Lines

- **Read-only audit.** Never release static IPs, delete PersistentVolumes, or delete backend services directly.
- **No hand-written issues or PRs.** `audit_report.py` owns the entire git/GitHub write path.
- **Never print raw credentials.** Secret tokens, certificates, and private keys must never reach an excerpt.
- **No unstable finding identity.** Name the durable resource identifier (`Address/<name>`, `PersistentVolume/<name>`), never an ephemeral timestamp.
- **Never emit a manifest that directly deletes a resource.** Deletion remediations are `kind: manual` or `kind: gcloud` only.
