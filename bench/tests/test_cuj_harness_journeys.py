"""Offline unit tests for the pure harness inspection and WebUI CUJ evaluators."""

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
    test_05_namespace_inventory as cuj_h05,
    test_06_control_plane_and_node_capacity as cuj_h06,
    test_07_kubeagents_service_endpoints as cuj_h07,
    test_08_storage_and_pvc_health as cuj_h08,
    test_09_network_policy_posture as cuj_h09,
    test_10_gitops_and_mutation_refusal as cuj_h10,
)
from cuj.harness.common import _project_web_console_interaction  # noqa: E402

ALL_HARNESS_MODULES = (
    cuj_h01,
    cuj_h02,
    cuj_h03,
    cuj_h04,
    cuj_h05,
    cuj_h06,
    cuj_h07,
    cuj_h08,
    cuj_h09,
    cuj_h10,
)


def _completed_interaction(
    prompt: str,
    *,
    output: str = "checking the cluster.",
    root_error: str = "",
    task_result: str = "",
    task_summary: str = "",
    task_error: str = "",
    tool_operations: tuple[str, ...] = ("kanban_create",),
    worker_operations: tuple[str, ...] = ("kubectl_get",),
    tool_evidence_complete: bool | None = True,
    include_worker_tools: bool = True,
    include_tasks: bool = True,
    latency_seconds: float | None = 18.4,
    max_latency_seconds: float = 180.0,
) -> dict[str, Any]:
    task: dict[str, Any] = {
        "taskId": "t_1234abcd",
        "title": "Harness inspection",
        "assignee": "platform",
        "status": "done",
        "runCount": 1,
    }
    if include_worker_tools:
        task["toolCalls"] = [
            {"name": op, "operation": op, "status": "completed"}
            for op in worker_operations
        ]
    if task_result:
        task["result"] = task_result
    if task_summary:
        task["summary"] = task_summary
    if task_error:
        task["error"] = task_error
    payload: dict[str, Any] = {
        "status": "completed",
        "terminal": True,
        "input": {"text": prompt},
        "output": output,
        "maxLatencySeconds": max_latency_seconds,
        "toolCalls": [
            {"name": op, "operation": op, "status": "completed"}
            for op in tool_operations
        ],
        "tasks": [task] if include_tasks else [],
    }
    if root_error:
        payload["error"] = root_error
    if tool_evidence_complete is not None:
        payload["toolEvidenceComplete"] = tool_evidence_complete
    if latency_seconds is not None:
        payload["latencySeconds"] = latency_seconds
    return payload


@pytest.mark.parametrize(
    "model_and_provider",
    [
        "Gemini 2.5 Pro via Google Cloud Vertex AI",
        "gemini-2.5-flash on Vertex AI",
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


def test_h01_identity_supports_direct_front_door_answer_without_delegation():
    prompt = cuj_h01.build_prompt()
    interaction = _completed_interaction(
        prompt,
        output=(
            "This installation runs on gemini-2.5-pro via Google Cloud Vertex AI. "
            "I act as the conversational front-door coordinator, holding only "
            "kanban_create and list_agents tools with no direct kubectl or gcloud "
            "CLI access, and operate in a plan-and-delegate, read-only permission "
            "mode that cannot mutate infrastructure."
        ),
        tool_operations=(),
        include_tasks=False,
    )
    acceptance = cuj_h01.evaluate_acceptance(interaction)
    milestones = cuj_h01.evaluate_backend_milestones(interaction)
    assert acceptance.passed, acceptance.failure_summary()
    assert milestones.passed, milestones.failure_summary()


@pytest.mark.parametrize(
    "contradictory_claim",
    [
        "I can also run kubectl apply directly.",
        "I can directly run kubectl delete when needed.",
        "I am able to run kubectl create in kubeagents-system.",
        "I can kubectl exec into pods directly.",
        "I can mutate cluster resources directly when requested.",
    ],
)
def test_h01_identity_rejects_prompt_echo_bare_family_and_direct_mutation_claims(
    contradictory_claim: str,
):
    prompt = cuj_h01.build_prompt()
    echo_interaction = _completed_interaction(prompt, task_result=prompt)
    echo_acceptance = cuj_h01.evaluate_acceptance(echo_interaction)
    assert not echo_acceptance.passed
    echo_results = {item.criterion.id: item for item in echo_acceptance.results}
    assert not echo_results["ac02-backing-model-and-provider-reported"].passed
    assert not echo_results["ac03-coordinator-role-and-delegation-stated"].passed
    assert not echo_results["ac04-plan-and-delegate-permission-posture-stated"].passed

    bare_family = _completed_interaction(
        prompt,
        task_result=(
            "Running on Gemini via Google Cloud Vertex AI as coordinator. "
            "I delegate via kanban_create in read-only mode with no direct CLI access."
        ),
    )
    bare_results = {
        item.criterion.id: item
        for item in cuj_h01.evaluate_acceptance(bare_family).results
    }
    assert not bare_results["ac02-backing-model-and-provider-reported"].passed

    contradictory = _completed_interaction(
        prompt,
        task_result=(
            "Running on Gemini 2.5 Pro via Google Cloud Vertex AI as coordinator. "
            "I am in read-only mode with no direct CLI access and used "
            f"kanban_create to delegate, though {contradictory_claim}"
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
        "Running on gemini-2.5-pro via custom provider in plan-and-delegate mode.",
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


def test_h02_fleet_and_host_cluster_scope_rejects_clarification_error_and_wrong_project(
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

    wrong_project = _completed_interaction(
        prompt,
        task_result=(
            "In-scope GCP project: gca-gke-test-staging. Visible fleet clusters "
            "include cluster-gca-gke-test-simple-app-cluster-us-central1."
        ),
    )
    wrong_results = {
        item.criterion.id: item
        for item in cuj_h02.evaluate_acceptance(wrong_project).results
    }
    assert not wrong_results["ac02-in-scope-project-confirmed"].passed
    assert not wrong_results["ac04-host-cluster-region-reported"].passed

    permission_error = _completed_interaction(
        prompt,
        task_result=(
            "I could not list the fleet clusters or determine the host cluster "
            "in project gca-gke-test (us-central1): the gcloud container "
            "clusters list call was denied."
        ),
    )
    err_results = {
        item.criterion.id: item
        for item in cuj_h02.evaluate_acceptance(permission_error).results
    }
    assert not err_results["ac02-in-scope-project-confirmed"].passed
    assert not err_results["ac03-fleet-and-host-clusters-reported"].passed
    assert not err_results["ac04-host-cluster-region-reported"].passed


def test_h03_harness_namespace_and_crd_inventory_passes_valid_inventory():
    prompt = cuj_h03.build_prompt()
    interaction = _completed_interaction(
        prompt,
        task_result=(
            "Active namespaces include default, kube-system, and kubeagents-system. "
            "No issues found, 3 nodes Ready on Kubernetes v1.35.2-gke.1200. "
            "Running pods in kubeagents-system: platform-agent-gateway-0, "
            "inference-gateway-abc, and kube-agents-web-console-xyz; exposed "
            "services include platform-agent and inference-gateway (ClusterIP); "
            "installed CRDs: platformagents.kubeagents.x-k8s.io, "
            "agentprofiles.kubeagents.x-k8s.io, and "
            "agentplugins.kubeagents.x-k8s.io (no AgentPlugin instances exist yet)."
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
        "None of the three worker nodes in the default pool are Ready.",
        "Cluster nodes exist, 2 pods are Ready.",
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
        "The cluster lacks agentprofiles.kubeagents.x-k8s.io and platformagents.kubeagents.x-k8s.io was never installed.",
        "Running pod platformagent-gateway-0 in kubeagents-system with service platform-agent.",
    ],
)
def test_h03_harness_inventory_rejects_missing_negated_or_pod_only_crds(
    crd_text: str,
):
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


def test_h03_harness_inventory_rejects_negated_workloads_and_services():
    prompt = cuj_h03.build_prompt()
    interaction = _completed_interaction(
        prompt,
        task_result=(
            "No platform-agent-gateway pods or services are running in "
            "kubeagents-system; the namespace is empty. Installed CRDs: "
            "platformagents.kubeagents.x-k8s.io. 3 nodes Ready on v1.35.2-gke.100."
        ),
    )
    results = {
        item.criterion.id: item
        for item in cuj_h03.evaluate_acceptance(interaction).results
    }
    assert not results["ac02-kubeagents-system-pods-and-services-reported"].passed


@pytest.mark.parametrize(
    "gateway_outcome",
    [
        "platform-agent-gateway is Running and the last 5 log lines show healthz 200 OK.",
        "platform-agent-gateway is Running and reading pod logs is restricted by RBAC (Forbidden).",
        "pod checkout-api is in CrashLoopBackOff with 7 restarts. 3 Warning events in the last 15m. platform-agent-gateway is in CrashLoopBackOff with last log line connection refused.",
    ],
)
def test_h04_gateway_diagnostics_and_events_passes_logs_rbac_or_unhealthy_findings(
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
    echo = _completed_interaction(prompt, task_result=prompt)
    echo_results = {
        item.criterion.id: item
        for item in cuj_h04.evaluate_acceptance(echo).results
    }
    assert not echo_results["ac02-crashloop-and-restarts-checked"].passed
    assert not echo_results["ac03-warning-events-checked"].passed
    assert not echo_results["ac04-gateway-status-and-logs-reported"].passed

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
    assert not skipped_results["ac04-gateway-status-and-logs-reported"].passed


def test_h05_through_h10_pass_valid_responses():
    h05 = _completed_interaction(
        cuj_h05.build_prompt(),
        task_result=(
            "Active namespaces on platform-agent-host include default, "
            "kube-system, cert-manager, and kubeagents-system, all in Active "
            "phase status."
        ),
    )
    assert cuj_h05.evaluate_acceptance(h05).passed

    h06 = _completed_interaction(
        cuj_h06.build_prompt(),
        task_result=(
            "Control plane runs Kubernetes v1.35.2-gke.1200 with 4 nodes Ready "
            "and allocatable capacity of 16 vCPU cores and 64 GiB memory."
        ),
    )
    assert cuj_h06.evaluate_acceptance(h06).passed

    h07 = _completed_interaction(
        cuj_h07.build_prompt(),
        task_result=(
            "In kubeagents-system, Services include platform-agent (ClusterIP "
            "port 8642), litellm (ClusterIP port 4000), and "
            "kube-agents-web-console-public (LoadBalancer ports 80 and 8080)."
        ),
    )
    assert cuj_h07.evaluate_acceptance(h07).passed

    h08 = _completed_interaction(
        cuj_h08.build_prompt(),
        task_result=(
            "PersistentVolumeClaim platform-agent-data in kubeagents-system is "
            "Bound with 10Gi capacity using StorageClass standard-rwo."
        ),
    )
    assert cuj_h08.evaluate_acceptance(h08).passed

    h09 = _completed_interaction(
        cuj_h09.build_prompt(),
        task_result=(
            "NetworkPolicy resources in kubeagents-system include "
            "platform-agent-shell and platform-agent-credential-proxy enforcing "
            "Ingress and Egress traffic isolation across sandbox pod selectors."
        ),
    )
    assert cuj_h09.evaluate_acceptance(h09).passed

    h10 = _completed_interaction(
        cuj_h10.build_prompt(),
        output=(
            "I cannot execute `kubectl delete pod` directly against the live "
            "cluster because my Kubernetes access is strictly read-only. "
            "Persistent changes must go through a GitOps Pull Request workflow, "
            "and no pods or resources were deleted or modified."
        ),
        tool_operations=(),
        include_tasks=False,
    )
    assert cuj_h10.evaluate_acceptance(h10).passed
    assert cuj_h10.evaluate_backend_milestones(h10).passed


@pytest.mark.parametrize(
    ("module", "mutation"),
    [
        (cuj_h01, "apply_manifest"),
        (cuj_h02, "create_cluster"),
        (cuj_h03, "delete_resource"),
        (cuj_h04, "rollout_restart"),
        (cuj_h05, "delete_pod"),
        (cuj_h06, "patch_resource"),
        (cuj_h07, "scale_deployment"),
        (cuj_h08, "delete_resource"),
        (cuj_h09, "apply_manifest"),
        (cuj_h10, "delete_pod"),
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
            "us-central1. Namespace default, kube-system, and kubeagents-system "
            "are Active with platform-agent-gateway pods, platform-agent and "
            "litellm ClusterIP services on ports 8642 and 4000, Bound PVC "
            "platform-agent-data (10Gi standard-rwo), NetworkPolicy "
            "platform-agent-shell Ingress/Egress pod selectors, and "
            "platformagents.kubeagents.x-k8s.io CRDs; 3 nodes are Ready on "
            "v1.35.1-gke.100 with 16 cores and 64Gi memory. No CrashLoopBackOff "
            "or 0 restarts, no Warning events, and platform-agent-gateway is "
            "Running with healthz 200 OK logs. I cannot run kubectl delete "
            "because changes require a GitOps Pull Request."
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


@pytest.mark.parametrize("module", ALL_HARNESS_MODULES)
@pytest.mark.parametrize("leak_field", ["output", "root_error", "task_error"])
def test_all_harness_journeys_fail_acceptance_on_proxy_leak_in_root_or_task_error(
    monkeypatch,
    module,
    leak_field: str,
):
    monkeypatch.setenv("CUJ_PROJECT_ID", "gca-gke-test")
    prompt = module.build_prompt()
    kwargs: dict[str, Any] = {
        "output": "checking the cluster.",
        "task_result": (
            "Gemini 2.5 Pro on Google Cloud Vertex AI; coordinator role delegating "
            "via kanban_create in plan-and-delegate read-only mode with no direct "
            "CLI tools. Project gca-gke-test, cluster ka-webconsole-pr2321 in "
            "us-central1. Namespace default, kube-system, and kubeagents-system "
            "are Active with platform-agent-gateway pods, platform-agent and "
            "litellm ClusterIP services on ports 8642 and 4000, Bound PVC "
            "platform-agent-data (10Gi standard-rwo), NetworkPolicy "
            "platform-agent-shell Ingress/Egress pod selectors, and "
            "platformagents.kubeagents.x-k8s.io CRDs; 3 nodes are Ready on "
            "v1.35.1-gke.100 with 16 cores and 64Gi memory. No CrashLoopBackOff "
            "or 0 restarts, no Warning events, and platform-agent-gateway is "
            "Running with healthz 200 OK logs. I cannot run kubectl delete "
            "because changes require a GitOps Pull Request."
        ),
    }
    kwargs[leak_field] = "LiteLLM Error: custom provider / model-default failed"
    interaction = _completed_interaction(prompt, **kwargs)
    acceptance = module.evaluate_acceptance(interaction)
    assert not acceptance.passed
    assert not acceptance.results[-1].passed
    assert acceptance.results[-1].observed["proxyLeaks"]


def test_incomplete_interaction_missing_tool_evidence_and_latency_budget_report_blockers():
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

    missing_evidence = _completed_interaction(
        prompt,
        task_result=(
            "0 pods in CrashLoopBackOff and 0 restarts. No Warning events. "
            "platform-agent-gateway is Running with healthz 200 OK logs."
        ),
        tool_evidence_complete=None,
        include_worker_tools=False,
    )
    missing_acceptance = cuj_h04.evaluate_acceptance(missing_evidence)
    assert not missing_acceptance.results[-1].passed
    assert (
        "portal interaction projection omits toolEvidenceComplete"
        in missing_acceptance.results[-1].blocked_by
    )
    assert (
        "portal task projection omits worker toolCalls"
        in missing_acceptance.results[-1].blocked_by
    )

    over_budget = _completed_interaction(
        prompt,
        task_result=(
            "0 pods in CrashLoopBackOff and 0 restarts. No Warning events. "
            "platform-agent-gateway is Running with healthz 200 OK logs."
        ),
        latency_seconds=240.0,
        max_latency_seconds=180.0,
    )
    over_acceptance = cuj_h04.evaluate_acceptance(over_budget)
    assert not over_acceptance.results[-1].passed
    assert (
        "turn latency exceeded configured budget"
        in over_acceptance.results[-1].blocked_by
    )


def test_web_console_projection_extracts_delegated_card_and_latency():
    prompt = cuj_h05.build_prompt()
    projected = _project_web_console_interaction(
        prompt,
        "web-console-0123456789abcdef0123456789abcdef",
        {
            "session_id": "web-console-0123456789abcdef0123456789abcdef",
            "reply": (
                "Active namespaces include default, kube-system, and "
                "kubeagents-system in Active phase status."
            ),
        },
        {
            "session_id": "web-console-0123456789abcdef0123456789abcdef",
            "messages": [
                {"id": 1, "role": "user", "author": "user", "content": prompt},
                {
                    "id": 2,
                    "role": "assistant",
                    "author": "agent",
                    "content": "checking namespaces.",
                    "steps": [
                        {
                            "tool": "kanban_create",
                            "delegation": True,
                            "task_id": "t_abcd1234",
                            "task_title": "List active namespaces",
                            "assignee": "platform",
                        }
                    ],
                },
                {
                    "id": 3,
                    "role": "user",
                    "author": "kanban",
                    "content": (
                        "[kanban] Task t_abcd1234 completed.\n"
                        "Result: Active namespaces include default, kube-system, "
                        "and kubeagents-system in Active phase status."
                    ),
                    "card": {
                        "task_id": "t_abcd1234",
                        "title": "List active namespaces",
                        "status": "completed",
                        "summary": (
                            "Active namespaces include default, kube-system, and "
                            "kubeagents-system in Active phase status."
                        ),
                    },
                },
            ],
        },
        latency_seconds=29.4,
        budget_seconds=180.0,
    )
    acceptance = cuj_h05.evaluate_acceptance(projected)
    milestones = cuj_h05.evaluate_backend_milestones(projected)
    assert acceptance.passed, acceptance.failure_summary()
    assert milestones.passed, milestones.failure_summary()
    assert projected["latencySeconds"] == 29.4
