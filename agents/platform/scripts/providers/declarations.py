#!/usr/bin/env python3
"""Which forges an administrator declared, read once from the environment.

A self-managed forge is not knowable at import time: its host, its scheme and
the file its token is mounted at come from the PlatformAgent, through the
operator. The operator renders them into one environment variable on the
credential sidecar as a JSON list, and this is the one reader of it, so every
`Registry()` built in the process -- the broker's, the content workspace's, the
one that derives the executor's allowlists -- sees the same forges.

An entry is a plain mapping: `name`, `provider`, `host`, `scheme`, `port`,
`tokenFile`. This module does not interpret any of it beyond "a list of
mappings". Each forge class picks out the entries naming its provider and
validates them itself, because what a valid host or port is for a forge is the
forge's rule, not a shared one.

A value that is not a JSON list is logged and read as no declarations. The
alternative -- refusing to start -- would take the default forge away from an
install over a typo in a forge it may never use.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

LOGGER = logging.getLogger("credential-proxy.vcs")

# The environment variable the operator renders the declared forges into.
FORGES_ENV = "CREDENTIAL_PROXY_FORGES"


def declared_forges() -> list[dict[str, Any]]:
    """The forge declarations this process was started with, or none."""
    raw = os.environ.get(FORGES_ENV, "").strip()
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        LOGGER.warning("%s is not JSON; no declared forges are built", FORGES_ENV)
        return []
    if not isinstance(value, list):
        LOGGER.warning("%s is not a JSON list; no declared forges are built", FORGES_ENV)
        return []
    entries = [entry for entry in value if isinstance(entry, dict)]
    if len(entries) != len(value):
        LOGGER.warning("%s: %d entries are not objects and are skipped",
                       FORGES_ENV, len(value) - len(entries))
    return entries
