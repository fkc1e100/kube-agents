# kube-agents Evaluation Suite (eval-runner compatible)

This directory contains the formal evaluation suite for `kube-agents`, authored in compliance with the [`gke-labs/eval-runner`](https://github.com/gke-labs/eval-runner) CI specification and the UK AI Security Institute Inspect framework (`inspect_ai`).

---

## 1. Overview & Architecture

`eval-runner` is a Kubernetes-native continuous integration system that evaluates agent performance and response quality across pull requests using statistical confidence intervals on paired samples.

In accordance with **ADR-001** and `docs/concept/functionality.md` of `eval-runner`:

- **Discovery via code:** The executable entrypoint at the repository root (`.evals/list`) outputs a JSON manifest of declared eval tasks, working directories, and resource needs.
- **Isolated Sandboxes:** Tasks run in isolated, least-privilege sandboxes (`automountServiceAccountToken: false`, UID 1000, drop all capabilities).
- **Statistical Quality Gates:** Measures task success rate, 95% Wilson confidence intervals, p50 latency, and token consumption.

---

## 2. Discovered Tasks (`.evals/list`)

The evaluation suite defines 6 core tasks across 21 standard evaluation prompts:

| Task ID                           | Spec                                        | Category                                  | Evaluation Criteria                                                                                                                                                               |
| :-------------------------------- | :------------------------------------------ | :---------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `kubeagents/identity_and_role`    | `kube_agents_tasks.py@identity_and_role`    | Category A: Identity & Model (#1–#4)      | Must identify actual backing LLM (`gemini-3.8-flash` on `Vertex AI`), clarify front door coordinator role, and verify zero LiteLLM proxy alias leaks (`model-default`, `custom`). |
| `kubeagents/fleet_cloud_scope`    | `kube_agents_tasks.py@fleet_cloud_scope`    | Category B: Fleet & Cloud Scope (#5–#8)   | Must accurately report GCP project scope (`gca-gke-test`), discover multi-cluster fleet inventory, and resolve host cluster location.                                             |
| `kubeagents/cluster_inspection`   | `kube_agents_tasks.py@cluster_inspection`   | Category C: Local Cluster State (#9–#13)  | Evaluates cluster state inspection: namespaces, node statuses, pods in `kubeagents-system`, K8s version, and CrashLoopBackOff audits without delegation stubs.                    |
| `kubeagents/workload_inspection`  | `kube_agents_tasks.py@workload_inspection`  | Category D: Workload Inspection (#14–#17) | Verifies deployment replicas, exposed services, installed CRDs, and LiteLLM CPU/memory requests and limits.                                                                       |
| `kubeagents/diagnostics_and_logs` | `kube_agents_tasks.py@diagnostics_and_logs` | Category E: Diagnostics & Logs (#18–#20)  | Audits cluster Warning events (<15m), checks container log RBAC boundaries, and verifies LiteLLM proxy health.                                                                    |
| `kubeagents/substrate_planning`   | `kube_agents_tasks.py@substrate_planning`   | Category F: Lifecycle Planning (#21)      | Verifies grounded recognition of Agent Substrate, explicit separation into **Cluster Part** vs. **Workload Part**, and `/plan` formulation prior to enabling.                     |

---

## 3. Directory Layout

```
.evals/
└── list                                 # Executable manifest generator (ADR-001)
evals/
├── datasets/
│   └── kube_agents_eval_dataset.jsonl   # 21 benchmark prompts with required/forbidden keywords
├── scorers.py                           # Deterministic CX quality & hygiene scorer (inspect_ai Scorer)
├── kube_agents_tasks.py                 # Inspect AI Task definitions (@task)
├── test_evals.py                        # Unit tests and schema validator for dataset and scorers
├── pyproject.toml                       # Python package dependencies (inspect-ai, google-genai)
└── README.md                            # Architecture and usage documentation
```

---

## 4. Running the Evals Locally

### Running the Dataset Unit Tests

```bash
python3 -m unittest evals/test_evals.py
```

### Running with Inspect AI

```bash
cd evals
uv run inspect eval kube_agents_tasks.py --model google/gemini-3.5-flash-lite
```

Without an endpoint, the tasks run the given model with a read-only `kubectl_inspect` tool. That
tool imports the repository's kubectl policy from `agents/platform/scripts/command_policy.py`, so run
the suite from a full checkout, not from a copy of `evals/` alone.

The tool uses your local kubeconfig, so it will not run against your current context. Set
`EVALS_KUBE_CONTEXT` to the context of a test cluster; the tool passes `--context` itself and
refuses every call while the variable is unset. Point it at a throwaway or test cluster, never
production: the model chooses the `get`, `describe` and `logs` calls, and they can read every
ConfigMap and pod log the context can see. Secrets, `-f`/`-k` manifest reads, `--template`, and any
`-o` format other than `wide`, `name`, `json`, `yaml`, inline `jsonpath=` or inline
`custom-columns=` are refused, because the file-based formats can print a local file such as a
kubeconfig.

```bash
EVALS_KUBE_CONTEXT=kind-evals uv run inspect eval kube_agents_tasks.py --model google/gemini-3.5-flash-lite
```

To send the prompts to a running install instead, set `KUBE_AGENTS_ENDPOINT` (or `AGENT_API_URL`)
to the gateway base URL and `PLATFORM_AGENT_TOKEN` (or `KUBE_AGENTS_TOKEN`) to its bearer token. The
endpoint must be `https`, or `http` on `localhost`, `127.0.0.1` or `[::1]` for a port-forward. The solver ignores `http_proxy`
and refuses redirects, so the token goes only to that endpoint. It posts each prompt
to `/v1/responses` with a fresh conversation id. A transport failure, or a reply with no `output`
list, is recorded as a sample error rather than scored. The solver makes one call per prompt and
does not wait for work the front door delegates.

### Running Discovery Manually

```bash
./.evals/list
```
