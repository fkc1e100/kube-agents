#!/usr/bin/env python3
"""Dispatcher for the ``first-run-quick-value-audit`` cron job.

After the bootstrap inventory scan completes, this job triggers a sequence of
high-value audits to show immediate ROI to the user:

1. Fleet Waste Audit (cost optimization)
2. Security & RBAC Posture Audit
3. Workload Reliability Audit
4. Stockout Prevention & Capacity Audit

These audits normally run on daily/weekly schedules, but waiting up to 6 days
for cost findings delays the "wow moment" that justifies the installation.

This job runs once after ``INVENTORY.raw.md`` exists (bootstrap complete) and
before ``.first-run-audits-complete`` is written. It files kanban cards for
each audit assigned to the Platform Agent, which executes them using the same
SOPs as the scheduled jobs.

The marker file ``.first-run-audits-filed`` is written immediately after filing
the cards, so:
- Pod restarts do not re-file the audits
- Upgrades/reinstalls do not re-file (marker persists on data volume)
- Manual re-run is possible by deleting the marker

Output is intentionally empty: ``deliver: local`` plus empty stdout means the
scheduler treats every run as silent. Results reach the user through the
normal kanban → chat delivery path.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Marker files
BOOTSTRAP_COMPLETE_MARKER = Path("/opt/data/INVENTORY.raw.md")
FIRST_RUN_FILED_MARKER = Path("/opt/data/.first-run-audits-filed")
FIRST_RUN_COMPLETE_MARKER = Path("/opt/data/.first-run-audits-complete")

# Audits to run, in order
# Each tuple: (audit_id, title, sop_path, delay_seconds)
FIRST_RUN_AUDITS = [
    (
        "first-run-waste-audit",
        "First-Run Fleet Waste Audit",
        "governance/fleet_wide_cost_analysis_sop.md",
        0,  # Run immediately after bootstrap
    ),
    (
        "first-run-security-audit",
        "First-Run Security & RBAC Posture Audit",
        "governance/compliance_audit_sop.md",
        300,  # 5 min after waste audit starts
    ),
    (
        "first-run-reliability-audit",
        "First-Run Workload Reliability Audit",
        "governance/obtainability_audit_sop.md",
        600,  # 10 min after waste audit starts
    ),
    (
        "first-run-capacity-audit",
        "First-Run Stockout Prevention & Capacity Audit",
        "governance/stockout_prevention_sop.md",
        900,  # 15 min after waste audit starts
    ),
]


def should_skip() -> bool:
    """Return True if first-run audits should not be filed."""
    # Skip if bootstrap hasn't completed yet
    if not BOOTSTRAP_COMPLETE_MARKER.exists():
        return True
    # Skip if we've already filed the audits
    if FIRST_RUN_FILED_MARKER.exists():
        return True
    # Skip if audits are already complete
    if FIRST_RUN_COMPLETE_MARKER.exists():
        return True
    return False


def file_audit_card(audit_id: str, title: str, sop_path: str) -> str | None:
    """File a kanban card for the given audit. Returns card ID or None on failure."""
    prompt = f"""Run the {title.replace('First-Run ', '')}. Read the SOP at '{sop_path}' in your profile home before you run anything. Execute it exactly, using the fleet-audit skill to open and close the audit run.

This is a FIRST-RUN audit triggered immediately after installation to show quick value. Results will be delivered to chat and posted to GitHub issues.

After completion, check if all first-run audits are done and write the completion marker."""

    # Use kanban_create via hermes CLI
    cmd = [
        "hermes",
        "kanban",
        "create",
        "--assignee", "platform",
        "--idempotency-key", audit_id,
        "--title", title,
        "--body", prompt,
        "--json",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("id")
        else:
            print(f"Failed to create card for {audit_id}: {result.stderr}", file=sys.stderr)
            return None
    except Exception as e:
        print(f"Error creating card for {audit_id}: {e}", file=sys.stderr)
        return None


def main() -> int:
    if should_skip():
        return 0

    print(f"Bootstrap complete, filing first-run quick value audits...", file=sys.stderr)

    filed_cards = []
    for audit_id, title, sop_path, delay in FIRST_RUN_AUDITS:
        if delay > 0:
            # Stagger the audits to avoid overwhelming the agent
            time.sleep(delay)

        card_id = file_audit_card(audit_id, title, sop_path)
        if card_id:
            filed_cards.append({"audit_id": audit_id, "card_id": card_id})
            print(f"Filed {audit_id} as card {card_id}", file=sys.stderr)

    # Write marker with filed card IDs
    if filed_cards:
        FIRST_RUN_FILED_MARKER.write_text(json.dumps({
            "filed_at": time.time(),
            "cards": filed_cards,
        }))
        print(f"First-run audits filed: {len(filed_cards)} cards", file=sys.stderr)

    # Output nothing to stdout - this is a silent job
    return 0


if __name__ == "__main__":
    sys.exit(main())
