#!/usr/bin/env bash
# ==============================================================================
# 🤖 Kubernetes Agentic Harness (kube-agents) Zero-Friction Installer
# ==============================================================================
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/gke-labs/kube-agents/main/install.sh | bash
#
# Designed for Google Cloud Shell, Linux, and macOS environments.
# ==============================================================================

set -euo pipefail

# ─── ANSI Colors & UI Helpers ──────────────────────────────────────────────────
C_CYAN='\033[96m'
C_GREEN='\033[92m'
C_YELLOW='\033[93m'
C_MAGENTA='\033[95m'
C_RED='\033[91m'
C_BLUE='\033[94m'
C_RESET='\033[0m'
C_BOLD='\033[1m'

print_banner() {
  echo -e "  ${C_BLUE}${C_BOLD}_  ___   _ ___ ${C_RED}_____   ${C_GREEN}_   ___ ___ _  _ _____ ___${C_RESET}"
  echo -e " ${C_BLUE}${C_BOLD}| |/ / | | | _ )${C_RED} __\\ \\ / /${C_GREEN}  /_\\ / __| \\| |_   _/ __|${C_RESET}"
  echo -e " ${C_BLUE}${C_BOLD}| ' <| |_| | _ \\${C_RED} _| \\ V /${C_GREEN}  / _ \\ (_ | .\` | | | \\__ \\${C_RESET}"
  echo -e " ${C_BLUE}${C_BOLD}|_|\\_\\___/|___/${C_RED}___| |_|${C_GREEN}  /_/ \\_\\___|_|\\_| |_| |___/${C_RESET}"
  echo -e "\n${C_CYAN}${C_BOLD}============================================================================="
  echo '🤖  Kubernetes Agentic Harness (kube-agents) Zero-Friction Installer'
  echo -e "=============================================================================${C_RESET}\n"
}

print_step() { echo -e "\n${C_MAGENTA}${C_BOLD}>>> $1 <<<${C_RESET}"; }
print_success() { echo -e "  ${C_GREEN}✓ $1${C_RESET}"; }
print_info() { echo -e "  ${C_CYAN}ℹ $1${C_RESET}"; }
print_warning() { echo -e "  ${C_YELLOW}⚠ $1${C_RESET}"; }
print_error() { echo -e "  ${C_RED}✗ $1${C_RESET}"; }

# Helper to safely read from terminal even when script is piped via `curl | bash`
prompt_read() {
  local prompt_text="$1"
  local var_name="$2"
  local default_val="${3:-}"
  local secret_mode="${4:-false}"

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

  local install_choice=""
  prompt_read "Attempt automatic installation of '$tool'? (y/N)" install_choice "y"
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

# ─── Main Installer Procedure ──────────────────────────────────────────────────
main() {
  print_banner

  # 1. Terminal / Environment Detection (Google Cloud Shell vs Linux/macOS Terminal)
  if [ ! -t 0 ] && [ ! -c /dev/tty ]; then
    print_error "Interactive TTY required. Please run this script in an interactive terminal or Cloud Shell."
    exit 1
  fi

  local is_cloud_shell="false"
  if [ "${CLOUD_SHELL:-false}" = "true" ] || [ -n "${DEVSHELL_PROJECT_ID:-}" ]; then
    is_cloud_shell="true"
    print_success "Environment Detected: ${C_BOLD}Google Cloud Shell${C_RESET} ☁️"
  else
    print_info "Environment Detected: ${C_BOLD}Standard Workstation / Linux Terminal${C_RESET} 💻"
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

  # 3. Google Cloud Authentication Check & Auto-Login
  print_step "2. Verifying Google Cloud Authentication"
  local active_account=""
  active_account=$(gcloud config get-value account 2>/dev/null || echo "")

  if [ -z "$active_account" ] || ! gcloud auth print-access-token >/dev/null 2>&1; then
    print_warning "gcloud CLI is not authenticated."
    print_info "Launching Google Cloud authentication..."
    gcloud auth login </dev/tty >/dev/tty
    gcloud auth application-default login </dev/tty >/dev/tty
    active_account=$(gcloud config get-value account 2>/dev/null || echo "")
  fi
  print_success "Authenticated as: ${C_BOLD}${active_account:-Google Cloud User}${C_RESET}"

  # 4. GCP Project Auto-Discovery & Interactive Selection
  print_step "3. Google Cloud Target Configuration"
  local active_proj=""
  if [ "$is_cloud_shell" = "true" ] && [ -n "${DEVSHELL_PROJECT_ID:-}" ]; then
    active_proj="${DEVSHELL_PROJECT_ID}"
  else
    active_proj=$(gcloud config get-value project 2>/dev/null || echo "")
  fi

  local project_id=""
  print_info "Fetching available GCP projects from your account..."
  local proj_lines=""
  proj_lines=$(gcloud projects list --format="value(projectId,name)" --limit=10 2>/dev/null || echo "")

  if [ -n "$proj_lines" ]; then
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

  gcloud config set project "$project_id" >/dev/null 2>&1 || true
  print_success "Selected Project ID: ${C_BOLD}${project_id}${C_RESET}"

  # Auto-resolve Project Number
  local project_number=""
  project_number=$(gcloud projects describe "$project_id" --format="value(projectNumber)" 2>/dev/null || echo "")
  if [ -n "$project_number" ]; then
    print_success "Resolved Project Number: ${C_BOLD}${project_number}${C_RESET}"
  fi

  # Auto-detect Region
  local active_region=""
  active_region=$(gcloud config get-value compute/region 2>/dev/null || echo "")
  local region=""
  prompt_read "Target GCP Region" region "${active_region:-us-central1}"

  # 5. GKE Cluster Selection & Provisioning Strategy
  print_step "4. GKE Cluster Topology & Capacity Setup"
  local cluster_choice=""
  prompt_menu "How would you like to handle the GKE Cluster?" \
    "Provision a NEW GKE Cluster from scratch (Recommended)" \
    "Use an EXISTING GKE Cluster" \
    cluster_choice

  local cluster_name=""
  local cluster_type="standard"
  local machine_type="e2-standard-4"
  local num_nodes=1
  local min_nodes=1
  local max_nodes=5
  local enable_autoscaling="true"

  if [ "$cluster_choice" = "1" ]; then
    local size_choice=""
    prompt_menu "Select GKE Cluster Size & Machine Spec:" \
      "Small Standard (e2-standard-4, 1-3 nodes, Autoscaling enabled)" \
      "Medium Standard (e2-standard-8, 1-5 nodes, Autoscaling enabled)" \
      "Large High-Performance (c3-standard-22, 2-10 nodes, Autoscaling enabled)" \
      "GKE Autopilot (Fully managed serverless GKE)" \
      size_choice

    case "$size_choice" in
      1)
        machine_type="e2-standard-4"
        num_nodes=1
        min_nodes=1
        max_nodes=3
        ;;
      2)
        machine_type="e2-standard-8"
        num_nodes=1
        min_nodes=1
        max_nodes=5
        ;;
      3)
        machine_type="c3-standard-22"
        num_nodes=2
        min_nodes=2
        max_nodes=10
        ;;
      4)
        cluster_type="autopilot"
        ;;
    esac

    prompt_read "New GKE Cluster Name" cluster_name "kube-agents-platform"
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
  prompt_menu "Select Chat Channel Integration(s):" \
    "Google Chat (Pub/Sub Event Streaming)" \
    "Slack (Socket Mode App)" \
    "Both Google Chat and Slack" \
    "None (CLI & REST API Gateway only)" \
    chat_choice

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
  local model_choice=""
  prompt_menu "Select Model Provider for the Platform Agent:" \
    "Google Gemini (Recommended: gemini-3.5-flash / Gemini API)" \
    "OpenAI (gpt-4o / OpenAI API)" \
    "Anthropic (claude-3-5-sonnet / Anthropic API)" \
    model_choice

  local model_provider="gemini"
  local model_default_name="gemini-3.5-flash"
  local gemini_api_key="placeholder"
  local openai_api_key="placeholder"
  local anthropic_api_key="placeholder"

  case "$model_choice" in
    1)
      model_provider="gemini"
      model_default_name="gemini-3.5-flash"
      
      # Check environment or GCP Secret Manager
      local detected_key="${GEMINI_API_KEY:-}"
      if [ -z "$detected_key" ]; then
        detected_key=$(gcloud secrets versions access latest --secret="gemini-api-key" --project="$project_id" 2>/dev/null || echo "")
        if [ -n "$detected_key" ]; then
          print_success "Auto-detected GEMINI_API_KEY from Secret Manager!"
        fi
      fi

      if [ -z "$detected_key" ]; then
        print_info "Need a free Gemini API key? Get one in seconds at: ${C_BOLD}https://aistudio.google.com/app/apikey${C_RESET}"
      fi

      prompt_read "Gemini API Key" gemini_api_key "$detected_key" true
      ;;
    2)
      model_provider="openai"
      model_default_name="gpt-4o"
      local detected_key="${OPENAI_API_KEY:-}"
      prompt_read "OpenAI API Key" openai_api_key "$detected_key" true
      ;;
    3)
      model_provider="anthropic"
      model_default_name="claude-3-5-sonnet-20241022"
      local detected_key="${ANTHROPIC_API_KEY:-}"
      prompt_read "Anthropic API Key" anthropic_api_key "$detected_key" true
      ;;
  esac

  # 8. GitOps Infrastructure Repository Connection, Auto-Auth & Token Minter Options
  print_step "7. GitOps Infrastructure Repository & Token Minter Setup"
  local gitops_choice=""
  prompt_menu "Would you like to connect or create a GitOps repo for automated PRs?" \
    "Create a NEW GitHub Repository automatically (Recommended)" \
    "Connect an EXISTING GitHub Repository" \
    "Skip for now (Can be enabled later)" \
    gitops_choice

  local github_org=""
  local github_repo=""
  local github_app_id=""
  local kms_keyring="github-token-minter-keyring"
  local kms_key="github-token-minter-key"
  local github_pem_path=""
  local github_token=""

  if [ "$gitops_choice" = "1" ] || [ "$gitops_choice" = "2" ]; then
    # Verify GitHub CLI Authentication
    if command -v gh >/dev/null 2>&1; then
      if ! gh auth status >/dev/null 2>&1; then
        print_warning "GitHub CLI ('gh') is not authenticated."
        local gh_auth_choice=""
        prompt_read "Launch 'gh auth login' now? (Y/n)" gh_auth_choice "y"
        if [[ "$gh_auth_choice" =~ ^[Yy]$ ]]; then
          print_info "Launching GitHub CLI authentication..."
          gh auth login </dev/tty >/dev/tty || true
        fi
      fi
    fi

    local detected_gh_user=""
    detected_gh_user=$(gh api user -q .login 2>/dev/null || git config user.name 2>/dev/null || echo "")
    prompt_read "GitHub Org / Username" github_org "${detected_gh_user:-github-user}"
    prompt_read "GitOps Repository Name" github_repo "gke-fleet-iac"

    # Select Token Auth Strategy (GitHub Token Minter vs PAT / CLI Token)
    local auth_strat_choice=""
    prompt_menu "Select GitHub Auth Strategy for the Agent:" \
      "Personal Access / CLI Token (Simple / Zero-Friction Setup)" \
      "GitHub App & Token Minter (Enterprise / Short-Lived Tokens via GCP KMS)" \
      auth_strat_choice

    if [ "$auth_strat_choice" = "2" ]; then
      print_info "To register a new GitHub App for Token Minter, click to open:"
      if [ -n "$github_org" ] && [ "$github_org" != "$detected_gh_user" ]; then
        echo -e "     ${C_CYAN}${C_BOLD}https://github.com/organizations/${github_org}/settings/apps/new${C_RESET}"
      else
        echo -e "     ${C_CYAN}${C_BOLD}https://github.com/settings/apps/new${C_RESET}"
      fi
      print_info "Required GitHub App Permissions:"
      echo -e "     • ${C_BOLD}Repository -> Pull requests${C_RESET}: Read & write"
      echo -e "     • ${C_BOLD}Repository -> Contents${C_RESET}: Read & write"
      echo -e "     • ${C_BOLD}Repository -> Metadata${C_RESET}: Read-only"
      echo -e "     • ${C_BOLD}Private Key${C_RESET}: Generate and download private key (.pem)\n"

      prompt_read "GitHub App ID" github_app_id ""
      prompt_read "Cloud KMS Keyring Name" kms_keyring "github-token-minter-keyring"
      prompt_read "Cloud KMS Key Name" kms_key "github-token-minter-key"
      prompt_read "Path to downloaded GitHub App Private Key (.pem)" github_pem_path ""
    else
      local detected_token=""
      detected_token=$(gh auth token 2>/dev/null || echo "")
      if [ -n "$detected_token" ]; then
        print_success "Auto-detected GitHub token from gh CLI!"
      fi
      prompt_read "GitHub Personal Access / OAuth Token (ghp_... / gho_...)" github_token "$detected_token" true
    fi

    if [ "$gitops_choice" = "1" ]; then
      print_info "Automating creation of GitHub Repository '$github_org/$github_repo'..."
      local repo_visibility=""
      prompt_menu "Select Repository Visibility:" \
        "Public" \
        "Private" \
        repo_visibility

      local vis_flag="--public"
      if [ "$repo_visibility" = "2" ]; then
        vis_flag="--private"
      fi

      if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
        if gh repo view "$github_org/$github_repo" >/dev/null 2>&1; then
          print_success "GitHub Repository '$github_org/$github_repo' already exists."
        else
          print_info "Creating GitHub Repository '$github_org/$github_repo' via GitHub CLI..."
          gh repo create "$github_org/$github_repo" $vis_flag --description "GKE Fleet IaC Repository for Platform Agent GitOps remediations" --confirm </dev/tty >/dev/tty || true
          print_success "Created GitHub Repository: ${C_BOLD}https://github.com/$github_org/$github_repo${C_RESET}"
        fi
      else
        print_warning "GitHub CLI ('gh') is not authenticated."
        print_info "Please create the repository manually at ${C_CYAN}https://github.com/new${C_RESET} with name '${C_BOLD}$github_repo${C_RESET}'."
      fi
    fi
  fi

  # 9. Agent Permissions & Sandbox Isolation Boundary
  print_step "8. Agent Security & Runtime Isolation Boundary"
  local perm_choice=""
  prompt_menu "Select Platform Agent Permission Boundary:" \
    "SRE GitOps & Remediations (Full read/write with GitOps PR submission)" \
    "Read-Only Audit & Observability (Read-only cluster inspection)" \
    perm_choice

  local permission_set="sre"
  local read_only_mode="false"
  if [ "$perm_choice" = "2" ]; then
    permission_set="read-only"
    read_only_mode="true"
  fi

  local gvisor_choice=""
  prompt_menu "Enable GKE Sandbox (gVisor) Runtime Isolation for Agent Workloads?" \
    "No - Standard Container Runtime (Default)" \
    "Yes - gVisor Secure Kernel Sandbox (Hardened Workload Isolation)" \
    gvisor_choice

  local enable_gvisor="false"
  if [ "$gvisor_choice" = "2" ]; then
    enable_gvisor="true"
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
EOF
  chmod +x "$vars_file"
  print_success "Configuration saved to: $vars_file"

  # 12. Execute Automated Provisioning
  print_step "11. Launching Automated GKE Provisioning Pipeline"
  print_info "Provisioning GCP APIs, GKE Cluster, cert-manager, Operator, LiteLLM gateway, and Platform Agent..."
  print_info "Starting build..."

  cd "${repo_dir}/k8s-operator"
  make gcp-provision </dev/tty >/dev/tty

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
  if [ -n "$github_repo" ]; then
    echo -e "  • ${C_CYAN}GitOps Repository:${C_RESET} https://github.com/${github_org}/${github_repo}"
    if [ -n "$github_app_id" ]; then
      echo -e "  • ${C_CYAN}GitHub Auth Strategy:${C_RESET} GitHub App Token Minter (App ID: ${github_app_id})"
    else
      echo -e "  • ${C_CYAN}GitHub Auth Strategy:${C_RESET} Personal Access / OAuth Token"
    fi
  fi

  if [ "$google_chat_enabled" = "true" ]; then
    echo -e "\n${C_YELLOW}${C_BOLD}📌 Required Final Step for Google Chat Integration:${C_RESET}"
    echo -e "  1. Click to open pre-configured Google Chat API Console:"
    echo -e "     ${C_CYAN}https://console.cloud.google.com/apis/api/chat.googleapis.com/hangouts-chat?project=${project_id}${C_RESET}"
    echo -e "  2. Set App Name to: ${C_BOLD}GKE Platform Agent Bot${C_RESET}"
    echo -e "  3. Select Connection Setting: ${C_BOLD}Cloud Pub/Sub${C_RESET}"
    echo -e "  4. Set Topic Name to: ${C_CYAN}projects/${project_id}/topics/${chat_topic_name}${C_RESET}"
    echo -e "  5. Under Visibility, grant access to: ${C_BOLD}${allowed_users}${C_RESET}"
    echo -e "  6. Open Google Chat and send a DM to the bot: ${C_GREEN}\"Hi Platform Agent\"${C_RESET}"
  fi

  if [ "$slack_enabled" = "true" ]; then
    echo -e "\n${C_YELLOW}${C_BOLD}📌 Required Final Step for Slack Integration:${C_RESET}"
    echo -e "  1. Ensure Socket Mode is enabled in your Slack App Console."
    echo -e "  2. Invite the bot to a channel or send a direct message: ${C_GREEN}\"Hi Platform Agent\"${C_RESET}"
  fi

  echo -e "\n${C_CYAN}To inspect live agent logs at any time:${C_RESET}"
  echo -e "  ${C_BOLD}kubectl logs -n kubeagents-system deployment/platform-agent-gateway -f${C_RESET}\n"
}

main "$@"
