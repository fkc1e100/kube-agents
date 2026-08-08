---
name: finops-cloud-waste-audit
description: Audits gross cloud resource overrequest, orphaned retained PersistentVolumes, unattached static IPs, and unindexed Cloud Logging cost runaway.
---

# Task

Audit Google Cloud and GKE resources for financial waste, massive CPU/RAM overrequests, orphaned retained PersistentVolumes, idle static IP addresses, and unindexed Cloud Logging cost runaway, emitting findings for the `fleet-audit` reporting harness.

# Workflow

## 1. Execute FinOps Inspection

Follow the authoritative checklist in `governance/finops_cloud_waste_sop.md` across target GCP projects:

- `massive-overrequest`: Flag workloads requesting excessive CPU/memory without utilization evidence.
- `orphan-retained-pvs`: Flag released PersistentVolumes with Retain policy incurring storage expense.
- `unattached-static-ips`: Flag reserved external static IP addresses lacking active bindings.
- `cloud-logging-cost-runaway`: Flag unfiltered high-throughput Cloud Logging export sinks.
- `idle-backend-services`: Flag Cloud Load Balancing backend services lacking active backends.

Optional helper runner for static IPs and backend services:

```bash
./skills/finops-cloud-waste-audit/scripts/finops_waste_audit.py --output /opt/data/scratch/finops_raw.json
```

## 2. Hand Findings to Fleet Audit

Emit findings using the `fleet-audit` harness lifecycle (`start` ... `finish`).
