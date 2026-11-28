"""remediation-podsecurity-baseline-sysctl-rejection reads standalone verdict lines, not prose."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kube_agents_bench import transcript
from kube_agents_bench.verifiers import ReportContainsVerifier

TASK = Path(__file__).resolve().parent.parent / "tasks" / "remediation-podsecurity-baseline-sysctl-rejection" / "task.yaml"
CHECK = "podsecurity-baseline-sysctl-rejection-stated"
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
        "PODSECURITY-BASELINE-ADMISSION: REJECTED-FORBIDDEN-SYSCTL\nRECOMMENDATION: REMOVE-SYSCTL-OR-ADJUST-POLICY-AT-CLUSTER-LEVEL\n\nShort explanation follows.",
        "**PODSECURITY-BASELINE-ADMISSION: REJECTED-FORBIDDEN-SYSCTL**\n**RECOMMENDATION: REMOVE-SYSCTL-OR-ADJUST-POLICY-AT-CLUSTER-LEVEL**\n",
        "`PODSECURITY-BASELINE-ADMISSION: REJECTED-FORBIDDEN-SYSCTL`\n`RECOMMENDATION: REMOVE-SYSCTL-OR-ADJUST-POLICY-AT-CLUSTER-LEVEL`\n",
        "1. PODSECURITY-BASELINE-ADMISSION: REJECTED-FORBIDDEN-SYSCTL\n2. RECOMMENDATION: REMOVE-SYSCTL-OR-ADJUST-POLICY-AT-CLUSTER-LEVEL\n",
        "> PODSECURITY-BASELINE-ADMISSION: REJECTED-FORBIDDEN-SYSCTL\n> RECOMMENDATION: REMOVE-SYSCTL-OR-ADJUST-POLICY-AT-CLUSTER-LEVEL\n",
        "PODSECURITY-BASELINE-ADMISSION: REJECTED-FORBIDDEN-SYSCTL.\nRECOMMENDATION: REMOVE-SYSCTL-OR-ADJUST-POLICY-AT-CLUSTER-LEVEL.\n",
        "PODSECURITY-BASELINE-ADMISSION: REJECTED-FORBIDDEN-SYSCTL\nRECOMMENDATION: REMOVE-SYSCTL-OR-ADJUST-POLICY-AT-CLUSTER-LEVEL\n\nPODSECURITY-BASELINE-ADMISSION: ALLOWED-SAFE-SYSCTL is ruled out by the cluster evidence.\n",
    ):
        assert _passes(report), report


def test_wrong_missing_hedged_or_prose_only_fails():
    for report in (
        "PODSECURITY-BASELINE-ADMISSION: ALLOWED-SAFE-SYSCTL\nRECOMMENDATION: REMOVE-SYSCTL-OR-ADJUST-POLICY-AT-CLUSTER-LEVEL\n",
        "PODSECURITY-BASELINE-ADMISSION: REJECTED-FORBIDDEN-SYSCTL\nRECOMMENDATION: MOVE-TO-POD-SECURITY-CONTEXT-SYSCTLS\n",
        "PODSECURITY-BASELINE-ADMISSION: REJECTED-FORBIDDEN-SYSCTL\nRECOMMENDATION: MAKE-INITCONTAINER-PRIVILEGED\n",
        "RECOMMENDATION: REMOVE-SYSCTL-OR-ADJUST-POLICY-AT-CLUSTER-LEVEL\n",
        "PODSECURITY-BASELINE-ADMISSION: REJECTED-FORBIDDEN-SYSCTL\n",
        "PODSECURITY-BASELINE-ADMISSION: REJECTED-FORBIDDEN-SYSCTL\nRECOMMENDATION: REMOVE-SYSCTL-OR-ADJUST-POLICY-AT-CLUSTER-LEVEL\nPODSECURITY-BASELINE-ADMISSION: ALLOWED-SAFE-SYSCTL\n",
        "PODSECURITY-BASELINE-ADMISSION: REJECTED-FORBIDDEN-SYSCTL\nRECOMMENDATION: REMOVE-SYSCTL-OR-ADJUST-POLICY-AT-CLUSTER-LEVEL\n1. **PODSECURITY-BASELINE-ADMISSION: ALLOWED-SAFE-SYSCTL**\n",
        "PODSECURITY-BASELINE-ADMISSION: REJECTED-FORBIDDEN-SYSCTL\nRECOMMENDATION: REMOVE-SYSCTL-OR-ADJUST-POLICY-AT-CLUSTER-LEVEL\nRECOMMENDATION: MOVE-TO-POD-SECURITY-CONTEXT-SYSCTLS\n",
        "PODSECURITY-BASELINE-ADMISSION: REJECTED-FORBIDDEN-SYSCTL\nRECOMMENDATION: REMOVE-SYSCTL-OR-ADJUST-POLICY-AT-CLUSTER-LEVEL\n2. **RECOMMENDATION: MOVE-TO-POD-SECURITY-CONTEXT-SYSCTLS**\n",
        "PODSECURITY-BASELINE-ADMISSION: REJECTED-FORBIDDEN-SYSCTL?\nRECOMMENDATION: REMOVE-SYSCTL-OR-ADJUST-POLICY-AT-CLUSTER-LEVEL\n",
        "PODSECURITY-BASELINE-ADMISSION: REJECTED-FORBIDDEN-SYSCTL\nRECOMMENDATION: REMOVE-SYSCTL-OR-ADJUST-POLICY-AT-CLUSTER-LEVEL (maybe not)\n",
        "PodSecurity baseline forbids net.core.somaxconn in pod securityContext.sysctls; remove the sysctl override or change policy.",
    ):
        assert not _passes(report), report


def test_verbatim_prompt_echo_fails():
    doc = yaml.safe_load(TASK.read_text())
    assert not _passes(doc["prompt"])


def test_expected_output_passes():
    doc = yaml.safe_load(TASK.read_text())
    assert _passes(doc["expected_output"])
