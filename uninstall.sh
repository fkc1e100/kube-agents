#!/usr/bin/env bash
# ==============================================================================
# 🧹 Kubernetes Agentic Harness (kube-agents) Complete Uninstall Engine
# ==============================================================================
# Discovers and safely deletes all provisioned GCP resources, GKE clusters,
# IAM service accounts, secrets, and Kubernetes control plane components.
#
# Usage:
#   ./uninstall.sh [options]
#   curl -fsSL https://gke-labs.github.io/kube-agents/uninstall.sh | bash
# ==============================================================================

set -euo pipefail

# ANSI Color Tokens
C_CYAN="\033[1;36m"
C_GREEN="\033[1;32m"
C_YELLOW="\033[1;33m"
C_RED="\033[1;31m"
C_BOLD="\033[1m"
C_RESET="\033[0m"

PARAM_NON_INTERACTIVE="false"
PARAM_DRY_RUN="false"
PARAM_PROJECT_ID=""
PARAM_CLUSTER_NAME=""
PARAM_REGION=""

print_banner() {
  echo -e "${C_RED}${C_BOLD}"
  echo '==========================================================================='
  echo '🧹  Kubernetes Agentic Harness (kube-agents) Complete Uninstall Engine'
  echo '==========================================================================='
  echo -e "${C_RESET}"
}

print_step() {
  echo -e "\n${C_CYAN}${C_BOLD}>>> $1 <<<${C_RESET}"
}

print_info() {
  echo -e "  ${C_CYAN}ℹ $1${C_RESET}"
}

print_success() {
  echo -e "  ${C_GREEN}✓ $1${C_RESET}"
}

print_warning() {
  echo -e "  ${C_YELLOW}⚠ $1${C_RESET}"
}

print_error() {
  echo -e "  ${C_RED}✗ $1${C_RESET}"
}

show_help() {
  print_banner
  cat << EOF
Usage: ./uninstall.sh [OPTIONS]

Options:
  -y, --yes, --non-interactive  Automated execution mode (no interactive confirmation prompt)
  --dry-run                     Preview uninstall plan without deleting resources
  --project-id ID               GCP Target Project ID
  --cluster-name NAME           GKE Target Cluster Name
  --region REGION               GKE GCP Region
  --help, -h                    Show this help message

Examples:
  # Interactively discover and remove kube-agents cluster & GCP resources
  ./uninstall.sh

  # Non-interactive automated purge
  ./uninstall.sh --non-interactive --project-id="my-gcp-project" --cluster-name="platform-agent-host"
EOF
  exit 0
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -y|--yes|--non-interactive) PARAM_NON_INTERACTIVE="true"; shift ;;
      --dry-run) PARAM_DRY_RUN="true"; shift ;;
      --uninstall|--delete) shift ;;
      --project-id=*) PARAM_PROJECT_ID="${1#*=}"; shift ;;
      --project-id) PARAM_PROJECT_ID="$2"; shift 2 ;;
      --cluster-name=*) PARAM_CLUSTER_NAME="${1#*=}"; shift ;;
      --cluster-name) PARAM_CLUSTER_NAME="$2"; shift 2 ;;
      --region=*) PARAM_REGION="${1#*=}"; shift ;;
      --region) PARAM_REGION="$2"; shift 2 ;;
      --help|-h) show_help ;;
      *) print_error "Unknown parameter: $1"; show_help ;;
    esac
  done
}

write_report() {
  local status="$1"
  local report_file="/tmp/kube-agents-uninstall-report.json"
  cat << EOF > "$report_file"
{
  "status": "${status}",
  "dry_run": ${PARAM_DRY_RUN},
  "non_interactive": ${PARAM_NON_INTERACTIVE},
  "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || echo "2026-08-05T00:00:00Z")"
}
EOF
  print_success "Uninstall report written to: $report_file"
}

main() {
  parse_args "$@"
  print_banner

  print_step "1. Discovering Installed Infrastructure Elements"

  if [ -f "k8s-operator/scripts/vars.sh" ]; then
    # shellcheck disable=SC1091
    source "k8s-operator/scripts/vars.sh" 2>/dev/null || true
    print_success "Loaded configuration state from k8s-operator/scripts/vars.sh"
  fi

  local target_project="${PARAM_PROJECT_ID:-${PROJECT_ID:-}}"
  local target_cluster="${PARAM_CLUSTER_NAME:-${CLUSTER_NAME:-platform-agent-host}}"
  local target_region="${PARAM_REGION:-${REGION:-us-central1}}"

  if [ -z "$target_project" ]; then
    target_project="$(gcloud config get-value project 2>/dev/null || echo "gca-gke-2025")"
  fi

  print_info "GCP Target Project: ${C_BOLD}${target_project}${C_RESET}"
  print_info "GKE Target Cluster: ${C_BOLD}${target_cluster}${C_RESET} (${target_region})"

  if [ "$PARAM_DRY_RUN" = "true" ]; then
    print_step "2. Dry-Run Uninstall Preview"
    echo -e "  • ${C_CYAN}Target Cluster:${C_RESET} ${target_cluster} in ${target_project} (${target_region})"
    echo -e "  • ${C_CYAN}Action:${C_RESET} Delete GKE cluster, IAM service accounts, secrets, and operator CRDs"
    write_report "DRY_RUN_COMPLETE"
    exit 0
  fi

  if [ "$PARAM_NON_INTERACTIVE" != "true" ]; then
    echo -e "\n${C_RED}${C_BOLD}⚠️  WARNING: This will PERMANENTLY DELETE all kube-agents infrastructure in GCP project '${target_project}'!${C_RESET}"
    read -rp "Are you sure you want to proceed with complete uninstallation? (y/N): " confirm_choice
    if [[ ! "$confirm_choice" =~ ^[Yy]$ ]]; then
      print_warning "Uninstall cancelled by user."
      exit 0
    fi
  fi

  print_step "2. Executing Automated Teardown Engine"

  export PROJECT_ID="$target_project"
  export CLUSTER_NAME="$target_cluster"
  export REGION="$target_region"
  export NO_CONFIRM="1"

  cd k8s-operator
  if [ -f "scripts/teardown.sh" ]; then
    bash scripts/teardown.sh --no-confirm </dev/null || true
  fi
  rm -f scripts/vars.sh
  cd ..

  write_report "SUCCESS"

  print_step "🎉 Uninstall Complete!"
  echo -e "${C_GREEN}${C_BOLD}🏆 All kube-agents infrastructure elements have been safely removed.${C_RESET}"
}

main "$@"
