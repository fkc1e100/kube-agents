"""Unit tests for upgrades-service-mesh-channel-downgrade-probe task.yaml patterns."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kube_agents_bench import transcript
from kube_agents_bench.verifiers import ReportContainsVerifier

TASK = (
    Path(__file__).resolve().parent.parent
    / "tasks"
    / "upgrades-service-mesh-channel-downgrade-probe"
    / "task.yaml"
)
CHECK_ROOT_CAUSE = "verdict-holds-channel-and-names-mesh-skew-root-cause"
CHECK_PRECHANGE = "prechange-checks-and-remediation-are-named"
TIMEOUT_SEC = 5.0


@pytest.fixture(autouse=True)
def _clean_transcript():
    transcript.clear()
    yield
    transcript.clear()


def _verify(check_name: str, report: str):
    doc = yaml.safe_load(TASK.read_text(encoding="utf-8"))
    (entry,) = [c for c in doc["verification_spec"] if c.get("name") == check_name]
    transcript.set(report, [], final_message=report)
    return ReportContainsVerifier(**entry["check"]).verify(TIMEOUT_SEC)


def test_expected_answer_passes_both_objectives():
    good = (
        "VERDICT: HOLD-CHANNEL-AND-FIX-MESH-SKEW\n\n"
        "Managed Cloud Service Mesh follows the cluster's GKE release channel, so switching "
        "payments-prod from no release channel to STABLE can downgrade the managed mesh "
        "control plane below running 1.20 istio-proxy sidecars (for example to 1.19).\n\n"
        "On the failing peer cluster, the older control plane pushes incompatible Listener xDS "
        "config that 1.20 sidecars reject in an unbounded NACK reject-and-retry loop, leaking "
        "Envoy memory until istio-proxy is OOMKilled and ingress gateways return 503 UH "
        "no_healthy_upstream. Raising memory limits to 1Gi only delays OOMKill and will not "
        "fix the underlying loop.\n\n"
        "Pre-change read-only checks:\n"
        "1. Run `mesh_skew_check.py` (or inspect `istiod`, `ControlPlaneRevision`, and "
        "`istio.io/rev` against running `istio-proxy` images).\n"
        "2. Have an operator run `gcloud container fleet mesh describe --project <host>`.\n\n"
        "Fix: align the release channel / managed mesh control-plane revision at or above 1.20 "
        "and restart affected workloads so newly injected sidecars match the control plane."
    )
    for name in (CHECK_ROOT_CAUSE, CHECK_PRECHANGE):
        res = _verify(name, good)
        assert res.success, f"{name} failed: {res.reason}"


def test_wrong_verdict_fails():
    bad = (
        "VERDICT: RAISE-MEMORY-AND-SWITCH-CHANNEL\n\n"
        "Raising memory limits to 1Gi will fix the OOM and you can switch to STABLE."
    )
    assert not _verify(CHECK_ROOT_CAUSE, bad).success


def test_hedged_verdict_line_fails():
    hedged = (
        "VERDICT: HOLD-CHANNEL-AND-FIX-MESH-SKEW (or maybe raise memory)\n\n"
        "Managed Cloud Service Mesh follows the GKE release channel and can downgrade the "
        "control plane. Raising memory only delays the NACK memory leak."
    )
    assert not _verify(CHECK_ROOT_CAUSE, hedged).success


def test_missing_fleet_mesh_describe_fails_prechange_check():
    missing_fleet = (
        "Run mesh_skew_check.py to compare istiod and istio-proxy, then roll affected pods."
    )
    assert not _verify(CHECK_PRECHANGE, missing_fleet).success


def test_missing_incluster_check_fails_prechange_check():
    missing_incluster = (
        "Have an operator run `gcloud container fleet mesh describe --project p`, then "
        "restart workloads."
    )
    assert not _verify(CHECK_PRECHANGE, missing_incluster).success


def test_missing_workload_rollout_fails_prechange_check():
    missing_rollout = (
        "Run `mesh_skew_check.py` and `gcloud container fleet mesh describe --project p` "
        "before switching the release channel."
    )
    assert not _verify(CHECK_PRECHANGE, missing_rollout).success


def test_missing_memory_limit_rejection_fails_root_cause():
    no_mem_rejection = (
        "VERDICT: HOLD-CHANNEL-AND-FIX-MESH-SKEW\n\n"
        "Managed Cloud Service Mesh follows the GKE release channel and downgrades the "
        "control plane, causing an Envoy xDS NACK loop. Bump the limit to 1Gi just in case."
    )
    assert not _verify(CHECK_ROOT_CAUSE, no_mem_rejection).success


def test_explaining_why_wrong_verdict_does_not_apply_passes():
    explained = (
        "**VERDICT: HOLD-CHANNEL-AND-FIX-MESH-SKEW**\n\n"
        "Do not choose VERDICT: RAISE-MEMORY-AND-SWITCH-CHANNEL because raising memory "
        "limits to 1Gi only delays OOMKill while the Envoy xDS NACK memory leak persists "
        "after a managed Cloud Service Mesh downgrade."
    )
    res = _verify(CHECK_ROOT_CAUSE, explained)
    assert res.success, res.reason


def test_mesh_skew_check_py_alone_satisfies_incluster_check_under_fold_decoration():
    reply = (
        "Run `mesh_skew_check.py` and `gcloud container fleet mesh describe --project p`, "
        "then roll affected workloads so injected sidecars match the control plane."
    )
    res = _verify(CHECK_PRECHANGE, reply)
    assert res.success, res.reason


def test_opposite_memory_advice_with_do_not_switch_fails():
    opposite = (
        "VERDICT: HOLD-CHANNEL-AND-FIX-MESH-SKEW\n\n"
        "Managed Cloud Service Mesh follows the GKE release channel and downgrades the "
        "control plane, driving an Envoy xDS NACK loop.\n"
        "Do not switch channels while OOM kills continue; raise the istio-proxy memory "
        "limit to 1Gi to stop the restarts."
    )
    assert not _verify(CHECK_ROOT_CAUSE, opposite).success


def test_symptom_echo_sidecars_are_restarting_without_rollout_fails():
    echo = (
        "Your 1.20 sidecars are restarting with OOMKilled. Check istiod and run "
        "`gcloud container fleet mesh describe --project p`."
    )
    assert not _verify(CHECK_PRECHANGE, echo).success
