#!/usr/bin/env python3
"""
finops_waste_audit.py — FinOps & Cloud Resource Waste Audit Runner.
Sweeps GCP projects for unattached external static IPs and idle backend services.
"""

import argparse
import json
import os
import subprocess
import sys

EXCLUDED_PURPOSES = {
    "GCE_ENDPOINT", "PRIVATE_SERVICE_CONNECT", "NAT_AUTO", "SHARED_LOADBALANCER_VIP"
}

def run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    """Runs a shell command and returns (rc, stdout, stderr)."""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return res.returncode, res.stdout, res.stderr
    except Exception as e:
        return -1, "", str(e)

def run_gcloud_json(cmd: list[str]) -> list[dict] | dict | None:
    """Runs a gcloud command and parses JSON output safely."""
    rc, stdout, stderr = run_cmd(cmd)
    if rc != 0:
        sys.stderr.write(f"gcloud command failed ({rc}): {' '.join(cmd)}\n{stderr}\n")
        return None
    if not stdout.strip():
        return []
    try:
        return json.loads(stdout)
    except Exception as e:
        sys.stderr.write(f"Error parsing JSON from {' '.join(cmd)}: {e}\n")
        return None

def get_target_projects(cli_project: str | None = None) -> list[str]:
    """Resolves all target GCP projects to audit."""
    if cli_project:
        return [cli_project]

    projects = set()
    monitored = os.environ.get("MONITORED_PROJECT_IDS", "")
    if monitored:
        for p in monitored.split(","):
            p = p.strip()
            if p:
                projects.add(p)

    for env_var in ("GCP_PROJECT_ID", "GKE_PROJECT_ID", "PROJECT_ID"):
        val = os.environ.get(env_var, "").strip()
        if val:
            projects.add(val)

    if not projects:
        rc, stdout, _ = run_cmd(["gcloud", "projects", "list", "--format=value(projectId)"])
        if rc == 0 and stdout.strip():
            for line in stdout.strip().splitlines():
                if line.strip():
                    projects.add(line.strip())

    if not projects:
        rc, stdout, _ = run_cmd(["gcloud", "config", "get-value", "project"])
        if rc == 0 and stdout.strip():
            projects.add(stdout.strip())

    return sorted(list(projects))

def audit_project_waste(project_id: str) -> list[dict]:
    """Audits external static IPs and backend services in a project."""
    findings = []
    # Inspect reserved external static addresses
    addresses = run_gcloud_json(["gcloud", "compute", "addresses", "list", "--project", project_id, "--format=json"])
    if isinstance(addresses, list):
        for addr in addresses:
            name = addr.get("name", "")
            region = addr.get("region", "").split("/")[-1]
            status = addr.get("status", "")
            addr_type = addr.get("addressType", "EXTERNAL")
            purpose = addr.get("purpose", "")
            users = addr.get("users", [])
            creation_ts = addr.get("creationTimestamp", "")

            # Filter out IP reservations created within the last 14 days (< 14 days ago)
            is_older_than_14d = True
            if creation_ts:
                try:
                    from datetime import datetime, timezone
                    created_dt = datetime.fromisoformat(creation_ts)
                    now_dt = datetime.now(timezone.utc)
                    if (now_dt - created_dt).days < 14:
                        is_older_than_14d = False
                except Exception:
                    pass

            if addr_type == "EXTERNAL" and status == "RESERVED" and not users and purpose not in EXCLUDED_PURPOSES and is_older_than_14d:
                findings.append({
                    "check": "unattached-static-ips",
                    "severity": "minor",
                    "title": f"Unattached reserved external static IP {name} in {region or 'global'}",
                    "cluster": f"project/{project_id}",
                    "namespace": "",
                    "object": f"Address/{name}",
                    "impact": "Unattached reserved external IP address incurs idle reservation billing charges.",
                    "evidence": {
                        "command": f"gcloud compute addresses list --project={project_id} --format=json",
                        "excerpt": f'{{"name": "{name}", "addressType": "{addr_type}", "status": "{status}", "creationTimestamp": "{creation_ts}", "users": []}}'
                    },
                    "recommendation": {
                        "action": f"Release unused external static IP reservation {name}.",
                        "rationale": "Reserved external static IP has been unbound for > 14 days with no active VM or forwarding rule bindings.",
                        "risk": "Ensure no external DNS records point to this address."
                    },
                    "remediation": {
                        "kind": "gcloud",
                        "path": ""
                    }
                })

    # Inspect backend services
    services = run_gcloud_json(["gcloud", "compute", "backend-services", "list", "--project", project_id, "--format=json"])
    if isinstance(services, list):
        for svc in services:
            s_name = svc.get("name", "")
            backends = svc.get("backends", [])
            if not backends and not (s_name.startswith("k8s-") or s_name.startswith("k8s2-")):
                findings.append({
                    "check": "idle-backend-services",
                    "severity": "minor",
                    "title": f"Backend service {s_name} has no configured backends",
                    "cluster": f"project/{project_id}",
                    "namespace": "",
                    "object": f"BackendService/{s_name}",
                    "impact": "Unused backend service adds configuration clutter and potential routing dead ends.",
                    "evidence": {
                        "command": f"gcloud compute backend-services list --project={project_id} --format=json",
                        "excerpt": f'{{"name": "{s_name}", "backends": []}}'
                    },
                    "recommendation": {
                        "action": f"Delete unused backend service {s_name} via gcloud or Terraform.",
                        "rationale": "Backend service has no instance group or NEGs attached.",
                        "risk": "Verify no URL maps reference this backend service."
                    },
                    "remediation": {
                        "kind": "gcloud",
                        "path": ""
                    }
                })

    return findings

def main():
    parser = argparse.ArgumentParser(description="Audit FinOps and Cloud Waste")
    parser.add_argument("--project-id", help="Optional target GCP Project ID")
    parser.add_argument("--output", help="Optional path to write findings JSON")
    args = parser.parse_args()

    target_projects = get_target_projects(args.project_id)
    all_findings = []

    for proj in target_projects:
        proj_findings = audit_project_waste(proj)
        all_findings.extend(proj_findings)

    if args.output:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
            with open(args.output, "w") as f:
                json.dump(all_findings, f, indent=2)
        except Exception as e:
            sys.stderr.write(f"Failed to write output to {args.output}: {e}\n")

    print(f"Wrote {len(all_findings)} waste findings across {len(target_projects)} projects")

if __name__ == "__main__":
    main()
