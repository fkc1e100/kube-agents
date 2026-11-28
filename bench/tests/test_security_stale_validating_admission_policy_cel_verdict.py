"""security-stale-validating-admission-policy-cel reads standalone verdict lines, not prose."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kube_agents_bench import transcript
from kube_agents_bench.verifiers import ReportContainsVerifier

TASK = Path(__file__).resolve().parent.parent / "tasks" / "security-stale-validating-admission-policy-cel" / "task.yaml"
CHECK = "stale-validating-admission-policy-cel-diagnosed"
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
        "BLOCKING-MECHANISM: VALIDATING-ADMISSION-POLICY-CEL\nREMEDIATION: UPDATE-OR-REMOVE-STALE-POLICY-AND-BINDING\n\nShort explanation follows.",
        "**BLOCKING-MECHANISM: VALIDATING-ADMISSION-POLICY-CEL**\n**REMEDIATION: UPDATE-OR-REMOVE-STALE-POLICY-AND-BINDING**\n",
        "`BLOCKING-MECHANISM: VALIDATING-ADMISSION-POLICY-CEL`\n`REMEDIATION: UPDATE-OR-REMOVE-STALE-POLICY-AND-BINDING`\n",
        "1. BLOCKING-MECHANISM: VALIDATING-ADMISSION-POLICY-CEL\n2. REMEDIATION: UPDATE-OR-REMOVE-STALE-POLICY-AND-BINDING\n",
        "> BLOCKING-MECHANISM: VALIDATING-ADMISSION-POLICY-CEL\n> REMEDIATION: UPDATE-OR-REMOVE-STALE-POLICY-AND-BINDING\n",
        "BLOCKING-MECHANISM: VALIDATING-ADMISSION-POLICY-CEL.\nREMEDIATION: UPDATE-OR-REMOVE-STALE-POLICY-AND-BINDING.\n",
        "BLOCKING-MECHANISM: VALIDATING-ADMISSION-POLICY-CEL\nREMEDIATION: UPDATE-OR-REMOVE-STALE-POLICY-AND-BINDING\n\nBLOCKING-MECHANISM: RBAC-SERVICEACCOUNT-DENIED is ruled out by the cluster evidence.\n",
    ):
        assert _passes(report), report


def test_wrong_missing_hedged_or_prose_only_fails():
    for report in (
        "BLOCKING-MECHANISM: RBAC-SERVICEACCOUNT-DENIED\nREMEDIATION: UPDATE-OR-REMOVE-STALE-POLICY-AND-BINDING\n",
        "BLOCKING-MECHANISM: RESOURCEQUOTA-EXCEEDED\nREMEDIATION: UPDATE-OR-REMOVE-STALE-POLICY-AND-BINDING\n",
        "BLOCKING-MECHANISM: IMAGEPULLBACKOFF\nREMEDIATION: UPDATE-OR-REMOVE-STALE-POLICY-AND-BINDING\n",
        "BLOCKING-MECHANISM: VALIDATING-ADMISSION-POLICY-CEL\nREMEDIATION: ADD-SKIP-ADMISSION-ANNOTATION\n",
        "BLOCKING-MECHANISM: VALIDATING-ADMISSION-POLICY-CEL\nREMEDIATION: RESTART-KUBE-CONTROLLER-MANAGER\n",
        "REMEDIATION: UPDATE-OR-REMOVE-STALE-POLICY-AND-BINDING\n",
        "BLOCKING-MECHANISM: VALIDATING-ADMISSION-POLICY-CEL\n",
        "BLOCKING-MECHANISM: VALIDATING-ADMISSION-POLICY-CEL\nREMEDIATION: UPDATE-OR-REMOVE-STALE-POLICY-AND-BINDING\nBLOCKING-MECHANISM: RBAC-SERVICEACCOUNT-DENIED\n",
        "BLOCKING-MECHANISM: VALIDATING-ADMISSION-POLICY-CEL\nREMEDIATION: UPDATE-OR-REMOVE-STALE-POLICY-AND-BINDING\n1. **BLOCKING-MECHANISM: RBAC-SERVICEACCOUNT-DENIED**\n",
        "BLOCKING-MECHANISM: VALIDATING-ADMISSION-POLICY-CEL\nREMEDIATION: UPDATE-OR-REMOVE-STALE-POLICY-AND-BINDING\nREMEDIATION: ADD-SKIP-ADMISSION-ANNOTATION\n",
        "BLOCKING-MECHANISM: VALIDATING-ADMISSION-POLICY-CEL\nREMEDIATION: UPDATE-OR-REMOVE-STALE-POLICY-AND-BINDING\n2. **REMEDIATION: ADD-SKIP-ADMISSION-ANNOTATION**\n",
        "BLOCKING-MECHANISM: VALIDATING-ADMISSION-POLICY-CEL?\nREMEDIATION: UPDATE-OR-REMOVE-STALE-POLICY-AND-BINDING\n",
        "BLOCKING-MECHANISM: VALIDATING-ADMISSION-POLICY-CEL\nREMEDIATION: UPDATE-OR-REMOVE-STALE-POLICY-AND-BINDING (maybe not)\n",
        "The ValidatingAdmissionPolicy require-legacy-cost-tag is denying pods; update or delete the policy/binding rather than using a fake bypass annotation.",
    ):
        assert not _passes(report), report


def test_verbatim_prompt_echo_fails():
    doc = yaml.safe_load(TASK.read_text())
    assert not _passes(doc["prompt"])


def test_expected_output_passes():
    doc = yaml.safe_load(TASK.read_text())
    assert _passes(doc["expected_output"])
