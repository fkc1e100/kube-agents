#!/usr/bin/env python3
"""The status whose shared reading is wrong for Gitea.

Gitea answers a second change proposal between the same two branches with 409
and `pull request already exists for these targets`. The shared guidance for
409 says the state moved underneath the call and to re-read and retry, which
sends a caller around the same loop: the proposal is not going away. GitHub
answers the same fault with 422, and the guidance for that -- fix the field the
detail names -- is the one that is right here too, so the two forges hand a
caller one code for one fault. Any other 409 keeps the shared reading.
"""

from __future__ import annotations

from ..errors import GUIDANCE, Guidance

# What Gitea says when the thing a create would make is already there.
_ALREADY_EXISTS_MARKERS = ("already exists", "has already been taken")


def _conflict(message: str) -> Guidance | None:
    """422's guidance when a 409 is a duplicate create, otherwise the shared one."""
    lowered = message.lower()
    if any(marker in lowered for marker in _ALREADY_EXISTS_MARKERS):
        return GUIDANCE[422]
    return None


ERROR_OVERRIDES = {409: _conflict}
