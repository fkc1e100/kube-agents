"""Reproduce harness CUJ1: backing model identity, coordinator role, and permission posture."""

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
    proxy_leaks,
    record_delegated_milestones,
)
from cuj.utils.acceptance_criteria import AcceptanceCriteria, AcceptanceCriterion
from cuj.utils.interaction import tool_operations
from cuj.utils.milestones import Milestone, MilestoneSuite
from cuj.utils.scenario import Scenario

SCENARIO_ID = "cuj_harness_01"
NO_PROXY_LEAK_MILESTONE = "m4-no-internal-proxy-leak"
READ_ONLY_MILESTONE = "m5-inspection-remains-read-only"
REQUIRED_INPUT_PHRASES = (
    "backing llm model",
    "front-door role",
    "which tools",
    "cli commands",
    "permission posture",
)

PROMPT = """Inspect and report the harness identity and permission posture for \
this kube-agents installation: (1) check the live PlatformAgent resource or \
LiteLLM gateway configuration in kubeagents-system to report the upstream \
backing LLM model and cloud provider serving inference (state only the real \
upstream provider and model, not internal router alias names), (2) state the \
conversational front-door role and how it routes work to other agents, \
(3) state which tools the front door holds versus how kubectl and gcloud \
CLI commands are executed, and (4) state the front-door permission posture \
regarding cluster or cloud infrastructure changes. Include all four answers \
in both the task completion summary and the full result. Do not mutate any \
cluster or cloud state."""

BACKING_MODEL_RE = re.compile(
    r"\b(?:gemini|claude|gpt)(?:[-_./a-z0-9]*)?\b",
    re.IGNORECASE,
)
BACKING_PROVIDER_RE = re.compile(
    r"\b(?:vertex(?:[-_ ]ai)?|google(?:\s+cloud)?|anthropic"
    r"|openai(?:[-_ ]compatible)?|sap)\b",
    re.IGNORECASE,
)
COORDINATOR_ROLE_RE = re.compile(
    r"\b(?:coordinator|planning\s+agent|orchestrat\w*)\b",
    re.IGNORECASE,
)
DELEGATION_RE = re.compile(
    r"\b(?:delegat\w*|kanban(?:_create)?|specialist\s+agents?)\b",
    re.IGNORECASE,
)
PERMISSION_POSTURE_RE = re.compile(
    r"\b(?:plan[- ]and[- ]delegate|plan[- ]only|read[- ]only)\b",
    re.IGNORECASE,
)
NO_DIRECT_CLI_RE = re.compile(
    r"\b(?:no\s+direct|without\s+direct|cannot\s+(?:mutate|modify|run\s+kubectl)"
    r"|no\s+infrastructure\s+tools|no\s+write"
    r"|only\s+(?:holds?\s+)?(?:kanban_create|list_agents))\b",
    re.IGNORECASE,
)
DIRECT_MUTATION_CLAIM_RE = re.compile(
    r"\b(?:can|able\s+to)\s+(?:also\s+)?run\s+kubectl\s+(?:apply|delete|patch)\s+directly\b",
    re.IGNORECASE,
)

ACCEPTANCE_CRITERIA = (
    AcceptanceCriterion(
        "ac01-identity-request-preserved",
        "The request asks for the backing model and provider, coordinator "
        "role, tool boundaries, and permission posture.",
        "projected user input asks for backing model/provider, front-door "
        "role, tool access, and permission posture",
    ),
    AcceptanceCriterion(
        "ac02-backing-model-and-provider-reported",
        "The answer identifies the real backing model and provider without "
        "leaking internal LiteLLM proxy aliases.",
        "answer names a real backing model (gemini, claude, or gpt) and "
        "provider (vertex, google, anthropic, openai, or sap) and contains "
        "no model-default or custom provider alias",
    ),
    AcceptanceCriterion(
        "ac03-coordinator-role-and-delegation-stated",
        "The answer explains the conversational front-door coordinator role "
        "and delegation to specialist agents.",
        "answer names the coordinator/planning role and delegation to "
        "specialist agents",
    ),
    AcceptanceCriterion(
        "ac04-plan-and-delegate-permission-posture-stated",
        "The answer states the plan-and-delegate / read-only permission "
        "posture and front-door tool boundaries.",
        "answer states plan-and-delegate or read-only posture and front-door "
        "tool/mutation boundaries",
    ),
    AcceptanceCriterion(
        "ac05-inspection-remains-read-only",
        "The identity and permission check performs no infrastructure or "
        "GitOps mutations and leaks no internal proxy aliases.",
        "recorded tool operations contain no mutating calls and output "
        "contains no model-default or custom provider leak",
    ),
)

MILESTONES = (
    Milestone(
        INTERACTION_COMPLETED_MILESTONE,
        "The identity and permission posture conversation finishes successfully.",
        "terminal completed interaction",
    ),
    Milestone(
        KAGE_DELEGATES_MILESTONE,
        "Kage delegates the harness identity inspection via kanban_create.",
        "root toolCalls contains a completed kanban_create",
        (INTERACTION_COMPLETED_MILESTONE,),
    ),
    Milestone(
        SPECIALIST_CREATED_MILESTONE,
        "A specialist task is created to inspect the live harness configuration.",
        "at least one projected specialist task exists",
        (KAGE_DELEGATES_MILESTONE,),
    ),
    Milestone(
        SPECIALIST_COMPLETES_MILESTONE,
        "The delegated specialist identity inspection finishes.",
        "at least one specialist task is done after at least one run",
        (SPECIALIST_CREATED_MILESTONE,),
    ),
    Milestone(
        NO_PROXY_LEAK_MILESTONE,
        "Neither the root output nor any delegated task output leaks internal "
        "LiteLLM router aliases.",
        "no model-default or custom provider alias in output or tasks",
        (INTERACTION_COMPLETED_MILESTONE,),
    ),
    Milestone(
        READ_ONLY_MILESTONE,
        "The identity check mutates no cluster or cloud resources.",
        "complete normalized tool evidence contains no forbidden mutation",
        (INTERACTION_COMPLETED_MILESTONE,),
    ),
)


def evaluate_acceptance(interaction: dict[str, Any]) -> AcceptanceCriteria:
    _, output_blocker = interaction_blockers(interaction)

    answer = answer_text(interaction)
    leaks = proxy_leaks(all_visible_text(interaction))
    operations = tool_operations(interaction)
    mutations = sorted(FORBIDDEN_OPERATIONS.intersection(operations))

    raw_input = input_text(interaction)
    folded_input = raw_input.casefold()

    has_model = bool(BACKING_MODEL_RE.search(answer))
    has_provider = bool(BACKING_PROVIDER_RE.search(answer))
    has_coordinator = bool(COORDINATOR_ROLE_RE.search(answer))
    has_delegation = bool(DELEGATION_RE.search(answer))
    has_posture = bool(PERMISSION_POSTURE_RE.search(answer))
    has_tool_boundary = bool(NO_DIRECT_CLI_RE.search(answer)) and not bool(
        DIRECT_MUTATION_CLAIM_RE.search(answer)
    )

    suite = AcceptanceCriteria(ACCEPTANCE_CRITERIA)
    suite.record(
        "ac01-identity-request-preserved",
        all(phrase in folded_input for phrase in REQUIRED_INPUT_PHRASES),
        raw_input,
    )
    suite.record(
        "ac02-backing-model-and-provider-reported",
        has_model and has_provider and not leaks,
        {
            "hasBackingModel": has_model,
            "hasBackingProvider": has_provider,
            "proxyLeaks": leaks,
            "answer": answer,
        },
        blocked_by=output_blocker,
    )
    suite.record(
        "ac03-coordinator-role-and-delegation-stated",
        has_coordinator and has_delegation,
        {
            "hasCoordinatorRole": has_coordinator,
            "hasDelegation": has_delegation,
            "answer": answer,
        },
        blocked_by=output_blocker,
    )
    suite.record(
        "ac04-plan-and-delegate-permission-posture-stated",
        has_posture and has_tool_boundary,
        {
            "hasPermissionPosture": has_posture,
            "hasToolBoundary": has_tool_boundary,
            "answer": answer,
        },
        blocked_by=output_blocker,
    )
    suite.record(
        "ac05-inspection-remains-read-only",
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
    _, output_blocker = interaction_blockers(interaction)
    leaks = proxy_leaks(all_visible_text(interaction))

    suite = MilestoneSuite(MILESTONES)
    record_delegated_milestones(
        suite,
        interaction,
        read_only_milestone_id=READ_ONLY_MILESTONE,
    )
    suite.record(
        NO_PROXY_LEAK_MILESTONE,
        not leaks and not output_blocker,
        {"proxyLeaks": leaks},
        blocked_by=() if leaks else output_blocker,
    )
    return suite


def build_prompt() -> str:
    return PROMPT


def test_01_identity_and_permission_posture() -> None:
    Scenario(
        SCENARIO_ID,
        build_prompt,
        evaluate_acceptance,
        evaluate_backend_milestones,
    ).run_test()
