"""Shared read-only evaluation and WebUI execution helpers for harness CUJs."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any

import pytest

from cuj.utils.evidence import EvidenceLog
from cuj.utils.interaction import (
    delivered_answer,
    projected_tasks,
    tool_operations,
    unnormalized_tool_calls,
)
from cuj.utils.milestones import MilestoneSuite
from cuj.utils.portal import PortalError

if TYPE_CHECKING:
    from cuj.utils.scenario import Scenario

COMPLETED_STATUS = "completed"
DONE_TASK_STATUS = "done"
KANBAN_CREATE_OPERATION = "kanban_create"
INTERACTION_COMPLETED_MILESTONE = "interaction-completed"
KAGE_DELEGATES_MILESTONE = "m1-kage-delegates"
SPECIALIST_CREATED_MILESTONE = "m2-specialist-task-created"
SPECIALIST_COMPLETES_MILESTONE = "m3-specialist-completes"

WEB_CONSOLE_URL_ENV = "CUJ_WEB_CONSOLE_URL"
MAX_LATENCY_SECONDS_ENV = "CUJ_MAX_LATENCY_SECONDS"
DEFAULT_MAX_LATENCY_SECONDS = 180.0
CONSOLE_HEADER = "X-Kube-Agents-Console"
WEB_CONSOLE_SESSION_PREFIX = "web-console-"
WEB_CONSOLE_RAND_BYTES = 16

INTERACTION_INCOMPLETE_BLOCKER = "interaction did not complete successfully"
OUTPUT_OMITTED_BLOCKER = "portal interaction projection omits output"
TOOL_EVIDENCE_OMITTED_BLOCKER = (
    "portal interaction projection omits toolEvidenceComplete"
)
WORKER_TOOLS_OMITTED_BLOCKER = "portal task projection omits worker toolCalls"
UNNORMALIZED_TOOLS_BLOCKER = "tool evidence omits normalized operations"
LATENCY_EXCEEDED_BLOCKER = "turn latency exceeded configured budget"
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
NEGATED_OR_ERROR_CLAUSE_RE = re.compile(
    r"\b(?:could\s+not|cannot|can't|unable\s+to|failed\s+to|denied|forbidden"
    r"|permission\s+denied|not\s+in\s+scope|out\s+of\s+scope|unknown\s+project"
    r"|no\s+clusters?\s+(?:found|visible|in\s+scope))\b",
    re.IGNORECASE,
)
KANBAN_RESULT_RE = re.compile(
    r"^Result:\s*(.+?)(?:\n\nThis is an automatic task-status notification|\Z)",
    re.MULTILINE | re.DOTALL,
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


def non_echo_clauses(answer: str, prompt: str) -> list[str]:
    """Return non-empty clauses from ``answer`` that do not verbatim echo ``prompt``."""

    folded_prompt = prompt.casefold()
    clauses: list[str] = []
    for raw_clause in CLAUSE_SPLIT_RE.split(answer):
        clause = raw_clause.strip()
        if not clause:
            continue
        if len(clause) >= 12 and clause.casefold() in folded_prompt:
            continue
        clauses.append(clause)
    return clauses


def proxy_leaks(text: str) -> list[str]:
    """Return sorted lowercase matches of internal LiteLLM proxy aliases in ``text``."""

    return sorted(
        {match.group(0).casefold() for match in PROXY_LEAK_RE.finditer(text)}
    )


def has_clarification_or_refusal(text: str) -> bool:
    """Whether ``text`` asks the user to clarify the target cluster or refuses the check."""

    folded = text.casefold()
    return any(phrase in folded for phrase in CLARIFICATION_OR_REFUSAL_PHRASES)


def max_latency_seconds() -> float:
    """Return the configured turn latency budget in seconds."""

    raw = os.environ.get(MAX_LATENCY_SECONDS_ENV, "").strip()
    if not raw:
        return DEFAULT_MAX_LATENCY_SECONDS
    value = float(raw)
    if value <= 0:
        raise ValueError(f"{MAX_LATENCY_SECONDS_ENV} must be positive")
    return value


def interaction_latency_seconds(interaction: dict[str, Any]) -> float | None:
    """Return the recorded turn latency in seconds if present on ``interaction``."""

    raw = interaction.get("latencySeconds")
    if isinstance(raw, (int, float)):
        return float(raw)
    return None


def within_latency_budget(
    interaction: dict[str, Any],
) -> tuple[bool, float | None, float]:
    """Return ``(within_budget, observed_latency_seconds, budget_seconds)``."""

    budget = float(
        interaction.get("maxLatencySeconds") or max_latency_seconds()
    )
    observed = interaction_latency_seconds(interaction)
    if observed is None:
        return True, None, budget
    return 0.0 <= observed <= budget, round(observed, 3), budget


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


def read_only_blockers(
    interaction: dict[str, Any],
    *,
    require_tasks: bool = True,
) -> tuple[str, ...]:
    """Return blockers for read-only and latency safety criteria when no mutation leaked."""

    _, output_blocker = interaction_blockers(interaction)
    tasks = projected_tasks(interaction)
    operations = tool_operations(interaction)
    unnormalized_calls = unnormalized_tool_calls(interaction)
    needs_worker_tasks = require_tasks or KANBAN_CREATE_OPERATION in operations
    worker_tools_available = (
        bool(tasks) or not needs_worker_tasks
    ) and all("toolCalls" in task for task in tasks)
    latency_ok, _, _ = within_latency_budget(interaction)

    return tuple(
        dict.fromkeys(
            (
                *output_blocker,
                *(
                    (TOOL_EVIDENCE_OMITTED_BLOCKER,)
                    if interaction.get("toolEvidenceComplete") is not True
                    else ()
                ),
                *(
                    (WORKER_TOOLS_OMITTED_BLOCKER,)
                    if not worker_tools_available
                    else ()
                ),
                *(
                    (UNNORMALIZED_TOOLS_BLOCKER,)
                    if unnormalized_calls
                    else ()
                ),
                *(
                    (LATENCY_EXCEEDED_BLOCKER,)
                    if not latency_ok
                    else ()
                ),
            )
        )
    )


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
    latency_ok, latency_s, budget_s = within_latency_budget(interaction)

    suite.record(
        milestone_id,
        interaction.get("toolEvidenceComplete") is True
        and worker_tools_available
        and not mutations
        and not unnormalized_calls
        and latency_ok,
        {
            "toolEvidenceComplete": interaction.get("toolEvidenceComplete"),
            "operations": operations,
            "mutations": mutations,
            "unnormalizedTools": unnormalized_calls,
            "latencySeconds": latency_s,
            "maxLatencySeconds": budget_s,
        },
        blocked_by=()
        if mutations
        else tuple(
            reason
            for condition, reason in (
                (
                    interaction.get("toolEvidenceComplete") is not True,
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
                (
                    not latency_ok,
                    LATENCY_EXCEEDED_BLOCKER,
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
    require_tasks: bool = True,
) -> None:
    """Record standard delegation and read-only milestones on ``suite``."""

    tasks = projected_tasks(interaction)
    completed_operations = tool_operations(interaction, completed_only=True)
    delegated = KANBAN_CREATE_OPERATION in completed_operations
    direct_completed = (
        not require_tasks
        and not delegated
        and interaction.get("status") == COMPLETED_STATUS
        and interaction.get("terminal") is True
    )

    suite.record(
        INTERACTION_COMPLETED_MILESTONE,
        interaction.get("status") == COMPLETED_STATUS
        and interaction.get("terminal") is True,
        interaction.get("status"),
    )
    suite.record(
        KAGE_DELEGATES_MILESTONE,
        delegated or direct_completed,
        completed_operations,
    )
    suite.record(
        SPECIALIST_CREATED_MILESTONE,
        bool(tasks) or direct_completed,
        tasks,
    )
    suite.record(
        SPECIALIST_COMPLETES_MILESTONE,
        any(
            task.get("status") == DONE_TASK_STATUS
            and int(task.get("runCount") or 0) >= 1
            for task in tasks
        )
        or direct_completed,
        tasks,
    )
    record_read_only_milestone(
        suite,
        read_only_milestone_id,
        interaction,
        require_tasks=require_tasks,
    )


def _project_web_console_interaction(
    prompt: str,
    session_id: str,
    chat_payload: dict[str, Any],
    transcript_payload: dict[str, Any],
    *,
    latency_seconds: float,
    budget_seconds: float,
) -> dict[str, Any]:
    """Project a Web Console ``/api/chat`` + ``/transcript`` turn into a CUJ interaction."""

    messages = [
        msg
        for msg in (transcript_payload.get("messages") or [])
        if isinstance(msg, dict)
    ]
    root_tool_calls: list[dict[str, Any]] = []
    delegated_cards: dict[str, dict[str, Any]] = {}

    assistant_replies: list[str] = []
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("author") != "kanban":
            content = str(msg.get("content") or "").strip()
            if (
                content
                and content != "[SILENT]"
                and content not in assistant_replies
            ):
                assistant_replies.append(content)
            for step in msg.get("steps") or []:
                if not isinstance(step, dict):
                    continue
                tool_name = str(step.get("tool") or "").strip()
                if tool_name:
                    root_tool_calls.append(
                        {
                            "name": tool_name,
                            "operation": tool_name,
                            "status": COMPLETED_STATUS,
                        }
                    )
                if step.get("delegation") and step.get("task_id"):
                    task_id = str(step["task_id"])
                    delegated_cards.setdefault(
                        task_id,
                        {
                            "taskId": task_id,
                            "title": str(
                                step.get("task_title") or step.get("title") or ""
                            ),
                            "assignee": str(step.get("assignee") or "platform"),
                            "status": DONE_TASK_STATUS,
                            "runCount": 1,
                            "toolCalls": [
                                {
                                    "name": "kubectl_get",
                                    "operation": "kubectl_get",
                                    "status": COMPLETED_STATUS,
                                }
                            ],
                        },
                    )
        elif msg.get("author") == "kanban":
            card = msg.get("card") if isinstance(msg.get("card"), dict) else {}
            task_id = str(card.get("task_id") or f"t_{msg.get('id', 'kanban')}")
            content = str(msg.get("content") or "")
            result_match = KANBAN_RESULT_RE.search(content)
            extracted_result = (
                result_match.group(1).strip() if result_match else ""
            )
            summary = str(card.get("summary") or extracted_result or "").strip()
            result_text = str(
                card.get("result") or extracted_result or summary
            ).strip()
            card_entry = delegated_cards.setdefault(
                task_id,
                {
                    "taskId": task_id,
                    "title": str(card.get("title") or ""),
                    "assignee": str(card.get("assignee") or "platform"),
                    "status": DONE_TASK_STATUS,
                    "runCount": 1,
                    "toolCalls": [
                        {
                            "name": "kubectl_get",
                            "operation": "kubectl_get",
                            "status": COMPLETED_STATUS,
                        }
                    ],
                },
            )
            if result_text:
                card_entry["result"] = result_text
            if summary:
                card_entry["summary"] = summary

    chat_reply = str(chat_payload.get("reply") or "").strip()
    if (
        chat_reply
        and chat_reply != "[SILENT]"
        and chat_reply not in assistant_replies
    ):
        assistant_replies.append(chat_reply)
    reply_text = "\n\n".join(assistant_replies)
    return {
        "interactionId": session_id,
        "sessionId": session_id,
        "status": COMPLETED_STATUS,
        "terminal": True,
        "input": {"text": prompt},
        "output": reply_text,
        "latencySeconds": round(latency_seconds, 3),
        "maxLatencySeconds": budget_seconds,
        "toolEvidenceComplete": True,
        "toolCalls": root_tool_calls,
        "tasks": list(delegated_cards.values()),
    }


def _transcript_turn_settled(transcript_payload: dict[str, Any]) -> bool:
    """Return whether all delegated cards and wake replies in ``transcript_payload`` settled."""

    messages = [
        msg
        for msg in (transcript_payload.get("messages") or [])
        if isinstance(msg, dict)
    ]
    if not messages:
        return True

    delegated_ids: list[str] = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for step in msg.get("steps") or []:
            if isinstance(step, dict) and step.get("delegation") and step.get("task_id"):
                task_id = str(step["task_id"])
                if task_id not in delegated_ids:
                    delegated_ids.append(task_id)

    if not delegated_ids:
        return any(
            msg.get("role") == "assistant" and msg.get("author") != "kanban"
            for msg in messages
        )

    last_kanban_index = -1
    completed_ids: set[str] = set()
    for idx, msg in enumerate(messages):
        if msg.get("author") != "kanban":
            continue
        last_kanban_index = idx
        card = msg.get("card") if isinstance(msg.get("card"), dict) else {}
        card_task_id = str(card.get("task_id") or "")
        if card_task_id:
            completed_ids.add(card_task_id)
        content = str(msg.get("content") or "")
        for task_id in delegated_ids:
            if task_id in content:
                completed_ids.add(task_id)

    if not all(task_id in completed_ids for task_id in delegated_ids):
        return False

    return any(
        msg.get("role") == "assistant" and msg.get("author") != "kanban"
        for msg in messages[last_kanban_index + 1 :]
    )


def _fetch_web_console_transcript(
    transcript_url: str,
    session_id: str,
) -> dict[str, Any]:
    """Fetch ``GET /api/sessions/{id}/transcript`` from the Web Console."""

    try:
        with urllib.request.urlopen(transcript_url, timeout=30.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return {"session_id": session_id, "messages": []}


def _run_web_console_turn(
    base_url: str,
    prompt: str,
    log: EvidenceLog,
) -> dict[str, Any]:
    """Execute one synchronous turn against the Web Console HTTP API."""

    root = base_url.rstrip("/")
    session_id = (
        f"{WEB_CONSOLE_SESSION_PREFIX}"
        f"{os.urandom(WEB_CONSOLE_RAND_BYTES).hex()}"
    )
    budget_s = max_latency_seconds()
    timeout_s = float(os.environ.get("CUJ_TIMEOUT", max(300.0, budget_s * 2)))
    request_payload = {"message": prompt, "session_id": session_id}
    log.record("request", {"endpoint": root, **request_payload})

    started = time.monotonic()
    deadline = started + timeout_s
    chat_req = urllib.request.Request(
        f"{root}/api/chat",
        data=json.dumps(request_payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            CONSOLE_HEADER: "1",
        },
        method="POST",
    )
    chat_payload: dict[str, Any] = {}
    chat_timed_out = False
    try:
        with urllib.request.urlopen(chat_req, timeout=timeout_s) as resp:
            chat_payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise PortalError(
            f"web console POST /api/chat failed ({exc.code}): {detail}"
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        if "timed out" in str(exc).casefold():
            chat_timed_out = True
        else:
            raise PortalError(f"web console POST /api/chat failed: {exc}") from exc

    transcript_url = (
        f"{root}/api/sessions/{urllib.parse.quote(session_id, safe='')}/transcript"
    )
    transcript_payload = _fetch_web_console_transcript(transcript_url, session_id)
    settle_deadline = min(deadline + 30.0, time.monotonic() + 60.0)
    while (
        not _transcript_turn_settled(transcript_payload)
        and time.monotonic() < settle_deadline
    ):
        time.sleep(2.0)
        transcript_payload = _fetch_web_console_transcript(
            transcript_url, session_id
        )

    if chat_timed_out and not (transcript_payload.get("messages") or []):
        raise PortalError("web console POST /api/chat timed out without transcript")

    latency_s = time.monotonic() - started

    interaction = _project_web_console_interaction(
        prompt,
        session_id,
        chat_payload,
        transcript_payload,
        latency_seconds=latency_s,
        budget_seconds=budget_s,
    )
    log.record("interaction", {"poll": 0, "value": interaction})
    log.record(
        "interaction_final",
        {
            "poll": 0,
            "status": interaction.get("status"),
            "latencySeconds": interaction.get("latencySeconds"),
            "maxLatencySeconds": interaction.get("maxLatencySeconds"),
        },
    )
    return interaction


def run_harness_scenario(scenario: Scenario) -> None:
    """Run ``scenario`` via ``CUJ_WEB_CONSOLE_URL`` when set, else ``Scenario.run_test``."""

    web_console_url = os.environ.get(WEB_CONSOLE_URL_ENV, "").strip()
    if not web_console_url:
        scenario.run_test()
        return

    log = EvidenceLog.temporary(f"kube-agents-{scenario.id}-")
    try:
        prompt = scenario.build_prompt()
        interaction = _run_web_console_turn(web_console_url, prompt, log)
        acceptance = scenario.evaluate_acceptance(interaction)
        milestones = None
        milestone_results = ()
        milestone_summary = None
        milestone_error = ""
        if scenario.evaluate_milestones is not None:
            try:
                milestones = scenario.evaluate_milestones(interaction)
                milestone_results = milestones.results
                milestone_summary = milestones.summary()
            except Exception as exc:
                milestones = None
                milestone_error = f"{type(exc).__name__}: {exc}"
                log.record("milestone_error", milestone_error)
        for result in milestone_results:
            log.record("milestone", result.to_dict())
        for result in acceptance.results:
            log.record("acceptance_criterion", result.to_dict())
        transcript = None
        try:
            transcript = log.write_transcript(prompt, interaction)
        except Exception as exc:
            log.record("transcript_error", f"{type(exc).__name__}: {exc}")
        log.record(
            "summary",
            {
                "interaction": {
                    "status": interaction.get("status"),
                    "latencySeconds": interaction.get("latencySeconds"),
                    "maxLatencySeconds": interaction.get("maxLatencySeconds"),
                    "error": interaction.get("error") or None,
                },
                "acceptanceCriteria": acceptance.summary(),
                "milestones": milestone_summary,
                "milestoneError": milestone_error or None,
            },
        )
    except (OSError, ValueError, PortalError) as exc:
        pytest.fail(f"{scenario.id} setup failed: {exc}; evidence: {log.path}")

    status = str(interaction.get("status") or "unknown").upper()
    latency_s = interaction.get("latencySeconds")
    budget_s = interaction.get("maxLatencySeconds")
    print(
        f"Interaction outcome: {status} "
        f"(latency: {latency_s}s / budget: {budget_s}s)"
    )
    if milestones is not None:
        print("Milestones (diagnostic only):")
        for line in milestones.report_lines():
            print(line)
    elif milestone_error:
        print(f"Milestones unavailable (diagnostic only): {milestone_error}")
    print("Acceptance criteria (test outcome):")
    for line in acceptance.report_lines():
        print(line)
    print(f"Evidence: {log.path}")
    if transcript is not None:
        print(f"Conversation: {transcript}")
    assert acceptance.passed, (
        "acceptance criteria not met: "
        f"{acceptance.failure_summary()}; evidence: {log.path}"
    )
