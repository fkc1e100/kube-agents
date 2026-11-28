"""incident-triage-multihop-502-netpol-and-targetport reads standalone verdict lines, not prose."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kube_agents_bench import transcript
from kube_agents_bench.verifiers import ReportContainsVerifier

TASK = Path(__file__).resolve().parent.parent / "tasks" / "incident-triage-multihop-502-netpol-and-targetport" / "task.yaml"
CHECK = "multihop-netpol-and-targetport-both-identified"
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
        "FAULTS-ON-PATH: BOTH-NETWORKPOLICY-AND-TARGETPORT\nSINGLE-PR-FIX: UPDATE-NETWORKPOLICY-AND-SERVICE-TARGETPORT\n\nShort explanation follows.",
        "**FAULTS-ON-PATH: BOTH-NETWORKPOLICY-AND-TARGETPORT**\n**SINGLE-PR-FIX: UPDATE-NETWORKPOLICY-AND-SERVICE-TARGETPORT**\n",
        "`FAULTS-ON-PATH: BOTH-NETWORKPOLICY-AND-TARGETPORT`\n`SINGLE-PR-FIX: UPDATE-NETWORKPOLICY-AND-SERVICE-TARGETPORT`\n",
        "1. FAULTS-ON-PATH: BOTH-NETWORKPOLICY-AND-TARGETPORT\n2. SINGLE-PR-FIX: UPDATE-NETWORKPOLICY-AND-SERVICE-TARGETPORT\n",
        "> FAULTS-ON-PATH: BOTH-NETWORKPOLICY-AND-TARGETPORT\n> SINGLE-PR-FIX: UPDATE-NETWORKPOLICY-AND-SERVICE-TARGETPORT\n",
        "FAULTS-ON-PATH: BOTH-NETWORKPOLICY-AND-TARGETPORT.\nSINGLE-PR-FIX: UPDATE-NETWORKPOLICY-AND-SERVICE-TARGETPORT.\n",
        "FAULTS-ON-PATH: BOTH-NETWORKPOLICY-AND-TARGETPORT\nSINGLE-PR-FIX: UPDATE-NETWORKPOLICY-AND-SERVICE-TARGETPORT\n\nFAULTS-ON-PATH: NETWORKPOLICY-ONLY is ruled out by the cluster evidence.\n",
    ):
        assert _passes(report), report


def test_wrong_missing_hedged_or_prose_only_fails():
    for report in (
        "FAULTS-ON-PATH: NETWORKPOLICY-ONLY\nSINGLE-PR-FIX: UPDATE-NETWORKPOLICY-AND-SERVICE-TARGETPORT\n",
        "FAULTS-ON-PATH: TARGETPORT-ONLY\nSINGLE-PR-FIX: UPDATE-NETWORKPOLICY-AND-SERVICE-TARGETPORT\n",
        "FAULTS-ON-PATH: SELECTOR-MISMATCH\nSINGLE-PR-FIX: UPDATE-NETWORKPOLICY-AND-SERVICE-TARGETPORT\n",
        "FAULTS-ON-PATH: BOTH-NETWORKPOLICY-AND-TARGETPORT\nSINGLE-PR-FIX: UPDATE-NETWORKPOLICY-ONLY\n",
        "FAULTS-ON-PATH: BOTH-NETWORKPOLICY-AND-TARGETPORT\nSINGLE-PR-FIX: UPDATE-TARGETPORT-ONLY\n",
        "SINGLE-PR-FIX: UPDATE-NETWORKPOLICY-AND-SERVICE-TARGETPORT\n",
        "FAULTS-ON-PATH: BOTH-NETWORKPOLICY-AND-TARGETPORT\n",
        "FAULTS-ON-PATH: BOTH-NETWORKPOLICY-AND-TARGETPORT\nSINGLE-PR-FIX: UPDATE-NETWORKPOLICY-AND-SERVICE-TARGETPORT\nFAULTS-ON-PATH: NETWORKPOLICY-ONLY\n",
        "FAULTS-ON-PATH: BOTH-NETWORKPOLICY-AND-TARGETPORT\nSINGLE-PR-FIX: UPDATE-NETWORKPOLICY-AND-SERVICE-TARGETPORT\n1. **FAULTS-ON-PATH: NETWORKPOLICY-ONLY**\n",
        "FAULTS-ON-PATH: BOTH-NETWORKPOLICY-AND-TARGETPORT\nSINGLE-PR-FIX: UPDATE-NETWORKPOLICY-AND-SERVICE-TARGETPORT\nSINGLE-PR-FIX: UPDATE-NETWORKPOLICY-ONLY\n",
        "FAULTS-ON-PATH: BOTH-NETWORKPOLICY-AND-TARGETPORT\nSINGLE-PR-FIX: UPDATE-NETWORKPOLICY-AND-SERVICE-TARGETPORT\n2. **SINGLE-PR-FIX: UPDATE-NETWORKPOLICY-ONLY**\n",
        "FAULTS-ON-PATH: BOTH-NETWORKPOLICY-AND-TARGETPORT?\nSINGLE-PR-FIX: UPDATE-NETWORKPOLICY-AND-SERVICE-TARGETPORT\n",
        "FAULTS-ON-PATH: BOTH-NETWORKPOLICY-AND-TARGETPORT\nSINGLE-PR-FIX: UPDATE-NETWORKPOLICY-AND-SERVICE-TARGETPORT (maybe not)\n",
        "Both the orders-ingress NetworkPolicy namespace selector and orders-svc targetPort 8081 vs containerPort 8080 are broken.",
    ):
        assert not _passes(report), report


def test_verbatim_prompt_echo_fails():
    doc = yaml.safe_load(TASK.read_text())
    assert not _passes(doc["prompt"])


def test_expected_output_passes():
    doc = yaml.safe_load(TASK.read_text())
    assert _passes(doc["expected_output"])
