"""`.github/workflows/docs-check.yml` runs every CI documentation target unconditionally.

`docs/README.md` states that `make docs-check` runs the same checks as
`.github/workflows/docs-check.yml`. Contributors and automated agents without
the GitHub App `workflows` permission add a new `docs-check-*` prerequisite to
`Makefile` first and list it temporarily in `PENDING_WORKFLOW_TARGETS`; a
maintainer follow-up pull request wires the workflow step and drops the
temporary entry (as this test finishes for `docs-check-prose` after `#3961`;
protected instruction-file references are tracked in `#3996`).
"""

import pathlib
import re
import unittest

import yaml

from tests._run_make import run_make

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "docs-check.yml"

#: Targets added to `Makefile` `docs-check:` by a contributor without `workflows`
#: permission that still await their `.github/workflows/docs-check.yml` step.
#: Must stay empty once the maintainer follow-up lands.
PENDING_WORKFLOW_TARGETS: frozenset[str] = frozenset()

_JOB_ID = "docs-check"
_MAKEFILE_DB_RULE_RE = re.compile(r"^docs-check:(?!=)\s*(?P<rest>.*)$")
_EXACT_MAKE_STEP_RE = re.compile(r"^make (?P<target>docs-check-[a-z0-9-]+)$")


def makefile_docs_check_prereqs(database_text: str | None = None) -> list[str]:
    """Return expanded `docs-check:` prerequisites from GNU Make's database."""
    if database_text is None:
        proc = run_make(["-pn", "--eval=__probe: ;@:", "__probe"], timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(f"make -pn failed (rc={proc.returncode}): {proc.stderr}")
        database_text = proc.stdout

    prereqs: list[str] = []
    found_rule = False
    for line in database_text.splitlines():
        match = _MAKEFILE_DB_RULE_RE.match(line)
        if not match:
            continue
        found_rule = True
        normal_prereqs = match.group("rest").split("#", 1)[0].split("|", 1)[0]
        for token in normal_prereqs.split():
            if token not in prereqs:
                prereqs.append(token)
    if not found_rule:
        raise ValueError("GNU Make database declares no docs-check: target")
    return prereqs


def _has_makeflags(env_block: object) -> bool:
    return isinstance(env_block, dict) and "MAKEFLAGS" in env_block


def _has_working_directory(defaults_block: object) -> bool:
    return (
        isinstance(defaults_block, dict)
        and isinstance(defaults_block.get("run"), dict)
        and "working-directory" in defaults_block["run"]
    )


def validate_docs_check_workflow(
    workflow_text: str,
    prereqs: list[str],
    pending: frozenset[str] = PENDING_WORKFLOW_TARGETS,
) -> list[str]:
    """Validate `docs-check.yml` against `Makefile` `docs-check:` prerequisites."""
    doc = yaml.safe_load(workflow_text)
    if not isinstance(doc, dict):
        raise ValueError("docs-check.yml must parse to a YAML mapping")

    on_block = doc.get("on", doc.get(True))
    if not isinstance(on_block, dict) or "pull_request" not in on_block:
        raise ValueError("docs-check.yml must trigger on pull_request")
    pr_trigger = on_block["pull_request"]
    if isinstance(pr_trigger, dict) and (
        "paths" in pr_trigger or "paths-ignore" in pr_trigger
    ):
        raise ValueError(
            "docs-check.yml pull_request trigger must not filter paths; "
            "Documentation Checks is a required status check on every pull request"
        )

    if _has_makeflags(doc.get("env")):
        raise ValueError("docs-check.yml must not set workflow-level MAKEFLAGS")
    if _has_working_directory(doc.get("defaults")):
        raise ValueError("docs-check.yml must not override defaults.run.working-directory")

    jobs = doc.get("jobs")
    job = jobs.get(_JOB_ID) if isinstance(jobs, dict) else None
    if not isinstance(job, dict):
        raise ValueError(f"docs-check.yml declares no `{_JOB_ID}` job")
    if "if" in job:
        raise ValueError(f"`{_JOB_ID}` job must not carry an `if:` condition")
    if job.get("continue-on-error") is not None:
        raise ValueError(f"`{_JOB_ID}` job must not set `continue-on-error`")
    if _has_makeflags(job.get("env")):
        raise ValueError(f"`{_JOB_ID}` job must not set MAKEFLAGS")
    if _has_working_directory(job.get("defaults")):
        raise ValueError(f"`{_JOB_ID}` job must not override defaults.run.working-directory")

    steps = job.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError(f"`{_JOB_ID}` job declares no steps")

    workflow_targets: list[str] = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or "run" not in step:
            continue
        step_label = step.get("name", f"step #{index}")
        if "if" in step:
            raise ValueError(f"run step {step_label!r} must not carry an `if:` condition")
        if step.get("continue-on-error") is not None:
            raise ValueError(f"run step {step_label!r} must not set `continue-on-error`")
        if "working-directory" in step:
            raise ValueError(f"run step {step_label!r} must not override `working-directory`")
        if _has_makeflags(step.get("env")):
            raise ValueError(f"run step {step_label!r} must not set MAKEFLAGS")

        run_script = step["run"]
        lines = (
            [line.strip() for line in run_script.splitlines() if line.strip()]
            if isinstance(run_script, str)
            else []
        )
        if len(lines) != 1:
            raise ValueError(
                f"run step {step_label!r} must execute a single `make docs-check-*` command, got {lines!r}"
            )
        match = _EXACT_MAKE_STEP_RE.match(lines[0])
        if not match:
            raise ValueError(
                f"run step {step_label!r} must match `make docs-check-<name>`, got {lines[0]!r}"
            )
        workflow_targets.append(match.group("target"))

    stale_pending = sorted(pending - set(prereqs))
    if stale_pending:
        raise ValueError(
            f"PENDING_WORKFLOW_TARGETS names targets absent from Makefile docs-check: {stale_pending}"
        )
    already_wired = sorted(pending & set(workflow_targets))
    if already_wired:
        raise ValueError(
            f"PENDING_WORKFLOW_TARGETS still lists targets already wired in docs-check.yml: {already_wired}"
        )

    expected_targets = [target for target in prereqs if target not in pending]
    if workflow_targets != expected_targets:
        raise ValueError(
            f"docs-check.yml steps {workflow_targets} do not match Makefile docs-check prerequisites {expected_targets}"
        )
    return workflow_targets


_SAMPLE_PREREQS = ["docs-check-links", "docs-check-prose"]
_VALID_WORKFLOW = """
name: Documentation Checks
on:
  pull_request:
    types: [opened, synchronize, reopened]
  merge_group:
    branches: [main]
jobs:
  docs-check:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Checkout code
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
      - name: Links resolve
        run: make docs-check-links
      - name: Prose stays within its ratchet
        run: make docs-check-prose
"""


class DocsCheckWorkflowTest(unittest.TestCase):
    def test_committed_workflow_matches_makefile_docs_check_prerequisites(self) -> None:
        prereqs = makefile_docs_check_prereqs()
        self.assertIn("docs-check-prose", prereqs)
        targets = validate_docs_check_workflow(
            _WORKFLOW_PATH.read_text(encoding="utf-8"),
            prereqs,
        )
        self.assertEqual(targets, prereqs)

    def test_dropping_prose_step_from_committed_workflow_fails(self) -> None:
        prereqs = makefile_docs_check_prereqs()
        without_prose = _WORKFLOW_PATH.read_text(encoding="utf-8").replace(
            "      - name: Site prose stays within its ratchet\n"
            "        run: make docs-check-prose\n\n",
            "",
        )
        with self.assertRaisesRegex(ValueError, "docs-check-prose"):
            validate_docs_check_workflow(without_prose, prereqs)

    def test_pending_allowlist_supports_two_step_handoff_and_rejects_stale_entries(self) -> None:
        prereqs_with_new = [*_SAMPLE_PREREQS, "docs-check-future"]
        self.assertEqual(
            validate_docs_check_workflow(
                _VALID_WORKFLOW,
                prereqs_with_new,
                pending=frozenset({"docs-check-future"}),
            ),
            _SAMPLE_PREREQS,
        )
        with self.assertRaisesRegex(ValueError, "absent from Makefile"):
            validate_docs_check_workflow(
                _VALID_WORKFLOW,
                _SAMPLE_PREREQS,
                pending=frozenset({"docs-check-nonexistent"}),
            )
        with self.assertRaisesRegex(ValueError, "already wired"):
            validate_docs_check_workflow(
                _VALID_WORKFLOW,
                _SAMPLE_PREREQS,
                pending=frozenset({"docs-check-prose"}),
            )

    def test_rejects_softened_conditional_or_filtered_gates(self) -> None:
        mutations = (
            ("empty YAML", "", "YAML mapping"),
            (
                "missing pull_request trigger",
                _VALID_WORKFLOW.replace("  pull_request:\n    types: [opened, synchronize, reopened]\n", ""),
                "trigger on pull_request",
            ),
            (
                "pull_request paths filter",
                _VALID_WORKFLOW.replace(
                    "    types: [opened, synchronize, reopened]",
                    "    paths: ['docs/**']",
                ),
                "must not filter paths",
            ),
            (
                "workflow MAKEFLAGS",
                "env:\n  MAKEFLAGS: -n\n" + _VALID_WORKFLOW,
                "workflow-level MAKEFLAGS",
            ),
            (
                "workflow working-directory",
                "defaults:\n  run:\n    working-directory: docs\n" + _VALID_WORKFLOW,
                "defaults.run.working-directory",
            ),
            (
                "missing docs-check job",
                _VALID_WORKFLOW.replace("  docs-check:", "  other-job:"),
                "declares no `docs-check` job",
            ),
            (
                "job if condition",
                _VALID_WORKFLOW.replace("    runs-on: ubuntu-latest", "    if: false\n    runs-on: ubuntu-latest"),
                "job must not carry an `if:`",
            ),
            (
                "job continue-on-error",
                _VALID_WORKFLOW.replace(
                    "    runs-on: ubuntu-latest",
                    "    continue-on-error: true\n    runs-on: ubuntu-latest",
                ),
                "job must not set `continue-on-error`",
            ),
            (
                "job MAKEFLAGS",
                _VALID_WORKFLOW.replace(
                    "    runs-on: ubuntu-latest",
                    "    env:\n      MAKEFLAGS: -i\n    runs-on: ubuntu-latest",
                ),
                "job must not set MAKEFLAGS",
            ),
            (
                "job working-directory",
                _VALID_WORKFLOW.replace(
                    "    runs-on: ubuntu-latest",
                    "    defaults:\n      run:\n        working-directory: docs\n    runs-on: ubuntu-latest",
                ),
                "job must not override defaults.run.working-directory",
            ),
            (
                "empty steps",
                "name: C\non:\n  pull_request:\njobs:\n  docs-check:\n    steps: []\n",
                "declares no steps",
            ),
            (
                "step if condition",
                _VALID_WORKFLOW.replace(
                    "        run: make docs-check-prose",
                    "        if: github.event_name == 'push'\n        run: make docs-check-prose",
                ),
                "must not carry an `if:`",
            ),
            (
                "step continue-on-error",
                _VALID_WORKFLOW.replace(
                    "        run: make docs-check-prose",
                    "        continue-on-error: true\n        run: make docs-check-prose",
                ),
                "must not set `continue-on-error`",
            ),
            (
                "step working-directory",
                _VALID_WORKFLOW.replace(
                    "        run: make docs-check-prose",
                    "        working-directory: docs\n        run: make docs-check-prose",
                ),
                "must not override `working-directory`",
            ),
            (
                "step MAKEFLAGS",
                _VALID_WORKFLOW.replace(
                    "        run: make docs-check-prose",
                    "        env:\n          MAKEFLAGS: -n\n        run: make docs-check-prose",
                ),
                "must not set MAKEFLAGS",
            ),
            (
                "multiline shell wrapper",
                _VALID_WORKFLOW.replace(
                    "        run: make docs-check-prose",
                    "        run: |\n          set +e\n          make docs-check-prose",
                ),
                "single `make docs-check-\\*` command",
            ),
            (
                "dry-run make flag",
                _VALID_WORKFLOW.replace(
                    "        run: make docs-check-prose",
                    "        run: make -n docs-check-prose",
                ),
                "must match `make docs-check-<name>`",
            ),
            (
                "duplicate step",
                _VALID_WORKFLOW + "      - name: Dup\n        run: make docs-check-prose\n",
                "do not match Makefile",
            ),
        )
        for label, mutated_yaml, expected_pattern in mutations:
            with self.subTest(label=label):
                with self.assertRaisesRegex(ValueError, expected_pattern):
                    validate_docs_check_workflow(mutated_yaml, _SAMPLE_PREREQS)

    def test_makefile_database_parser_ignores_variables_and_order_only_prereqs(self) -> None:
        sample_db = (
            "docs-check := not-a-rule\n"
            "docs-check: docs-check-a docs-check-b | order-only-dep # comment\n"
            "docs-check: docs-check-b docs-check-c\n"
        )
        self.assertEqual(
            makefile_docs_check_prereqs(sample_db),
            ["docs-check-a", "docs-check-b", "docs-check-c"],
        )
        with self.assertRaisesRegex(ValueError, "no docs-check: target"):
            makefile_docs_check_prereqs("all: build\n")


if __name__ == "__main__":
    unittest.main()
