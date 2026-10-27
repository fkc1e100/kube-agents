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

import functools
import re
import time
import unittest
import urllib.parse
from pathlib import Path

from markdown_it import MarkdownIt

try:
    from test_sandbox_entrypoint import sandbox_forwarded_env_names
except ModuleNotFoundError:
    from tests.test_sandbox_entrypoint import sandbox_forwarded_env_names

REPO_ROOT = Path(__file__).resolve().parents[1]
PLATFORM_SOUL = REPO_ROOT / "agents/platform/SOUL.md"
CLUSTER_SOUL = REPO_ROOT / "agents/cluster/SOUL.md"
CONSOLE_LINKS_DOC = REPO_ROOT / "agents/platform/docs/gcp-console-links.md"
MARKDOWN = MarkdownIt("commonmark")

# Closed allowlist of bare all-caps non-variable acronyms permitted in
# unbackticked prose in the two guarded SOUL bullets. Any other bare all-caps
# word of two or more characters in prose fails loud naming the word so
# underscore-free unforwarded variables (`HOSTNAME`, `ENV`, `PROJECT`, `HOME`,
# `PATH`, `KUBECONFIG`) cannot slip past behind an unpiped `export`/`set` or
# unlisted env-table dump.
PROSE_ACRONYM_ALLOWLIST = frozenset(
    {
        "API",
        "CLI",
        "CR",
        "CRD",
        "DNS",
        "GCP",
        "GKE",
        "HTTP",
        "HTTPS",
        "IAM",
        "ID",
        "IP",
        "JSON",
        "PR",
        "RBAC",
        "SSH",
        "URI",
        "URL",
        "UTC",
        "VPC",
        "YAML",
    }
)

# A SOUL.md shorter than this was truncated or replaced, not edited.
MIN_SOUL_CHARS = 1000
EXPECTED_CONSOLE_URL_COUNT = 4
ADVERSARIAL_REPEAT_COUNT = 10_000
MAX_SCAN_CPU_SECONDS = 1.0
IDENTITY_BULLET = "- **Host and Cluster Identity Queries:**"
PROJECT_RESOLUTION_BULLET = "- **Dynamic Project Resolution:**"
# Dynamic Project Resolution quotes `$GCP_PROJECT_ID` once after `literal` as a
# negative prose example of an unexpanded variable shipped in INVENTORY.md.
# Matching that token pair rather than the surrounding sentence lets prose or
# punctuation edits land without falsely blaming SANDBOX_FORWARDED_ENV_NAMES.
NEGATIVE_PROSE_LITERAL_RE = re.compile(r"\bliteral\s+`\$\{?GCP_PROJECT_ID\}?`")
SANDBOX_UNREACHABLE_DOCS = "/opt/defaults/docs/"
CONSOLE_URL_RE = re.compile(r"`(https://console\.cloud\.google\.com/[^`]+)`")
# Environment variable names must open with `[A-Z]` and end with `[A-Z0-9]` so a
# trailing-underscore prefix filter like `env | grep GKE_` or `GKE_|KUBE_CONTEXT_`
# is not misreported as an unforwarded variable name.
# Closed code-span scan: cites every uppercase identifier token inside a
# backticked span (excluding `/`-prefixed path segments, `-[A-Z]` CLI flags,
# `%XX` URL escapes / `%ENV`, `<PLACEHOLDER>` template slots, `BEGIN{`/`END{`
# awk blocks, `ENVIRON[...]`/`in ENVIRON)` table names,
# `ENV{...}`/`ENV[...]`/`ENV.<method>` table names, trailing-underscore prefixes
# like `GKE_`, and uppercase filenames like `INVENTORY_2026.md` or
# `CLUSTER_POLICY.yaml`), paired with `ATTACHED_UNSET_OPT_RE` for attached
# `env -uVAR` short options, so no quoted, piped, awk/perl/grep, or other
# command spelling in a SOUL code span can hide an unforwarded variable name
# behind an unenumerated verb.
CODE_SPAN_ENV_RE = re.compile(
    r"(?<![/%<-])\b(?!(?:BEGIN|END)\s*\{)(?!ENVIRON\s*[\[\)])"
    r"(?!ENV(?:\s*[\{\[]|\.[A-Za-z_]))"
    r"([A-Z](?:[A-Z0-9_]*[A-Z0-9])?)\b(?!\.(?:md|yaml|yml|json|py|sh|txt|toml)\b)"
)
ATTACHED_UNSET_OPT_RE = re.compile(
    r"(?<![\w-])-[A-HJ-TV-Za-hj-tv-z]*u([A-Z](?:[A-Z0-9_]*[A-Z0-9])?)\b"
)
# Matches `$VAR`, `${VAR}`, `${!VAR}`, `${#VAR}`, and `${VAR:-...}` expansions
# in unbackticked prose (excluding `$ENV{...}` / `$ENV.VAR` table prefixes and
# trailing-underscore `$GKE_`), bare SCREAMING_SNAKE_CASE identifiers, and bare
# all-caps words of two or more characters (subtracting PROSE_ACRONYM_ALLOWLIST).
# `[^A-Z0-9_}]` keeps the identifier and operator suffix disjoint on unclosed
# `${...`.
DOLLAR_ENV_RE = re.compile(
    r"\$(?:\{[!#]?([A-Z](?:[A-Z0-9_]*[A-Z0-9])?)(?:[^A-Z0-9_}][^}]*)?\}|"
    r"(?!ENV(?:\s*\{|\.[A-Za-z_]))([A-Z](?:[A-Z0-9_]*[A-Z0-9])?)\b)"
)
SCREAMING_SNAKE_RE = re.compile(r"\b([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)\b")
PROSE_ALL_CAPS_RE = re.compile(r"(?<![%<])\b([A-Z][A-Z0-9]+)\b")
# Style check catching common shell and interpreter env-read spellings left
# unbackticked in prose (while PROSE_ALL_CAPS_RE minus PROSE_ACRONYM_ALLOWLIST
# acts as the closed prose backstop for unpiped `export`/`set` or unlisted env
# dumps). Adjacent quantifiers and option/redirection loops use pairwise-disjoint
# character classes so adversarial `-ppp...`, `-uuu...`, `&& `, and ` & &` runs
# stay strictly O(n).
UNBACKTICKED_ENV_READ_RE = re.compile(
    r"\b(?:printenv|getenv|strenv)\b"
    r"|\.environ\b"
    r"|/proc/(?:self|\d+)/environ\b"
    r"|\bENVIRON\s*\["
    r"|\bin\s+ENVIRON\b"
    r"|(?:[%@]ENV\b|\$_(?:ENV|SERVER)\b|\$ENV(?:\s*\{|\.[A-Za-z_])|\bENV\s*(?:[\[\{]|\.[A-Za-z_]))"
    r"|\bcompgen\s+-[A-DF-Za-df-z]*[eE][A-Za-z]*\b"
    r"|\b(?:process|Deno|Bun)\.env\b"
    r"|\benv\.[A-Z]"
    r"|\b(?:str)?env\(\s*[A-Z\"']"
    r"|\b(?:declare|typeset|export)\s+-[A-OQ-WYZa-oq-wyz]*[pPxX][A-Za-z]*\b"
    r"|\b(?:env|set|export|declare|typeset)(?:[ \t]+(?:-[^\s|;&<>]+|\d*(?:>[>&]?|<[<>]?|&>>?)[ \t]*[^\s|;&<>]+))*[ \t]*\|(?!\|)"
    r"|\b(?:env|set|export|declare)\s+(?:-[A-HJ-TV-Za-hj-tv-z]*[iIuU][A-Za-z0-9_]*|--unset\b|--ignore-environment\b)"
)


@functools.lru_cache(maxsize=64)
def _doc_references(doc: str) -> dict[str, dict[str, object]]:
    env: dict[str, object] = {}
    MARKDOWN.parse(doc, env)
    refs = env.get("references")
    return dict(refs) if isinstance(refs, dict) else {}


@functools.lru_cache(maxsize=64)
def _code_spans_and_prose(text: str, doc: str | None = None) -> tuple[tuple[str, ...], str]:
    """Return ``(code_spans, unbackticked_prose)`` tokenized by CommonMark,
    including link/image ``href``, ``src``, and ``title`` attributes plus link
    reference definitions."""
    code_spans: list[str] = []
    prose_parts: list[str] = []
    local_env: dict[str, object] = {}
    local_tokens = MARKDOWN.parse(text, local_env)
    if doc is not None:
        seeded_refs = dict(_doc_references(doc))
        local_refs = local_env.get("references")
        if isinstance(local_refs, dict):
            seeded_refs.update(local_refs)
        tokens = MARKDOWN.parse(text, {"references": seeded_refs})
    else:
        tokens = local_tokens

    def _walk_inline(children: list[object]) -> None:
        for child in children:
            if child.type == "code_inline":
                code_spans.append(child.content)
                prose_parts.append(" ")
                continue
            for attr_name in ("href", "src", "title"):
                attr_val = child.attrGet(attr_name)
                if attr_val:
                    decoded = urllib.parse.unquote(attr_val) if attr_name in ("href", "src") else attr_val
                    prose_parts.extend(("\n", decoded, "\n"))
            if child.type in ("softbreak", "hardbreak"):
                prose_parts.append("\n")
            elif child.children:
                _walk_inline(child.children)
            elif child.content:
                prose_parts.append(child.content)

    for token in tokens:
        if token.type in ("fence", "code_block"):
            code_spans.append(token.content)
            prose_parts.append("\n")
        elif token.type == "html_block":
            prose_parts.append(token.content)
            prose_parts.append("\n")
        elif token.type.endswith("_close") or token.type == "hr":
            prose_parts.append("\n")
        elif token.type == "inline" and token.children:
            _walk_inline(token.children)

    local_refs = local_env.get("references")
    if isinstance(local_refs, dict):
        for ref in local_refs.values():
            if isinstance(ref, dict):
                href = ref.get("href")
                if isinstance(href, str) and href:
                    prose_parts.extend(("\n", urllib.parse.unquote(href), "\n"))
                title = ref.get("title")
                if isinstance(title, str) and title:
                    prose_parts.extend(("\n", title, "\n"))
    return tuple(code_spans), "".join(prose_parts)


def _unbackticked_env_reads(text: str, *, doc: str | None = None) -> list[str]:
    _, prose = _code_spans_and_prose(text, doc)
    return [m.group(0).strip() for m in UNBACKTICKED_ENV_READ_RE.finditer(prose)]


def _cited_env_vars(text: str, *, doc: str | None = None) -> set[str]:
    code_spans, prose = _code_spans_and_prose(text, doc)
    names = {braced or bare for braced, bare in DOLLAR_ENV_RE.findall(prose)}
    names.update(SCREAMING_SNAKE_RE.findall(prose))
    names.update(word for word in PROSE_ALL_CAPS_RE.findall(prose) if word not in PROSE_ACRONYM_ALLOWLIST)
    for span in code_spans:
        names.update(CODE_SPAN_ENV_RE.findall(span))
        names.update(ATTACHED_UNSET_OPT_RE.findall(span))
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


def _bullet_block(text: str, prefix: str) -> str:
    """Return the full CommonMark list item starting with ``prefix``, including
    indented sub-bullets, loose indented paragraphs across blank lines, fenced
    code blocks, and lazy continuation lines."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[str] = []
    item_depth = 0
    for token in MARKDOWN.parse(text):
        if token.type == "list_item_open":
            if item_depth == 0 and token.map is not None:
                start, end = token.map
                block = "\n".join(lines[start:end]).rstrip()
                if block.startswith(prefix):
                    blocks.append(block)
            item_depth += 1
        elif token.type == "list_item_close":
            item_depth -= 1
    if not blocks:
        raise AssertionError(f"no line starts with {prefix!r}")
    if len(blocks) > 1:
        raise AssertionError(f"multiple list items start with {prefix!r}")
    return blocks[0]


class PersonaIdentityPostureTests(unittest.TestCase):
    def test_platform_persona_resolves_cluster_identity_immediately(self):
        bullet = _bullet_block(_read(PLATFORM_SOUL), IDENTITY_BULLET)
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
        bullet = _bullet_block(soul, IDENTITY_BULLET)
        forwarded = sandbox_forwarded_env_names()
        self.assertTrue(forwarded, "deploy/sandbox/entrypoint.sh must define SANDBOX_FORWARDED_ENV_NAMES")

        # Assert shell/interpreter env reads in the full identity list item are backticked and
        # every cited environment variable (including continuation lines, nested sub-bullets,
        # link/image URLs or titles, and reference definitions) is forwarded to the sandbox.
        self.assertEqual(
            _unbackticked_env_reads(bullet, doc=soul),
            [],
            "identity bullet must wrap shell/interpreter env-read commands in backticks",
        )
        vars_in_bullet = _cited_env_vars(bullet, doc=soul)
        self.assertTrue(vars_in_bullet, "identity bullet must cite at least one forwarded env var")
        self.assertTrue(
            vars_in_bullet.issubset(forwarded),
            f"identity bullet names vars not in SANDBOX_FORWARDED_ENV_NAMES: {vars_in_bullet - forwarded}",
        )

        # Apply the same backtick-enforcement and whole-list-item forwarded-subset guard to
        # Dynamic Project Resolution, excluding only its single `literal `$GCP_PROJECT_ID``
        # negative prose token.
        cleaned_project_bullet = _cleaned_project_resolution_bullet(_bullet_block(soul, PROJECT_RESOLUTION_BULLET))
        self.assertEqual(
            _unbackticked_env_reads(cleaned_project_bullet, doc=soul),
            [],
            "Dynamic Project Resolution must wrap shell/interpreter env-read commands in backticks",
        )
        vars_in_project = _cited_env_vars(cleaned_project_bullet, doc=soul)
        self.assertTrue(vars_in_project, "Dynamic Project Resolution must cite at least one forwarded env var")
        self.assertTrue(
            vars_in_project.issubset(forwarded),
            f"Dynamic Project Resolution names vars not in SANDBOX_FORWARDED_ENV_NAMES: {vars_in_project - forwarded}",
        )

    def test_cited_env_vars_catches_dollar_braced_and_bare_unforwarded_spellings(self):
        soul = _read(PLATFORM_SOUL)
        identity_bullet = _bullet_block(soul, IDENTITY_BULLET)
        raw_project_bullet = _bullet_block(soul, PROJECT_RESOLUTION_BULLET)
        cleaned_project_bullet = _cleaned_project_resolution_bullet(raw_project_bullet)
        forwarded = sandbox_forwarded_env_names()

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
            ("HOSTNAME", "`printenv -- HOSTNAME`"),
            ("HOSTNAME", "`printenv GKE_PROJECT_ID HOSTNAME`"),
            ("HOSTNAME", "`env | grep HOSTNAME`"),
            ("HOSTNAME", "`printenv | grep -w HOSTNAME`"),
            ("HOSTNAME", "`printenv | sort | grep HOSTNAME`"),
            ("HOSTNAME", "`printenv | sort -u | tr -s ' ' | grep --color=auto HOSTNAME`"),
            ("HOSTNAME", "`env | grep --color=auto HOSTNAME`"),
            ("HOSTNAME", "`env -uHOSTNAME printenv GKE_PROJECT_ID`"),
            ("HOSTNAME", "`env --unset=HOSTNAME printenv GKE_PROJECT_ID`"),
            ("HOSTNAME", "`set | sort | grep HOSTNAME`"),
            ("HOSTNAME", "`cat /proc/self/environ | tr '\\0' '\\n' | grep HOSTNAME`"),
            ("HOSTNAME", "`env | grep '^HOSTNAME='`"),
            ("HOSTNAME", "`awk 'BEGIN{print ENVIRON[\"HOSTNAME\"]}'`"),
            ("HOSTNAME", "`perl -e 'print \"$ENV{HOSTNAME}\\n\"'`"),
            ("HOSTNAME", "`perl -e 'print $ENV{HOSTNAME}'`"),
            ("HOSTNAME", "`python3 -c 'import os; print(os.environ[\"HOSTNAME\"])'`"),
            ("HOSTNAME", "`os.environ.get('HOSTNAME')`"),
            ("HOSTNAME", "`jq -rn 'env.HOSTNAME'`"),
            ("HOSTNAME", "`yq -n 'strenv(HOSTNAME)'`"),
            ("HOSTNAME", "`yq -n 'env(HOSTNAME)'`"),
            ("HOSTNAME", "read `HOSTNAME` from the environment"),
            ("HOSTNAME", "${!HOSTNAME}"),
            ("HOSTNAME", "`${!HOSTNAME}`"),
            ("HOSTNAME", "Run export and read HOSTNAME from it."),
            ("HOSTNAME", "run set and look for HOSTNAME"),
            ("HOSTNAME", "compgen -e and read HOSTNAME"),
            ("HOSTNAME", 'PHP $_ENV["HOSTNAME"]'),
            ("HOSTNAME", 'PHP $_SERVER["HOSTNAME"]'),
            ("HOSTNAME", '__import__("os").environ["HOSTNAME"]'),
            ("ENV", "`printenv ENV`"),
            ("ENV", "$ENV"),
            ("ENV", "Ruby: p ENV"),
            ("PROJECT", "`declare -p PROJECT`"),
            ("PROJECT", '`declare -p "PROJECT"`'),
            ("PROJECT", "`typeset -xp PROJECT`"),
            ("PROJECT", "Run declare and read PROJECT from it."),
            ("GKE", "$GKE"),
            ("GCP", "`printenv GCP`"),
            ("HOSTNAME", "$HOSTNAME"),
            ("HOSTNAME", "`` `printenv HOSTNAME` ``"),
            ("HOSTNAME", "`` `env -uHOSTNAME printenv GKE_PROJECT_ID` ``"),
            ("KUBE_CONTEXT", "`env | grep -E 'GKE_|KUBE_CONTEXT'`"),
        ):
            with self.subTest(snippet=snippet):
                self.assertIn(expected_var, _cited_env_vars(snippet))
                self.assertFalse(_cited_env_vars(f"{identity_bullet} ({snippet})").issubset(forwarded))
                self.assertFalse(_cited_env_vars(f"{cleaned_project_bullet} ({snippet})").issubset(forwarded))

        # Double-backtick inline code spans count as backticked rather than prose.
        self.assertEqual(_unbackticked_env_reads("`` `printenv HOSTNAME` ``"), [])
        self.assertEqual(_unbackticked_env_reads("`` `env -uHOSTNAME printenv GKE_PROJECT_ID` ``"), [])

        # Trailing-underscore prefixes (`GKE_`, `KUBE_CONTEXT_`) are not cited as variable names.
        self.assertNotIn("GKE_", _cited_env_vars("`env | grep -E 'GKE_|KUBE_CONTEXT'`"))
        for prefix_filter, expected_set in (
            ("`env | grep GKE_`", set()),
            ("`env | grep -E 'GKE_|KUBE_CONTEXT_'`", set()),
            ("`env | grep -E 'GKE_|KUBE_CONTEXT_NAME'`", {"KUBE_CONTEXT_NAME"}),
            (
                "`python3 -c 'import os; print({k: v for k, v in os.environ.items() if k.startswith((\"GKE_\", \"KUBE_CONTEXT_\"))})'`",
                set(),
            ),
            ("$GKE_", set()),
            ("${GKE_}", set()),
        ):
            with self.subTest(prefix_filter=prefix_filter):
                self.assertEqual(_unbackticked_env_reads(prefix_filter), [])
                self.assertEqual(_cited_env_vars(prefix_filter), expected_set)
                self.assertTrue(_cited_env_vars(f"{identity_bullet} ({prefix_filter})").issubset(forwarded))

        # Unbackticked shell/interpreter env-read commands in prose fail the backtick guard
        # directly, including between paired English possessives (`host's ... pod's`).
        for unbackticked_read in (
            "Use the host's shell: printenv HOSTNAME prints the pod's name.",
            'printenv "HOSTNAME"',
            "printenv -- HOSTNAME",
            "env | grep HOSTNAME",
            "Dump them with env -0 | tr '\\0' '\\n' | grep HOSTNAME.",
            "env 2>/dev/null | grep HOSTNAME",
            "env 2> /dev/null | grep HOSTNAME",
            "env 2>&1 | grep HOSTNAME",
            "env -0|grep HOSTNAME",
            "typeset | grep HOSTNAME",
            "compgen -e",
            "compgen -ae",
            "printenv | sort | grep --color=auto HOSTNAME",
            "env -uHOSTNAME printenv GKE_PROJECT_ID",
            "env --unset=HOSTNAME printenv GKE_PROJECT_ID",
            "set | sort | grep HOSTNAME",
            "cat /proc/self/environ | tr '\\0' '\\n' | grep HOSTNAME",
            "declare -p PROJECT",
            'declare -p "PROJECT"',
            "typeset -xp PROJECT",
            "export -p | grep HOSTNAME",
            "awk 'BEGIN{print ENVIRON[\"HOSTNAME\"]}'",
            "perl -e 'print \"$ENV{HOSTNAME}\\n\"'",
            "ruby -e 'puts ENV.fetch(\"HOSTNAME\")'",
            '$_ENV["HOSTNAME"]',
            '$_SERVER["HOSTNAME"]',
            "python3 -c 'import os; print(os.environ[\"HOSTNAME\"])'",
            '__import__("os").environ["HOSTNAME"]',
            "os.environ.get('HOSTNAME')",
            "os.getenv('HOSTNAME')",
            "jq -rn 'env.HOSTNAME'",
            "yq -n 'strenv(HOSTNAME)'",
            "yq -n 'env(HOSTNAME)'",
        ):
            with self.subTest(unbackticked_read=unbackticked_read):
                self.assertTrue(_unbackticked_env_reads(unbackticked_read))
                self.assertTrue(_unbackticked_env_reads(f"{identity_bullet} {unbackticked_read}"))
                self.assertTrue(_unbackticked_env_reads(f"{cleaned_project_bullet} {unbackticked_read}"))

        # Expanding either guarded bullet across nested sub-bullets, loose indented paragraphs,
        # indented fenced code blocks, wrapped lazy continuation lines, or Markdown link/image
        # destinations, titles, and reference definitions still scans the whole list item, while
        # leaving variables in adjacent top-level bullets or standalone post-blank paragraphs
        # outside the item.
        for continuation in (
            "\n  - `$GCP_PROJECT_ID` for the project",
            '\n  - resolve with `printenv "HOSTNAME"`',
            "\n\n  - `printenv HOSTNAME`",
            "\n  ```sh\n  awk 'BEGIN{print ENVIRON[\"HOSTNAME\"]}'\n  ```\n  and `$GKE_CLUSTER_NAME`",
            "\nor resolve it via `printenv HOSTNAME`.",
            "\n#not-an-atx-heading `printenv HOSTNAME`",
            "\n####### seven-hashes `$HOSTNAME`",
            " or open [the cluster page](https://console.cloud.google.com/kubernetes/clusters/details/$GKE_LOCATION/$GKE_CLUSTER_NAME?project=$GCP_PROJECT_ID).",
            " or open [the cluster page](https://console.cloud.google.com/kubernetes/clusters/details/$GKE_LOCATION/$GKE_CLUSTER_NAME?project=${HOSTNAME}).",
            ' or open [the cluster page](https://console.cloud.google.com/ "Cluster $HOSTNAME").',
            " ![cluster](https://console.cloud.google.com/$HOSTNAME)",
            "\n\n  [console]: https://console.cloud.google.com/?project=$GCP_PROJECT_ID",
            '\n\n  [console]: https://console.cloud.google.com/ "Ref $HOSTNAME"',
        ):
            with self.subTest(continuation=continuation):
                expanded_identity_soul = soul.replace(identity_bullet, identity_bullet + continuation, 1)
                self.assertFalse(
                    _cited_env_vars(
                        _bullet_block(expanded_identity_soul, IDENTITY_BULLET),
                        doc=expanded_identity_soul,
                    ).issubset(forwarded)
                )
                expanded_project_soul = soul.replace(raw_project_bullet, raw_project_bullet + continuation, 1)
                self.assertFalse(
                    _cited_env_vars(
                        _cleaned_project_resolution_bullet(_bullet_block(expanded_project_soul, PROJECT_RESOLUTION_BULLET)),
                        doc=expanded_project_soul,
                    ).issubset(forwarded)
                )

        # A document-level reference definition referenced inside the guarded bullet is scanned,
        # while an unreferenced sibling reference definition outside the bullet stays outside.
        doc_ref_soul = (
            soul.replace(identity_bullet, identity_bullet + " Open [the cluster page][console].", 1)
            + "\n\n[console]: https://console.cloud.google.com/?project=$GCP_PROJECT_ID\n"
        )
        self.assertIn(
            "GCP_PROJECT_ID",
            _cited_env_vars(_bullet_block(doc_ref_soul, IDENTITY_BULLET), doc=doc_ref_soul),
        )
        unused_outside_ref_soul = soul + "\n\n[unused]: https://console.cloud.google.com/?project=$UNFORWARDED_OUTSIDE_VAR\n"
        self.assertTrue(
            _cited_env_vars(
                _bullet_block(unused_outside_ref_soul, IDENTITY_BULLET),
                doc=unused_outside_ref_soul,
            ).issubset(forwarded)
        )

        for unbackticked_continuation in (
            "\n  - Use the host's shell: printenv HOSTNAME prints the pod's name.",
            "\n#not-an-atx-heading printenv HOSTNAME",
            "\n####### seven-hashes printenv HOSTNAME",
            ' or open [the cluster page](https://console.cloud.google.com/ "printenv HOSTNAME").',
        ):
            with self.subTest(unbackticked_continuation=unbackticked_continuation):
                unbackticked_continuation_soul = soul.replace(
                    identity_bullet,
                    identity_bullet + unbackticked_continuation,
                    1,
                )
                self.assertTrue(
                    _unbackticked_env_reads(
                        _bullet_block(unbackticked_continuation_soul, IDENTITY_BULLET),
                        doc=unbackticked_continuation_soul,
                    )
                )

        # Multi-block items whose opening paragraph ends in a word character preserve block
        # boundaries rather than gluing into the first word of a nested sub-bullet.
        word_end_unforwarded_soul = soul.replace(
            identity_bullet,
            f"{IDENTITY_BULLET} Read `$GKE_CLUSTER_NAME` and these variables\n  - GCP_PROJECT_ID for the project",
            1,
        )
        self.assertIn(
            "GCP_PROJECT_ID",
            _cited_env_vars(_bullet_block(word_end_unforwarded_soul, IDENTITY_BULLET)),
        )
        word_end_unbackticked_soul = soul.replace(
            identity_bullet,
            f"{IDENTITY_BULLET} Read `$GKE_CLUSTER_NAME` via run\n  - printenv HOSTNAME prints it",
            1,
        )
        self.assertEqual(
            _unbackticked_env_reads(_bullet_block(word_end_unbackticked_soul, IDENTITY_BULLET)),
            ["printenv"],
        )
        tight_forwarded_subbullets_soul = soul.replace(
            identity_bullet,
            f"{IDENTITY_BULLET} Read:\n  - the project in GKE_PROJECT_ID\n  - GKE_LOCATION for the region",
            1,
        )
        self.assertEqual(
            _cited_env_vars(_bullet_block(tight_forwarded_subbullets_soul, IDENTITY_BULLET)),
            {"GKE_PROJECT_ID", "GKE_LOCATION"},
        )

        # Non-`\n` Unicode line separators (`\u2028`) either earlier in SOUL.md or inside a
        # guarded bullet keep `_bullet_block` aligned with `MARKDOWN.parse` `token.map`.
        earlier_ls_soul = "\u2028" + soul
        self.assertEqual(_bullet_block(earlier_ls_soul, IDENTITY_BULLET), identity_bullet)
        inline_ls_soul = soul.replace(
            identity_bullet,
            identity_bullet + "\u2028`$HOSTNAME`",
            1,
        )
        self.assertIn(
            "HOSTNAME",
            _cited_env_vars(_bullet_block(inline_ls_soul, IDENTITY_BULLET)),
        )

        sibling_leak_soul = soul.replace(
            identity_bullet,
            identity_bullet + "\n- **Sibling Item:** `$UNFORWARDED_SIBLING_VAR`",
            1,
        )
        self.assertTrue(_cited_env_vars(_bullet_block(sibling_leak_soul, IDENTITY_BULLET)).issubset(forwarded))
        outside_para_soul = soul.replace(
            identity_bullet,
            identity_bullet + "\n\nUnindented paragraph citing `$UNFORWARDED_OUTSIDE_VAR`.",
            1,
        )
        self.assertTrue(_cited_env_vars(_bullet_block(outside_para_soul, IDENTITY_BULLET)).issubset(forwarded))

        # Rewording prose or punctuation around `literal `$GCP_PROJECT_ID`` keeps passing,
        # while changing the token itself fails naming NEGATIVE_PROSE_LITERAL_RE.
        reworded_prose = raw_project_bullet.replace(" — ", " -- ").replace(
            "shipped with exactly that.", "shipped that."
        )
        self.assertEqual(_unbackticked_env_reads(_cleaned_project_resolution_bullet(reworded_prose)), [])
        self.assertTrue(_cited_env_vars(_cleaned_project_resolution_bullet(reworded_prose)).issubset(forwarded))
        with self.assertRaisesRegex(AssertionError, "NEGATIVE_PROSE_LITERAL_RE"):
            _cleaned_project_resolution_bullet(raw_project_bullet.replace("literal `$GCP_PROJECT_ID`", "example"))

        for forwarded_only in (
            "On GKE, resolve the GCP project ID via `printenv | sort | grep GKE_PROJECT_ID` on GCP.",
            "Run `printenv GKE_PROJECT_ID` (GCP project) first.",
            "Run `printenv GKE_PROJECT_ID`, GKE only; GKE installs.",
            "Resolve it from the sandbox env (GKE only) via `$GKE_PROJECT_ID`.",
            "The host env ('kind' installs aside) sets `$GKE_PROJECT_ID`.",
            "Use the host's `printenv GKE_PROJECT_ID` for the pod's GCP project.",
            "On a `kind` set-up, the install's env-file and env-specific set-aside or export-import rules read `$GKE_PROJECT_ID`.",
            "Open [the cluster page](https://console.cloud.google.com/kubernetes/clusters/details?project=$GKE_PROJECT_ID) on GKE.",
            "`` `printenv GKE_PROJECT_ID` ``",
            "`awk 'BEGIN{print ENVIRON[\"GKE_PROJECT_ID\"]}'`",
            "`perl -e 'print $ENV{GKE_PROJECT_ID}'`",
            "`jq -rn '$ENV.GKE_PROJECT_ID'`",
        ):
            with self.subTest(forwarded_only=forwarded_only):
                self.assertEqual(_unbackticked_env_reads(forwarded_only), [])
                self.assertEqual(_cited_env_vars(forwarded_only), {"GKE_PROJECT_ID"})
                self.assertEqual(_unbackticked_env_reads(f"{identity_bullet} {forwarded_only}"), [])
                self.assertEqual(_unbackticked_env_reads(f"{cleaned_project_bullet} {forwarded_only}"), [])

        prose_with_code = (
            "on GKE installs in GCP (`in-cluster`, `gke_kind_kind_kind`, "
            "`gke_<project>_<location>_<cluster>`, `gke_<PROJECT>_<LOCATION>_<CLUSTER>`, "
            "`gcloud container clusters describe <CLUSTER_NAME> --location <LOCATION>`, "
            "`projects/<PROJECT_ID>/locations/<REGION>/clusters/<CLUSTER_NAME>`, "
            "`/opt/data/INVENTORY.md`, `/opt/data/INVENTORY_2026.md`, `INVENTORY.md`, "
            "`CLUSTER_POLICY.yaml`, `kubectl get pods -A --GKE_X`, `%2F_PATH`)"
        )
        self.assertEqual(_unbackticked_env_reads(prose_with_code), [])
        self.assertEqual(_cited_env_vars(prose_with_code), set())

    def test_posture_regexes_run_linearly_on_adversarial_inputs(self):
        payloads = (
            "env | grep" + "   0" * ADVERSARIAL_REPEAT_COUNT + "!",
            "printenv | grep" + " -w" * ADVERSARIAL_REPEAT_COUNT + "!",
            "printenv" + " | sort" * ADVERSARIAL_REPEAT_COUNT + "!",
            "env " * ADVERSARIAL_REPEAT_COUNT + "!",
            "env" + " -0" * ADVERSARIAL_REPEAT_COUNT + "!",
            "env" + " 2>/dev/null" * ADVERSARIAL_REPEAT_COUNT + "!",
            "env " + "&& " * ADVERSARIAL_REPEAT_COUNT + "!",
            "env " + " & &" * ADVERSARIAL_REPEAT_COUNT + "!",
            "compgen -" + "e" * ADVERSARIAL_REPEAT_COUNT + "1",
            "${" + "A" * ADVERSARIAL_REPEAT_COUNT + "_",
            "`" + "A" * ADVERSARIAL_REPEAT_COUNT + "_`",
            "`env -" + "u" * ADVERSARIAL_REPEAT_COUNT + "1`",
            "$" + "A" * ADVERSARIAL_REPEAT_COUNT + "_",
            "declare -" + "p" * ADVERSARIAL_REPEAT_COUNT + "1",
            "env -" + "u" * ADVERSARIAL_REPEAT_COUNT + "1",
            "set-" + "u" * ADVERSARIAL_REPEAT_COUNT + "1",
            "x#y\n" * ADVERSARIAL_REPEAT_COUNT,
        )
        # Pre-tokenize CommonMark once outside the CPU timer so coverage.py line
        # tracing inside pure-Python markdown-it-py is not charged against the
        # posture regexes' O(n) backtracking budget.
        for payload in payloads:
            _code_spans_and_prose(payload, None)
        start = time.process_time()
        for payload in payloads:
            self.assertEqual(_cited_env_vars(payload), set())
            _unbackticked_env_reads(payload)
        elapsed = time.process_time() - start
        self.assertLess(elapsed, MAX_SCAN_CPU_SECONDS)

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
