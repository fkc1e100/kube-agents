"""Reproduce harness CUJ3: read-only inventory of kubeagents-system pods, services, CRDs, and nodes."""

from __future__ import annotations

import re
from typing import Any

from cuj.harness.common import (
    FORBIDDEN_OPERATIONS,
    INTERACTION_COMPLETED_MILESTONE,
    KAGE_DELEGATES_MILESTONE,
    SPECIALIST_COMPLETES_MILESTONE,
    SPECIALIST_CREATED_MILESTONE,
    all_visible_text,
    answer_text,
    input_text,
    interaction_blockers,
    non_echo_clauses,
    proxy_leaks,
    read_only_blockers,
    record_delegated_milestones,
    run_harness_scenario,
    within_latency_budget,
)
from cuj.utils.acceptance_criteria import AcceptanceCriteria, AcceptanceCriterion
from cuj.utils.interaction import tool_operations
from cuj.utils.milestones import Milestone, MilestoneSuite
from cuj.utils.scenario import Scenario

SCENARIO_ID = "cuj_harness_03"
HARNESS_NAMESPACE = "kubeagents-system"
HARNESS_CRD_GROUP = "kubeagents.x-k8s.io"
READ_ONLY_MILESTONE = "m4-inventory-remains-read-only"
REQUIRED_INPUT_PHRASES = (
    HARNESS_NAMESPACE,
    "running pods",
    "services",
    HARNESS_CRD_GROUP,
    "node readiness",
)

PROMPT = """Perform a read-only Kubernetes inventory of this host cluster's \
kube-agents harness installation: (1) list the active cluster namespaces \
(confirming kubeagents-system) and report cluster node readiness and the \
Kubernetes server version (v1.x), (2) list the running pods and exposed \
services in the kubeagents-system namespace, and (3) list the installed \
kubeagents.x-k8s.io Custom Resource Definitions (CRDs). Include the \
kubeagents-system pods, services, kubeagents.x-k8s.io CRDs, node Ready \
status, and v1.x version in both the task completion summary and the full \
result. Do not create, modify, or delete any cluster resources."""

HARNESS_WORKLOAD_RE = re.compile(
    r"\b(?:platform-?agent(?:-[a-z0-9-]+)?|inference-gateway|litellm"
    r"|kube-agents-(?:web-console|controller-manager))\b",
    re.IGNORECASE,
)
SERVICE_RE = re.compile(
    r"\b(?:services?|svc|clusterip|loadbalancer|port\s+\d+)\b",
    re.IGNORECASE,
)
NEGATED_WORKLOAD_OR_SERVICE_RE = re.compile(
    r"\b(?:no|none|0|zero|without|missing|absent|empty)\b[^.\n;]{0,60}"
    r"\b(?:pods?|workloads?|services?|svc|running|kubeagents-system)\b"
    r"|\b(?:pods?|workloads?|services?|namespace)\b[^.\n;]{0,40}"
    r"\b(?:not\s+running|do\s+not\s+exist|doesn't\s+exist|is\s+empty|are\s+empty|missing|absent)\b",
    re.IGNORECASE,
)
CRD_RE = re.compile(
    r"\b(?:platformagents|agentprofiles|agentplugins)\.kubeagents\.x-k8s\.io\b",
    re.IGNORECASE,
)
PAREN_GROUP_RE = re.compile(r"\([^)]*\)")
NEGATED_CRD_BEFORE_RE = re.compile(
    r"\b(?:no|not|none|never|neither|without|lacks?|missing|absent"
    r"|failed\s+to\s+(?:find|list|get)|unable\s+to\s+(?:find|list|get)"
    r"|0\s+(?:installed\s+)?crds?)\b[^\n;()]{0,120}\Z",
    re.IGNORECASE,
)
NEGATED_CRD_AFTER_RE = re.compile(
    r"\A[^\n;()]{0,80}\b(?:do\s+not\s+exist|doesn't\s+exist|not\s+installed"
    r"|not\s+found|was\s+never\s+installed|were\s+never\s+installed"
    r"|is\s+missing|are\s+missing|is\s+absent|are\s+absent)\b",
    re.IGNORECASE,
)
K8S_VERSION_RE = re.compile(
    r"\bv1\.\d+(?:\.\d+)?(?:-[a-z0-9.+_-]+)?\b",
    re.IGNORECASE,
)
NODE_RE = re.compile(r"\bnodes?\b", re.IGNORECASE)
NEGATED_NODE_READY_RE = re.compile(
    r"\b(?:no|not|none(?:\s+of)?|never|0|zero)\s+"
    r"(?:(?:the|all|three|two|four|\d+|worker|cluster|pool|default|in)\s+){0,8}?"
    r"nodes?\b[^,.\n;]{0,40}\bready\b"
    r"|\bnodes?\b(?:(?!\b(?:pods?|containers?|workloads?)\b)[^,.\n;]){0,40}"
    r"\b(?:not\s+ready|notready|isn't\s+ready|aren't\s+ready|never\s+ready"
    r"|0\s*(?:/\s*\d+\s*)?ready|ready\s*[:=]\s*(?:false|0|no|unknown))\b"
    r"|\b0\s*/\s*\d+\s*(?:nodes?\s+)?ready\b"
    r"|\bready\s*[:=]\s*(?:false|0|no|unknown)\b"
    r"|\bnotready\b",
    re.IGNORECASE,
)
POSITIVE_NODE_READY_RE = re.compile(
    r"\bnodes?\b(?:(?!\b(?:pods?|containers?|workloads?|services?)\b)[^,.\n;]){0,40}"
    r"\b(?!(?:not|no|never|0|zero)\s+ready\b)ready\b"
    r"|\b(?<!not\s)(?<!no\s)(?<!0\s)(?<!zero\s)ready\b"
    r"(?:(?!\b(?:pods?|containers?|workloads?|services?)\b)[^,.\n;]){0,25}\bnodes?\b",
    re.IGNORECASE,
)

ACCEPTANCE_CRITERIA = (
    AcceptanceCriterion(
        "ac01-inventory-request-preserved",
        "The request asks for kubeagents-system pods and services, "
        "kubeagents.x-k8s.io CRDs, and node readiness and version.",
        "projected user input names kubeagents-system, pods, services, "
        "kubeagents.x-k8s.io CRDs, and node readiness",
    ),
    AcceptanceCriterion(
        "ac02-kubeagents-system-pods-and-services-reported",
        "The answer inventories running pods and exposed services in the "
        "kubeagents-system namespace.",
        "delivered answer names kubeagents-system, running harness workloads, "
        "and exposed services in non-negated clauses",
    ),
    AcceptanceCriterion(
        "ac03-kubeagents-crds-reported",
        "The answer lists the installed kube-agents Custom Resource Definitions.",
        "delivered answer names installed *.kubeagents.x-k8s.io CRDs",
    ),
    AcceptanceCriterion(
        "ac04-node-readiness-and-version-reported",
        "The answer reports cluster node readiness and the Kubernetes server "
        "version.",
        "delivered answer reports positive node Ready status and a v1.x "
        "Kubernetes version",
    ),
    AcceptanceCriterion(
        "ac05-inventory-remains-read-only",
        "The inventory check performs no mutations, leaks no internal "
        "LiteLLM proxy aliases, and finishes within the turn latency budget.",
        "complete normalized tool evidence contains no mutating calls, output "
        "contains no model-default or custom provider leak, and turn latency "
        "is within budget",
    ),
)

MILESTONES = (
    Milestone(
        INTERACTION_COMPLETED_MILESTONE,
        "The harness namespace and CRD inventory conversation finishes "
        "successfully.",
        "terminal completed interaction",
    ),
    Milestone(
        KAGE_DELEGATES_MILESTONE,
        "Kage delegates the cluster and harness inventory via kanban_create.",
        "root toolCalls contains a completed kanban_create",
        (INTERACTION_COMPLETED_MILESTONE,),
    ),
    Milestone(
        SPECIALIST_CREATED_MILESTONE,
        "A specialist task is created to inspect the harness namespace and CRDs.",
        "at least one projected specialist task exists",
        (KAGE_DELEGATES_MILESTONE,),
    ),
    Milestone(
        SPECIALIST_COMPLETES_MILESTONE,
        "The delegated specialist inventory task finishes.",
        "at least one specialist task is done after at least one run",
        (SPECIALIST_CREATED_MILESTONE,),
    ),
    Milestone(
        READ_ONLY_MILESTONE,
        "Inspecting the harness namespace, CRDs, and nodes mutates nothing.",
        "complete normalized tool evidence contains no forbidden mutation",
        (INTERACTION_COMPLETED_MILESTONE,),
    ),
)


def _has_positive_node_ready(clauses: list[str]) -> bool:
    for clause in clauses:
        if not NODE_RE.search(clause):
            continue
        if NEGATED_NODE_READY_RE.search(clause):
            continue
        if POSITIVE_NODE_READY_RE.search(clause):
            return True
    return False


def _reported_crds(clauses: list[str]) -> list[str]:
    found: set[str] = set()
    for raw_clause in clauses:
        clause = PAREN_GROUP_RE.sub(" ", raw_clause)
        for match in CRD_RE.finditer(clause):
            prefix = clause[: match.start()]
            suffix = clause[match.end() :]
            if NEGATED_CRD_BEFORE_RE.search(prefix) or NEGATED_CRD_AFTER_RE.search(
                suffix
            ):
                continue
            found.add(match.group(0).casefold())
    return sorted(found)


def _positive_workloads_and_services(
    clauses: list[str],
) -> tuple[bool, list[str], bool]:
    positive_clauses = [
        clause
        for clause in clauses
        if not NEGATED_WORKLOAD_OR_SERVICE_RE.search(clause)
    ]
    positive_text = "\n".join(positive_clauses)
    has_namespace = HARNESS_NAMESPACE in positive_text.casefold()
    workloads = sorted(
        {
            match.group(0).casefold()
            for match in HARNESS_WORKLOAD_RE.finditer(positive_text)
        }
    )
    has_services = bool(SERVICE_RE.search(positive_text))
    return has_namespace, workloads, has_services


def evaluate_acceptance(interaction: dict[str, Any]) -> AcceptanceCriteria:
    _, output_blocker = interaction_blockers(interaction)
    ro_blockers = read_only_blockers(interaction)
    latency_ok, latency_s, budget_s = within_latency_budget(interaction)

    raw_input = input_text(interaction)
    folded_input = raw_input.casefold()

    answer = answer_text(interaction)
    clauses = non_echo_clauses(answer, raw_input)
    non_echo_text = "\n".join(clauses)
    leaks = proxy_leaks(all_visible_text(interaction))
    operations = tool_operations(interaction)
    mutations = sorted(FORBIDDEN_OPERATIONS.intersection(operations))

    has_namespace, workloads, has_services = _positive_workloads_and_services(
        clauses
    )
    crds = _reported_crds(clauses)
    versions = sorted(
        {
            match.group(0).casefold()
            for match in K8S_VERSION_RE.finditer(non_echo_text)
        }
    )
    node_ready = _has_positive_node_ready(clauses)

    suite = AcceptanceCriteria(ACCEPTANCE_CRITERIA)
    suite.record(
        "ac01-inventory-request-preserved",
        all(phrase in folded_input for phrase in REQUIRED_INPUT_PHRASES),
        raw_input,
    )
    suite.record(
        "ac02-kubeagents-system-pods-and-services-reported",
        has_namespace and bool(workloads) and has_services,
        {
            "hasNamespace": has_namespace,
            "workloads": workloads,
            "hasServices": has_services,
            "answer": answer,
        },
        blocked_by=output_blocker,
    )
    suite.record(
        "ac03-kubeagents-crds-reported",
        bool(crds),
        {"crds": crds, "answer": answer},
        blocked_by=output_blocker,
    )
    suite.record(
        "ac04-node-readiness-and-version-reported",
        node_ready and bool(versions),
        {
            "nodeReady": node_ready,
            "versions": versions,
            "answer": answer,
        },
        blocked_by=output_blocker,
    )
    suite.record(
        "ac05-inventory-remains-read-only",
        not mutations and not leaks and not ro_blockers and latency_ok,
        {
            "operations": operations,
            "mutations": mutations,
            "proxyLeaks": leaks,
            "latencySeconds": latency_s,
            "maxLatencySeconds": budget_s,
        },
        blocked_by=() if mutations or leaks else ro_blockers,
    )
    return suite


def evaluate_backend_milestones(interaction: dict[str, Any]) -> MilestoneSuite:
    suite = MilestoneSuite(MILESTONES)
    record_delegated_milestones(
        suite,
        interaction,
        read_only_milestone_id=READ_ONLY_MILESTONE,
    )
    return suite


def build_prompt() -> str:
    return PROMPT


def test_03_harness_namespace_and_crd_inventory() -> None:
    run_harness_scenario(
        Scenario(
            SCENARIO_ID,
            build_prompt,
            evaluate_acceptance,
            evaluate_backend_milestones,
        )
    )
