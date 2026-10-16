"""Regression tests for chat and platform persona host/cluster identity posture (#3350).

Verifies that:
1. agents/chat/SOUL.md directs the front door to answer host cluster and
   deployment identity queries directly without delegating to Kanban.
2. agents/platform/SOUL.md directs the platform worker to resolve host cluster
   queries immediately from environment variables without fleet enumeration.
3. Both agents/platform/SOUL.md and agents/cluster/SOUL.md inline the canonical
   Google Cloud Console URL templates so workers do not spend tool turns
   searching the filesystem for gcp-console-links.md.

Run:
  python3 -m unittest discover -s tests -p 'test_persona_identity_posture.py' -v
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_SOUL = REPO_ROOT / "agents/chat/SOUL.md"
PLATFORM_SOUL = REPO_ROOT / "agents/platform/SOUL.md"
CLUSTER_SOUL = REPO_ROOT / "agents/cluster/SOUL.md"


def _read(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if len(text) < 1000:
        raise AssertionError(f"{path} read back suspiciously short ({len(text)} chars)")
    return text


class PersonaIdentityPostureTests(unittest.TestCase):
    def test_chat_persona_answers_identity_directly(self):
        soul = _read(CHAT_SOUL)
        self.assertIn(
            "**Answer harness identity and host queries directly.**",
            soul,
            "agents/chat/SOUL.md lost the rule directing front door to answer host/cluster identity directly",
        )
        self.assertIn(
            "without delegating to Kanban",
            soul,
            "agents/chat/SOUL.md must state not to delegate host identity queries to Kanban",
        )

    def test_platform_persona_resolves_cluster_identity_immediately(self):
        soul = _read(PLATFORM_SOUL)
        self.assertIn(
            "**Host and Cluster Identity Queries:**",
            soul,
            "agents/platform/SOUL.md lost the rule directing workers to resolve cluster identity immediately",
        )
        self.assertIn(
            "$GKE_CLUSTER_NAME",
            soul,
            "agents/platform/SOUL.md must cite $GKE_CLUSTER_NAME for immediate resolution",
        )
        self.assertIn(
            "Do not enumerate the fleet",
            soul,
            "agents/platform/SOUL.md must forbid enumerating the fleet for basic host queries",
        )

    def test_platform_and_cluster_personas_inline_console_links(self):
        for path in (PLATFORM_SOUL, CLUSTER_SOUL):
            with self.subTest(persona=path.name):
                soul = _read(path)
                self.assertIn(
                    "Do not spend tool calls searching the filesystem for URL templates",
                    soul,
                    f"{path.name} must instruct workers not to search filesystem for URL templates",
                )
                self.assertIn(
                    "https://console.cloud.google.com/logs/query",
                    soul,
                    f"{path.name} must inline the Cloud Logging URL template",
                )
                self.assertIn(
                    "https://console.cloud.google.com/kubernetes/workload/overview",
                    soul,
                    f"{path.name} must inline the GKE Workloads Console URL template",
                )


if __name__ == "__main__":
    unittest.main()
