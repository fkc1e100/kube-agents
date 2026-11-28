"""remediation-liveness-probe-port-and-path reads standalone verdict lines, not prose."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kube_agents_bench import transcript
from kube_agents_bench.verifiers import ReportContainsVerifier

TASK = Path(__file__).resolve().parent.parent / "tasks" / "remediation-liveness-probe-port-and-path" / "task.yaml"
CHECK = "liveness-probe-port-and-path-both-fixed"
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
        "PORT-ONLY-FIX-SUFFICIENT: NO-PATH-ALSO-FAILS-404\nREQUIRED-PATCH: CHANGE-PORT-TO-8080-AND-PATH-TO-ROOT\n\nShort explanation follows.",
        "**PORT-ONLY-FIX-SUFFICIENT: NO-PATH-ALSO-FAILS-404**\n**REQUIRED-PATCH: CHANGE-PORT-TO-8080-AND-PATH-TO-ROOT**\n",
        "`PORT-ONLY-FIX-SUFFICIENT: NO-PATH-ALSO-FAILS-404`\n`REQUIRED-PATCH: CHANGE-PORT-TO-8080-AND-PATH-TO-ROOT`\n",
        "1. PORT-ONLY-FIX-SUFFICIENT: NO-PATH-ALSO-FAILS-404\n2. REQUIRED-PATCH: CHANGE-PORT-TO-8080-AND-PATH-TO-ROOT\n",
        "> PORT-ONLY-FIX-SUFFICIENT: NO-PATH-ALSO-FAILS-404\n> REQUIRED-PATCH: CHANGE-PORT-TO-8080-AND-PATH-TO-ROOT\n",
        "PORT-ONLY-FIX-SUFFICIENT: NO-PATH-ALSO-FAILS-404.\nREQUIRED-PATCH: CHANGE-PORT-TO-8080-AND-PATH-TO-ROOT.\n",
        "PORT-ONLY-FIX-SUFFICIENT: NO-PATH-ALSO-FAILS-404\nREQUIRED-PATCH: CHANGE-PORT-TO-8080-AND-PATH-TO-ROOT\n\nPORT-ONLY-FIX-SUFFICIENT: YES-PORT-8080-RESOLVES-PROBE is ruled out by the cluster evidence.\n",
    ):
        assert _passes(report), report


def test_wrong_missing_hedged_or_prose_only_fails():
    for report in (
        "PORT-ONLY-FIX-SUFFICIENT: YES-PORT-8080-RESOLVES-PROBE\nREQUIRED-PATCH: CHANGE-PORT-TO-8080-AND-PATH-TO-ROOT\n",
        "PORT-ONLY-FIX-SUFFICIENT: NO-PATH-ALSO-FAILS-404\nREQUIRED-PATCH: CHANGE-PORT-TO-8080-ONLY\n",
        "PORT-ONLY-FIX-SUFFICIENT: NO-PATH-ALSO-FAILS-404\nREQUIRED-PATCH: REMOVE-LIVENESS-PROBE\n",
        "REQUIRED-PATCH: CHANGE-PORT-TO-8080-AND-PATH-TO-ROOT\n",
        "PORT-ONLY-FIX-SUFFICIENT: NO-PATH-ALSO-FAILS-404\n",
        "PORT-ONLY-FIX-SUFFICIENT: NO-PATH-ALSO-FAILS-404\nREQUIRED-PATCH: CHANGE-PORT-TO-8080-AND-PATH-TO-ROOT\nPORT-ONLY-FIX-SUFFICIENT: YES-PORT-8080-RESOLVES-PROBE\n",
        "PORT-ONLY-FIX-SUFFICIENT: NO-PATH-ALSO-FAILS-404\nREQUIRED-PATCH: CHANGE-PORT-TO-8080-AND-PATH-TO-ROOT\n1. **PORT-ONLY-FIX-SUFFICIENT: YES-PORT-8080-RESOLVES-PROBE**\n",
        "PORT-ONLY-FIX-SUFFICIENT: NO-PATH-ALSO-FAILS-404\nREQUIRED-PATCH: CHANGE-PORT-TO-8080-AND-PATH-TO-ROOT\nREQUIRED-PATCH: CHANGE-PORT-TO-8080-ONLY\n",
        "PORT-ONLY-FIX-SUFFICIENT: NO-PATH-ALSO-FAILS-404\nREQUIRED-PATCH: CHANGE-PORT-TO-8080-AND-PATH-TO-ROOT\n2. **REQUIRED-PATCH: CHANGE-PORT-TO-8080-ONLY**\n",
        "PORT-ONLY-FIX-SUFFICIENT: NO-PATH-ALSO-FAILS-404?\nREQUIRED-PATCH: CHANGE-PORT-TO-8080-AND-PATH-TO-ROOT\n",
        "PORT-ONLY-FIX-SUFFICIENT: NO-PATH-ALSO-FAILS-404\nREQUIRED-PATCH: CHANGE-PORT-TO-8080-AND-PATH-TO-ROOT (maybe not)\n",
        "Changing port to 8080 alone still hits 404 on /healthz; change both port to 8080 and path to /.",
    ):
        assert not _passes(report), report


def test_verbatim_prompt_echo_fails():
    doc = yaml.safe_load(TASK.read_text())
    assert not _passes(doc["prompt"])


def test_expected_output_passes():
    doc = yaml.safe_load(TASK.read_text())
    assert _passes(doc["expected_output"])
