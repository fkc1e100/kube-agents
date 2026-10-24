"""Preflight fixture override for harness CUJs when CUJ_WEB_CONSOLE_URL is set."""

from __future__ import annotations

import os

import pytest

from cuj.harness.common import (
    COMPLETED_STATUS,
    WEB_CONSOLE_URL_ENV,
    _run_web_console_turn,
)
from cuj.utils.evidence import EvidenceLog
from cuj.utils.portal import (
    PortalError,
    configured_agent_profiles,
    isolated_portal,
    verify_agent,
)

PREFLIGHT_PROMPT = "Reply with exactly READY and nothing else. Do not use tools."
EXPECTED_PREFLIGHT_REPLY = "READY"


@pytest.fixture(scope="session")
def agent_preflight_results() -> dict[tuple[str, str], str]:
    """Verify either ``CUJ_WEB_CONSOLE_URL`` or the local ``isolated_portal``."""

    web_console_url = os.environ.get(WEB_CONSOLE_URL_ENV, "").strip()
    configured = configured_agent_profiles()
    results: dict[tuple[str, str], str] = {}

    if web_console_url:
        log = EvidenceLog.temporary("kube-agents-webui-prerequisite-")
        try:
            interaction = _run_web_console_turn(
                web_console_url,
                PREFLIGHT_PROMPT,
                log,
            )
            status = str(interaction.get("status") or "unknown")
            response = str(interaction.get("output") or "").strip()
            if status != COMPLETED_STATUS or response != EXPECTED_PREFLIGHT_REPLY:
                raise PortalError(
                    "web console preflight did not return READY: "
                    f"status={status}, output={response!r}"
                )
        except (OSError, ValueError, PortalError) as exc:
            detail = f"{exc}; evidence: {log.path}"
            for key in configured:
                results[key] = detail
        else:
            for key in configured:
                results[key] = ""
            print(
                f"Web Console prerequisite passed ({web_console_url}); "
                f"latency: {interaction.get('latencySeconds')}s; "
                f"evidence: {log.path}"
            )
        return results

    for agent_id, profile in configured:
        log = EvidenceLog.temporary("kube-agents-prerequisite-")
        try:
            with isolated_portal(log.root) as endpoint:
                evidence = verify_agent(
                    endpoint,
                    agent_id,
                    log,
                    profile=profile,
                )
        except (OSError, ValueError, PortalError) as exc:
            detail = str(exc)
            if "evidence:" not in detail:
                detail += f"; evidence: {log.root}"
            results[(agent_id, profile)] = detail
        else:
            results[(agent_id, profile)] = ""
            print(
                f"Agent prerequisite passed: {agent_id}/{profile}; "
                f"evidence: {evidence}"
            )
    return results
