"""Regression tests for platform and cluster persona host/cluster identity posture (#3350).

Verifies that:
1. agents/platform/SOUL.md directs the platform worker to resolve host cluster
   queries immediately from environment variables without fleet enumeration,
   naming only variables the shell sandbox session receives (`GKE_PROJECT_ID`,
   not `GCP_PROJECT_ID`, which is set on the agent container only).
2. Both agents/platform/SOUL.md and agents/cluster/SOUL.md inline the canonical
   Google Cloud Console URL templates and name neither `/opt/defaults/docs/`
   nor `gcp-console-links.md`, which the sandbox file tool cannot open by any
   path, so workers do not spend tool turns searching the filesystem for it.

Run:
  python3 -m unittest discover -s tests -p 'test_persona_identity_posture.py' -v
"""

from __future__ import annotations

import re
import shlex
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLATFORM_SOUL = REPO_ROOT / "agents/platform/SOUL.md"
CLUSTER_SOUL = REPO_ROOT / "agents/cluster/SOUL.md"
CONSOLE_LINKS_DOC = REPO_ROOT / "agents/platform/docs/gcp-console-links.md"
SANDBOX_ENTRYPOINT = REPO_ROOT / "deploy/sandbox/entrypoint.sh"

# A SOUL.md shorter than this was truncated or replaced, not edited.
MIN_SOUL_CHARS = 1000
EXPECTED_CONSOLE_URL_COUNT = 4
IDENTITY_BULLET = "- **Host and Cluster Identity Queries:**"
PROJECT_RESOLUTION_BULLET = "- **Dynamic Project Resolution:**"
# Dynamic Project Resolution quotes `$GCP_PROJECT_ID` once after `literal` as a
# negative prose example of an unexpanded variable shipped in INVENTORY.md.
# Matching that token pair rather than the surrounding sentence lets prose or
# punctuation edits land without falsely blaming SANDBOX_FORWARDED_ENV_NAMES.
NEGATIVE_PROSE_LITERAL_RE = re.compile(r"\bliteral\s+`\$\{?GCP_PROJECT_ID\}?`")
SANDBOX_UNREACHABLE_DOCS = "/opt/defaults/docs/"
CONSOLE_URL_RE = re.compile(r"`(https://console\.cloud\.google\.com/[^`]+)`")
FORWARDED_ENV_RE = re.compile(r'SANDBOX_FORWARDED_ENV_NAMES="([^"]+)"')
CODE_SPAN_RE = re.compile(r"`([^`]+)`")
ENV_IDENT_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
# Closed code-span scan: cites every uppercase identifier token inside a
# backticked span (excluding `/`-prefixed path segments, `-[A-Z]` CLI flags,
# `%XX` URL escapes, and uppercase filenames like `INVENTORY.md`), so no quoted,
# piped, awk/grep, or other command spelling in a SOUL code span can hide an
# unforwarded variable name behind an unenumerated verb.
CODE_SPAN_ENV_RE = re.compile(
    r"(?<![/%-])\b([A-Z][A-Z0-9_]*)\b(?!\.(?:md|yaml|yml|json|py|sh|txt|toml)\b)"
)
# Matches `$VAR`, `${VAR}`, `${!VAR}`, `${#VAR}`, and `${VAR:-...}` expansions
# anywhere in prose or code spans, plus bare SCREAMING_SNAKE_CASE identifiers.
DOLLAR_ENV_RE = re.compile(r"\$(?:\{[!#]?([A-Z][A-Z0-9_]*)(?:[^}]*)?\}|([A-Z][A-Z0-9_]*)\b)")
SCREAMING_SNAKE_RE = re.compile(r"\b([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)\b")
# Unbackticked fallbacks for plain-prose shell or Python env reads written
# without code fences (including quoted variable names and piped grep dumps).
QUOTED_OR_BARE_ENV_TOKEN_RE = re.compile(r"[\"']?([A-Z][A-Z0-9_]*)[\"']?")
EXEC_ENV_ARGS_RE = re.compile(
    r"\b(?:printenv(?:\s+(?:-0|--null))*|(?:declare|typeset)(?:\s+-[A-Za-z]+)*|"
    r"export(?:\s+-[A-Za-z]+)+|env\s+(?:-u|--unset))(?:=|\s+)(?:--\s+)?"
    r"([\"']?[A-Z][A-Z0-9_]*[\"']?(?:\s+[\"']?[A-Z][A-Z0-9_]*[\"']?)*)"
)
DUMP_PIPE_GREP_RE = re.compile(
    r"\b(?:printenv|env|set|export|declare|typeset)\b[^.\n]*?\|\s*(?:e?grep|fgrep|rg)\b"
    r"(?:\s+(?:-[A-Za-z0-9-]+|\d+)\s+)*\s*[\"'^(]*([A-Z][A-Z0-9_]*)"
)
PY_ENV_LOOKUP_RE = re.compile(r"\b(?:environ(?:\.get)?\s*[\[(]|getenv\s*\()\s*['\"]([A-Z][A-Z0-9_]*)['\"]")


def _cited_env_vars(text: str) -> set[str]:
    names = {braced or bare for braced, bare in DOLLAR_ENV_RE.findall(text)}
    names.update(SCREAMING_SNAKE_RE.findall(text))
    for span in CODE_SPAN_RE.findall(text):
        try:
            tokens = shlex.split(span, posix=True)
        except ValueError:
            tokens = []
        for token in tokens:
            candidate = token.split("=", 1)[0] if "=" in token else token
            if ENV_IDENT_RE.fullmatch(candidate):
                names.add(candidate)
        names.update(CODE_SPAN_ENV_RE.findall(span))
    for arg_group in EXEC_ENV_ARGS_RE.findall(text):
        names.update(QUOTED_OR_BARE_ENV_TOKEN_RE.findall(arg_group))
    names.update(DUMP_PIPE_GREP_RE.findall(text))
    names.update(PY_ENV_LOOKUP_RE.findall(text))
    return names


def _cleaned_project_resolution_bullet(project_bullet: str) -> str:
    cleaned, count = NEGATIVE_PROSE_LITERAL_RE.subn("", project_bullet, count=1)
    if count != 1:
        raise AssertionError(
            "Dynamic Project Resolution no longer matches NEGATIVE_PROSE_LITERAL_RE "
            r"(\bliteral\s+`\$\{?GCP_PROJECT_ID\}?`); update or remove that token pin in "
            "tests/test_persona_identity_posture.py if the negative prose example was reworded"
        )
    return cleaned


def _read(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if len(text) < MIN_SOUL_CHARS:
        raise AssertionError(f"{path} read back suspiciously short ({len(text)} chars)")
    return text


def _line_starting(text: str, prefix: str) -> str:
    for line in text.splitlines():
        if line.startswith(prefix):
            return line
    raise AssertionError(f"no line starts with {prefix!r}")


class PersonaIdentityPostureTests(unittest.TestCase):
    def test_platform_persona_resolves_cluster_identity_immediately(self):
        bullet = _line_starting(_read(PLATFORM_SOUL), IDENTITY_BULLET)
        for var in ("$GKE_CLUSTER_NAME", "$GKE_PROJECT_ID", "$GKE_LOCATION", "$KUBE_CONTEXT_NAME"):
            self.assertIn(var, bullet, f"identity bullet must cite {var} for immediate resolution")
        self.assertIn(
            "`in-cluster`",
            bullet,
            "identity bullet must note that kind installs use the in-cluster kubectl context",
        )
        self.assertIn(
            "`gke_kind_kind_kind`",
            bullet,
            "identity bullet must warn that KUBE_CONTEXT_NAME holds gke_kind_kind_kind in the sandbox on kind",
        )
        self.assertIn(
            "Do not enumerate the fleet",
            bullet,
            "identity bullet must forbid enumerating the fleet for basic host queries",
        )

    def test_platform_identity_bullet_names_only_sandbox_forwarded_vars(self):
        soul = _read(PLATFORM_SOUL)
        bullet = _line_starting(soul, IDENTITY_BULLET)
        entrypoint = _read(SANDBOX_ENTRYPOINT)
        match = FORWARDED_ENV_RE.search(entrypoint)
        self.assertIsNotNone(match, "deploy/sandbox/entrypoint.sh must define SANDBOX_FORWARDED_ENV_NAMES")
        forwarded = set(match.group(1).split())

        # Assert every environment variable cited in the identity bullet (any uppercase
        # identifier in a backticked code span, any `$VAR`/`${VAR}`/`${!VAR}` expansion, bare
        # SCREAMING_SNAKE_CASE, or unbackticked env-read command) is forwarded to the sandbox.
        vars_in_bullet = _cited_env_vars(bullet)
        self.assertTrue(vars_in_bullet, "identity bullet must cite at least one forwarded env var")
        self.assertTrue(
            vars_in_bullet.issubset(forwarded),
            f"identity bullet names vars not in SANDBOX_FORWARDED_ENV_NAMES: {vars_in_bullet - forwarded}",
        )

        # Apply the same forwarded-subset guard to Dynamic Project Resolution, excluding only
        # its single `literal `$GCP_PROJECT_ID`` negative prose token.
        cleaned_project_bullet = _cleaned_project_resolution_bullet(_line_starting(soul, PROJECT_RESOLUTION_BULLET))
        vars_in_project = _cited_env_vars(cleaned_project_bullet)
        self.assertTrue(vars_in_project, "Dynamic Project Resolution must cite at least one forwarded env var")
        self.assertTrue(
            vars_in_project.issubset(forwarded),
            f"Dynamic Project Resolution names vars not in SANDBOX_FORWARDED_ENV_NAMES: {vars_in_project - forwarded}",
        )

    def test_cited_env_vars_catches_dollar_braced_and_bare_unforwarded_spellings(self):
        soul = _read(PLATFORM_SOUL)
        identity_bullet = _line_starting(soul, IDENTITY_BULLET)
        raw_project_bullet = _line_starting(soul, PROJECT_RESOLUTION_BULLET)
        cleaned_project_bullet = _cleaned_project_resolution_bullet(raw_project_bullet)
        entrypoint = _read(SANDBOX_ENTRYPOINT)
        forwarded = set(FORWARDED_ENV_RE.search(entrypoint).group(1).split())

        for expected_var, snippet in (
            ("GCP_PROJECT_ID", "$GCP_PROJECT_ID"),
            ("GCP_PROJECT_ID", "${GCP_PROJECT_ID}"),
            ("GCP_PROJECT_ID", "printenv GCP_PROJECT_ID"),
            ("GCP_PROJECT_ID", "also exported as `$GCP_PROJECT_ID`"),
            ("GCP_PROJECT_ID", "`$GKE_PROJECT_ID`, i.e. `${GCP_PROJECT_ID}`"),
            ("GCP_PROJECT_ID", "or `printenv GCP_PROJECT_ID`"),
            ("HOSTNAME", "resolve it with `printenv HOSTNAME`"),
            ("HOSTNAME", 'resolve it with `printenv "HOSTNAME"`'),
            ("HOSTNAME", "resolve it with `printenv 'HOSTNAME'`"),
            ("HOSTNAME", 'printenv "HOSTNAME"'),
            ("HOSTNAME", "printenv -- HOSTNAME"),
            ("HOSTNAME", "printenv GKE_PROJECT_ID HOSTNAME"),
            ("HOSTNAME", "`env | grep HOSTNAME`"),
            ("HOSTNAME", "env | grep HOSTNAME"),
            ("HOSTNAME", "`printenv | grep -w HOSTNAME`"),
            ("HOSTNAME", "printenv | grep -w HOSTNAME"),
            ("HOSTNAME", "`env | grep '^HOSTNAME='`"),
            ("HOSTNAME", "`awk 'BEGIN{print ENVIRON[\"HOSTNAME\"]}'`"),
            ("HOSTNAME", "read `HOSTNAME` from the environment"),
            ("HOSTNAME", "${!HOSTNAME}"),
            ("HOSTNAME", "`${!HOSTNAME}`"),
            ("PROJECT", "declare -p PROJECT"),
            ("PROJECT", 'declare -p "PROJECT"'),
            ("PROJECT", "typeset -xp PROJECT"),
            ("HOSTNAME", "$HOSTNAME"),
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(expected_var, _cited_env_vars(snippet))
                self.assertFalse(_cited_env_vars(f"{identity_bullet} ({snippet})").issubset(forwarded))
                self.assertFalse(_cited_env_vars(f"{cleaned_project_bullet} ({snippet})").issubset(forwarded))

        # Rewording prose or punctuation around `literal `$GCP_PROJECT_ID`` keeps passing,
        # while changing the token itself fails naming NEGATIVE_PROSE_LITERAL_RE.
        reworded_prose = raw_project_bullet.replace(" — ", " -- ").replace(
            "shipped with exactly that.", "shipped that."
        )
        self.assertTrue(_cited_env_vars(_cleaned_project_resolution_bullet(reworded_prose)).issubset(forwarded))
        with self.assertRaisesRegex(AssertionError, "NEGATIVE_PROSE_LITERAL_RE"):
            _cleaned_project_resolution_bullet(raw_project_bullet.replace("literal `$GCP_PROJECT_ID`", "example"))

        self.assertEqual(
            _cited_env_vars(
                "on GKE installs in GCP (`in-cluster`, `gke_kind_kind_kind`, "
                "`gke_<project>_<location>_<cluster>`, `/opt/data/INVENTORY.md`, "
                "`INVENTORY.md`, `kubectl get pods -A`)"
            ),
            set(),
        )

    def test_platform_and_cluster_personas_inline_console_links(self):
        canonical_urls = CONSOLE_URL_RE.findall(CONSOLE_LINKS_DOC.read_text(encoding="utf-8"))
        self.assertEqual(
            len(canonical_urls),
            EXPECTED_CONSOLE_URL_COUNT,
            f"{CONSOLE_LINKS_DOC} must define the {EXPECTED_CONSOLE_URL_COUNT} canonical console URL templates",
        )
        for path in (PLATFORM_SOUL, CLUSTER_SOUL):
            with self.subTest(persona=path.parent.name):
                soul = _read(path)
                self.assertEqual(
                    CONSOLE_URL_RE.findall(soul),
                    canonical_urls,
                    f"{path} inlined console URL templates drifted from {CONSOLE_LINKS_DOC}",
                )
                self.assertNotIn(
                    SANDBOX_UNREACHABLE_DOCS,
                    soul,
                    f"{path} names a {SANDBOX_UNREACHABLE_DOCS} path the sandbox file tool cannot open",
                )
                self.assertNotIn(
                    CONSOLE_LINKS_DOC.name,
                    soul,
                    f"{path} names {CONSOLE_LINKS_DOC.name}, a file the sandbox file tool cannot open by any path",
                )


if __name__ == "__main__":
    unittest.main()
