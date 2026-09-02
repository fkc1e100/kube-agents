# GCP Ephemeral Research Sandbox

This directory contains automated tooling and operational documentation for provisioning a disposable, cloud-hosted **Google Kubernetes Engine (GKE)** research environment. The sandbox provides a realistic, production-grade microservices topology for running and evaluating autonomous Site Reliability Engineering (SRE) infrastructure agents using the dynamic evaluation framework in `evals/`.

---

## 1. Overview

Evaluating autonomous SRE agents on local mock clusters (e.g., Kind or Minikube) has inherent fidelity limitations: local environments lack native cloud metrics, realistic multi-node topology constraints, and managed control plane telemetry.

The GCP Ephemeral Sandbox solves this by providing:

- **One-Command Cloud Provisioning:** Automates GKE cluster creation, API enablement, and credential configuration.
- **Baseline Workload Deployment:** Deploys Google Cloud's official **Online Boutique** (an 11-tier microservices application) with realistic inter-service dependencies.
- **Reproducible Evaluation Execution:** Seamlessly connects to `evals/eval_runner.py` and `evals/chaos_injector.py` to inject synthetic faults and measure agent remediation accuracy.
- **Safe Teardown:** A teardown script to completely deprovision cloud resources and prevent unintended compute billing.

```text
+-------------------------------------------------------------------------+
| GCP Ephemeral Research Sandbox                                          |
|                                                                         |
|  +-------------------------------------------------------------------+  |
|  | Google Kubernetes Engine (GKE) Cluster                            |  |
|  | (3x e2-standard-4 nodes, System/Workload Logging & Monitoring)   |  |
|  |                                                                   |  |
|  |  +-------------------------------------------------------------+  |  |
|  |  | Online Boutique Microservices (Default Namespace)            |  |  |
|  |  | - frontend, cartservice, productcatalogservice, ...         |  |  |
|  |  +-------------------------------------------------------------+  |  |
|  +-------------------------------------------------------------------+  |
|                                ^                                        |
|                                | inject faults / observe / remediate    |
|  +-----------------------------+-------------------------------------+  |
|  | Evaluation Harness (`evals/eval_runner.py`)                       |  |
|  | - Dynamic Chaos Injection (`evals/chaos_injector.py`)             |  |
|  | - Agent Execution & Artifact Capture                              |  |
|  | - Quantitative Scoring (F1_diag, M_SR, ASI, C_EF)                |  |
|  +-------------------------------------------------------------------+  |
+-------------------------------------------------------------------------+
```

---

## 2. Prerequisites & Required IAM Roles

To use this sandbox, the researcher only needs access to a **Google Cloud Project** and basic local CLI tools. No prior GKE administration experience is required.

### Local CLI Tools

Ensure the following CLI utilities are installed on your workstation:

- **Google Cloud SDK (`gcloud`):** [Install Guide](https://cloud.google.com/sdk/docs/install)
- **Kubernetes CLI (`kubectl`):** [Install Guide](https://kubernetes.io/docs/tasks/tools/)
- **Python 3.11+:** With dependencies installed via `pip install -r evals/requirements.txt`

### Required Google Cloud IAM Permissions

The researcher or service account must be granted the following IAM roles on the designated Google Cloud Project:

| IAM Role Name               | Role ID                                   | Purpose                                                      |
| :-------------------------- | :---------------------------------------- | :----------------------------------------------------------- |
| **Kubernetes Engine Admin** | `roles/container.admin`                   | Create, configure, and delete GKE clusters and workloads.    |
| **Service Account User**    | `roles/iam.serviceAccountUser`            | Attach Compute Engine default service accounts to GKE nodes. |
| **Monitoring Viewer**       | `roles/monitoring.viewer`                 | Read Cloud Monitoring metrics during diagnostic triage.      |
| **Logging Viewer**          | `roles/logging.viewer`                    | Read container and control plane logs during RCA evaluation. |
| **Service Usage Consumer**  | `roles/serviceusage.serviceUsageConsumer` | Enable required GCP APIs (`container.googleapis.com`, etc.). |

---

## 3. Step-by-Step Execution Guide

### Step 1: Authenticate to Google Cloud

Log in with your Google Cloud user account and configure application default credentials:

```bash
gcloud auth login
gcloud auth application-default login
```

### Step 2: Provision the Research Sandbox

Run the provisioning script with your assigned GCP Project ID:

```bash
./evals/sandbox/gcp/provision_sandbox.sh --project-id YOUR_PROJECT_ID
```

_Optional Flags:_

- `--cluster-name <name>`: Custom cluster name (default: `evals-sandbox-cluster`).
- `--zone <zone>`: Compute zone (default: `us-central1-a`).
- `--machine-type <type>`: Node machine type (default: `e2-standard-4`).
- `--num-nodes <n>`: Number of worker nodes (default: `3`).
- `--skip-app`: Skip automated deployment of Online Boutique microservices.

The script will:

1. Enable necessary GCP APIs (`container`, `monitoring`, `logging`).
2. Provision a GKE standard cluster with workload logging and monitoring enabled.
3. Configure your local `kubectl` context to target the new cluster.
4. Deploy the Online Boutique application and wait for all microservice pods to become ready.

### Step 3: Run Dynamic Evaluation Benchmark Scenarios

Once the cluster is ready, run evaluation scenarios using the dynamic benchmark harness:

```bash
# Run against live scenario
python evals/eval_runner.py --scenario evals/scenarios/online-boutique-oom-crash.yaml

# Run in synthetic mock mode (offline verification)
python evals/eval_runner.py --scenario evals/scenarios/online-boutique-oom-crash.yaml --mock
```

### Step 4: Teardown and Release Cloud Resources

When evaluation experiments are complete, immediately tear down the cluster to avoid ongoing compute charges:

```bash
./evals/sandbox/gcp/teardown_sandbox.sh --project-id YOUR_PROJECT_ID --yes
```

---

## 4. Troubleshooting & FAQ

- **API Enablement Error:** If you encounter `API [container.googleapis.com] not enabled`, ensure your IAM identity has `roles/serviceusage.serviceUsageConsumer`.
- **Quota Exceeded Error:** If GKE fails with `IN_USE_ADDRESSES` or `CPUS` quota exceeded, verify that your project has available quota in the chosen region/zone, or specify a different zone using `--zone us-east1-b`.
- **kubectl Context Confusion:** Verify your active cluster target at any time by running `kubectl config current-context` or `kubectl get nodes`.
