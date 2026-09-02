#!/usr/bin/env bash
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

set -euo pipefail

# Default configuration values
DEFAULT_REGION="us-central1"
DEFAULT_ZONE="us-central1-a"
DEFAULT_CLUSTER_NAME="evals-sandbox-cluster"
DEFAULT_MACHINE_TYPE="e2-standard-4"
DEFAULT_NUM_NODES="3"

PROJECT_ID=""
REGION="${DEFAULT_REGION}"
ZONE="${DEFAULT_ZONE}"
CLUSTER_NAME="${DEFAULT_CLUSTER_NAME}"
MACHINE_TYPE="${DEFAULT_MACHINE_TYPE}"
NUM_NODES="${DEFAULT_NUM_NODES}"
SKIP_APP_DEPLOY="false"

function print_usage() {
    cat <<EOF
Usage: $0 --project-id <PROJECT_ID> [OPTIONS]

Provisions an ephemeral Google Kubernetes Engine (GKE) research sandbox cluster
and deploys a baseline microservices benchmark application (Online Boutique)
for evaluating autonomous SRE infrastructure agents.

Required arguments:
  -p, --project-id PROJECT_ID    Google Cloud Project ID

Optional arguments:
  -c, --cluster-name NAME        Name of the GKE cluster (default: ${DEFAULT_CLUSTER_NAME})
  -z, --zone ZONE                GCP Compute Zone (default: ${DEFAULT_ZONE})
  -r, --region REGION            GCP Compute Region (default: ${DEFAULT_REGION})
  -m, --machine-type TYPE        GCE Machine Type (default: ${DEFAULT_MACHINE_TYPE})
  -n, --num-nodes NUM            Number of nodes per zone (default: ${DEFAULT_NUM_NODES})
  --skip-app                     Skip deploying the benchmark target application
  -h, --help                     Display this help message and exit

Example:
  $0 --project-id my-evals-project-123
EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -p|--project-id)
            PROJECT_ID="$2"
            shift 2
            ;;
        -c|--cluster-name)
            CLUSTER_NAME="$2"
            shift 2
            ;;
        -z|--zone)
            ZONE="$2"
            shift 2
            ;;
        -r|--region)
            REGION="$2"
            shift 2
            ;;
        -m|--machine-type)
            MACHINE_TYPE="$2"
            shift 2
            ;;
        -n|--num-nodes)
            NUM_NODES="$2"
            shift 2
            ;;
        --skip-app)
            SKIP_APP_DEPLOY="true"
            shift
            ;;
        -h|--help)
            print_usage
            exit 0
            ;;
        *)
            echo "Error: Unknown parameter: $1" >&2
            print_usage
            exit 1
            ;;
    esac
done

if [[ -z "${PROJECT_ID}" ]]; then
    echo "Error: --project-id is required." >&2
    print_usage
    exit 1
fi

echo "============================================================"
echo " Starting GCP Ephemeral Research Sandbox Provisioning"
echo "============================================================"
echo " Project ID:     ${PROJECT_ID}"
echo " Cluster Name:   ${CLUSTER_NAME}"
echo " Zone:           ${ZONE}"
echo " Machine Type:   ${MACHINE_TYPE}"
echo " Node Count:     ${NUM_NODES}"
echo "============================================================"

# Check CLI dependencies
for cmd in gcloud kubectl; do
    if ! command -v "${cmd}" &> /dev/null; then
        echo "Error: Required CLI tool '${cmd}' is not installed or not in PATH." >&2
        exit 1
    fi
done

# Configure active GCP project
echo "==> Configuring active Google Cloud project..."
gcloud config set project "${PROJECT_ID}"

# Enable required Google Cloud APIs
echo "==> Enabling required Google Cloud APIs..."
gcloud services enable \
    container.googleapis.com \
    monitoring.googleapis.com \
    logging.googleapis.com \
    cloudresourcemanager.googleapis.com

# Check if cluster already exists
if gcloud container clusters describe "${CLUSTER_NAME}" --zone="${ZONE}" --project="${PROJECT_ID}" &>/dev/null; then
    echo "==> Cluster '${CLUSTER_NAME}' already exists in zone '${ZONE}'."
else
    echo "==> Provisioning GKE Cluster '${CLUSTER_NAME}' (this may take 3-5 minutes)..."
    gcloud container clusters create "${CLUSTER_NAME}" \
        --project="${PROJECT_ID}" \
        --zone="${ZONE}" \
        --machine-type="${MACHINE_TYPE}" \
        --num-nodes="${NUM_NODES}" \
        --enable-autoscaling --min-nodes=1 --max-nodes=5 \
        --enable-ip-alias \
        --release-channel="regular" \
        --logging=SYSTEM,WORKLOAD \
        --monitoring=SYSTEM,WORKLOAD \
        --scopes="https://www.googleapis.com/auth/cloud-platform" \
        --quiet
fi

# Fetch kubectl credentials
echo "==> Fetching cluster credentials for kubectl..."
gcloud container clusters get-credentials "${CLUSTER_NAME}" --zone="${ZONE}" --project="${PROJECT_ID}"

# Verify cluster connectivity
echo "==> Verifying Kubernetes cluster connectivity..."
kubectl cluster-info
kubectl get nodes

# Deploy target benchmark application (Online Boutique) if not skipped
if [[ "${SKIP_APP_DEPLOY}" == "false" ]]; then
    echo "==> Deploying baseline research target application (Online Boutique)..."
    kubectl apply -f https://raw.githubusercontent.com/GoogleCloudPlatform/microservices-demo/main/release/kubernetes-manifests.yaml

    echo "==> Waiting for microservices deployments to be ready (up to 300s)..."
    kubectl wait --for=condition=available --timeout=300s deployment --all || true
    echo "==> Target workload deployment completed."
fi

echo ""
echo "============================================================"
echo " GCP Research Sandbox Provisioning Complete!"
echo "============================================================"
echo " Cluster: ${CLUSTER_NAME} (${ZONE})"
echo " Current kubectl context: $(kubectl config current-context)"
echo ""
echo " You are ready to run benchmark evaluations:"
echo "   python evals/eval_runner.py --scenario evals/scenarios/online-boutique-oom-crash.yaml"
echo ""
echo " To teardown when finished:"
echo "   ./evals/sandbox/gcp/teardown_sandbox.sh --project-id ${PROJECT_ID} --zone ${ZONE} --cluster-name ${CLUSTER_NAME}"
echo "============================================================"
