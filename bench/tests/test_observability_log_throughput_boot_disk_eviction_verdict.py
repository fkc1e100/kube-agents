"""observability-log-throughput-boot-disk-eviction reads standalone verdict lines, not prose."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kube_agents_bench import transcript
from kube_agents_bench.verifiers import ReportContainsVerifier

TASK = Path(__file__).resolve().parent.parent / "tasks" / "observability-log-throughput-boot-disk-eviction" / "task.yaml"
CHECK = "boot-disk-log-pressure-cause-and-remediation-stated"
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
        "ROOT-CAUSE: CONTAINER-LOG-FOOTPRINT-EXHAUSTING-BOOT-DISK\nREMEDIATION: REDUCE-LOG-VOLUME-TUNE-LOG-ROTATION-AND-SIZE-BOOT-DISK\n\nShort explanation follows.",
        "**ROOT-CAUSE: CONTAINER-LOG-FOOTPRINT-EXHAUSTING-BOOT-DISK**\n**REMEDIATION: REDUCE-LOG-VOLUME-TUNE-LOG-ROTATION-AND-SIZE-BOOT-DISK**\n",
        "`ROOT-CAUSE: CONTAINER-LOG-FOOTPRINT-EXHAUSTING-BOOT-DISK`\n`REMEDIATION: REDUCE-LOG-VOLUME-TUNE-LOG-ROTATION-AND-SIZE-BOOT-DISK`\n",
        "1. ROOT-CAUSE: CONTAINER-LOG-FOOTPRINT-EXHAUSTING-BOOT-DISK\n2. REMEDIATION: REDUCE-LOG-VOLUME-TUNE-LOG-ROTATION-AND-SIZE-BOOT-DISK\n",
        "> ROOT-CAUSE: CONTAINER-LOG-FOOTPRINT-EXHAUSTING-BOOT-DISK\n> REMEDIATION: REDUCE-LOG-VOLUME-TUNE-LOG-ROTATION-AND-SIZE-BOOT-DISK\n",
        "ROOT-CAUSE: CONTAINER-LOG-FOOTPRINT-EXHAUSTING-BOOT-DISK.\nREMEDIATION: REDUCE-LOG-VOLUME-TUNE-LOG-ROTATION-AND-SIZE-BOOT-DISK.\n",
        "ROOT-CAUSE: CONTAINER-LOG-FOOTPRINT-EXHAUSTING-BOOT-DISK\nREMEDIATION: REDUCE-LOG-VOLUME-TUNE-LOG-ROTATION-AND-SIZE-BOOT-DISK\n\nROOT-CAUSE: MEMORY-OOM-EVICTION is ruled out by the cluster evidence.\n",
    ):
        assert _passes(report), report


def test_wrong_missing_hedged_or_prose_only_fails():
    for report in (
        "ROOT-CAUSE: MEMORY-OOM-EVICTION\nREMEDIATION: REDUCE-LOG-VOLUME-TUNE-LOG-ROTATION-AND-SIZE-BOOT-DISK\n",
        "ROOT-CAUSE: PERSISTENT-VOLUME-FULL\nREMEDIATION: REDUCE-LOG-VOLUME-TUNE-LOG-ROTATION-AND-SIZE-BOOT-DISK\n",
        "ROOT-CAUSE: IMAGE-CACHE-BLOAT-ONLY\nREMEDIATION: REDUCE-LOG-VOLUME-TUNE-LOG-ROTATION-AND-SIZE-BOOT-DISK\n",
        "ROOT-CAUSE: CONTAINER-LOG-FOOTPRINT-EXHAUSTING-BOOT-DISK\nREMEDIATION: INCREASE-POD-MEMORY-LIMITS\n",
        "ROOT-CAUSE: CONTAINER-LOG-FOOTPRINT-EXHAUSTING-BOOT-DISK\nREMEDIATION: ADD-PVC-WITHOUT-CHANGING-LOGGING\n",
        "REMEDIATION: REDUCE-LOG-VOLUME-TUNE-LOG-ROTATION-AND-SIZE-BOOT-DISK\n",
        "ROOT-CAUSE: CONTAINER-LOG-FOOTPRINT-EXHAUSTING-BOOT-DISK\n",
        "ROOT-CAUSE: CONTAINER-LOG-FOOTPRINT-EXHAUSTING-BOOT-DISK\nREMEDIATION: REDUCE-LOG-VOLUME-TUNE-LOG-ROTATION-AND-SIZE-BOOT-DISK\nROOT-CAUSE: MEMORY-OOM-EVICTION\n",
        "ROOT-CAUSE: CONTAINER-LOG-FOOTPRINT-EXHAUSTING-BOOT-DISK\nREMEDIATION: REDUCE-LOG-VOLUME-TUNE-LOG-ROTATION-AND-SIZE-BOOT-DISK\n1. **ROOT-CAUSE: MEMORY-OOM-EVICTION**\n",
        "ROOT-CAUSE: CONTAINER-LOG-FOOTPRINT-EXHAUSTING-BOOT-DISK\nREMEDIATION: REDUCE-LOG-VOLUME-TUNE-LOG-ROTATION-AND-SIZE-BOOT-DISK\nREMEDIATION: INCREASE-POD-MEMORY-LIMITS\n",
        "ROOT-CAUSE: CONTAINER-LOG-FOOTPRINT-EXHAUSTING-BOOT-DISK\nREMEDIATION: REDUCE-LOG-VOLUME-TUNE-LOG-ROTATION-AND-SIZE-BOOT-DISK\n2. **REMEDIATION: INCREASE-POD-MEMORY-LIMITS**\n",
        "ROOT-CAUSE: CONTAINER-LOG-FOOTPRINT-EXHAUSTING-BOOT-DISK?\nREMEDIATION: REDUCE-LOG-VOLUME-TUNE-LOG-ROTATION-AND-SIZE-BOOT-DISK\n",
        "ROOT-CAUSE: CONTAINER-LOG-FOOTPRINT-EXHAUSTING-BOOT-DISK\nREMEDIATION: REDUCE-LOG-VOLUME-TUNE-LOG-ROTATION-AND-SIZE-BOOT-DISK (maybe not)\n",
        "Verbose container logs in /var/log/pods are filling the 100GB node boot disk and triggering DiskPressure; tune log rotation and disk size.",
    ):
        assert not _passes(report), report


def test_verbatim_prompt_echo_fails():
    doc = yaml.safe_load(TASK.read_text())
    assert not _passes(doc["prompt"])


def test_expected_output_passes():
    doc = yaml.safe_load(TASK.read_text())
    assert _passes(doc["expected_output"])
