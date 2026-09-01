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
DEFAULT_ZONE="us-central1-a"
DEFAULT_CLUSTER_NAME="evals-sandbox-cluster"

PROJECT_ID=""
ZONE="${DEFAULT_ZONE}"
CLUSTER_NAME="${DEFAULT_CLUSTER_NAME}"
FORCE="false"

function print_usage() {
    cat <<EOF
Usage: $0 --project-id <PROJECT_ID> [OPTIONS]

Tears down an ephemeral Google Kubernetes Engine (GKE) research sandbox cluster
and cleans up cloud resources to prevent ongoing billing.

Required arguments:
  -p, --project-id PROJECT_ID    Google Cloud Project ID

Optional arguments:
  -c, --cluster-name NAME        Name of the GKE cluster (default: ${DEFAULT_CLUSTER_NAME})
  -z, --zone ZONE                GCP Compute Zone (default: ${DEFAULT_ZONE})
  -f, --force, -y, --yes         Skip confirmation prompt
  -h, --help                     Display this help message and exit

Example:
  $0 --project-id my-evals-project-123 -y
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
        -f|--force|-y|--yes)
            FORCE="true"
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
echo " GCP Ephemeral Research Sandbox Teardown"
echo "============================================================"
echo " Project ID:     ${PROJECT_ID}"
echo " Cluster Name:   ${CLUSTER_NAME}"
echo " Zone:           ${ZONE}"
echo "============================================================"

# Confirmation prompt
if [[ "${FORCE}" != "true" ]]; then
    read -r -p "Are you sure you want to delete cluster '${CLUSTER_NAME}' in project '${PROJECT_ID}'? [y/N] " response
    if [[ ! "${response}" =~ ^([yY][eE][sS]|[yY])$ ]]; then
        echo "Teardown cancelled."
        exit 0
    fi
fi

# Check CLI dependency
if ! command -v gcloud &> /dev/null; then
    echo "Error: 'gcloud' CLI tool is not installed or not in PATH." >&2
    exit 1
fi

# Configure active GCP project
gcloud config set project "${PROJECT_ID}"

# Check if cluster exists
if gcloud container clusters describe "${CLUSTER_NAME}" --zone="${ZONE}" --project="${PROJECT_ID}" &>/dev/null; then
    echo "==> Deleting GKE cluster '${CLUSTER_NAME}' in zone '${ZONE}'..."
    gcloud container clusters delete "${CLUSTER_NAME}" \
        --zone="${ZONE}" \
        --project="${PROJECT_ID}" \
        --quiet
    echo "==> GKE cluster '${CLUSTER_NAME}' successfully deleted."
else
    echo "==> Cluster '${CLUSTER_NAME}' not found in zone '${ZONE}' (already deleted or nonexistent)."
fi

echo ""
echo "============================================================"
echo " Teardown Complete! Cloud resources have been released."
echo "============================================================"
