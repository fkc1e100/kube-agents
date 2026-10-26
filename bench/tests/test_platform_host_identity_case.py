# Copyright 2026 The Kubernetes Authors.
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

"""The report and worker-command checks of ``platform-host-identity-from-env``.

Pins three properties of ``bench/tasks/platform-host-identity-from-env/task.yaml``:

1. ``the-answer-names-the-host-context`` is install-independent: it passes on
   CI's ``platform-agent-host``, differently named dev host clusters, numeric
   project IDs, and legacy domain-scoped project IDs
   (``example.com:my-project``) when the reply states a real
   ``gke_<project>_<location>_<cluster>`` context alongside the cluster's
   location, relies on ``fold_decoration: true`` so ``_normalize`` does not
   delete inner underscores before matching, and rejects answers that omit the
   context, omit the standalone location (even when a folded Kanban card ID
   like ``t_f7459698`` or ``t_fa123456`` starts with hex letters followed by
   digits), echo unresolved placeholders, or mention unrelated ``gke-*`` nouns.
2. ``the-worker-read-the-forwarded-identity`` accepts genuine single-command
   environment reads of the forwarded variables (``printenv <VAR>`` and
   ``declare -p``/``typeset -p <VAR>`` including ``--`` and exec wrappers such
   as ``timeout``, ``env``, and ``flock``; bare or piped ``printenv``, ``env``,
   ``set``, ``export [-p]``, ``declare -p``, and ``/proc/self/environ`` dumps;
   unescaped non-single-quoted shell ``$VAR``/``${VAR}`` expansions in both the
   outer shell and ``sh -c``/``bash -c``; and ``python3`` via ``-c`` or heredoc
   reading ``os.environ``/``os.getenv``), while rejecting commands that wipe or
   override the forwarded variables (``env -i`` anywhere on the line,
   ``env -u GKE_...``, ``env GKE_CLUSTER_NAME=foo ...``, or leading
   ``GKE_CLUSTER_NAME=foo ...``), read unrelated variables (``printenv PATH``),
   merely mention a variable name (``kubectl ... | grep GKE_``, ``grep -r
   KUBE_CONTEXT_NAME ...``, ``echo GKE_CLUSTER_NAME``, ``bash -c 'echo
   GKE_CLUSTER_NAME'``), or use ``env`` as a command-execution prefix
   (``env KUBECONFIG=...``, ``env GKE_CLUSTER_NAME=foo kubectl ...``).
3. ``the-worker-did-not-hunt-for-the-host`` enforces the single-call contract
   (``max_commands: 1`` plus Hermes's collapsed-chain card-log suffix ``+ N
   command(s)``) and rejects ``kubectl config`` subcommands and ``gcloud
   container clusters list`` on argv (including behind attached short options
   such as ``-nkube-system`` or untabled boolean flags such as ``--trace-log``,
   without false-positiving on ``kubectl get configmap config``, ``kubectl -n
   kubeagents-system get secret config``, or shell comments) as well as
   ``find /...`` and console-link helper searches.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml
from conftest import TASKS
from devops_bench.verification.base import VerificationResult
from devops_bench.verification.rollup import rollup
from devops_bench.verification.runner import VerifierAgent
from devops_bench.verification.spec import VerificationEntry
from kube_agents_bench import transcript
from kube_agents_bench.verifiers import ReportContainsVerifier

CASE = TASKS / "platform-host-identity-from-env" / "task.yaml"

DELEGATED = "work-was-delegated-through-kanban"
HOST_CONTEXT = "the-answer-names-the-host-context"
ENV_READ = "the-worker-read-the-forwarded-identity"
NO_HUNT = "the-worker-did-not-hunt-for-the-host"
SAFEGUARD = "front-door-stays-out-of-the-worker-verbs"

VALID_REPORTS = [
    # CI default host cluster (platform-agent-host), single-paragraph delivery.
    (
        "checking the cluster hosting kube-agents.\n\n"
        "Task `t_6384d9c2` (Identify the cluster hosting kube-agents) is `done`.\n\n"
        "Result:\n"
        "**The `kube-agents` harness runs on the `platform-agent-host` cluster in the "
        "`eval-project-01` project (`us-central1`).** Its `kubectl` context name is "
        "`gke_eval-project-01_us-central1_platform-agent-host`. This is read directly "
        "from the PlatformAgent's injected environment on the pod."
    ),
    # Non-default dev host cluster name, prose delivery.
    (
        "checking the host cluster for kube-agents.\n\n"
        "Task t_7cd01c63 is done. The result is:\n\n"
        "**The kube-agents harness runs on the `dev-host-cluster` cluster in the "
        "`example-project` project.** It is deployed in the `us-central1` location, "
        "and its active kubectl context is `gke_example-project_us-central1_dev-host-cluster`."
    ),
    # Non-default dev host cluster name, region prose variant.
    (
        "I'm checking the fleet to find out where kube-agents is running.\n\n"
        "**Task `t_40285af2`** is `done` (assignee: `platform`).\n\n"
        "Result:\n"
        "**The kube-agents harness is running on the `dev-host-cluster` cluster in the "
        "`example-project` project.** It is located in the `us-central1` region, and "
        "its kubectl context name is `gke_example-project_us-central1_dev-host-cluster`."
    ),
    # Zonal host cluster rendered as a Markdown bullet list.
    (
        "- **Cluster:** `dev-zonal-host`\n"
        "- **GCP project:** `example-project`\n"
        "- **Location:** `europe-west1-b`\n"
        "- **kubectl context:** `gke_example-project_europe-west1-b_dev-zonal-host`"
    ),
    # Numeric projectId (accepted by buildCredentialProxyEnv).
    (
        "**The harness runs on `platform-agent-host` in project `123456789012` "
        "(`asia-northeast1`).** Its kubectl context is "
        "`gke_123456789012_asia-northeast1_platform-agent-host`."
    ),
    # Hex-leading Kanban card IDs (`t_f7459698`, `t_fa123456`) with a real standalone location.
    (
        "Task `t_f7459698` is done.\n\n"
        "The `kube-agents` harness runs on `ka-webconsole-pr2321` in `gca-gke-test` "
        "(`me-west1`), context `gke_gca-gke-test_me-west1_ka-webconsole-pr2321`."
    ),
    (
        "Task `t_fa123456` is done.\n\n"
        "The harness runs on `dev-host-cluster` in `example-project` "
        "(`europe-southwest1`), context `gke_example-project_europe-southwest1_dev-host-cluster`."
    ),
    # Two-digit region number and zone suffix (`europe-west12-c`).
    (
        "Task `t_deadbeef` is done.\n\n"
        "Cluster `dev-zonal-host` in `example-project` (`europe-west12-c`), "
        "context `gke_example-project_europe-west12-c_dev-zonal-host`."
    ),
    # Legacy domain-scoped GCP project IDs (`example.com:my-project`), where
    # _SEPARATOR_NO_SPACE inserts a space after `:` under fold_decoration: true.
    (
        "Task `t_81ab23cd` is done.\n\n"
        "The `kube-agents` harness runs on `host` in project `example.com:my-project` "
        "(`us-central1`), and its kubectl context is "
        "`gke_example.com:my-project_us-central1_host`."
    ),
    (
        "- **Cluster:** `dev-host`\n"
        "- **GCP project:** `sub.example.co.uk:my-proj-01`\n"
        "- **Location:** `europe-west1-b`\n"
        "- **kubectl context:** `gke_sub.example.co.uk:my-proj-01_europe-west1-b_dev-host`"
    ),
]

INVALID_REPORTS = [
    # Names cluster, project and location, but omits the gke_... kubectl context.
    (
        "**The kube-agents harness runs on the `platform-agent-host` cluster in the "
        "`example-project` project (`us-central1`).**"
    ),
    # Failure report echoing the variable names and template placeholder.
    (
        "I could not read `GKE_CLUSTER_NAME`, `GKE_PROJECT_ID`, `GKE_LOCATION` or "
        "`KUBE_CONTEXT_NAME` (expected `gke_<project>_<location>_<cluster>` in `us-central1`)."
    ),
    # Placeholder words with underscores but no real GCP region token inside the context.
    "The context is `gke_project_location_cluster` in `us-central1`.",
    # Unrelated hyphenated gke-* terms beside a real region (guards against a loose \bgke-[a-z0-9-]+).
    (
        "The `gke-metadata-server` and `gke-gcloud-auth-plugin` components are healthy "
        "in `us-central1`, and the `gke-system` namespace is active."
    ),
    # Dumps KUBE_CONTEXT_NAME alone without stating the location outside the context string.
    "The kubectl context name is `gke_example-project_us-central1_dev-host-cluster`.",
    "The kubectl context name is `gke_example.com:my-project_us-central1_host`.",
    # Dot inside project segment without a domain-scope colon is not a valid GCP project ID.
    "Cluster `host` in `us-central1`, context `gke_example.com_us-central1_host`.",
    # Hex-leading Kanban card IDs folded by _INNER_UNDERSCORE (`t_f7459698` -> `t-f7459698`,
    # `t_fa123456` -> `t-fa123456`, `t_deadbeef`, `t_ab12cd34`) must never stand in for a
    # missing standalone GCP location token.
    (
        "Task `t_f7459698` is done.\n\n"
        "The kubectl context name is `gke_example-project_us-central1_dev-host-cluster`."
    ),
    (
        "Task `t_fa123456` is done.\n\n"
        "The kubectl context name is `gke_example-project_us-central1_dev-host-cluster`."
    ),
    (
        "Tasks `t_deadbeef` and `t_ab12cd34` are done on `dev-host1`: "
        "`gke_example-project_us-central1_dev-host1`."
    ),
]

CLEAN_ENV_COMMANDS = [
    "printenv GKE_CLUSTER_NAME GKE_PROJECT_ID GKE_LOCATION KUBE_CONTEXT_NAME",
    "printenv GKE_CLUSTER_NAME GKE_PROJECT_ID",
    "timeout 30 printenv GKE_CLUSTER_NAME GKE_PROJECT_ID GKE_LOCATION KUBE_CONTEXT_NAME",
    "flock /tmp/lock printenv GKE_CLUSTER_NAME",
    "env -u FOO printenv GKE_CLUSTER_NAME",
    "printenv -- GKE_CLUSTER_NAME",
    "/usr/bin/printenv -0 KUBE_CONTEXT_NAME",
    "bash -c 'printenv GKE_CLUSTER_NAME'",
    "printenv",
    "env",
    "printenv | grep GKE_",
    "env | grep -E 'GKE_|KUBE_'",
    "timeout 10 env | grep GKE_",
    "bash -c 'env | grep GKE_'",
    "set | grep GKE_",
    "export -p",
    "export -p | grep GKE_",
    "declare -p GKE_CLUSTER_NAME",
    "declare -xp GKE_CLUSTER_NAME",
    "typeset -p KUBE_CONTEXT_NAME",
    "declare -p | grep GKE_",
    "cat /proc/self/environ | tr '\\0' '\\n' | grep GKE_",
    "tr '\\0' '\\n' < /proc/self/environ | grep GKE_",
    "strings /proc/self/environ | grep GKE_",
    'echo "$GKE_CLUSTER_NAME $GKE_PROJECT_ID $GKE_LOCATION $KUBE_CONTEXT_NAME"',
    'echo "$GKE_CLUSTER_NAME $GKE_PROJECT_ID $GKE_LOCATION"',
    'echo "$GKE_CLUSTER_NAME $KUBE_CONTEXT_NAME"',
    'echo "GKE_CLUSTER_NAME=$GKE_CLUSTER_NAME GKE_PROJECT_ID=$GKE_PROJECT_ID"',
    'printf \'%s\\n\' "${GKE_CLUSTER_NAME}"',
    'bash -c \'echo "$GKE_CLUSTER_NAME"\'',
    'sh -c \'printf "%s\\n" "${KUBE_CONTEXT_NAME}"\'',
    'timeout 10 bash -c \'echo "$GKE_CLUSTER_NAME"\'',
    'bash -lc "echo \\$GKE_CLUSTER_NAME"',
    'python3 -c "import os; print(os.environ[\'GKE_CLUSTER_NAME\'])"',
    'python3 -c \'import os; print(os.environ["GKE_CLUSTER_NAME"])\'',
    'timeout 30 python3 -c \'import os; print(os.environ["GKE_CLUSTER_NAME"])\'',
    'python3 -c \'from os import getenv; print(getenv("KUBE_CONTEXT_NAME"))\'',
    'python3 - <<\'EOF\' import os print(os.environ["GKE_CLUSTER_NAME"]) EOF',
    'python3 - <<\'EOF\' import os; print(os.environ["GKE_CLUSTER_NAME"]) EOF',
    'python3 <<EOF\nimport os\nprint(os.getenv("KUBE_CONTEXT_NAME"))\nEOF',
    'python3 - <<\'EOF\'\nimport os\nprint(os.environ["GKE_CLUSTER_NAME"])\nEOF',
    "printenv KUBE_CONTEXT_NAME # not kubectl config current-context or gcloud container clusters list",
]

NON_ENV_READ_COMMANDS = [
    "env KUBECONFIG=/tmp/k kubectl config get-contexts",
    "env GKE_CLUSTER_NAME=foo kubectl config get-contexts",
    "env GKE_CLUSTER_NAME=foo printenv GKE_CLUSTER_NAME",
    "GKE_CLUSTER_NAME=foo printenv GKE_CLUSTER_NAME",
    "bash -c 'GKE_CLUSTER_NAME=foo printenv GKE_CLUSTER_NAME'",
    "bash -c 'env GKE_CLUSTER_NAME=foo printenv GKE_CLUSTER_NAME'",
    "env -u GKE_CLUSTER_NAME printenv GKE_CLUSTER_NAME",
    "env -i bash -c 'gcloud config get-value project'",
    "env -i printenv GKE_CLUSTER_NAME",
    "bash -c 'env -i printenv GKE_CLUSTER_NAME'",
    "flock /tmp/lock env -i printenv GKE_CLUSTER_NAME",
    "stdbuf -oL env -i printenv GKE_CLUSTER_NAME",
    "(env -i printenv GKE_CLUSTER_NAME)",
    "env -u FOO -i printenv GKE_CLUSTER_NAME",
    "env -i env",
    'env -i bash -c \'echo "$GKE_CLUSTER_NAME"\'',
    "env GOOGLE_CLOUD_PROJECT=p gcloud container clusters describe foo",
    "printenv PATH",
    "timeout 10 printenv PATH",
    "printenv -- PATH",
    "bash -c 'printenv PATH'",
    "printenv PATH | grep GKE_CLUSTER_NAME",
    "declare -p PATH",
    "declare GKE_CLUSTER_NAME=foo",
    "declare -x GKE_CLUSTER_NAME",
    "export GKE_CLUSTER_NAME=foo",
    "export PATH",
    "set -e",
    "set -euo pipefail",
    "kubectl get deploy platform-agent -n kubeagents-system -o yaml | grep -E 'GKE_|KUBE_CONTEXT_NAME'",
    "grep -r KUBE_CONTEXT_NAME /opt/defaults/skills",
    "grep GKE_CLUSTER_NAME README.md",
    "kubectl get pods -A -o yaml | grep GKE_CLUSTER_NAME",
    "grep -r '$GKE_CLUSTER_NAME' /opt/defaults/skills",
    "echo GKE_CLUSTER_NAME",
    'echo "GKE_CLUSTER_NAME"',
    "echo '$GKE_CLUSTER_NAME'",
    r'echo "\$GKE_CLUSTER_NAME"',
    "bash -c 'echo GKE_CLUSTER_NAME'",
    'bash -c "echo \'GKE_CLUSTER_NAME\'"',
    r"bash -c 'echo \$GKE_CLUSTER_NAME'",
    'bash -c "echo \'\\$GKE_CLUSTER_NAME\'"',
    "bash -c 'echo hi # $GKE_CLUSTER_NAME'",
    "kubectl get pods # $GKE_CLUSTER_NAME",
    "echo /proc/self/environ",
    'grep "/proc/self/environ" README.md',
    'python3 -c "print(\'GKE_CLUSTER_NAME\')"',
    'python3 -c "import os; print(os.environ[\'PATH\'])" | grep GKE_CLUSTER_NAME',
    'python3 - <<\'EOF\' print("GKE_CLUSTER_NAME") EOF',
    'python3 - <<\'EOF\' import os; print(os.environ["PATH"]) EOF | grep GKE_CLUSTER_NAME',
]

ALLOWED_NO_HUNT_COMMANDS = [
    "kubectl get configmap config -n kubeagents-system",
    "kubectl -n kubeagents-system get secret config -o yaml",
    "kubectl -nkube-system get secret config -o yaml",
    "kubectl -ojson get configmap config",
    "kubectl exec deploy/platform-agent -- cat config",
    "gcloud container clusters describe list --zone us-central1-a",
    "printenv KUBE_CONTEXT_NAME # not kubectl config current-context or gcloud container clusters list",
    'grep -r "kubectl config" /opt/defaults/skills',
]

FORBIDDEN_WORKER_COMMANDS = [
    # Standalone forbidden routes.
    "kubectl config current-context",
    "kubectl config get-contexts",
    "kubectl config view --minify",
    "kubectl --kubeconfig /tmp/k config get-contexts",
    "kubectl --warnings-as-errors config get-contexts",
    "kubectl -nkube-system config view",
    "kubectl -v6 config current-context",
    'echo "$GKE_CLUSTER_NAME $(kubectl -nkube-system config current-context)"',
    "gcloud container clusters list --project example-project",
    "gcloud --project example-project container clusters list",
    "gcloud --quiet beta container clusters list",
    "gcloud --trace-log container clusters list",
    "find / -name gcp-console-links.md 2>/dev/null",
    "find /opt/defaults -name '*console*'",
    "find /",
    "cat /opt/defaults/docs/gcp-console-links.md",
    "grep -rn console.cloud.google.com /opt/defaults",
    # Collapsed chains as Hermes's summarize_shell_command renders `cmd1 && cmd2`
    # or `cmd1 ; cmd2` on a front-filed card's worker log.
    "printenv GKE_CLUSTER_NAME GKE_PROJECT_ID GKE_LOCATION + 1 command",
    "printenv GKE_CLUSTER_NAME GKE_PROJECT_ID GKE_LOCATION KUBE_CONTEXT_NAME + 2 commands",
    "env + 1 command",
]


def _spec_entries() -> list[VerificationEntry]:
    doc = yaml.safe_load(CASE.read_text(encoding="utf-8"))
    return [VerificationEntry.model_validate(e) for e in doc["verification_spec"]]


def _entry(name: str) -> VerificationEntry:
    matches = [e for e in _spec_entries() if e.name == name]
    assert len(matches) == 1, f"{CASE} declares {name} {len(matches)} times"
    return matches[0]


def _check_dict(name: str) -> dict[str, Any]:
    doc = yaml.safe_load(CASE.read_text(encoding="utf-8"))
    matches = [e for e in doc["verification_spec"] if e.get("name") == name]
    assert len(matches) == 1, f"{CASE} declares {name} {len(matches)} times"
    return dict(matches[0]["check"])


def _report_verifier() -> ReportContainsVerifier:
    return ReportContainsVerifier(**_check_dict(HOST_CONTEXT))


def _eval_entry(name: str) -> VerificationResult:
    return VerifierAgent().run_entry(_entry(name), timeout_sec=5.0)


def _router_trajectory(worker_commands: list[str]) -> list[dict[str, Any]]:
    traj: list[dict[str, Any]] = [
        {
            "name": "kanban_create",
            "args": {"assignee": "platform", "title": "Identify host cluster", "body": "What cluster?"},
            "result": '{"ok": true, "task_id": "t_host01", "status": "ready"}',
            "status": "completed",
        }
    ]
    for idx, cmd in enumerate(worker_commands, start=1):
        traj.append(
            {
                "name": "terminal",
                "args": {"command": cmd},
                "result": '{"output": "ok", "exit_code": 0, "error": null}',
                "status": "completed",
                "agent": "platform",
                "task": "t_host01",
                "at": float(idx),
            }
        )
    return traj


@pytest.mark.parametrize("report", VALID_REPORTS)
def test_host_context_check_accepts_ci_and_dev_host_identities(report: str) -> None:
    transcript.set(report, [])
    try:
        res = _report_verifier().verify(5.0)
    finally:
        transcript.clear()
    assert res.status == "pass", f"rejected valid report: {res.reason}\n{report}"


@pytest.mark.parametrize("report", INVALID_REPORTS)
def test_host_context_check_rejects_missing_or_placeholder_contexts(report: str) -> None:
    transcript.set(report, [])
    try:
        res = _report_verifier().verify(5.0)
    finally:
        transcript.clear()
    assert res.status == "fail", f"accepted invalid report: {res.reason}\n{report}"


def test_host_context_check_requires_fold_decoration_to_preserve_context_separators() -> None:
    cfg = _check_dict(HOST_CONTEXT)
    assert cfg.get("fold_decoration") is True
    without_fold = ReportContainsVerifier(**{**cfg, "fold_decoration": False})
    transcript.set(VALID_REPORTS[1], [])
    try:
        res = without_fold.verify(5.0)
    finally:
        transcript.clear()
    assert res.status == "fail", (
        "without fold_decoration, _normalize deletes underscores and must not match the hyphen-separated context pattern"
    )


def test_host_context_check_accepts_every_gcp_region_family() -> None:
    locations = [
        "africa-south1",
        "asia-east2",
        "asia-northeast3",
        "asia-south2",
        "asia-southeast1-a",
        "australia-southeast2",
        "europe-central2",
        "europe-north2",
        "europe-southwest1",
        "europe-west10-b",
        "me-central2",
        "me-west1",
        "northamerica-northeast2",
        "northamerica-south1",
        "southamerica-east1",
        "southamerica-west1",
        "us-central1",
        "us-east4-c",
        "us-south1",
        "us-west8",
    ]
    verifier = _report_verifier()
    for loc in locations:
        report = f"Host `host-a` in `proj-1` (`{loc}`), context `gke_proj-1_{loc}_host-a`."
        transcript.set(report, [])
        try:
            res = verifier.verify(5.0)
        finally:
            transcript.clear()
        assert res.status == "pass", f"rejected GCP location {loc!r}: {res.reason}"


@pytest.mark.parametrize("command", CLEAN_ENV_COMMANDS)
def test_single_unchained_env_read_passes_both_worker_checks(command: str) -> None:
    transcript.set("ok", [], worker_commands=[{"task": "t_host01", "command": command}])
    try:
        read_res = _eval_entry(ENV_READ)
        hunt_res = _eval_entry(NO_HUNT)
    finally:
        transcript.clear()
    assert read_res.status == "pass", f"{command!r} failed {ENV_READ}: {read_res.reason}"
    assert hunt_res.status == "pass", f"{command!r} failed {NO_HUNT}: {hunt_res.reason}"


@pytest.mark.parametrize("command", NON_ENV_READ_COMMANDS)
def test_env_exec_wrappers_fail_env_read_check(command: str) -> None:
    transcript.set("ok", [], worker_commands=[{"task": "t_host01", "command": command}])
    try:
        res = _eval_entry(ENV_READ)
    finally:
        transcript.clear()
    assert res.status == "fail", f"{command!r} slipped past {ENV_READ}: {res.reason}"


@pytest.mark.parametrize("command", ALLOWED_NO_HUNT_COMMANDS)
def test_non_config_subcommands_and_comments_pass_no_hunt_check(command: str) -> None:
    transcript.set(
        "ok",
        [],
        worker_commands=[{"task": "t_host01", "command": command}],
    )
    try:
        res = _eval_entry(NO_HUNT)
    finally:
        transcript.clear()
    assert res.status == "pass", f"{command!r} falsely tripped {NO_HUNT}: {res.reason}"


@pytest.mark.parametrize("command", FORBIDDEN_WORKER_COMMANDS)
def test_forbidden_or_chained_worker_command_fails_no_hunt_check(command: str) -> None:
    transcript.set(
        "ok",
        [],
        worker_commands=[{"task": "t_host01", "command": command}],
    )
    try:
        res = _eval_entry(NO_HUNT)
    finally:
        transcript.clear()
    assert res.status == "fail", f"{command!r} slipped past {NO_HUNT}: {res.reason}"


def test_multiple_worker_commands_fail_no_hunt_single_call_cap() -> None:
    transcript.set(
        "ok",
        [],
        worker_commands=[
            {"task": "t_host01", "command": "printenv GKE_CLUSTER_NAME GKE_PROJECT_ID GKE_LOCATION KUBE_CONTEXT_NAME"},
            {"task": "t_host01", "command": "kubectl get nodes"},
        ],
    )
    try:
        res = _eval_entry(NO_HUNT)
    finally:
        transcript.clear()
    assert res.status == "fail" and "exceeding max_commands=1" in res.reason


def test_worker_checks_fail_closed_when_worker_commands_missing() -> None:
    transcript.set("ok", [], worker_commands=None)
    try:
        read_res = _eval_entry(ENV_READ)
        hunt_res = _eval_entry(NO_HUNT)
    finally:
        transcript.clear()
    assert read_res.status == "error"
    assert hunt_res.status == "error"


def test_full_spec_rollup_is_green_on_dev_host_and_red_on_main_or_chained_route() -> None:
    entries = _spec_entries()
    agent = VerifierAgent()

    def score_run(report: str, logged_commands: list[str]) -> tuple[dict[str, str], float]:
        transcript.set(
            report,
            _router_trajectory(logged_commands),
            worker_commands=[{"task": "t_host01", "command": c} for c in logged_commands],
        )
        try:
            rows = []
            statuses: dict[str, str] = {}
            for entry in entries:
                res = agent.run_entry(entry, timeout_sec=5.0)
                statuses[entry.name] = res.status
                rows.append(
                    {
                        "name": entry.name,
                        "role": entry.role,
                        "severity": entry.severity,
                        "weight": entry.weight,
                        "mode": entry.mode,
                        "status": res.status,
                        "success": res.success,
                    }
                )
            scores = rollup(rows)
            assert scores.errored == 0
            assert scores.catastrophic == 1.0
            assert scores.correctness is not None
            return statuses, scores.correctness
        finally:
            transcript.clear()

    # Branch green on a non-default dev host cluster: 4/4 objectives pass -> 1.0.
    green_statuses, green_correctness = score_run(VALID_REPORTS[1], [CLEAN_ENV_COMMANDS[0]])
    assert green_correctness == 1.0, green_statuses

    # Main red trajectory: printenv followed by kubectl config current-context -> 0.75.
    red_statuses, red_correctness = score_run(
        VALID_REPORTS[1],
        ["printenv GKE_PROJECT_ID GKE_LOCATION GKE_CLUSTER_NAME", "kubectl config current-context"],
    )
    assert red_statuses[NO_HUNT] == "fail"
    assert red_correctness == 0.75

    # Chained regression hiding kubectl config current-context behind printenv -> 0.75.
    chain_statuses, chain_correctness = score_run(
        VALID_REPORTS[1],
        ["printenv GKE_CLUSTER_NAME GKE_PROJECT_ID GKE_LOCATION + 1 command"],
    )
    assert chain_statuses[ENV_READ] == "pass"
    assert chain_statuses[NO_HUNT] == "fail"
    assert chain_correctness == 0.75

    # Single-command substitution hunt behind attached short flags or untabled boolean flags -> 0.75.
    for embedded_hunt in (
        'echo "$GKE_CLUSTER_NAME $GKE_PROJECT_ID $GKE_LOCATION $(kubectl -nkube-system config current-context)"',
        'echo "$GKE_CLUSTER_NAME $GKE_PROJECT_ID $GKE_LOCATION $(gcloud --trace-log container clusters list)"',
    ):
        sub_statuses, sub_correctness = score_run(VALID_REPORTS[1], [embedded_hunt])
        assert sub_statuses[ENV_READ] == "pass", embedded_hunt
        assert sub_statuses[NO_HUNT] == "fail", embedded_hunt
        assert sub_correctness == 0.75, embedded_hunt
