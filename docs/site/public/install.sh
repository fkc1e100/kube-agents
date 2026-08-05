#!/usr/bin/env bash
# ==============================================================================
# 🤖 Kubernetes Agentic Harness (kube-agents) Zero-Friction Installer
# ==============================================================================
# Usage (Interactive):
#   curl -fsSL https://raw.githubusercontent.com/gke-labs/kube-agents/main/install.sh | bash
#
# Usage (AI Agents & Non-Interactive Automation):
#   curl -fsSL https://raw.githubusercontent.com/gke-labs/kube-agents/main/install.sh | bash -s -- \
#     --non-interactive --project-id="my-gcp-project" --cluster-name="platform-agent"
#
# Designed for Google Cloud Shell, Linux, macOS, and AI Agent harnesses.
# ==============================================================================

set -euo pipefail

# ─── ANSI Colors & Terminal Responsive Helpers ─────────────────────────────────
if [ -n "${NO_COLOR:-}" ] || [ ! -t 1 ]; then
  C_CYAN='' C_GREEN='' C_YELLOW='' C_MAGENTA='' C_RED='' C_RESET='' C_BOLD=''
else
  C_CYAN='\e[96m' C_GREEN='\e[92m' C_YELLOW='\e[93m' C_MAGENTA='\e[95m' C_RED='\e[91m' C_RESET='\e[0m' C_BOLD='\e[1m'
fi

# ─── Agentic & Automation Parameter States ────────────────────────────────────
PARAM_NON_INTERACTIVE="${NONINTERACTIVE:-false}"
PARAM_DRY_RUN="${DRY_RUN:-false}"
PARAM_PROJECT_ID="${PROJECT_ID:-}"
PARAM_REGION="${REGION:-}"
PARAM_CLUSTER_NAME="${CLUSTER_NAME:-}"
PARAM_CLUSTER_TYPE="${CLUSTER_TYPE:-standard}"
PARAM_MACHINE_TYPE="${MACHINE_TYPE:-e2-standard-4}"
PARAM_NUM_NODES="${NUM_NODES:-1}"
PARAM_MIN_NODES="${MIN_NODES:-1}"
PARAM_MAX_NODES="${MAX_NODES:-5}"
PARAM_ENABLE_AUTOSCALING="${ENABLE_AUTOSCALING:-true}"
PARAM_MODEL_PROVIDER="${MODEL_PROVIDER:-gemini}"
PARAM_GEMINI_API_KEY="${GEMINI_API_KEY:-}"
PARAM_OPENAI_API_KEY="${OPENAI_API_KEY:-}"
PARAM_ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"
PARAM_GITOPS_ORG="${GITHUB_ORG:-}"
PARAM_GITOPS_REPO="${GITHUB_REPO:-}"
PARAM_PERMISSION_SET="${PLATFORM_AGENT_PERMISSION_SET:-sre}"
PARAM_ENABLE_GVISOR="${ENABLE_GVISOR:-false}"

show_help() {
  cat << EOF
🤖 kube-agents Zero-Friction Installer

Usage:
  ./install.sh [FLAGS]

Flags for AI Agents & Automation:
  -y, --yes, --non-interactive  Run in non-interactive mode (use flags/defaults)
  --dry-run                     Validate prerequisites & output config/plan without creating resources
  --project-id=ID               Target GCP Project ID
  --region=REGION               Target GCP Region (default: us-central1)
  --cluster-name=NAME           GKE Cluster Name (default: kube-agents-platform)
  --cluster-type=TYPE           GKE Cluster Type: standard | autopilot (default: standard)
  --machine-type=SPEC           Node machine spec: e2-standard-4 | e2-standard-8 | c3-standard-22
  --model-provider=PROVIDER     Model provider: gemini | openai | anthropic (default: gemini)
  --gemini-api-key=KEY          Gemini API Key
  --openai-api-key=KEY          OpenAI API Key
  --anthropic-api-key=KEY       Anthropic API Key
  --gitops-org=ORG              GitHub Org/Username for GitOps repo
  --gitops-repo=REPO            GitOps IaC Repository Name (default: gke-fleet-iac)
  --permission-set=SET          Agent permission boundary: sre | read-only (default: sre)
  --gvisor=true|false           Enable GKE Sandbox (gVisor) runtime isolation (default: false)
  -h, --help                    Show this help message
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -y|--yes|--non-interactive) PARAM_NON_INTERACTIVE="true"; shift ;;
      --dry-run) PARAM_DRY_RUN="true"; shift ;;
      --project-id=*) PARAM_PROJECT_ID="${1#*=}"; shift ;;
      --region=*) PARAM_REGION="${1#*=}"; shift ;;
      --cluster-name=*) PARAM_CLUSTER_NAME="${1#*=}"; shift ;;
      --cluster-type=*) PARAM_CLUSTER_TYPE="${1#*=}"; shift ;;
      --machine-type=*) PARAM_MACHINE_TYPE="${1#*=}"; shift ;;
      --model-provider=*) PARAM_MODEL_PROVIDER="${1#*=}"; shift ;;
      --gemini-api-key=*) PARAM_GEMINI_API_KEY="${1#*=}"; shift ;;
      --openai-api-key=*) PARAM_OPENAI_API_KEY="${1#*=}"; shift ;;
      --anthropic-api-key=*) PARAM_ANTHROPIC_API_KEY="${1#*=}"; shift ;;
      --gitops-org=*) PARAM_GITOPS_ORG="${1#*=}"; shift ;;
      --gitops-repo=*) PARAM_GITOPS_REPO="${1#*=}"; shift ;;
      --permission-set=*) PARAM_PERMISSION_SET="${1#*=}"; shift ;;
      --gvisor=*) PARAM_ENABLE_GVISOR="${1#*=}"; shift ;;
      -h|--help) show_help; exit 0 ;;
      *) shift ;;
    esac
  done
}

get_term_width() {
  local cols
  cols=$(tput cols 2>/dev/null || echo 80)
  if ! [[ "$cols" =~ ^[0-9]+$ ]] || [ "$cols" -lt 40 ]; then
    cols=80
  fi
  echo "$cols"
}

draw_separator() {
  local width
  width=$(get_term_width)
  if [ "$width" -gt 75 ]; then
    width=75
  fi
  printf '%*s' "$width" '' | tr ' ' '='
}

print_banner() {
  local term_w
  term_w=$(get_term_width)

  printf '%b\n' "${C_CYAN}${C_BOLD}"
  draw_separator

  if [ "$term_w" -ge 60 ]; then
    cat << "EOF"
    __ ____  ______  ______     ___   _____________   _____________
   / //_/ / / / __ )/ ____/    /   | / ____/ ____/ | / /_  __/ ___/
  / ,< / / / / __  / __/______/ /| |/ / __/ __/ /  |/ / / /  \__ \ 
 / /| / /_/ / /_/ / /__/_____/ ___ / /_/ / /___/ /|  / / /  ___/ / 
/_/ |_\____/_____/_____/    /_/  |_\____/_____/_/ |_/ /_/  /____/  
EOF
  else
    printf '%b\n' "🤖 KUBE-AGENTS PLATFORM HARNESS"
  fi

  printf '\n%b\n' "🤖 Kubernetes Agentic Harness (kube-agents) Zero-Friction Installer"
  draw_separator
  printf '%b\n\n' "${C_RESET}"
}

print_step() { echo -e "\n${C_MAGENTA}${C_BOLD}>>> $1 <<<${C_RESET}"; }
print_success() { echo -e "  ${C_GREEN}✓ $1${C_RESET}"; }
print_info() { echo -e "  ${C_CYAN}ℹ $1${C_RESET}"; }
print_warning() { echo -e "  ${C_YELLOW}⚠ $1${C_RESET}"; }
print_error() { echo -e "  ${C_RED}✗ $1${C_RESET}"; }

# Safe prompt helper: supports non-interactive mode and /dev/tty fallback
prompt_read() {
  local prompt_text="$1"
  local var_name="$2"
  local default_val="${3:-}"
  local secret_mode="${4:-false}"

  # Non-interactive mode override
  if [ "$PARAM_NON_INTERACTIVE" = "true" ] || [ ! -c /dev/tty ]; then
    local current_val="${!var_name:-}"
    if [ -n "$current_val" ]; then
      eval "$var_name=\"$current_val\""
    else
      eval "$var_name=\"$default_val\""
    fi
    print_info "Auto-selected ($var_name): ${!var_name}"
    return 0
  fi

  if [ -n "$default_val" ]; then
    prompt_text="$prompt_text [default: ${C_BOLD}$default_val${C_RESET}]: "
  else
    prompt_text="$prompt_text: "
  fi

  echo -ne "${C_CYAN}${prompt_text}${C_RESET}" >/dev/tty

  local input_val=""
  if [ "$secret_mode" = "true" ]; then
    read -r -s input_val </dev/tty
    echo "" >/dev/tty
  else
    read -r input_val </dev/tty
  fi

  if [ -z "$input_val" ] && [ -n "$default_val" ]; then
    eval "$var_name=\"$default_val\""
  else
    eval "$var_name=\"$input_val\""
  fi
}

prompt_menu() {
  local prompt_text="$1"
  shift
  local options=("$@")
  local var_name="${options[${#options[@]}-1]}"
  unset 'options[${#options[@]}-1]'

  if [ "$PARAM_NON_INTERACTIVE" = "true" ] || [ ! -c /dev/tty ]; then
    local current_choice="${!var_name:-1}"
    eval "$var_name=\"$current_choice\""
    print_info "Auto-selected option ($var_name): $current_choice"
    return 0
  fi

  echo -e "\n${C_BOLD}$prompt_text${C_RESET}" >/dev/tty
  for i in "${!options[@]}"; do
    echo -e "  ${C_YELLOW}$((i+1)))${C_RESET} ${options[$i]}" >/dev/tty
  done

  local choice=""
  while true; do
    prompt_read "Select an option (1-${#options[@]})" choice "1"
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#options[@]}" ]; then
      eval "$var_name=\"$choice\""
      break
    else
      print_error "Invalid selection. Please enter a number between 1 and ${#options[@]}." >/dev/tty
    fi
  done
}

# Auto-install missing CLI tool if possible
auto_install_tool() {
  local tool="$1"
  print_warning "Missing required CLI tool: $tool"

  if [ "$PARAM_NON_INTERACTIVE" = "true" ]; then
    print_info "Non-interactive mode: Auto-installing $tool..."
    local install_choice="y"
  else
    local install_choice=""
    prompt_read "Attempt automatic installation of '$tool'? (y/N)" install_choice "y"
  fi

  if [[ "$install_choice" =~ ^[Yy]$ ]]; then
    if command -v brew >/dev/null 2>&1; then
      print_info "Installing $tool via Homebrew..."
      brew install "$tool" </dev/tty >/dev/tty || true
    elif command -v apt-get >/dev/null 2>&1; then
      print_info "Installing $tool via apt..."
      if [ "$tool" = "gh" ]; then
        type -p curl >/dev/null || sudo apt-get install curl -y
        curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg 2>/dev/null
        sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
        sudo apt-get install gh -y || true
      else
        sudo apt-get update >/dev/null 2>&1 || true
        sudo apt-get install -y "$tool" || true
      fi
    else
      print_error "Could not auto-install $tool. Package manager not recognized."
    fi
  fi

  if command -v "$tool" >/dev/null 2>&1; then
    print_success "CLI tool '$tool' installed successfully!"
  else
    print_error "Tool '$tool' is still missing. Please install $tool manually."
    exit 1
  fi
}

# Generate Machine-Readable JSON Report for AI Agents
write_json_report() {
  local status="$1"
  local report_file="/tmp/kube-agents-install-report.json"
  local timestamp
  timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || echo "2026-08-05T00:00:00Z")

  cat << EOF > "$report_file"
{
  "status": "${status}",
  "dry_run": ${PARAM_DRY_RUN},
  "non_interactive": ${PARAM_NON_INTERACTIVE},
  "project_id": "${project_id}",
  "project_number": "${project_number}",
  "cluster_name": "${cluster_name}",
  "region": "${region}",
  "model_provider": "${model_provider}",
  "permission_set": "${permission_set}",
  "gvisor_enabled": ${enable_gvisor},
  "gitops_repo": "https://github.com/${github_org}/${github_repo}",
  "vars_file": "${vars_file:-}",
  "timestamp": "${timestamp}"
}
EOF
  print_success "Machine-readable report written to: ${C_BOLD}${report_file}${C_RESET}"
}

# ─── Main Installer Procedure ──────────────────────────────────────────────────
main() {
  parse_args "$@"
  print_banner

  # 1. Environment Detection (Google Cloud Shell vs Linux/macOS Terminal)
  local is_cloud_shell="false"
  if [ "${CLOUD_SHELL:-false}" = "true" ] || [ -n "${DEVSHELL_PROJECT_ID:-}" ]; then
    is_cloud_shell="true"
    print_success "Environment Detected: ${C_BOLD}Google Cloud Shell${C_RESET} ☁️"
  else
    print_info "Environment Detected: ${C_BOLD}Standard Workstation / Linux Terminal${C_RESET} 💻"
  fi

  if [ "$PARAM_NON_INTERACTIVE" = "true" ]; then
    print_info "Execution Mode: ${C_BOLD}Non-Interactive / AI Agent Automated Mode${C_RESET} 🤖"
  fi

  # 2. Prerequisite CLI Tools Check & Auto-Installation
  print_step "1. Checking Prerequisites & Installing Missing Tools"
  for tool in git make gcloud kubectl gh helm; do
    if command -v "$tool" >/dev/null 2>&1; then
      print_success "Found CLI tool: $tool"
    else
      auto_install_tool "$tool"
    fi
  done

  # 3. Google Cloud Authentication Check
  print_step "2. Verifying Google Cloud Authentication"
  local active_account=""
  active_account=$(gcloud config get-value account 2>/dev/null || echo "")

  if [ -z "$active_account" ] || ! gcloud auth print-access-token >/dev/null 2>&1; then
    if [ "$PARAM_NON_INTERACTIVE" = "true" ]; then
      print_error "gcloud CLI is not authenticated and non-interactive mode is enabled."
      print_info "Please run 'gcloud auth login' before executing the installer."
      exit 1
    fi
    print_warning "gcloud CLI is not authenticated."
    print_info "Launching Google Cloud authentication..."
    gcloud auth login </dev/tty >/dev/tty
    gcloud auth application-default login </dev/tty >/dev/tty
    active_account=$(gcloud config get-value account 2>/dev/null || echo "")
  fi
  print_success "Authenticated as: ${C_BOLD}${active_account:-Google Cloud User}${C_RESET}"

  # 4. GCP Project Target Configuration
  print_step "3. Google Cloud Target Configuration"
  local active_proj=""
  if [ "$is_cloud_shell" = "true" ] && [ -n "${DEVSHELL_PROJECT_ID:-}" ]; then
    active_proj="${DEVSHELL_PROJECT_ID}"
  else
    active_proj=$(gcloud config get-value project 2>/dev/null || echo "")
  fi

  local project_id=""
  if [ -n "$PARAM_PROJECT_ID" ]; then
    project_id="$PARAM_PROJECT_ID"
  else
    print_info "Fetching available GCP projects from your account..."
    local proj_lines=""
    proj_lines=$(gcloud projects list --format="value(projectId,name)" --limit=10 2>/dev/null || echo "")

    if [ -n "$proj_lines" ] && [ "$PARAM_NON_INTERACTIVE" != "true" ]; then
      local proj_menu_opts=()
      local proj_ids=()
      while IFS=$'\t' read -r p_id p_name; do
        if [ -n "$p_id" ]; then
          proj_ids+=("$p_id")
          if [ "$p_id" = "$active_proj" ]; then
            proj_menu_opts+=("$p_id ($p_name) ${C_GREEN}[active]${C_RESET}")
          else
            proj_menu_opts+=("$p_id ($p_name)")
          fi
        fi
      done <<< "$proj_lines"
      proj_menu_opts+=("Enter a custom GCP Project ID manually")

      local proj_choice=""
      prompt_menu "Select target GCP Project:" "${proj_menu_opts[@]}" proj_choice

      if [ "$proj_choice" -le "${#proj_ids[@]}" ]; then
        project_id="${proj_ids[$((proj_choice-1))]}"
      else
        prompt_read "Target GCP Project ID" project_id "${active_proj:-my-gcp-project}"
      fi
    else
      prompt_read "Target GCP Project ID" project_id "${active_proj:-my-gcp-project}"
    fi
  fi

  gcloud config set project "$project_id" >/dev/null 2>&1 || true
  print_success "Selected Project ID: ${C_BOLD}${project_id}${C_RESET}"

  # Auto-resolve Project Number
  local project_number=""
  project_number=$(gcloud projects describe "$project_id" --format="value(projectNumber)" 2>/dev/null || echo "")
  if [ -n "$project_number" ]; then
    print_success "Resolved Project Number: ${C_BOLD}${project_number}${C_RESET}"
  fi

  # Region Selection
  local active_region=""
  active_region=$(gcloud config get-value compute/region 2>/dev/null || echo "")
  local region="${PARAM_REGION:-}"
  if [ -z "$region" ]; then
    prompt_read "Target GCP Region" region "${active_region:-us-central1}"
  fi

  # 5. GKE Cluster Selection & Provisioning Strategy
  print_step "4. GKE Cluster Topology & Capacity Setup"
  local cluster_choice=""
  if [ "$PARAM_NON_INTERACTIVE" = "true" ]; then
    cluster_choice="1"
  else
    prompt_menu "How would you like to handle the GKE Cluster?" \
      "Provision a NEW GKE Cluster from scratch (Recommended)" \
      "Use an EXISTING GKE Cluster" \
      cluster_choice
  fi

  local cluster_name="${PARAM_CLUSTER_NAME:-}"
  local cluster_type="${PARAM_CLUSTER_TYPE:-standard}"
  local machine_type="${PARAM_MACHINE_TYPE:-e2-standard-4}"
  local num_nodes="${PARAM_NUM_NODES:-1}"
  local min_nodes="${PARAM_MIN_NODES:-1}"
  local max_nodes="${PARAM_MAX_NODES:-5}"
  local enable_autoscaling="${PARAM_ENABLE_AUTOSCALING:-true}"

  if [ "$cluster_choice" = "1" ]; then
    if [ "$PARAM_NON_INTERACTIVE" != "true" ]; then
      local size_choice=""
      prompt_menu "Select GKE Cluster Size & Machine Spec:" \
        "Small Standard (e2-standard-4, 1-3 nodes, Autoscaling enabled)" \
        "Medium Standard (e2-standard-8, 1-5 nodes, Autoscaling enabled)" \
        "Large High-Performance (c3-standard-22, 2-10 nodes, Autoscaling enabled)" \
        "GKE Autopilot (Fully managed serverless GKE)" \
        size_choice

      case "$size_choice" in
        1) machine_type="e2-standard-4"; num_nodes=1; min_nodes=1; max_nodes=3 ;;
        2) machine_type="e2-standard-8"; num_nodes=1; min_nodes=1; max_nodes=5 ;;
        3) machine_type="c3-standard-22"; num_nodes=2; min_nodes=2; max_nodes=10 ;;
        4) cluster_type="autopilot" ;;
      esac
    fi

    if [ -z "$cluster_name" ]; then
      prompt_read "New GKE Cluster Name" cluster_name "kube-agents-platform"
    fi
  else
    # Auto-discover existing clusters
    print_info "Querying existing GKE clusters in project '$project_id'..."
    local cluster_lines=""
    cluster_lines=$(gcloud container clusters list --project="$project_id" --format="value(name,location)" 2>/dev/null || echo "")

    if [ -n "$cluster_lines" ]; then
      local cluster_opts=()
      local cluster_names=()
      while IFS=$'\t' read -r c_name c_loc; do
        if [ -n "$c_name" ]; then
          cluster_names+=("$c_name")
          cluster_opts+=("$c_name (location: $c_loc)")
        fi
      done <<< "$cluster_lines"
      cluster_opts+=("Type an unlisted cluster name manually")

      local c_choice=""
      prompt_menu "Select existing GKE cluster:" "${cluster_opts[@]}" c_choice
      if [ "$c_choice" -le "${#cluster_names[@]}" ]; then
        cluster_name="${cluster_names[$((c_choice-1))]}"
      else
        prompt_read "Existing GKE Cluster Name" cluster_name "platform-agent-host"
      fi
    else
      print_warning "No existing GKE clusters found in project '$project_id'."
      prompt_read "Existing GKE Cluster Name" cluster_name "platform-agent-host"
    fi
  fi
  print_success "Selected Cluster Name: ${C_BOLD}${cluster_name}${C_RESET}"

  # 6. Chat & Messaging Platform Integration
  print_step "5. Chat & Messaging Integrations Setup"
  local chat_choice=""
  if [ "$PARAM_NON_INTERACTIVE" = "true" ]; then
    chat_choice="4"
  else
    prompt_menu "Select Chat Channel Integration(s):" \
      "Google Chat (Pub/Sub Event Streaming)" \
      "Slack (Socket Mode App)" \
      "Both Google Chat and Slack" \
      "None (CLI & REST API Gateway only)" \
      chat_choice
  fi

  local google_chat_enabled="false"
  local slack_enabled="false"
  local allowed_users="${active_account:-user@example.com}"
  local chat_topic_name="platform-agent-chat-events"
  local chat_sub_name="platform-agent-chat-events-sub"
  local slack_bot_token=""
  local slack_app_token=""
  local slack_allowed_users=""
  local slack_home_channel=""
  local slack_home_channel_name=""

  case "$chat_choice" in
    1)
      google_chat_enabled="true"
      prompt_read "Allowed User Email(s) for Google Chat (comma-separated)" allowed_users "$allowed_users"
      prompt_read "Pub/Sub Topic Name for Google Chat" chat_topic_name "platform-agent-chat-events"
      ;;
    2)
      slack_enabled="true"
      prompt_read "Slack Bot Token (xoxb-...)" slack_bot_token "" true
      prompt_read "Slack App Token (xapp-...)" slack_app_token "" true
      prompt_read "Allowed Slack User IDs / Emails (comma-separated)" slack_allowed_users "$allowed_users"
      prompt_read "Slack Home Channel ID (optional, e.g. C0123456789)" slack_home_channel ""
      prompt_read "Slack Home Channel Name (optional, e.g. #gke-alerts)" slack_home_channel_name ""
      ;;
    3)
      google_chat_enabled="true"
      slack_enabled="true"
      prompt_read "Allowed User Email(s) for Google Chat (comma-separated)" allowed_users "$allowed_users"
      prompt_read "Pub/Sub Topic Name for Google Chat" chat_topic_name "platform-agent-chat-events"
      prompt_read "Slack Bot Token (xoxb-...)" slack_bot_token "" true
      prompt_read "Slack App Token (xapp-...)" slack_app_token "" true
      prompt_read "Allowed Slack User IDs / Emails (comma-separated)" slack_allowed_users "$allowed_users"
      prompt_read "Slack Home Channel ID (optional, e.g. C0123456789)" slack_home_channel ""
      prompt_read "Slack Home Channel Name (optional, e.g. #gke-alerts)" slack_home_channel_name ""
      ;;
    4)
      print_info "Chat integrations disabled. Agent will operate via CLI / REST API Gateway."
      ;;
  esac

  # 7. LLM Model Provider Selection & API Key Auto-Discovery
  print_step "6. AI Model Provider Credentials"
  local model_provider="${PARAM_MODEL_PROVIDER:-gemini}"
  local model_default_name="gemini-3.5-flash"
  local gemini_api_key="${PARAM_GEMINI_API_KEY:-placeholder}"
  local openai_api_key="${PARAM_OPENAI_API_KEY:-placeholder}"
  local anthropic_api_key="${PARAM_ANTHROPIC_API_KEY:-placeholder}"

  if [ "$PARAM_NON_INTERACTIVE" != "true" ]; then
    local model_choice=""
    prompt_menu "Select Model Provider for the Platform Agent:" \
      "Google Gemini (Recommended: gemini-3.5-flash / Gemini API)" \
      "OpenAI (gpt-4o / OpenAI API)" \
      "Anthropic (claude-3-5-sonnet / Anthropic API)" \
      model_choice

    case "$model_choice" in
      1)
        model_provider="gemini"
        model_default_name="gemini-3.5-flash"
        local detected_key="${GEMINI_API_KEY:-}"
        if [ -z "$detected_key" ]; then
          detected_key=$(gcloud secrets versions access latest --secret="gemini-api-key" --project="$project_id" 2>/dev/null || echo "")
        fi
        prompt_read "Gemini API Key" gemini_api_key "$detected_key" true
        ;;
      2)
        model_provider="openai"
        model_default_name="gpt-4o"
        prompt_read "OpenAI API Key" openai_api_key "${OPENAI_API_KEY:-}" true
        ;;
      3)
        model_provider="anthropic"
        model_default_name="claude-3-5-sonnet-20241022"
        prompt_read "Anthropic API Key" anthropic_api_key "${ANTHROPIC_API_KEY:-}" true
        ;;
    esac
  fi

  # 8. GitOps Infrastructure Repository Connection
  print_step "7. GitOps Infrastructure Repository Setup"
  local github_org="${PARAM_GITOPS_ORG:-}"
  local github_repo="${PARAM_GITOPS_REPO:-gke-fleet-iac}"
  local github_app_id=""
  local kms_keyring="github-token-minter-keyring"
  local kms_key="github-token-minter-key"
  local github_pem_path=""
  local github_token=""

  if [ "$PARAM_NON_INTERACTIVE" != "true" ]; then
    local gitops_choice=""
    prompt_menu "Would you like to connect or create a GitOps repo for automated PRs?" \
      "Create a NEW GitHub Repository automatically (Recommended)" \
      "Connect an EXISTING GitHub Repository" \
      "Skip for now (Can be enabled later)" \
      gitops_choice

    if [ "$gitops_choice" = "1" ] || [ "$gitops_choice" = "2" ]; then
      local detected_gh_user=""
      detected_gh_user=$(gh api user -q .login 2>/dev/null || git config user.name 2>/dev/null || echo "")
      prompt_read "GitHub Org / Username" github_org "${detected_gh_user:-github-user}"
      prompt_read "GitOps Repository Name" github_repo "gke-fleet-iac"

      local auth_strat_choice=""
      prompt_menu "Select GitHub Auth Strategy for the Agent:" \
        "Personal Access / CLI Token (Simple / Zero-Friction Setup)" \
        "GitHub App & Token Minter (Enterprise / Short-Lived Tokens via GCP KMS)" \
        auth_strat_choice

      if [ "$auth_strat_choice" = "2" ]; then
        prompt_read "GitHub App ID" github_app_id ""
        prompt_read "Cloud KMS Keyring Name" kms_keyring "github-token-minter-keyring"
        prompt_read "Cloud KMS Key Name" kms_key "github-token-minter-key"
        prompt_read "Path to downloaded GitHub App Private Key (.pem)" github_pem_path ""
      else
        local detected_token=""
        detected_token=$(gh auth token 2>/dev/null || echo "")
        prompt_read "GitHub Personal Access / OAuth Token (ghp_... / gho_...)" github_token "$detected_token" true
      fi
    fi
  fi

  # 9. Agent Permissions & Sandbox Isolation Boundary
  print_step "8. Agent Security & Runtime Isolation Boundary"
  local permission_set="${PARAM_PERMISSION_SET:-sre}"
  local read_only_mode="false"
  if [ "$permission_set" = "read-only" ]; then
    read_only_mode="true"
  fi

  local enable_gvisor="${PARAM_ENABLE_GVISOR:-false}"
  if [ "$PARAM_NON_INTERACTIVE" != "true" ]; then
    local perm_choice=""
    prompt_menu "Select Platform Agent Permission Boundary:" \
      "SRE GitOps & Remediations (Full read/write with GitOps PR submission)" \
      "Read-Only Audit & Observability (Read-only cluster inspection)" \
      perm_choice

    if [ "$perm_choice" = "2" ]; then
      permission_set="read-only"
      read_only_mode="true"
    fi

    local gvisor_choice=""
    prompt_menu "Enable GKE Sandbox (gVisor) Runtime Isolation for Agent Workloads?" \
      "No - Standard Container Runtime (Default)" \
      "Yes - gVisor Secure Kernel Sandbox (Hardened Workload Isolation)" \
      gvisor_choice

    if [ "$gvisor_choice" = "2" ]; then
      enable_gvisor="true"
    fi
  fi

  # 10. Repository Cloning & Execution Context
  print_step "9. Setting up Workspace Repository"
  local repo_dir=""
  if [ -f "k8s-operator/scripts/provision.sh" ]; then
    repo_dir="$(pwd)"
    print_success "Using current repository directory: $repo_dir"
  else
    repo_dir="$HOME/kube-agents"
    if [ -d "$repo_dir" ]; then
      print_info "Updating existing repository at $repo_dir..."
      cd "$repo_dir"
      git pull origin main || true
    else
      print_info "Cloning kube-agents repository into $repo_dir..."
      git clone https://github.com/gke-labs/kube-agents.git "$repo_dir"
      cd "$repo_dir"
    fi
  fi

  # 11. Generate Config Variables (vars.sh)
  print_step "10. Generating Configuration State (k8s-operator/scripts/vars.sh)"
  local vars_file="${repo_dir}/k8s-operator/scripts/vars.sh"
  
  cat << EOF > "$vars_file"
# Auto-generated by kube-agents zero-friction installer
export PROJECT_ID="${project_id}"
export PROJECT_NUMBER="${project_number}"
export CLUSTER_NAME="${cluster_name}"
export REGION="${region}"
export CLUSTER_TYPE="${cluster_type}"
export MACHINE_TYPE="${machine_type}"
export NUM_NODES="${num_nodes}"
export MIN_NODES="${min_nodes}"
export MAX_NODES="${max_nodes}"
export ENABLE_AUTOSCALING="${enable_autoscaling}"
export ENABLE_GVISOR="${enable_gvisor}"
export GVISOR_POOL_NAME="gvisor-pool"
export READ_ONLY_MODE="${read_only_mode}"
export MODEL_PROVIDER="${model_provider}"
export MODEL_DEFAULT_NAME="${model_default_name}"
export GEMINI_API_KEY="${gemini_api_key}"
export OPENAI_API_KEY="${openai_api_key}"
export ANTHROPIC_API_KEY="${anthropic_api_key}"
export ALLOWED_USERS="${allowed_users}"
export CHAT_TOPIC_NAME="${chat_topic_name}"
export CHAT_SUB_NAME="${chat_sub_name}"
export GOOGLE_CHAT_ENABLED="${google_chat_enabled}"
export SLACK_ENABLED="${slack_enabled}"
export SLACK_BOT_TOKEN="${slack_bot_token}"
export SLACK_APP_TOKEN="${slack_app_token}"
export SLACK_ALLOWED_USERS="${slack_allowed_users}"
export SLACK_HOME_CHANNEL="${slack_home_channel}"
export SLACK_HOME_CHANNEL_NAME="${slack_home_channel_name}"
export API_SERVER_KEY="$(openssl rand -hex 16 2>/dev/null || echo "a1b2c3d4e5f67890a1b2c3d4e5f67890")"
export PLATFORM_AGENT_PERMISSION_SET="${permission_set}"
export GITHUB_ORG="${github_org}"
export GITHUB_REPO="${github_repo}"
export GITHUB_APP_ID="${github_app_id}"
export KMS_KEYRING="${kms_keyring}"
export KMS_KEY="${kms_key}"
export GITHUB_PEM_PATH="${github_pem_path}"
export GITHUB_TOKEN="${github_token}"
export MEMORY_ENABLED="false"
export MEMORY_PROVIDER="multiuser_memory"
export USER_PROFILE_ENABLED="false"
export IMAGE_TAG="latest"
export REGISTRY_PREFIX="ghcr.io/gke-labs/kube-agents"
export NO_CONFIRM="1"
EOF
  chmod +x "$vars_file"
  print_success "Configuration saved to: $vars_file"

  # Pre-Flight Summary & Final Confirmation Checkpoint
  print_step "10. Pre-Flight Configuration Summary"
  echo -e "${C_CYAN}${C_BOLD}"
  draw_separator
  echo -e "${C_RESET}${C_BOLD}Please review your selections before provisioning begins:${C_RESET}"
  echo -e "  • ${C_CYAN}GCP Target Project:${C_RESET} ${C_BOLD}${project_id}${C_RESET} (Project Number: ${project_number:-unknown})"
  echo -e "  • ${C_CYAN}GKE Cluster:${C_RESET} ${C_BOLD}${cluster_name}${C_RESET} (${region}, type: ${cluster_type})"
  echo -e "  • ${C_CYAN}Node Machine Spec:${C_RESET} ${machine_type} (${min_nodes}-${max_nodes} nodes, autoscaling: ${enable_autoscaling})"
  echo -e "  • ${C_CYAN}gVisor Sandbox Isolation:${C_RESET} ${enable_gvisor}"
  echo -e "  • ${C_CYAN}AI Model Provider:${C_RESET} ${model_provider} (${model_default_name})"
  echo -e "  • ${C_CYAN}Permission Boundary:${C_RESET} ${permission_set}"
  if [ -n "$github_repo" ]; then
    echo -e "  • ${C_CYAN}GitOps Infrastructure Repo:${C_RESET} https://github.com/${github_org}/${github_repo}"
  fi
  echo -e "${C_CYAN}${C_BOLD}"
  draw_separator
  echo -e "${C_RESET}"

  if [ "$PARAM_DRY_RUN" = "true" ]; then
    print_success "Dry-run execution complete! Configuration generated without touching cloud resources."
    write_json_report "DRY_RUN_SUCCESS"
    exit 0
  fi

  if [ "$PARAM_NON_INTERACTIVE" != "true" ]; then
    local confirm_choice=""
    prompt_read "\nProceed with automated GKE cluster & Platform Agent provisioning? (Y/n)" confirm_choice "y"
    if [[ ! "$confirm_choice" =~ ^[Yy]$ ]]; then
      print_warning "Provisioning paused by user. Configuration saved to: $vars_file"
      print_info "To launch provisioning later, run: ${C_BOLD}cd k8s-operator && make gcp-provision${C_RESET}"
      write_json_report "PAUSED"
      exit 0
    fi
  fi

  # 12. Execute Automated Provisioning
  print_step "11. Launching Automated GKE Provisioning Pipeline"
  print_info "Provisioning GCP APIs, GKE Cluster, cert-manager, Operator, LiteLLM gateway, and Platform Agent..."
  print_info "Starting build..."

  cd "${repo_dir}/k8s-operator"
  if [ "$PARAM_NON_INTERACTIVE" = "true" ]; then
    make gcp-provision ARGS="-y" </dev/null >/dev/null 2>&1 || make gcp-provision ARGS="-y"
  else
    make gcp-provision ARGS="-y" </dev/tty >/dev/tty
  fi

  write_json_report "SUCCESS"

  # 13. Installation Summary & Next Steps
  print_step "🎉 Installation Complete!"
  echo -e "${C_GREEN}${C_BOLD}"
  echo '============================================================================='
  echo '🏆  Kubernetes Agentic Harness (kube-agents) is Live & Operational!'
  echo '============================================================================='
  echo -e "${C_RESET}"

  echo -e "${C_BOLD}Component Status Summary:${C_RESET}"
  echo -e "  • ${C_CYAN}GCP Project:${C_RESET} ${project_id} (Project Number: ${project_number})"
  echo -e "  • ${C_CYAN}GKE Cluster:${C_RESET} ${cluster_name} (${region})"
  echo -e "  • ${C_CYAN}Runtime Isolation:${C_RESET} ${enable_gvisor:-false} (gVisor Sandbox)"
  echo -e "  • ${C_CYAN}Model Provider:${C_RESET} ${model_provider} (${model_default_name})"
  echo -e "  • ${C_CYAN}Permission Mode:${C_RESET} ${permission_set}"
}

main "$@"
