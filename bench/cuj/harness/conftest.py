"""Preflight fixture override for harness CUJs when CUJ_WEB_CONSOLE_URL is set."""

from __future__ import annotations

import os

import pytest

from cuj.conftest import agent_preflight_results as _portal_preflight_results
from cuj.harness.common import (
    COMPLETED_STATUS,
    WEB_CONSOLE_URL_ENV,
    _run_web_console_turn,
)
from cuj.utils.evidence import EvidenceLog
from cuj.utils.portal import (
    PortalError,
    configured_agent_profiles,
)

PREFLIGHT_PROMPT = "Reply with exactly READY and nothing else. Do not use tools."
EXPECTED_PREFLIGHT_REPLY = "READY"


@pytest.fixture(scope="session")
def agent_preflight_results() -> dict[tuple[str, str], str]:
    """Verify either ``CUJ_WEB_CONSOLE_URL`` or the local ``isolated_portal``."""

    web_console_url = os.environ.get(WEB_CONSOLE_URL_ENV, "").strip()
    if not web_console_url:
        return _portal_preflight_results.__wrapped__()

    configured = configured_agent_profiles()
    results: dict[tuple[str, str], str] = {}
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
