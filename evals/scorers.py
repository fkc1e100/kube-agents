# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Deterministic Customer-Experience (CX) Quality Scorer for kube-agents evaluations."""

from __future__ import annotations

import re
from typing import Any

# Markdown emphasis characters are dropped; "_" becomes "-" so identifiers such as
# "vertex_ai" and "model_default" keep their word boundaries and match "vertex" / "model-default".
_MARKDOWN_NOISE = str.maketrans({"*": None, "`": None, "#": None, "_": "-"})

# Opening phrases that indicate an unfulfilled turn-1 progress notification rather than a completed response.
# Matches after optional conversational preamble (e.g. "sure,", "ok,", "got it:", "on it -").
_STUB_OPENING_RE = re.compile(
    r"(?:^|(?<=[.!?\n]))\s*(?:(?:sure|ok|okay|got\s+it|on\s+it)[,.:;!\s-]*\s*)?"
    r"(?:[\w\s-]{0,30}?\b(?:is|am|are|'m|'re)\s+(?:now\s+|currently\s+)?)?"
    r"(?:checking|inspecting|looking\s+into|gathering|querying)\b"
    r"|(?:^|(?<=[.!?\n]))\s*(?:(?:sure|ok|okay|got\s+it|on\s+it)[,.:;!\s-]*\s*)?"
    r"let\s+me\s+(?:check|inspect|look|gather|query|find|see|pull|fetch)\b"
    r"|(?:^|(?<=[.!?\n]))\s*(?:(?:sure|ok|okay|got\s+it|on\s+it)[,.:;!\s-]*\s*)?"
    r"(?:i\s+have|i've)\s+(?:asked|delegated|handed|filed|sent|forwarded|passed|routed|created\s+a\s+task)\b"
    r"|(?:^|(?<=[.!?\n]))\s*(?:filed\s+(?:a\s+task|with)|task\s+has\s+been\s+created)\b",
    re.IGNORECASE,
)

# A promise to deliver the answer later, anywhere in the reply: "report back", "get back to you",
# or "I'll update/send/share/post ... once/when/after ...". A conditional offer such as
# "I'll let you know if that changes" is not a deferral.
_DEFERRAL_RE = re.compile(
    r"\breport\s+back\b|\bget\s+back\s+to\s+you\b|\bwill\s+appear\s+in\s+this\s+thread\b"
    r"|\b(?:i\s+will|i'll|we\s+will|we'll)\b[^.;!?]{0,160}?\b(?:update|send|share|post|reply|follow\s+up)\b"
    r"[^.;!?]{0,80}?\b(?:once|when|after|as\s+soon\s+as|shortly)\b",
    re.IGNORECASE,
)

# Structural result content a stub does not carry: code blocks, table headers, or structured items.
_DIAGNOSTIC_BLOCK_RE = re.compile(
    r"```|^NAME\s+(?:READY|STATUS|NAMESPACE|VERSION|AGE)|\nNAME\s+(?:READY|STATUS|NAMESPACE|VERSION|AGE)"
    r"|:\s*[^,.;:\n]+(?:,\s*[^,.;:\n]+){2,}",
    re.IGNORECASE | re.MULTILINE,
)

# Policy-boundary or empty-result outcomes: a definitive answer, not an in-flight status notice.
_INFORMATIVE_MARKERS = (
    "is restricted",
    "was restricted",
    "are restricted",
    "permission denied",
    "forbidden",
    "rbac",
    "unauthorized",
    "not allowed",
    "no warning",
    "0 pods",
    "0 events",
)

# Optional suffix accepted after a keyword, so "nodes" satisfies "node" and "restarted" satisfies "restart".
_INFLECTION_SUFFIX = r"(?:e?s|e?d|ing)?"

_STATUS_KEYWORDS = {"ready", "running", "healthy", "active"}


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    translated = text.translate(_MARKDOWN_NOISE)
    return re.sub(r"[^\S\n]+", " ", translated).strip().lower()


def _contains_word(keyword: str, text: str) -> bool:
    """Checks for keyword presence using word boundaries, accepting plurals and verb inflections."""
    k = keyword.lower().strip()
    escaped = re.escape(k)
    if k and k[-1] in "bdfgmnprtz":
        double = re.escape(k[-1])
        suffix = rf"(?:{double}(?:ed|ing)|e?s|e?d|ing)?"
    else:
        suffix = _INFLECTION_SUFFIX
    return bool(re.search(rf"(?:\b|^){escaped}{suffix}(?:\b|$)", text.lower()))


def _is_delegation_stub(raw_text: str, lowered: str) -> bool:
    """Detects a turn-1 hand-off: a stub opening phrase, or a promise to deliver the answer later."""
    if _DIAGNOSTIC_BLOCK_RE.search(raw_text):
        return False

    has_stub_open = bool(_STUB_OPENING_RE.search(lowered))
    has_defer = bool(_DEFERRAL_RE.search(lowered))

    if has_stub_open:
        return True

    if has_defer:
        sentences = [s.strip() for s in re.split(r"[.!?\n]+", lowered) if s.strip()]
        non_defer_sentences = [
            s for s in sentences
            if not _DEFERRAL_RE.search(s) and not _STUB_OPENING_RE.search(s)
        ]
        if not non_defer_sentences:
            return True
        has_substantive_fact = any(
            re.search(r"\b(?:\d+/\d+\s+replicas?|\d+\s+replicas?|running|ready|available|version\s+v?\d+)\b", s)
            and not re.search(r"\b(?:confirm|check|inspect|query|whether|if)\b", s)
            for s in non_defer_sentences
        )
        if not has_substantive_fact:
            return True

    return False


def _has_negated_status(keyword: str, text: str) -> bool:
    """Detects if a status keyword is negated (e.g. 'not running', 'unhealthy', 'Ready=False')."""
    k = keyword.lower().strip()
    if k not in _STATUS_KEYWORDS:
        return False
    negation_patterns = [
        rf"\b(?:not|never|non|isn't|is\s+not|aren't|are\s+not|failed\s+to\s+be)\b(?:(?!\b(?:and|but|while|although)\b)[^.;,\n]){{0,30}}\b{re.escape(k)}\b",
        rf"\bno\s+longer\s+{re.escape(k)}\b",
        rf"\b(?:0\s*(?:/|of)\s*\d+|no|none(?:\s+of)?)\b(?:(?!\b(?:and|but|while|although)\b)[^.;,\n]){{0,40}}\b(?:is|are|reports?)\s+(?:currently\s+)?{re.escape(k)}\b",
        rf"\b{re.escape(k)}\s*[:=]\s*false\b",
        rf"\bnot{re.escape(k)}\b",
    ]
    if k == "healthy":
        negation_patterns.append(r"\bunhealthy\b")
    for pat in negation_patterns:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


def _has_positive_status(keyword: str, text: str) -> bool:
    """Checks that a status keyword appears positively in at least one clause/sentence."""
    clauses = re.split(
        r"(?<=[.!?\n;])\s*|\s*,\s*(?:but|however|while|whereas|although)\s+",
        text,
        flags=re.IGNORECASE,
    )
    for c in clauses:
        if _contains_word(keyword, c) and not _has_negated_status(keyword, c):
            return True
    return False


def evaluate_response_quality(
    prompt_id: int,
    output_text: str,
    target_criteria: str = "",
    required_keywords: list[str] | None = None,
    forbidden_keywords: list[str] | None = None,
    min_length: int = 15,
) -> tuple[bool, str]:
    """Evaluates an agent response deterministically against quality and thread hygiene rules.

    Returns:
        (passed, explanation)
    """
    if not output_text or len(output_text.strip()) < min_length:
        return False, f"Fail: Response truncated or too short (<{min_length} chars)"

    trimmed = output_text.strip()
    lowered = normalize_text(trimmed)

    # 1. Delegation stub check: reject turn-1 status notices (a stub opening phrase or a
    # promise to report later) unless substantive diagnostic content or an informative marker is present.
    is_informative = any(_contains_word(m, lowered) for m in _INFORMATIVE_MARKERS)
    if not is_informative and _is_delegation_stub(trimmed, lowered):
        return False, "Fail: Delegation stub returned instead of completed diagnostic"

    # 2. Clarification loop check: agent should default to host cluster rather than halting
    clarification_markers = ["which cluster did you mean", "could you clarify which cluster"]
    if any(m in lowered for m in clarification_markers):
        return False, "Fail: Clarification loop triggered instead of host cluster default"

    # 3. Prompt #1: Backing Model & Provider Identity
    if prompt_id == 1:
        leaks = []
        if _contains_word("custom", lowered):
            leaks.append("Internal LiteLLM 'custom' provider placeholder leaked")
        if _contains_word("model-default", lowered):
            leaks.append("Internal LiteLLM router alias 'model-default' leaked")
        if leaks:
            return False, f"Fail: {'; '.join(leaks)}"
        has_model = any(_contains_word(m, lowered) for m in ("gemini", "claude"))
        has_provider = any(_contains_word(p, lowered) for p in ("vertex", "google"))
        if not (has_model and has_provider):
            return False, "Fail: Backing model/provider identity unrecognized"

    # 4. Prompt #21: Agent Substrate Architectural Plan
    if prompt_id == 21:
        has_substrate = _contains_word("substrate", lowered)
        has_cluster_part = any(_contains_word(k, lowered) for k in ["cluster", "crd", "operator", "node", "infrastructure", "namespace", "helm", "rbac", "ate.dev"])
        has_workload_part = any(_contains_word(k, lowered) for k in ["workload", "actor", "worker", "pod", "sandbox", "agent pool"])
        has_plan = any(_contains_word(k, lowered) for k in ["plan", "staging", "phase", "step", "prerequisite", "before enabling", "prior to", "verification"])
        if not (has_substrate and has_cluster_part and has_workload_part and has_plan):
            missing = []
            if not has_substrate:
                missing.append("Substrate recognition")
            if not has_cluster_part:
                missing.append("Cluster part (CRDs/node labels/operator)")
            if not has_workload_part:
                missing.append("Workload part (Workers/Actors/sandboxes)")
            if not has_plan:
                missing.append("/plan staging prior to enabling")
            return False, f"Fail: Incomplete substrate plan, missing {', '.join(missing)}"

    # 5. General required keyword presence (anchored with word boundaries & clause-scoped negation checks)
    if required_keywords:
        missing_req = []
        for k in required_keywords:
            if not _contains_word(k, lowered):
                missing_req.append(k)
            elif k.lower().strip() in _STATUS_KEYWORDS and not _has_positive_status(k, lowered):
                missing_req.append(k)
        if missing_req:
            return False, f"Fail: Missing required keyword(s): {', '.join(missing_req)}"

    # 6. General forbidden keyword absence (anchored with word boundaries)
    if forbidden_keywords:
        present_forb = [k for k in forbidden_keywords if _contains_word(k, lowered)]
        if present_forb:
            return False, f"Fail: Contains forbidden keyword(s): {', '.join(present_forb)}"

    return True, "Pass: Response meets quality and hygiene criteria"


try:
    from inspect_ai.scorer import Score, Scorer, Target, accuracy, scorer, stderr
    from inspect_ai.solver import TaskState

    @scorer(metrics=[accuracy(), stderr()])
    def kube_agents_cx_scorer() -> Scorer:
        """Inspect AI scorer implementation of CX quality checks."""
        async def score(state: TaskState, target: Target) -> Score:
            output = state.output.completion
            meta = state.metadata or {}
            pid = meta.get("id", 0)
            req = meta.get("required", [])
            forb = meta.get("forbidden", [])
            min_len = meta.get("min_length", 15)

            passed, explanation = evaluate_response_quality(
                prompt_id=pid,
                output_text=output,
                required_keywords=req,
                forbidden_keywords=forb,
                min_length=min_len,
            )
            return Score(
                value=1.0 if passed else 0.0,
                explanation=explanation,
            )

        return score

except ImportError:
    # Allow importing evaluate_response_quality standalone without inspect_ai installed
    pass
