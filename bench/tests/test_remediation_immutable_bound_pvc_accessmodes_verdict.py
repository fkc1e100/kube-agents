"""remediation-immutable-bound-pvc-accessmodes reads standalone verdict lines, not prose."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kube_agents_bench import transcript
from kube_agents_bench.verifiers import ReportContainsVerifier

TASK = Path(__file__).resolve().parent.parent / "tasks" / "remediation-immutable-bound-pvc-accessmodes" / "task.yaml"
CHECK = "immutable-pvc-accessmodes-rejected-and-valid-path-stated"
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
        "IN-PLACE-PVC-EDIT: REJECTED-SPEC-ACCESSMODES-IMMUTABLE\nVALID-REMEDIATION: USE-RECREATE-SINGLE-REPLICA-OR-MIGRATE-TO-NEW-RWX-PVC\n\nShort explanation follows.",
        "**IN-PLACE-PVC-EDIT: REJECTED-SPEC-ACCESSMODES-IMMUTABLE**\n**VALID-REMEDIATION: USE-RECREATE-SINGLE-REPLICA-OR-MIGRATE-TO-NEW-RWX-PVC**\n",
        "`IN-PLACE-PVC-EDIT: REJECTED-SPEC-ACCESSMODES-IMMUTABLE`\n`VALID-REMEDIATION: USE-RECREATE-SINGLE-REPLICA-OR-MIGRATE-TO-NEW-RWX-PVC`\n",
        "1. IN-PLACE-PVC-EDIT: REJECTED-SPEC-ACCESSMODES-IMMUTABLE\n2. VALID-REMEDIATION: USE-RECREATE-SINGLE-REPLICA-OR-MIGRATE-TO-NEW-RWX-PVC\n",
        "> IN-PLACE-PVC-EDIT: REJECTED-SPEC-ACCESSMODES-IMMUTABLE\n> VALID-REMEDIATION: USE-RECREATE-SINGLE-REPLICA-OR-MIGRATE-TO-NEW-RWX-PVC\n",
        "IN-PLACE-PVC-EDIT: REJECTED-SPEC-ACCESSMODES-IMMUTABLE.\nVALID-REMEDIATION: USE-RECREATE-SINGLE-REPLICA-OR-MIGRATE-TO-NEW-RWX-PVC.\n",
        "IN-PLACE-PVC-EDIT: REJECTED-SPEC-ACCESSMODES-IMMUTABLE\nVALID-REMEDIATION: USE-RECREATE-SINGLE-REPLICA-OR-MIGRATE-TO-NEW-RWX-PVC\n\nIN-PLACE-PVC-EDIT: ACCEPTED-BY-API-SERVER is ruled out by the cluster evidence.\n",
    ):
        assert _passes(report), report


def test_wrong_missing_hedged_or_prose_only_fails():
    for report in (
        "IN-PLACE-PVC-EDIT: ACCEPTED-BY-API-SERVER\nVALID-REMEDIATION: USE-RECREATE-SINGLE-REPLICA-OR-MIGRATE-TO-NEW-RWX-PVC\n",
        "IN-PLACE-PVC-EDIT: REJECTED-SPEC-ACCESSMODES-IMMUTABLE\nVALID-REMEDIATION: PATCH-ACCESSMODES-IN-PLACE\n",
        "IN-PLACE-PVC-EDIT: REJECTED-SPEC-ACCESSMODES-IMMUTABLE\nVALID-REMEDIATION: CHANGE-STORAGECLASS-IN-PLACE\n",
        "VALID-REMEDIATION: USE-RECREATE-SINGLE-REPLICA-OR-MIGRATE-TO-NEW-RWX-PVC\n",
        "IN-PLACE-PVC-EDIT: REJECTED-SPEC-ACCESSMODES-IMMUTABLE\n",
        "IN-PLACE-PVC-EDIT: REJECTED-SPEC-ACCESSMODES-IMMUTABLE\nVALID-REMEDIATION: USE-RECREATE-SINGLE-REPLICA-OR-MIGRATE-TO-NEW-RWX-PVC\nIN-PLACE-PVC-EDIT: ACCEPTED-BY-API-SERVER\n",
        "IN-PLACE-PVC-EDIT: REJECTED-SPEC-ACCESSMODES-IMMUTABLE\nVALID-REMEDIATION: USE-RECREATE-SINGLE-REPLICA-OR-MIGRATE-TO-NEW-RWX-PVC\n1. **IN-PLACE-PVC-EDIT: ACCEPTED-BY-API-SERVER**\n",
        "IN-PLACE-PVC-EDIT: REJECTED-SPEC-ACCESSMODES-IMMUTABLE\nVALID-REMEDIATION: USE-RECREATE-SINGLE-REPLICA-OR-MIGRATE-TO-NEW-RWX-PVC\nVALID-REMEDIATION: PATCH-ACCESSMODES-IN-PLACE\n",
        "IN-PLACE-PVC-EDIT: REJECTED-SPEC-ACCESSMODES-IMMUTABLE\nVALID-REMEDIATION: USE-RECREATE-SINGLE-REPLICA-OR-MIGRATE-TO-NEW-RWX-PVC\n2. **VALID-REMEDIATION: PATCH-ACCESSMODES-IN-PLACE**\n",
        "IN-PLACE-PVC-EDIT: REJECTED-SPEC-ACCESSMODES-IMMUTABLE?\nVALID-REMEDIATION: USE-RECREATE-SINGLE-REPLICA-OR-MIGRATE-TO-NEW-RWX-PVC\n",
        "IN-PLACE-PVC-EDIT: REJECTED-SPEC-ACCESSMODES-IMMUTABLE\nVALID-REMEDIATION: USE-RECREATE-SINGLE-REPLICA-OR-MIGRATE-TO-NEW-RWX-PVC (maybe not)\n",
        "spec.accessModes is immutable on a bound PVC; use Recreate strategy or migrate to a new RWX PersistentVolumeClaim.",
    ):
        assert not _passes(report), report


def test_verbatim_prompt_echo_fails():
    doc = yaml.safe_load(TASK.read_text())
    assert not _passes(doc["prompt"])


def test_expected_output_passes():
    doc = yaml.safe_load(TASK.read_text())
    assert _passes(doc["expected_output"])
