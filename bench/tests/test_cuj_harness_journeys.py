"""Offline unit tests for the pure harness inspection CUJ evaluators."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

BENCH_ROOT = Path(__file__).resolve().parents[1]
if str(BENCH_ROOT) not in sys.path:
    sys.path.insert(0, str(BENCH_ROOT))

import pytest

from cuj.harness import (  # noqa: E402
    test_01_identity_and_permission_posture as cuj_h01,
    test_02_fleet_and_host_cluster_scope as cuj_h02,
    test_03_harness_namespace_and_crd_inventory as cuj_h03,
    test_04_gateway_diagnostics_and_events as cuj_h04,
)


def _completed_interaction(
    prompt: str,
    *,
    output: str = "checking the cluster.",
    task_result: str = "",
    task_summary: str = "",
    task_error: str = "",
    tool_operations: tuple[str, ...] = ("kanban_create",),
    worker_operations: tuple[str, ...] = ("kubectl_get",),
    tool_evidence_complete: bool = True,
) -> dict[str, Any]:
    task: dict[str, Any] = {
        "taskId": "t_1234abcd",
        "title": "Harness inspection",
        "assignee": "platform",
        "status": "done",
        "runCount": 1,
        "toolCalls": [
            {"name": op, "operation": op, "status": "completed"}
            for op in worker_operations
        ],
    }
    if task_result:
        task["result"] = task_result
    if task_summary:
        task["summary"] = task_summary
    if task_error:
        task["error"] = task_error
    return {
        "status": "completed",
        "terminal": True,
        "input": {"text": prompt},
        "output": output,
        "toolEvidenceComplete": tool_evidence_complete,
        "toolCalls": [
            {"name": op, "operation": op, "status": "completed"}
            for op in tool_operations
        ],
        "tasks": [task],
    }


@pytest.mark.parametrize(
    "model_and_provider",
    [
        "Gemini 2.5 Pro via Google Cloud Vertex AI",
        "Claude Sonnet 4.6 via Anthropic",
        "gpt-5.4 via OpenAI",
    ],
)
def test_h01_identity_and_permission_posture_passes_clean_response(
    model_and_provider: str,
):
    prompt = cuj_h01.build_prompt()
    interaction = _completed_interaction(
        prompt,
        task_result=(
            f"This installation runs on {model_and_provider}. "
            "I act as the conversational front-door coordinator, holding only "
            "kanban_create and list_agents tools with no direct kubectl or gcloud "
            "CLI access, and operate in a plan-and-delegate, read-only permission "
            "mode that cannot mutate infrastructure."
        ),
    )
    acceptance = cuj_h01.evaluate_acceptance(interaction)
    milestones = cuj_h01.evaluate_backend_milestones(interaction)
    assert acceptance.passed, acceptance.failure_summary()
    assert milestones.passed, milestones.failure_summary()


def test_h01_identity_rejects_prompt_echo_and_direct_mutation_claims():
    prompt = cuj_h01.build_prompt()
    echo_interaction = _completed_interaction(prompt, task_result=prompt)
    echo_acceptance = cuj_h01.evaluate_acceptance(echo_interaction)
    assert not echo_acceptance.passed
    echo_results = {item.criterion.id: item for item in echo_acceptance.results}
    assert not echo_results["ac03-coordinator-role-and-delegation-stated"].passed
    assert not echo_results["ac04-plan-and-delegate-permission-posture-stated"].passed

    contradictory = _completed_interaction(
        prompt,
        task_result=(
            "Running on Gemini 2.5 Pro via Google Cloud Vertex AI as coordinator. "
            "I am in read-only mode and used kanban_create to delegate, though "
            "I can also run kubectl apply directly."
        ),
    )
    contradictory_acceptance = cuj_h01.evaluate_acceptance(contradictory)
    contradictory_results = {
        item.criterion.id: item for item in contradictory_acceptance.results
    }
    assert not contradictory_results[
        "ac04-plan-and-delegate-permission-posture-stated"
    ].passed


@pytest.mark.parametrize(
    "leak_text",
    [
        "Running on model-default via Google Cloud Vertex AI as coordinator.",
        "Running on Gemini via custom provider in plan-and-delegate mode.",
        "Configured with provider: custom and model_default behind the gateway.",
    ],
)
def test_h01_identity_rejects_internal_litellm_proxy_leaks(leak_text: str):
    prompt = cuj_h01.build_prompt()
    interaction = _completed_interaction(
        prompt,
        task_result=(
            f"{leak_text} I am the front-door coordinator and delegate via "
            "kanban_create in read-only, plan-and-delegate mode with no direct "
            "infrastructure tools."
        ),
    )
    acceptance = cuj_h01.evaluate_acceptance(interaction)
    milestones = cuj_h01.evaluate_backend_milestones(interaction)
    assert not acceptance.passed
    results = {item.criterion.id: item for item in acceptance.results}
    assert not results["ac02-backing-model-and-provider-reported"].passed
    assert not results["ac05-inspection-remains-read-only"].passed
    milestone_map = {item.milestone.id: item for item in milestones.results}
    assert not milestone_map["m4-no-internal-proxy-leak"].passed


def test_h02_fleet_and_host_cluster_scope_requires_project_env(monkeypatch):
    monkeypatch.delenv("CUJ_PROJECT_ID", raising=False)
    with pytest.raises(ValueError, match="CUJ_PROJECT_ID"):
        cuj_h02.build_prompt()


def test_h02_fleet_and_host_cluster_scope_passes_and_supports_summary_projection(
    monkeypatch,
):
    monkeypatch.setenv("CUJ_PROJECT_ID", "gca-gke-test")
    prompt = cuj_h02.build_prompt()
    assert "gca-gke-test" in prompt

    interaction = _completed_interaction(
        prompt,
        task_summary=(
            "In-scope GCP project: gca-gke-test. Visible fleet clusters include "
            "ka-webconsole-pr2321 (host cluster) running in gca-gke-test in "
            "region us-central1."
        ),
    )
    acceptance = cuj_h02.evaluate_acceptance(interaction)
    milestones = cuj_h02.evaluate_backend_milestones(interaction)
    assert acceptance.passed, acceptance.failure_summary()
    assert milestones.passed, milestones.failure_summary()


def test_h02_fleet_and_host_cluster_scope_rejects_clarification_loop_and_wrong_project(
    monkeypatch,
):
    monkeypatch.setenv("CUJ_PROJECT_ID", "gca-gke-test")
    prompt = cuj_h02.build_prompt()
    interaction = _completed_interaction(
        prompt,
        task_result="Which cluster did you mean? Please specify a project and region.",
    )
    acceptance = cuj_h02.evaluate_acceptance(interaction)
    assert not acceptance.passed
    results = {item.criterion.id: item for item in acceptance.results}
    assert not results["ac02-in-scope-project-confirmed"].passed
    assert not results["ac03-fleet-and-host-clusters-reported"].passed
    assert not results["ac04-host-cluster-region-reported"].passed


def test_h03_harness_namespace_and_crd_inventory_passes_valid_inventory():
    prompt = cuj_h03.build_prompt()
    interaction = _completed_interaction(
        prompt,
        task_result=(
            "Active namespaces include default, kube-system, and kubeagents-system. "
            "All 3 cluster nodes are Ready on Kubernetes v1.35.2-gke.1200. "
            "Running pods in kubeagents-system: platformagent-gateway-0, "
            "inference-gateway-abc, and kube-agents-web-console-xyz; exposed "
            "services include platform-agent and inference-gateway (ClusterIP); "
            "0 errors in kubeagents-system; installed CRDs: "
            "platformagents.kubeagents.x-k8s.io, agentprofiles.kubeagents.x-k8s.io, "
            "and agentplugins.kubeagents.x-k8s.io."
        ),
    )
    acceptance = cuj_h03.evaluate_acceptance(interaction)
    milestones = cuj_h03.evaluate_backend_milestones(interaction)
    assert acceptance.passed, acceptance.failure_summary()
    assert milestones.passed, milestones.failure_summary()


@pytest.mark.parametrize(
    "node_text",
    [
        "nodes are NotReady and 0 Ready.",
        "Running pods in kubeagents-system are Ready. No nodes are Ready.",
        "Running pods in kubeagents-system are Ready. Cluster nodes have Ready=False.",
        "All pods in kubeagents-system are Ready, while cluster nodes are NotReady.",
        "Summary: 2/2 pods Ready; nodes: 0/3 Ready.",
        "Cluster nodes report Ready=Unknown (kubelet stopped posting status).",
    ],
)
def test_h03_harness_inventory_rejects_negated_or_unknown_node_readiness(
    node_text: str,
):
    prompt = cuj_h03.build_prompt()
    interaction = _completed_interaction(
        prompt,
        task_result=(
            "In kubeagents-system, platform-agent-gateway and services are present "
            "alongside platformagents.kubeagents.x-k8s.io CRDs on v1.35.2-gke.100. "
            f"{node_text}"
        ),
    )
    acceptance = cuj_h03.evaluate_acceptance(interaction)
    results = {item.criterion.id: item for item in acceptance.results}
    assert not results["ac04-node-readiness-and-version-reported"].passed


@pytest.mark.parametrize(
    "crd_text",
    [
        "kubeagents-system namespace and kubeagents.x-k8s.io CRDs do not exist on this cluster.",
        "No platformagents.kubeagents.x-k8s.io, agentprofiles.kubeagents.x-k8s.io, or agentplugins.kubeagents.x-k8s.io CRDs are installed.",
        "platformagents.kubeagents.x-k8s.io do not exist.",
    ],
)
def test_h03_harness_inventory_rejects_missing_or_negated_crds(crd_text: str):
    prompt = cuj_h03.build_prompt()
    interaction = _completed_interaction(
        prompt,
        task_result=(
            "Kubernetes inventory completed: Server version is v1.35.8-gke.1439001, "
            f"3 nodes are Ready, {crd_text}"
        ),
    )
    acceptance = cuj_h03.evaluate_acceptance(interaction)
    results = {item.criterion.id: item for item in acceptance.results}
    assert not results["ac03-kubeagents-crds-reported"].passed
    assert results["ac04-node-readiness-and-version-reported"].passed


@pytest.mark.parametrize(
    "gateway_outcome",
    [
        "platform-agent-gateway is Running and the last 5 log lines show healthz 200 OK.",
        "platform-agent-gateway is Running; reading pod logs is restricted by RBAC (Forbidden).",
    ],
)
def test_h04_gateway_diagnostics_and_events_passes_logs_or_rbac_boundary(
    gateway_outcome: str,
):
    prompt = cuj_h04.build_prompt()
    interaction = _completed_interaction(
        prompt,
        task_result=(
            "Audited all namespaces: 0 pods are in CrashLoopBackOff and all "
            "containers have 0 restarts. Checked cluster events from the last "
            f"15 minutes: no Warning events found. {gateway_outcome}"
        ),
    )
    acceptance = cuj_h04.evaluate_acceptance(interaction)
    milestones = cuj_h04.evaluate_backend_milestones(interaction)
    assert acceptance.passed, acceptance.failure_summary()
    assert milestones.passed, milestones.failure_summary()


def test_h04_gateway_diagnostics_rejects_prompt_echo_clarification_and_skipped_checks():
    prompt = cuj_h04.build_prompt()
    refusal = _completed_interaction(
        prompt,
        task_result=(
            "I cannot check for CrashLoopBackOff or restart counts, Warning events, "
            "or platform-agent-gateway log lines until you confirm which cluster "
            "to inspect."
        ),
    )
    acceptance = cuj_h04.evaluate_acceptance(refusal)
    assert not acceptance.passed
    results = {item.criterion.id: item for item in acceptance.results}
    assert not results["ac02-crashloop-and-restarts-checked"].passed
    assert not results["ac03-warning-events-checked"].passed
    assert not results["ac04-gateway-status-and-logs-reported"].passed

    skipped = _completed_interaction(
        prompt,
        task_result=(
            "Warning events were not checked; CrashLoopBackOff and restarts were "
            "skipped. platform-agent-gateway is Running and healthy."
        ),
    )
    skipped_acceptance = cuj_h04.evaluate_acceptance(skipped)
    skipped_results = {
        item.criterion.id: item for item in skipped_acceptance.results
    }
    assert not skipped_results["ac02-crashloop-and-restarts-checked"].passed
    assert not skipped_results["ac03-warning-events-checked"].passed
    assert skipped_results["ac04-gateway-status-and-logs-reported"].passed


@pytest.mark.parametrize(
    ("module", "mutation"),
    [
        (cuj_h01, "apply_manifest"),
        (cuj_h02, "create_cluster"),
        (cuj_h03, "delete_resource"),
        (cuj_h04, "rollout_restart"),
    ],
)
def test_all_harness_journeys_fail_acceptance_and_milestones_on_mutating_tools(
    monkeypatch,
    module,
    mutation: str,
):
    monkeypatch.setenv("CUJ_PROJECT_ID", "gca-gke-test")
    prompt = module.build_prompt()
    interaction = _completed_interaction(
        prompt,
        task_result=(
            "Gemini 2.5 Pro on Google Cloud Vertex AI; coordinator role delegating "
            "via kanban_create in plan-and-delegate read-only mode with no direct "
            "CLI tools. Project gca-gke-test, cluster ka-webconsole-pr2321 in "
            "us-central1. Namespace kubeagents-system has platform-agent-gateway "
            "pods, services, and platformagents.kubeagents.x-k8s.io CRDs; nodes "
            "are Ready on v1.35.1-gke.100. No CrashLoopBackOff or 0 restarts, no "
            "Warning events, and platform-agent-gateway is Running and healthy."
        ),
        worker_operations=("kubectl_get", mutation),
    )
    acceptance = module.evaluate_acceptance(interaction)
    milestones = module.evaluate_backend_milestones(interaction)
    assert not acceptance.passed
    assert not acceptance.results[-1].passed
    assert mutation in acceptance.results[-1].observed["mutations"]
    assert not milestones.results[-1].passed
    assert milestones.results[-1].blocked_by == ()


@pytest.mark.parametrize("module", [cuj_h01, cuj_h02, cuj_h03, cuj_h04])
def test_all_harness_journeys_fail_acceptance_on_proxy_leak_in_root_or_task_error(
    monkeypatch,
    module,
):
    monkeypatch.setenv("CUJ_PROJECT_ID", "gca-gke-test")
    prompt = module.build_prompt()
    interaction = _completed_interaction(
        prompt,
        output="checking the cluster.",
        task_error="LiteLLM Error: custom provider / model-default failed",
        task_result=(
            "Gemini 2.5 Pro on Google Cloud Vertex AI; coordinator role delegating "
            "via kanban_create in plan-and-delegate read-only mode with no direct "
            "CLI tools. Project gca-gke-test, cluster ka-webconsole-pr2321 in "
            "us-central1. Namespace kubeagents-system has platform-agent-gateway "
            "pods, services, and platformagents.kubeagents.x-k8s.io CRDs; nodes "
            "are Ready on v1.35.1-gke.100. No CrashLoopBackOff or 0 restarts, no "
            "Warning events, and platform-agent-gateway is Running and healthy."
        ),
    )
    acceptance = module.evaluate_acceptance(interaction)
    assert not acceptance.passed
    assert not acceptance.results[-1].passed
    assert acceptance.results[-1].observed["proxyLeaks"]


def test_incomplete_interaction_and_missing_tool_evidence_report_blockers():
    prompt = cuj_h04.build_prompt()
    incomplete = {
        "status": "timed_out",
        "terminal": True,
        "input": {"text": prompt},
    }
    acceptance = cuj_h04.evaluate_acceptance(incomplete)
    assert not acceptance.passed
    for item in acceptance.results[1:]:
        assert "interaction did not complete successfully" in item.blocked_by

    ack_only_output = {
        "status": "completed",
        "terminal": True,
        "input": {"text": prompt},
        "output": "checking the cluster.",
        "toolEvidenceComplete": True,
        "toolCalls": [
            {"name": "kanban_create", "operation": "kanban_create", "status": "completed"}
        ],
        "tasks": [],
    }
    empty_acceptance = cuj_h04.evaluate_acceptance(ack_only_output)
    assert not empty_acceptance.results[-1].passed
    assert (
        "portal interaction projection omits output"
        in empty_acceptance.results[-1].blocked_by
    )
    empty_milestones = cuj_h04.evaluate_backend_milestones(ack_only_output)
    assert not empty_milestones.results[-1].passed
    assert (
        "portal task projection omits worker toolCalls"
        in empty_milestones.results[-1].blocked_by
    )
