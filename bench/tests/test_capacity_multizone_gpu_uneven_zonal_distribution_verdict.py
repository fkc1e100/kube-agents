"""capacity-multizone-gpu-uneven-zonal-distribution reads standalone verdict lines, not prose."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kube_agents_bench import transcript
from kube_agents_bench.verifiers import ReportContainsVerifier

TASK = Path(__file__).resolve().parent.parent / "tasks" / "capacity-multizone-gpu-uneven-zonal-distribution" / "task.yaml"
CHECK = "multizone-gpu-uneven-distribution-diagnosed"
TIMEOUT_SEC = 5.0


@pytest.fixture(autouse=True)
def _clean_transcript():
    transcript.clear()
    yield
    transcript.clear()


def _passes(report: str) -> bool:
    doc = yaml.safe_load(TASK.read_text())
    (check,) = [c for c in doc["verification_spec"] if c.get("name") == CHECK]
    assert check["check"]["type"] == "all"
    transcript.set(report, [], final_message=report)
    return all(
        ReportContainsVerifier(**part).verify(TIMEOUT_SEC).success
        for part in check["check"]["checks"]
    )


def test_structured_verdict_lines_pass():
    for report in (
        "CAUSE: UNEVEN-ZONAL-GPU-DISTRIBUTION-STRANDING-QUOTA\nREMEDIATION: REBALANCE-ZONAL-NODES-OR-USE-REGIONAL-STORAGE-AND-ZONAL-CAPS\n\nShort explanation follows.",
        "**CAUSE: UNEVEN-ZONAL-GPU-DISTRIBUTION-STRANDING-QUOTA**\n**REMEDIATION: REBALANCE-ZONAL-NODES-OR-USE-REGIONAL-STORAGE-AND-ZONAL-CAPS**\n",
        "`CAUSE: UNEVEN-ZONAL-GPU-DISTRIBUTION-STRANDING-QUOTA`\n`REMEDIATION: REBALANCE-ZONAL-NODES-OR-USE-REGIONAL-STORAGE-AND-ZONAL-CAPS`\n",
        "1. CAUSE: UNEVEN-ZONAL-GPU-DISTRIBUTION-STRANDING-QUOTA\n2. REMEDIATION: REBALANCE-ZONAL-NODES-OR-USE-REGIONAL-STORAGE-AND-ZONAL-CAPS\n",
        "> CAUSE: UNEVEN-ZONAL-GPU-DISTRIBUTION-STRANDING-QUOTA\n> REMEDIATION: REBALANCE-ZONAL-NODES-OR-USE-REGIONAL-STORAGE-AND-ZONAL-CAPS\n",
        "CAUSE: UNEVEN-ZONAL-GPU-DISTRIBUTION-STRANDING-QUOTA.\nREMEDIATION: REBALANCE-ZONAL-NODES-OR-USE-REGIONAL-STORAGE-AND-ZONAL-CAPS.\n",
        "CAUSE: UNEVEN-ZONAL-GPU-DISTRIBUTION-STRANDING-QUOTA\nREMEDIATION: REBALANCE-ZONAL-NODES-OR-USE-REGIONAL-STORAGE-AND-ZONAL-CAPS\n\nCAUSE: HEALTHY-WAIT-FOR-SCHEDULER is ruled out by the cluster evidence.\n",
    ):
        assert _passes(report), report


def test_wrong_missing_hedged_or_prose_only_fails():
    for report in (
        "CAUSE: HEALTHY-WAIT-FOR-SCHEDULER\nREMEDIATION: REBALANCE-ZONAL-NODES-OR-USE-REGIONAL-STORAGE-AND-ZONAL-CAPS\n",
        "CAUSE: POD-MISSING-GPU-LIMIT\nREMEDIATION: REBALANCE-ZONAL-NODES-OR-USE-REGIONAL-STORAGE-AND-ZONAL-CAPS\n",
        "CAUSE: PVC-NOT-BOUND\nREMEDIATION: REBALANCE-ZONAL-NODES-OR-USE-REGIONAL-STORAGE-AND-ZONAL-CAPS\n",
        "CAUSE: UNEVEN-ZONAL-GPU-DISTRIBUTION-STRANDING-QUOTA\nREMEDIATION: IGNORE-PENDING-POD\n",
        "CAUSE: UNEVEN-ZONAL-GPU-DISTRIBUTION-STRANDING-QUOTA\nREMEDIATION: REMOVE-VOLUME-MOUNT\n",
        "REMEDIATION: REBALANCE-ZONAL-NODES-OR-USE-REGIONAL-STORAGE-AND-ZONAL-CAPS\n",
        "CAUSE: UNEVEN-ZONAL-GPU-DISTRIBUTION-STRANDING-QUOTA\n",
        "CAUSE: UNEVEN-ZONAL-GPU-DISTRIBUTION-STRANDING-QUOTA\nREMEDIATION: REBALANCE-ZONAL-NODES-OR-USE-REGIONAL-STORAGE-AND-ZONAL-CAPS\nCAUSE: HEALTHY-WAIT-FOR-SCHEDULER\n",
        "CAUSE: UNEVEN-ZONAL-GPU-DISTRIBUTION-STRANDING-QUOTA\nREMEDIATION: REBALANCE-ZONAL-NODES-OR-USE-REGIONAL-STORAGE-AND-ZONAL-CAPS\n1. **CAUSE: HEALTHY-WAIT-FOR-SCHEDULER**\n",
        "CAUSE: UNEVEN-ZONAL-GPU-DISTRIBUTION-STRANDING-QUOTA\nREMEDIATION: REBALANCE-ZONAL-NODES-OR-USE-REGIONAL-STORAGE-AND-ZONAL-CAPS\nREMEDIATION: IGNORE-PENDING-POD\n",
        "CAUSE: UNEVEN-ZONAL-GPU-DISTRIBUTION-STRANDING-QUOTA\nREMEDIATION: REBALANCE-ZONAL-NODES-OR-USE-REGIONAL-STORAGE-AND-ZONAL-CAPS\n2. **REMEDIATION: IGNORE-PENDING-POD**\n",
        "CAUSE: UNEVEN-ZONAL-GPU-DISTRIBUTION-STRANDING-QUOTA?\nREMEDIATION: REBALANCE-ZONAL-NODES-OR-USE-REGIONAL-STORAGE-AND-ZONAL-CAPS\n",
        "CAUSE: UNEVEN-ZONAL-GPU-DISTRIBUTION-STRANDING-QUOTA\nREMEDIATION: REBALANCE-ZONAL-NODES-OR-USE-REGIONAL-STORAGE-AND-ZONAL-CAPS (maybe not)\n",
        "All 6 GPUs sit in us-central1-a consuming the regional quota so us-central1-b cannot scale up for the zonal PV; rebalance zones.",
    ):
        assert not _passes(report), report


def test_verbatim_prompt_echo_fails():
    doc = yaml.safe_load(TASK.read_text())
    assert not _passes(doc["prompt"])


def test_expected_output_passes():
    doc = yaml.safe_load(TASK.read_text())
    assert _passes(doc["expected_output"])
