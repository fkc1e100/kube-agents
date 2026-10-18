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

"""Inspect AI evaluation tasks for kube-agents conforming to eval-runner specifications."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Any
import urllib.request
import uuid

CURRENT_DIR = Path(__file__).resolve().parent
DATASET_PATH = CURRENT_DIR / "datasets" / "kube_agents_eval_dataset.jsonl"
DEFAULT_MODEL = "google/gemini-3.5-flash-lite"
REQUIRED_RECORD_KEYS = ("id", "task_id", "input")
RESPONSES_PATH = "/v1/responses"
REPLY_EXCERPT_CHARS = 200

_SCRIPTS_DIR = CURRENT_DIR.parent / "agents" / "platform" / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# The repository's read-only kubectl policy is required: without it the tool's own checks below
# would be the only gate, and they do not cover shorthand runs or file-writing flags.
import command_policy  # noqa: E402

try:
    from inspect_ai import Task, task
    from inspect_ai.dataset import MemoryDataset, Sample
    from inspect_ai.model import ChatMessageAssistant, ChatMessageSystem, ModelOutput
    from inspect_ai.solver import Generate, TaskState, solver, use_tools
    from inspect_ai.tool import Tool, tool

    _INSPECT_AVAILABLE = True
except ImportError:
    _INSPECT_AVAILABLE = False

    # Pass-through decorators so the unit tests can import the tool and the task names without
    # inspect_ai. Building samples or tasks needs Inspect's types, so only the loader's error
    # paths run without it.
    def task(fn):
        return fn

    def tool(fn):
        return fn

    def solver(fn):
        return fn

    use_tools = None
    Generate = Any
    TaskState = Any
    Tool = Any

try:
    from .scorers import kube_agents_cx_scorer
except (ImportError, ValueError):
    try:
        from scorers import kube_agents_cx_scorer
    except ImportError:
        if _INSPECT_AVAILABLE:
            raise
        kube_agents_cx_scorer = None


def _resolve_model():
    try:
        from inspect_ai.model._model import active_model
        m = active_model()
        if m is not None and str(m) != "none/none":
            return m
    except Exception:
        pass
    return DEFAULT_MODEL


def _load_samples_for_task(task_id: str) -> list[Sample]:
    samples = []
    with open(DATASET_PATH, encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{DATASET_PATH}:{line_no}: malformed eval record: {exc}") from exc
            missing = [k for k in REQUIRED_RECORD_KEYS if k not in data]
            if missing:
                raise ValueError(f"{DATASET_PATH}:{line_no}: eval record missing {missing}")
            if data.get("task_id") == task_id:
                samples.append(
                    Sample(
                        input=data["input"],
                        target=data.get("target", ""),
                        id=data["id"],
                        metadata={
                            "id": data["id"],
                            "task_id": data["task_id"],
                            "category": data.get("category", ""),
                            "required": data.get("required", []),
                            "forbidden": data.get("forbidden", []),
                            "min_length": data.get("min_length", 15),
                        },
                    )
                )
    if not samples:
        raise ValueError(f"{DATASET_PATH}: no eval records for task_id {task_id!r}")
    return samples


_ALLOWED_SUBCOMMANDS = {"get", "describe", "logs", "version", "cluster-info"}
_MUTATING_SUBCOMMANDS = {
    "delete", "apply", "patch", "edit", "scale", "exec", "run", "replace", "create",
    "drain", "cordon", "uncordon", "taint", "rollout", "set", "attach", "cp", "port-forward",
}
_FLAG_ARGS = {
    "-n", "--namespace", "-l", "--selector", "-c", "--container",
    "--context", "--cluster", "--user", "--kubeconfig", "-s", "--server", "-f", "--filename",
}
_DENIED_FLAGS = {
    "-s", "--server", "--kubeconfig", "--token", "--as", "--as-group", "--as-uid", "--username",
    "--password", "--certificate-authority", "--client-certificate", "--client-key",
    "--insecure-skip-tls-verify", "--raw",
    "--context", "--cluster", "--user",
    "-f", "--filename", "-k", "--kustomize", "-R", "--recursive",
}
_DENIED_RESOURCES = {"secret", "secrets"}


@tool
def kubectl_inspect() -> Tool:
    """Execute read-only kubectl commands against the target Kubernetes cluster.

    Permitted read-only subcommands: get, describe, logs, version, cluster-info.
    """
    async def execute(command: str) -> str:
        """Run a read-only kubectl command.

        Args:
            command: The kubectl command line to run, e.g. 'kubectl get pods -n kubeagents-system'.
        """
        tokens = shlex.split(command)
        if not tokens or tokens[0] != "kubectl":
            return "Error: Command must start with 'kubectl'."

        # 1. Consult the repository command policy first.
        decision = command_policy.evaluate(tokens)
        if not decision.allowed:
            return f"Error: {decision.message}"

        # 2. Guard against mutating subcommands anywhere in the command arguments
        for t in tokens[1:]:
            if t.lower() in _MUTATING_SUBCOMMANDS:
                return f"Error: Mutating subcommand '{t}' is prohibited."

        # 3. Connection/identity/target overrides, indirect manifest reads, and Secret reads.
        # Catches exact denied flags and attached short flags (e.g. -s<url>, -f<path>, -k<dir>).
        for t in tokens[1:]:
            flag = t.split("=", 1)[0]
            if flag in _DENIED_FLAGS or (t.startswith(("-s", "-f", "-k")) and not t.startswith("--")):
                return f"Error: Flag '{flag}' is prohibited."
            if any(part in _DENIED_RESOURCES for part in re.split(r"[,/.]", t.lower())):
                return f"Error: Reading '{t}' is prohibited."

        # Extract subcommand with flag-argument awareness
        subcmd = None
        i = 1
        while i < len(tokens):
            tok = tokens[i]
            if tok in _FLAG_ARGS:
                i += 2
                continue
            if tok.startswith("-"):
                i += 1
                continue
            subcmd = tok
            break

        if not subcmd:
            return "Error: No kubectl subcommand specified."
        if subcmd not in _ALLOWED_SUBCOMMANDS:
            return f"Error: Only read-only subcommands {sorted(_ALLOWED_SUBCOMMANDS)} are permitted."

        try:
            res = subprocess.run(tokens, capture_output=True, text=True, timeout=30)
            out = res.stdout
            if res.stderr:
                out += f"\nSTDERR: {res.stderr}"
            return out or "(empty output)"
        except Exception as e:
            return f"Error executing kubectl command: {e}"

    return execute


def _conversation_id(sample_id: Any, epoch: int) -> str:
    """Returns a fresh conversation id for one gateway call.

    The gateway keeps state per conversation id, so a re-run, another epoch, or an Inspect retry
    of the same sample must not continue an earlier call's conversation.
    """
    return f"eval_{sample_id}_{epoch}_{uuid.uuid4().hex}"


def _post_json(req: urllib.request.Request, timeout: float) -> Any:
    """Sends a request and returns its decoded JSON body; runs in a worker thread."""
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _responses_text(data: Any) -> str:
    """Joins the assistant's output_text chunks from a /v1/responses reply."""
    items = data.get("output") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise RuntimeError(f"kube-agents gateway reply has no 'output' list: {str(data)[:REPLY_EXCERPT_CHARS]}")
    texts = []
    for item in items:
        if not isinstance(item, dict):
            continue
        for chunk in item.get("content") or []:
            if isinstance(chunk, dict) and chunk.get("type") == "output_text":
                texts.append(chunk.get("text", ""))
    return "\n".join(texts).strip()


@solver
def kube_agents_solver(
    sys_prompt: str | None = None,
    endpoint: str | None = None,
    timeout: float = 60.0,
):
    """Inspect AI solver that dispatches prompts to running kube-agents or executes inspection tools."""
    tool_solver = use_tools([kubectl_inspect()]) if use_tools else None

    async def solve(state: TaskState, gen: Generate) -> TaskState:
        ep = endpoint or os.environ.get("KUBE_AGENTS_ENDPOINT") or os.environ.get("AGENT_API_URL")
        if ep:
            prompt = state.user_prompt.text
            url = ep.rstrip("/")
            if not url.endswith(RESPONSES_PATH):
                url = f"{url}{RESPONSES_PATH}"
            sample_id = getattr(state, "sample_id", getattr(state, "id", "default"))
            payload = {
                "model": os.environ.get("AGENT_MODEL_NAME", "model-default"),
                "conversation": _conversation_id(sample_id, getattr(state, "epoch", 1)),
                "input": prompt,
                "message": prompt,
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            token = os.environ.get("PLATFORM_AGENT_TOKEN") or os.environ.get("KUBE_AGENTS_TOKEN")
            if token:
                req.add_header("Authorization", f"Bearer {token}")

            # A transport failure raises, so Inspect records a sample error instead of scoring it.
            try:
                data = await asyncio.to_thread(_post_json, req, timeout)
            except Exception as exc:
                raise RuntimeError(f"Failed to reach kube-agents gateway at {url}: {exc}") from exc
            text = _responses_text(data)

            state.output = ModelOutput.from_content(model="kube-agents", content=text)
            state.messages.append(ChatMessageAssistant(content=text))
            state.completed = True
            return state

        if sys_prompt:
            state.messages.insert(0, ChatMessageSystem(content=sys_prompt))
        if tool_solver:
            state = await tool_solver(state, gen)
        return await gen(state)

    return solve


@task
def identity_and_role() -> Task:
    """Evaluates model identity, role description, and permission boundaries."""
    sys_prompt = (
        "You are kube-agents, the conversational front door coordinator for Kubernetes fleet operations. "
        "You are backed by gemini-3.8-flash on Google Cloud Vertex AI (vertex_ai). "
        "You operate in a plan-and-delegate model with no direct CLI execution tools."
    )
    return Task(
        name="kubeagents/identity_and_role",
        model=_resolve_model(),
        dataset=MemoryDataset(_load_samples_for_task("kubeagents/identity_and_role")),
        solver=[kube_agents_solver(sys_prompt=sys_prompt)],
        scorer=kube_agents_cx_scorer() if kube_agents_cx_scorer else None,
    )


@task
def fleet_cloud_scope() -> Task:
    """Evaluates GCP project scope and GKE multi-cluster fleet discovery."""
    sys_prompt = (
        "You are kube-agents coordinator. The active GCP project in scope is gca-gke-test. "
        "Host cluster is ka-webconsole-pr2321 in us-central1."
    )
    return Task(
        name="kubeagents/fleet_cloud_scope",
        model=_resolve_model(),
        dataset=MemoryDataset(_load_samples_for_task("kubeagents/fleet_cloud_scope")),
        solver=[kube_agents_solver(sys_prompt=sys_prompt)],
        scorer=kube_agents_cx_scorer() if kube_agents_cx_scorer else None,
    )


@task
def cluster_inspection() -> Task:
    """Evaluates cluster state inspection (namespaces, node status, pods, K8s version)."""
    return Task(
        name="kubeagents/cluster_inspection",
        model=_resolve_model(),
        dataset=MemoryDataset(_load_samples_for_task("kubeagents/cluster_inspection")),
        solver=[kube_agents_solver()],
        scorer=kube_agents_cx_scorer() if kube_agents_cx_scorer else None,
    )


@task
def workload_inspection() -> Task:
    """Evaluates workload inspection (web-console replicas, services, CRDs, resource limits)."""
    return Task(
        name="kubeagents/workload_inspection",
        model=_resolve_model(),
        dataset=MemoryDataset(_load_samples_for_task("kubeagents/workload_inspection")),
        solver=[kube_agents_solver()],
        scorer=kube_agents_cx_scorer() if kube_agents_cx_scorer else None,
    )


@task
def diagnostics_and_logs() -> Task:
    """Evaluates cluster diagnostics, Warning events, and container log RBAC boundaries."""
    return Task(
        name="kubeagents/diagnostics_and_logs",
        model=_resolve_model(),
        dataset=MemoryDataset(_load_samples_for_task("kubeagents/diagnostics_and_logs")),
        solver=[kube_agents_solver()],
        scorer=kube_agents_cx_scorer() if kube_agents_cx_scorer else None,
    )


@task
def substrate_planning() -> Task:
    """Evaluates Agent Substrate recognition, two-part architecture, and /plan staging."""
    sys_prompt = (
        "You are kube-agents coordinator. When asked to install Agent Substrate, always structure "
        "a /plan separating the Cluster Part (operator, CRDs, node labels ate.dev/substrate-version) "
        "from the Workload Part (Worker compute pools, Actor definitions, pod execution sandboxes) "
        "prior to enabling or mutating infrastructure."
    )
    return Task(
        name="kubeagents/substrate_planning",
        model=_resolve_model(),
        dataset=MemoryDataset(_load_samples_for_task("kubeagents/substrate_planning")),
        solver=[kube_agents_solver(sys_prompt=sys_prompt)],
        scorer=kube_agents_cx_scorer() if kube_agents_cx_scorer else None,
    )
