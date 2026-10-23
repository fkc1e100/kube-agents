"""Reproduce harness CUJ2: fleet and host cluster GCP project and region scope."""

from __future__ import annotations

import os
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
    has_clarification_or_refusal,
    input_text,
    interaction_blockers,
    proxy_leaks,
    record_delegated_milestones,
)
from cuj.utils.acceptance_criteria import AcceptanceCriteria, AcceptanceCriterion
from cuj.utils.interaction import tool_operations
from cuj.utils.milestones import Milestone, MilestoneSuite
from cuj.utils.scenario import Scenario, required_env

SCENARIO_ID = "cuj_harness_02"
PROJECT_ID_ENV = "CUJ_PROJECT_ID"
READ_ONLY_MILESTONE = "m4-scope-check-remains-read-only"
MIN_SCOPE_ANSWER_CHARS = 20
REQUIRED_INPUT_PHRASES = (
    "gke clusters",
    "host cluster",
    "region",
)

PROMPT = """Inspect the fleet and host cluster scope for this kube-agents \
installation in project {project_id}: (1) confirm the GCP projects currently \
in scope, (2) list the GKE clusters visible across the fleet in {project_id}, \
and (3) identify the host cluster name, its GCP project, and its GCP region \
or location. Include the in-scope project ID, visible fleet clusters, host \
cluster name, and GCP region in both the task completion summary and the full \
result. This is a read-only scope check: do not create, modify, or delete any \
resources."""

GCP_LOCATION_RE = re.compile(
    r"\b(?:us|europe|asia|northamerica|southamerica|australia|me|africa)"
    r"-[a-z]+\d+(?:-[a-z])?\b",
    re.IGNORECASE,
)
PROMPT_PROJECT_RE = re.compile(
    r"\bin\s+project\s+([a-z][a-z0-9-]{4,61})\b",
    re.IGNORECASE,
)
CLUSTER_SCOPE_RE = re.compile(r"\b(?:clusters?|fleet|host)\b", re.IGNORECASE)

ACCEPTANCE_CRITERIA = (
    AcceptanceCriterion(
        "ac01-scope-request-preserved",
        "The request asks for in-scope GCP projects, visible GKE fleet "
        "clusters, and the host cluster project and region.",
        "projected user input names the target project ID, fleet clusters, "
        "host cluster, and region",
    ),
    AcceptanceCriterion(
        "ac02-in-scope-project-confirmed",
        "The answer confirms the target GCP project is in scope.",
        "delivered answer names the configured GCP project ID",
    ),
    AcceptanceCriterion(
        "ac03-fleet-and-host-clusters-reported",
        "The answer reports the visible GKE fleet clusters and identifies the "
        "host cluster.",
        "delivered answer reports fleet/host cluster scope without asking "
        "which cluster was meant",
    ),
    AcceptanceCriterion(
        "ac04-host-cluster-region-reported",
        "The answer reports the GCP region or zone where the host cluster is "
        "located.",
        "delivered answer contains a valid GCP region or zone identifier",
    ),
    AcceptanceCriterion(
        "ac05-scope-check-remains-read-only",
        "The fleet and host scope check performs no mutations and leaks no "
        "internal LiteLLM proxy aliases.",
        "recorded tool operations contain no mutating calls and output "
        "contains no model-default or custom provider leak",
    ),
)

MILESTONES = (
    Milestone(
        INTERACTION_COMPLETED_MILESTONE,
        "The fleet and host cluster scope conversation finishes successfully.",
        "terminal completed interaction",
    ),
    Milestone(
        KAGE_DELEGATES_MILESTONE,
        "Kage delegates the fleet and host cluster scope inspection via "
        "kanban_create.",
        "root toolCalls contains a completed kanban_create",
        (INTERACTION_COMPLETED_MILESTONE,),
    ),
    Milestone(
        SPECIALIST_CREATED_MILESTONE,
        "A specialist task is created to inspect fleet and host cluster scope.",
        "at least one projected specialist task exists",
        (KAGE_DELEGATES_MILESTONE,),
    ),
    Milestone(
        SPECIALIST_COMPLETES_MILESTONE,
        "The delegated specialist scope inspection finishes.",
        "at least one specialist task is done after at least one run",
        (SPECIALIST_CREATED_MILESTONE,),
    ),
    Milestone(
        READ_ONLY_MILESTONE,
        "Inspecting fleet and host cluster scope mutates nothing.",
        "complete normalized tool evidence contains no forbidden mutation",
        (INTERACTION_COMPLETED_MILESTONE,),
    ),
)


def _target_project_id(raw_input: str) -> str:
    configured = os.environ.get(PROJECT_ID_ENV, "").strip()
    if configured:
        return configured
    match = PROMPT_PROJECT_RE.search(raw_input)
    return match.group(1) if match else ""


def evaluate_acceptance(interaction: dict[str, Any]) -> AcceptanceCriteria:
    _, output_blocker = interaction_blockers(interaction)

    raw_input = input_text(interaction)
    folded_input = raw_input.casefold()
    project_id = _target_project_id(raw_input)

    answer = answer_text(interaction)
    folded_answer = answer.casefold()
    leaks = proxy_leaks(all_visible_text(interaction))
    operations = tool_operations(interaction)
    mutations = sorted(FORBIDDEN_OPERATIONS.intersection(operations))

    project_confirmed = bool(project_id) and project_id.casefold() in folded_answer
    clarification_loop = has_clarification_or_refusal(answer)
    clusters_reported = (
        bool(CLUSTER_SCOPE_RE.search(answer))
        and not clarification_loop
        and len(answer.strip()) >= MIN_SCOPE_ANSWER_CHARS
    )
    locations = sorted(
        {match.group(0).casefold() for match in GCP_LOCATION_RE.finditer(answer)}
    )

    suite = AcceptanceCriteria(ACCEPTANCE_CRITERIA)
    suite.record(
        "ac01-scope-request-preserved",
        bool(project_id)
        and project_id.casefold() in folded_input
        and all(phrase in folded_input for phrase in REQUIRED_INPUT_PHRASES),
        raw_input,
    )
    suite.record(
        "ac02-in-scope-project-confirmed",
        project_confirmed,
        {"expectedProjectId": project_id, "answer": answer},
        blocked_by=output_blocker,
    )
    suite.record(
        "ac03-fleet-and-host-clusters-reported",
        clusters_reported,
        {"clarificationLoop": clarification_loop, "answer": answer},
        blocked_by=output_blocker,
    )
    suite.record(
        "ac04-host-cluster-region-reported",
        bool(locations),
        {"locations": locations, "answer": answer},
        blocked_by=output_blocker,
    )
    suite.record(
        "ac05-scope-check-remains-read-only",
        not mutations and not leaks,
        {
            "operations": operations,
            "mutations": mutations,
            "proxyLeaks": leaks,
        },
        blocked_by=() if mutations or leaks else output_blocker,
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
    return PROMPT.format(project_id=required_env(PROJECT_ID_ENV))


def test_02_fleet_and_host_cluster_scope() -> None:
    Scenario(
        SCENARIO_ID,
        build_prompt,
        evaluate_acceptance,
        evaluate_backend_milestones,
    ).run_test()
