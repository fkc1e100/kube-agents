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

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
from typing import Any
import urllib.request

CURRENT_DIR = Path(__file__).resolve().parent
DATASET_PATH = CURRENT_DIR / "datasets" / "kube_agents_eval_dataset.jsonl"
DEFAULT_MODEL = "google/gemini-3.5-flash-lite"
REQUIRED_RECORD_KEYS = ("id", "task_id", "input")

try:
    from inspect_ai import Task, task
    from inspect_ai.dataset import MemoryDataset, Sample
    from inspect_ai.model import ChatMessageAssistant, ChatMessageSystem, ModelOutput
    from inspect_ai.solver import Generate, TaskState, generate, solver, system_message, use_tools
    from inspect_ai.tool import Tool, tool

    _INSPECT_AVAILABLE = True
except ImportError:
    _INSPECT_AVAILABLE = False

    # Minimal fallback dummy decorators when inspect_ai is not installed
    def task(fn):
        return fn

    def tool(fn):
        return fn

    def solver(fn):
        return fn

    class Sample:
        def __init__(self, input="", target="", id=0, metadata=None):
            self.input = input
            self.target = target
            self.id = id
            self.metadata = metadata or {}

    class MemoryDataset(list):
        def __init__(self, samples=None):
            super().__init__(samples or [])

    class Task:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class ModelOutput:
        @classmethod
        def from_content(cls, model="", content=""):
            return cls(model=model, content=content)

        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class ChatMessageAssistant:
        def __init__(self, content="", **kwargs):
            self.content = content

    class ChatMessageSystem:
        def __init__(self, content="", **kwargs):
            self.content = content

    generate = None
    system_message = None
    use_tools = None
    Generate = Any
    TaskState = Any
    Tool = Any

try:
    # Sibling import: Inspect loads this file by path, so it has no parent package.
    from scorers import kube_agents_cx_scorer
except ImportError:
    # scorers.py defines kube_agents_cx_scorer only when inspect_ai imports; with
    # inspect_ai present, a failed import is a real error and must not yield unscored tasks.
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

        # Guard against mutating subcommands anywhere in the command arguments
        for t in tokens[1:]:
            if t.lower() in _MUTATING_SUBCOMMANDS:
                return f"Error: Mutating subcommand '{t}' is prohibited."

        # Connection and identity overrides would send the caller's kubeconfig credentials to a
        # server the model chooses or impersonate another user; Secret objects stay unreadable.
        for t in tokens[1:]:
            flag = t.split("=", 1)[0]
            if flag in _DENIED_FLAGS:
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


@solver
def kube_agents_solver(
    sys_prompt: str | None = None,
    endpoint: str | None = None,
    timeout: float = 60.0,
):
    """Inspect AI solver that dispatches prompts to running kube-agents or executes inspection tools."""
    tool_solver = use_tools([kubectl_inspect()]) if use_tools and use_tools != Any else None

    async def solve(state: TaskState, gen: Generate) -> TaskState:
        ep = endpoint or os.environ.get("KUBE_AGENTS_ENDPOINT") or os.environ.get("AGENT_API_URL")
        if ep:
            prompt = state.user_prompt.text
            url = ep.rstrip("/")
            if not url.endswith(("/v1/responses", "/api/chat")):
                url = f"{url}/v1/responses"
            sample_id = getattr(state, "sample_id", getattr(state, "id", "default"))
            payload = {
                "model": os.environ.get("AGENT_MODEL_NAME", "model-default"),
                "conversation": f"eval_{sample_id}",
                "input": prompt,
                "message": prompt,
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    text = data.get("response") or data.get("output") or data.get("text") or str(data)
                    state.output = ModelOutput.from_content(model="kube-agents", content=text)
                    state.messages.append(ChatMessageAssistant(content=text))
                    state.completed = True
                    return state
            except Exception as exc:
                err_msg = f"Failed to reach kube-agents gateway at {url}: {exc}"
                state.output = ModelOutput.from_content(model="kube-agents", content=err_msg)
                state.messages.append(ChatMessageAssistant(content=err_msg))
                state.completed = True
                return state

        if sys_prompt and ChatMessageSystem and ChatMessageSystem != Any:
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
