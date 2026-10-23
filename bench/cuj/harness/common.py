"""Shared read-only evaluation helpers for harness self-inspection CUJs."""

from __future__ import annotations

import re
from typing import Any

from cuj.utils.interaction import (
    delivered_answer,
    projected_tasks,
    tool_operations,
    unnormalized_tool_calls,
)
from cuj.utils.milestones import MilestoneSuite

COMPLETED_STATUS = "completed"
DONE_TASK_STATUS = "done"
KANBAN_CREATE_OPERATION = "kanban_create"
INTERACTION_COMPLETED_MILESTONE = "interaction-completed"
KAGE_DELEGATES_MILESTONE = "m1-kage-delegates"
SPECIALIST_CREATED_MILESTONE = "m2-specialist-task-created"
SPECIALIST_COMPLETES_MILESTONE = "m3-specialist-completes"

INTERACTION_INCOMPLETE_BLOCKER = "interaction did not complete successfully"
OUTPUT_OMITTED_BLOCKER = "portal interaction projection omits output"
TOOL_EVIDENCE_OMITTED_BLOCKER = (
    "portal interaction projection omits toolEvidenceComplete"
)
WORKER_TOOLS_OMITTED_BLOCKER = "portal task projection omits worker toolCalls"
UNNORMALIZED_TOOLS_BLOCKER = "tool evidence omits normalized operations"
VISIBLE_TASK_FIELDS = ("title", "result", "summary", "error")
CLARIFICATION_OR_REFUSAL_PHRASES = (
    "which cluster did you mean",
    "could you clarify",
    "confirm which cluster",
    "please specify which cluster",
    "cannot check",
    "unable to check",
)

FORBIDDEN_OPERATIONS = frozenset(
    {
        "apply_manifest",
        "create_cluster",
        "delete_cluster",
        "delete_pod",
        "delete_resource",
        "open_pull_request",
        "patch_resource",
        "rollout_restart",
        "scale_deployment",
        "submit_provisioning_request",
        "submit_suggestion",
    }
)

PROXY_LEAK_RE = re.compile(
    r"\b(?:model[-_]default|custom\s+provider|provider\s*[:=]\s*['\"]?custom)\b",
    re.IGNORECASE,
)
CLAUSE_SPLIT_RE = re.compile(
    r"(?:\.(?=\s|$)|[!?\n;]+|\b(?:while|whereas|but|however|although)\b)",
    re.IGNORECASE,
)


def input_text(interaction: dict[str, Any]) -> str:
    """Return the projected user prompt text from ``interaction``."""

    user_input = interaction.get("input")
    return str(
        (user_input or {}).get("text") if isinstance(user_input, dict) else ""
    )


def answer_text(interaction: dict[str, Any]) -> str:
    """Return user-facing answer text from root output, task results, and summaries."""

    base = delivered_answer(interaction)
    parts = [base] if base else []
    for task in projected_tasks(interaction):
        summary = task.get("summary")
        if (
            isinstance(summary, str)
            and summary.strip()
            and summary.strip() not in base
            and summary.strip() not in parts
        ):
            parts.append(summary.strip())
    return "\n\n".join(parts)


def all_visible_text(interaction: dict[str, Any]) -> str:
    """Return every user-visible string across root output, errors, and tasks."""

    parts = [
        str(interaction.get("output") or ""),
        str(interaction.get("error") or ""),
        answer_text(interaction),
    ]
    for task in projected_tasks(interaction):
        for field in VISIBLE_TASK_FIELDS:
            value = task.get(field)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
    return "\n".join(part for part in parts if part)


def proxy_leaks(text: str) -> list[str]:
    """Return sorted lowercase matches of internal LiteLLM proxy aliases in ``text``."""

    return sorted(
        {match.group(0).casefold() for match in PROXY_LEAK_RE.finditer(text)}
    )


def has_clarification_or_refusal(text: str) -> bool:
    """Whether ``text`` asks the user to clarify the target cluster or refuses the check."""

    folded = text.casefold()
    return any(phrase in folded for phrase in CLARIFICATION_OR_REFUSAL_PHRASES)


def interaction_blockers(
    interaction: dict[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return ``(interaction_blocker, output_blocker)`` tuples for acceptance evaluation."""

    interaction_blocker = (
        ()
        if interaction.get("status") == COMPLETED_STATUS
        and interaction.get("terminal") is True
        else (INTERACTION_INCOMPLETE_BLOCKER,)
    )
    output_projected = bool(answer_text(interaction).strip())
    output_blocker = tuple(
        dict.fromkeys(
            (
                *interaction_blocker,
                *(
                    ()
                    if output_projected
                    else (OUTPUT_OMITTED_BLOCKER,)
                ),
            )
        )
    )
    return interaction_blocker, output_blocker


def record_read_only_milestone(
    suite: MilestoneSuite,
    milestone_id: str,
    interaction: dict[str, Any],
    *,
    require_tasks: bool = True,
) -> None:
    """Record the read-only tool evidence milestone on ``suite``."""

    tasks = projected_tasks(interaction)
    operations = tool_operations(interaction)
    unnormalized_calls = unnormalized_tool_calls(interaction)
    needs_worker_tasks = require_tasks or KANBAN_CREATE_OPERATION in operations
    worker_tools_available = (
        bool(tasks) or not needs_worker_tasks
    ) and all("toolCalls" in task for task in tasks)
    mutations = sorted(FORBIDDEN_OPERATIONS.intersection(operations))

    suite.record(
        milestone_id,
        interaction.get("toolEvidenceComplete") is True
        and worker_tools_available
        and not mutations
        and not unnormalized_calls,
        {
            "toolEvidenceComplete": interaction.get("toolEvidenceComplete"),
            "operations": operations,
            "mutations": mutations,
            "unnormalizedTools": unnormalized_calls,
        },
        blocked_by=()
        if mutations
        else tuple(
            reason
            for condition, reason in (
                (
                    "toolEvidenceComplete" not in interaction,
                    TOOL_EVIDENCE_OMITTED_BLOCKER,
                ),
                (
                    not worker_tools_available,
                    WORKER_TOOLS_OMITTED_BLOCKER,
                ),
                (
                    bool(unnormalized_calls),
                    UNNORMALIZED_TOOLS_BLOCKER,
                ),
            )
            if condition
        ),
    )


def record_delegated_milestones(
    suite: MilestoneSuite,
    interaction: dict[str, Any],
    *,
    read_only_milestone_id: str,
) -> None:
    """Record standard delegation and read-only milestones on ``suite``."""

    tasks = projected_tasks(interaction)
    completed_operations = tool_operations(interaction, completed_only=True)

    suite.record(
        INTERACTION_COMPLETED_MILESTONE,
        interaction.get("status") == COMPLETED_STATUS
        and interaction.get("terminal") is True,
        interaction.get("status"),
    )
    suite.record(
        KAGE_DELEGATES_MILESTONE,
        KANBAN_CREATE_OPERATION in completed_operations,
        completed_operations,
    )
    suite.record(SPECIALIST_CREATED_MILESTONE, bool(tasks), tasks)
    suite.record(
        SPECIALIST_COMPLETES_MILESTONE,
        any(
            task.get("status") == DONE_TASK_STATUS
            and int(task.get("runCount") or 0) >= 1
            for task in tasks
        ),
        tasks,
    )
    record_read_only_milestone(
        suite,
        read_only_milestone_id,
        interaction,
        require_tasks=True,
    )
