#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Claw Boutique end-to-end deployment orchestration
# =============================================================================
#
# Runs every step needed to go from a fresh checkout to a fully operational
# ClawBot instance: CDK stack, Secrets Manager, RDS/MySQL, database seed,
# Lambda zip, OpenClaw configuration on Lightsail, and final validation.
#
# Usage:
#   ./scripts/deploy.sh \
#     --region ap-southeast-1 \
#     --stack-name ClawBoutiqueStack \
#     --openclw-instance-ip 1.2.3.4 \
#     --openclw-instance-user ec2-user
#
# All other values are read from the .env file in the repo root.
# Copy .env.example to .env and fill in real values before running.
#
# Exit codes:
#   0  — deployment complete
#   1  — prerequisite check failed or step failed (message printed to stderr)
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Colour helpers (disabled automatically when not a TTY)
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
    CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; CYAN=''; BOLD=''; RESET=''
fi

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[ OK ]${RESET}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERR ]${RESET}  $*" >&2; }
die()     { error "$*"; exit 1; }
step()    { echo -e "\n${BOLD}━━━  Step $*  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"; }
banner()  { echo -e "\n${BOLD}${CYAN}$*${RESET}"; }

# ---------------------------------------------------------------------------
# Resolve repo root relative to this script
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ---------------------------------------------------------------------------
# Parse CLI arguments
# ---------------------------------------------------------------------------
REGION=""
STACK_NAME=""
OPENCLW_IP=""
OPENCLW_USER=""

usage() {
    echo "Usage: $0 --region <region> --stack-name <name> --openclw-instance-ip <ip> --openclw-instance-user <user>"
    echo ""
    echo "  --region               AWS region to deploy into (e.g. ap-southeast-1)"
    echo "  --stack-name           CDK stack name (e.g. ClawBoutiqueStack)"
    echo "  --openclw-instance-ip  Public IP of the Lightsail instance running OpenClaw"
    echo "  --openclw-instance-user SSH username for the Lightsail instance (e.g. ec2-user)"
    echo ""
    echo "All other config is read from \$REPO_ROOT/.env — copy .env.example first."
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --region)               REGION="$2";       shift 2 ;;
        --stack-name)           STACK_NAME="$2";   shift 2 ;;
        --openclw-instance-ip)  OPENCLW_IP="$2";   shift 2 ;;
        --openclw-instance-user) OPENCLW_USER="$2"; shift 2 ;;
        -h|--help)              usage ;;
        *)  die "Unknown argument: $1. Run with --help for usage." ;;
    esac
done

[[ -n "$REGION"      ]] || die "--region is required. Run with --help."
[[ -n "$STACK_NAME"  ]] || die "--stack-name is required. Run with --help."
[[ -n "$OPENCLW_IP"  ]] || die "--openclw-instance-ip is required. Run with --help."
[[ -n "$OPENCLW_USER" ]] || die "--openclw-instance-user is required. Run with --help."

# ---------------------------------------------------------------------------
# Load .env file
# ---------------------------------------------------------------------------
ENV_FILE="${REPO_ROOT}/.env"
ENV_EXAMPLE="${REPO_ROOT}/.env.example"

if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -f "$ENV_EXAMPLE" ]]; then
        die ".env not found at ${ENV_FILE}. Copy .env.example: cp .env.example .env and fill in your values."
    else
        die ".env not found at ${ENV_FILE} and no .env.example present. Cannot continue."
    fi
fi

set -o allexport
# shellcheck source=/dev/null
source "$ENV_FILE"
set +o allexport

# CLI args override .env values
REGION="${REGION}"
STACK_NAME="${STACK_NAME}"
LIGHTSAIL_INSTANCE_IP="${OPENCLW_IP}"
LIGHTSAIL_INSTANCE_USER="${OPENCLW_USER}"

# Derived paths
CDK_DIR="${REPO_ROOT}/cdk"
LAMBDA_DIR="${REPO_ROOT}/lambda/dispatcher"
OPENCLAW_DIR="${REPO_ROOT}/openclaw"
SCRIPTS_DIR="${REPO_ROOT}/scripts"
OUTPUTS_FILE="${REPO_ROOT}/.cdk-outputs.json"

# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------
START_TIME=$(date +%s)

banner "╔══════════════════════════════════════════════════════════════╗"
banner "║           Claw Boutique — Deployment Orchestrator            ║"
banner "╚══════════════════════════════════════════════════════════════╝"
echo ""
info "Region        : ${REGION}"
info "Stack name    : ${STACK_NAME}"
info "Lightsail IP  : ${LIGHTSAIL_INSTANCE_IP}"
info "SSH user      : ${LIGHTSAIL_INSTANCE_USER}"
info "Repo root     : ${REPO_ROOT}"
echo ""

# =============================================================================
# STEP 1 — Validate prerequisites
# =============================================================================
step "1 of 11 — Validate prerequisites"

REQUIRED_TOOLS=(aws node python3 mysql)
MISSING_TOOLS=()
for tool in "${REQUIRED_TOOLS[@]}"; do
    if command -v "$tool" &>/dev/null; then
        success "'${tool}' found ($(command -v "$tool"))"
    else
        MISSING_TOOLS+=("$tool")
    fi
done

# CDK CLI — accept both 'cdk' and 'npx cdk'
if command -v cdk &>/dev/null; then
    CDK_CMD="cdk"
    success "'cdk' found ($(command -v cdk))"
elif command -v npx &>/dev/null && npx --yes cdk --version &>/dev/null 2>&1; then
    CDK_CMD="npx cdk"
    success "'cdk' available via npx"
else
    MISSING_TOOLS+=("cdk (install with: npm install -g aws-cdk)")
fi

if [[ ${#MISSING_TOOLS[@]} -gt 0 ]]; then
    error "The following required tools are missing:"
    for t in "${MISSING_TOOLS[@]}"; do
        error "  - ${t}"
    done
    die "Install the missing tools and re-run deploy.sh."
fi

# Verify AWS credentials
info "Checking AWS credentials..."
CALLER_ACCOUNT=$(aws sts get-caller-identity --region "${REGION}" --query 'Account' --output text 2>/dev/null) \
    || die "AWS credentials are not configured or have expired. Run: aws configure"
success "AWS caller identity verified (account: ${CALLER_ACCOUNT})"

# Verify .env required variables
REQUIRED_VARS=(DB_HOST DB_USER DB_PASSWORD DB_NAME
               WHATSAPP_PHONE_NUMBER_ID
               SELLER_PHONE SELLER_EMAIL
               SES_FROM_EMAIL)
ENV_ERRORS=()
for var in "${REQUIRED_VARS[@]}"; do
    val="${!var:-}"
    if [[ -z "$val" || "$val" == *"placeholder"* || "$val" == *"your_"* ]]; then
        ENV_ERRORS+=("$var")
    fi
done

if [[ ${#ENV_ERRORS[@]} -gt 0 ]]; then
    error "The following variables in .env are missing or still have placeholder values:"
    for v in "${ENV_ERRORS[@]}"; do
        error "  - ${v}"
    done
    die "Edit ${ENV_FILE} and fill in all real values, then re-run."
fi

success "All prerequisite checks passed"

# =============================================================================
# STEP 2 — Build and deploy CDK stack
# =============================================================================
step "2 of 11 — Deploy CDK stack (${STACK_NAME})"

info "Installing CDK dependencies..."
(cd "${CDK_DIR}" && npm install --silent) \
    || die "npm install failed in ${CDK_DIR}"

info "Building CDK TypeScript..."
(cd "${CDK_DIR}" && npm run build) \
    || die "CDK TypeScript build failed. Check for compile errors above."

info "Building Lambda dispatcher..."
(cd "${LAMBDA_DIR}" && npm install --silent && npm run build) \
    || die "Lambda dispatcher build failed in ${LAMBDA_DIR}"

info "Running: cdk deploy --require-approval never (this may take 3–5 minutes)..."
(cd "${CDK_DIR}" && ${CDK_CMD} deploy "${STACK_NAME}" \
    --require-approval never \
    --region "${REGION}" \
    --outputs-file "${OUTPUTS_FILE}") \
    || die "CDK deploy failed. Review CloudFormation events in the AWS console."

success "CDK stack deployed successfully"

# =============================================================================
# STEP 3 — Capture stack outputs
# =============================================================================
step "3 of 11 — Capture stack outputs to ${OUTPUTS_FILE}"

[[ -f "${OUTPUTS_FILE}" ]] \
    || die "Expected CDK outputs file not found at ${OUTPUTS_FILE}. The deploy may have partially failed."

# Parse key outputs
SNS_TOPIC_ARN=$(python3 -c "
import json, sys
data = json.load(open('${OUTPUTS_FILE}'))
stack = data.get('${STACK_NAME}', {})
for k, v in stack.items():
    if 'InboundTopicArn' in k:
        print(v); sys.exit(0)
print(''); sys.exit(0)
")

DISPATCHER_FN=$(python3 -c "
import json, sys
data = json.load(open('${OUTPUTS_FILE}'))
stack = data.get('${STACK_NAME}', {})
for k, v in stack.items():
    if 'DispatcherFunctionName' in k:
        print(v); sys.exit(0)
print('ClawBoutiqueDispatcher'); sys.exit(0)
")

LIGHTSAIL_ROLE_ARN=$(python3 -c "
import json, sys
data = json.load(open('${OUTPUTS_FILE}'))
stack = data.get('${STACK_NAME}', {})
for k, v in stack.items():
    if 'LightsailRoleArn' in k:
        print(v); sys.exit(0)
print(''); sys.exit(0)
")

DB_SECRET_ARN=$(python3 -c "
import json, sys
data = json.load(open('${OUTPUTS_FILE}'))
stack = data.get('${STACK_NAME}', {})
for k, v in stack.items():
    if 'DbCredentialsSecretArn' in k:
        print(v); sys.exit(0)
print(''); sys.exit(0)
")

info "SNS Topic ARN       : ${SNS_TOPIC_ARN:-<not found>}"
info "Dispatcher function : ${DISPATCHER_FN:-<not found>}"
info "Lightsail role ARN  : ${LIGHTSAIL_ROLE_ARN:-<not found>}"
info "DB secret ARN       : ${DB_SECRET_ARN:-<not found>}"
success "Stack outputs captured"

# =============================================================================
# STEP 4 — Create / update Secrets Manager secret with DB credentials
# =============================================================================
step "4 of 11 — Upsert Secrets Manager secret (ClawBoutique/DbCredentials)"

SECRET_NAME="ClawBoutique/DbCredentials"
SECRET_VALUE=$(python3 -c "import json; print(json.dumps({
    'host':     '${DB_HOST}',
    'port':     '${DB_PORT:-3306}',
    'dbname':   '${DB_NAME}',
    'username': '${DB_USER}',
    'password': '${DB_PASSWORD}'
}))")

# Check if the secret already exists
if aws secretsmanager describe-secret \
        --secret-id "${SECRET_NAME}" \
        --region "${REGION}" &>/dev/null 2>&1; then
    info "Secret '${SECRET_NAME}' already exists — updating value..."
    aws secretsmanager put-secret-value \
        --secret-id "${SECRET_NAME}" \
        --secret-string "${SECRET_VALUE}" \
        --region "${REGION}" \
        --output text --query 'ARN' > /dev/null \
        || die "Failed to update secret '${SECRET_NAME}'. Check IAM permissions."
    success "Secret updated with current DB credentials"
else
    info "Secret '${SECRET_NAME}' not found — creating..."
    aws secretsmanager create-secret \
        --name "${SECRET_NAME}" \
        --description "Database credentials for Claw Boutique OpenClaw application" \
        --secret-string "${SECRET_VALUE}" \
        --region "${REGION}" \
        --output text --query 'ARN' > /dev/null \
        || die "Failed to create secret '${SECRET_NAME}'. Check IAM permissions."
    success "Secret created successfully"
fi

# =============================================================================
# STEP 5 — Create MySQL database if it does not exist
# =============================================================================
step "5 of 11 — Ensure MySQL database '${DB_NAME}' exists and schema is applied"

info "Testing database connectivity to ${DB_HOST}:${DB_PORT:-3306}..."
mysql \
    --host="${DB_HOST}" \
    --port="${DB_PORT:-3306}" \
    --user="${DB_USER}" \
    --password="${DB_PASSWORD}" \
    --connect-timeout=15 \
    --execute="SELECT 1" &>/dev/null \
    || die "Cannot connect to MySQL at ${DB_HOST}:${DB_PORT:-3306}. Check DB_HOST, DB_PORT, DB_USER, DB_PASSWORD."

success "MySQL connection OK"

info "Creating database '${DB_NAME}' if it does not exist..."
mysql \
    --host="${DB_HOST}" \
    --port="${DB_PORT:-3306}" \
    --user="${DB_USER}" \
    --password="${DB_PASSWORD}" \
    --connect-timeout=15 \
    --execute="CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" \
    || die "Failed to create database '${DB_NAME}'."

success "Database '${DB_NAME}' is ready"

info "Applying schema (${SCRIPTS_DIR}/schema.sql)..."
mysql \
    --host="${DB_HOST}" \
    --port="${DB_PORT:-3306}" \
    --user="${DB_USER}" \
    --password="${DB_PASSWORD}" \
    --connect-timeout=15 \
    "${DB_NAME}" < "${SCRIPTS_DIR}/schema.sql" \
    || die "schema.sql failed. Check the error above."

success "Schema applied (idempotent — IF NOT EXISTS used throughout)"

# =============================================================================
# STEP 6 — Seed the database catalog
# =============================================================================
step "6 of 11 — Seed product catalog (seed_catalog.py)"

info "Running seed_catalog.py — safe to re-run (INSERT IGNORE)..."
export DB_HOST DB_PORT DB_USER DB_PASSWORD DB_NAME
python3 "${SCRIPTS_DIR}/seed_catalog.py" \
    || die "seed_catalog.py failed. Check DB credentials and table schema."

success "Catalog seeded (20 products, 3 test customers)"

# =============================================================================
# STEP 7 — Build Lambda zip and print console instruction
# =============================================================================
step "7 of 11 — Package Lambda dispatcher"

LAMBDA_DIST="${LAMBDA_DIR}/dist"
LAMBDA_ZIP="${LAMBDA_DIR}/claw-boutique-dispatcher.zip"

info "Building dispatcher bundle..."
(cd "${LAMBDA_DIR}" && npm run build) \
    || die "Lambda dispatcher build failed."

info "Creating deployment zip: ${LAMBDA_ZIP}"
(cd "${LAMBDA_DIST}" && zip -r "${LAMBDA_ZIP}" . -x "*.map") \
    || die "zip command failed. Ensure 'zip' is installed."

success "Lambda zip created: ${LAMBDA_ZIP}"

echo ""
echo -e "${YELLOW}  Console step required:${RESET}"
echo "  If you are updating an existing Lambda function, the CDK deploy above"
echo "  already uploaded the compiled asset. If you deployed with the inline"
echo "  placeholder code, update the function code via the console or CLI:"
echo ""
echo -e "  ${BOLD}Option A — AWS CLI:${RESET}"
echo "    aws lambda update-function-code \\"
echo "      --function-name ${DISPATCHER_FN:-ClawBoutiqueDispatcher} \\"
echo "      --zip-file fileb://${LAMBDA_ZIP} \\"
echo "      --region ${REGION}"
echo ""
echo -e "  ${BOLD}Option B — Console:${RESET}"
echo "    1. Open Lambda > Functions > ${DISPATCHER_FN:-ClawBoutiqueDispatcher}"
echo "    2. Click 'Upload from' > '.zip file'"
echo "    3. Upload: ${LAMBDA_ZIP}"
echo ""

# =============================================================================
# STEP 8 — Copy openclaw/ directory to Lightsail instance
# =============================================================================
step "8 of 11 — Copy openclaw/ to Lightsail (${LIGHTSAIL_INSTANCE_IP})"

SSH_KEY_ARGS=""
if [[ -n "${LIGHTSAIL_SSH_KEY_PATH:-}" && -f "${LIGHTSAIL_SSH_KEY_PATH}" ]]; then
    SSH_KEY_ARGS="-i ${LIGHTSAIL_SSH_KEY_PATH}"
    info "Using SSH key: ${LIGHTSAIL_SSH_KEY_PATH}"
else
    warn "LIGHTSAIL_SSH_KEY_PATH not set or file not found — using default SSH key (~/.ssh/id_rsa)"
fi

SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=15 ${SSH_KEY_ARGS}"

info "Testing SSH connectivity to ${LIGHTSAIL_INSTANCE_USER}@${LIGHTSAIL_INSTANCE_IP}..."
# shellcheck disable=SC2086
ssh ${SSH_OPTS} \
    "${LIGHTSAIL_INSTANCE_USER}@${LIGHTSAIL_INSTANCE_IP}" \
    "echo ssh_ok" \
    || die "SSH connection to ${LIGHTSAIL_INSTANCE_USER}@${LIGHTSAIL_INSTANCE_IP} failed. Check the IP, user, and SSH key."

info "Copying openclaw/ directory to remote ~/openclaw/ ..."
# shellcheck disable=SC2086
scp ${SSH_OPTS} -r \
    "${OPENCLAW_DIR}/" \
    "${LIGHTSAIL_INSTANCE_USER}@${LIGHTSAIL_INSTANCE_IP}:~/openclaw/" \
    || die "scp failed. Check SSH key permissions and available disk space on the instance."

success "openclaw/ copied to ${LIGHTSAIL_INSTANCE_IP}:~/openclaw/"

# =============================================================================
# STEP 9 — SSH to Lightsail: write .env and run openclaw config setup
# =============================================================================
step "9 of 11 — Configure OpenClaw on Lightsail"

info "Writing environment variables to remote ~/.env and configuring OpenClaw..."

# shellcheck disable=SC2086
ssh ${SSH_OPTS} \
    "${LIGHTSAIL_INSTANCE_USER}@${LIGHTSAIL_INSTANCE_IP}" \
    "bash -s" << REMOTE_SCRIPT
set -euo pipefail

# Write environment file on the remote instance
cat > ~/.env << 'ENVEOF'
# Claw Boutique — OpenClaw instance environment
# Generated by deploy.sh on $(date -u '+%Y-%m-%dT%H:%M:%SZ')

AWS_REGION=${REGION}

# Database
DB_HOST=${DB_HOST}
DB_PORT=${DB_PORT:-3306}
DB_USER=${DB_USER}
DB_PASSWORD=${DB_PASSWORD}
DB_NAME=${DB_NAME}

# WhatsApp (AWS End User Messaging Social)
WHATSAPP_PHONE_NUMBER_ID=${WHATSAPP_PHONE_NUMBER_ID}
WHATSAPP_WABA_ID=${WHATSAPP_WABA_ID:-}

# Seller info
SELLER_PHONE=${SELLER_PHONE}
SELLER_EMAIL=${SELLER_EMAIL}
SELLER_NAME=${SELLER_NAME:-"Store Owner"}

# SES
SES_FROM_EMAIL=${SES_FROM_EMAIL}
SES_FROM_NAME=${SES_FROM_NAME:-"Claw Boutique"}

# OpenClaw Gateway
OPENCLAW_GATEWAY_TOKEN=${OPENCLAW_GATEWAY_TOKEN:-"$(openssl rand -hex 32 2>/dev/null || echo 'REPLACE_WITH_SECURE_TOKEN')"}

# IAM role for Secrets Manager access
LIGHTSAIL_ROLE_ARN=${LIGHTSAIL_ROLE_ARN:-}
ENVEOF

chmod 600 ~/.env
echo "[remote] .env written (600)"

# Ensure openclaw config directory is in place
if [ -d ~/openclaw ]; then
    echo "[remote] openclaw directory found at ~/openclaw"
    ls ~/openclaw/
else
    echo "[remote] ERROR: ~/openclaw directory not found after scp"
    exit 1
fi

# Set up the AWS profile for Secrets Manager access if role ARN is set
if [ -n "${LIGHTSAIL_ROLE_ARN:-}" ]; then
    mkdir -p ~/.aws
    if ! grep -q 'clawboutique' ~/.aws/config 2>/dev/null; then
        cat >> ~/.aws/config << AWSEOF

[profile clawboutique]
role_arn = ${LIGHTSAIL_ROLE_ARN}
source_profile = default
region = ${REGION}
AWSEOF
        echo "[remote] AWS profile 'clawboutique' added to ~/.aws/config"
    else
        echo "[remote] AWS profile 'clawboutique' already present in ~/.aws/config"
    fi
fi

echo "[remote] OpenClaw environment configured"
REMOTE_SCRIPT

success "OpenClaw environment configured on Lightsail instance"

# =============================================================================
# STEP 9b — Apply schema additions (new tables for admin, reviews, stock, etc.)
# =============================================================================
step "9b of 13 — Apply schema additions"

if [[ -f "${SCRIPTS_DIR}/schema_additions.sql" ]]; then
    info "Applying schema additions (admin_actions, interaction_memory, reviews, abandoned_carts)..."
    mysql \
        --host="${DB_HOST}" \
        --port="${DB_PORT:-3306}" \
        --user="${DB_USER}" \
        --password="${DB_PASSWORD}" \
        --connect-timeout=15 \
        "${DB_NAME}" < "${SCRIPTS_DIR}/schema_additions.sql" \
        || warn "schema_additions.sql had errors (may be OK if tables already exist)"
    success "Schema additions applied"
else
    warn "schema_additions.sql not found — skipping"
fi

# =============================================================================
# STEP 10 — Copy web server and install dependencies on Lightsail
# =============================================================================
step "10 of 13 — Deploy web server to Lightsail"

WEB_DIR="${REPO_ROOT}/web"

info "Copying web/ directory to remote ~/web/ ..."
# shellcheck disable=SC2086
scp ${SSH_OPTS} -r \
    "${WEB_DIR}/" \
    "${LIGHTSAIL_INSTANCE_USER}@${LIGHTSAIL_INSTANCE_IP}:~/web/" \
    || die "Failed to copy web/ to Lightsail"

info "Installing Python dependencies and setting up web server..."
# shellcheck disable=SC2086
ssh ${SSH_OPTS} \
    "${LIGHTSAIL_INSTANCE_USER}@${LIGHTSAIL_INSTANCE_IP}" \
    "bash -s" << 'WEB_SETUP'
set -euo pipefail

# Install pip if missing
if ! command -v pip3 &>/dev/null; then
    sudo apt-get update -qq && sudo apt-get install -y -qq python3-pip 2>/dev/null \
    || sudo yum install -y python3-pip 2>/dev/null \
    || echo "[remote] pip3 may already be installed"
fi

# Install web server dependencies
cd ~/web
pip3 install -r requirements.txt --quiet 2>/dev/null || pip3 install -r requirements.txt

# Create a systemd service for the web server
sudo tee /etc/systemd/system/claw-boutique-web.service > /dev/null << 'SVCEOF'
[Unit]
Description=Claw Boutique Web Server
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=/home/$USER/web
EnvironmentFile=/home/$USER/.env
ExecStart=/usr/bin/python3 /home/$USER/web/server.py
Restart=always
RestartSec=5
Environment=PORT=8080

[Install]
WantedBy=multi-user.target
SVCEOF

# Fix the User field in the service file
sudo sed -i "s/User=\$USER/User=$(whoami)/" /etc/systemd/system/claw-boutique-web.service
sudo sed -i "s|/home/\$USER|/home/$(whoami)|g" /etc/systemd/system/claw-boutique-web.service

sudo systemctl daemon-reload
sudo systemctl enable claw-boutique-web
sudo systemctl restart claw-boutique-web

echo "[remote] Web server installed and started on port 8080"
WEB_SETUP

success "Web server deployed and running on port 8080"

# =============================================================================
# STEP 11 — Validate WABA is linked to SNS topic
# =============================================================================
step "11 of 13 — Validate End User Messaging Social WABA linked to SNS"

if [[ -n "${SNS_TOPIC_ARN}" ]]; then
    info "Checking SNS topic exists and has EUM Social publish permission..."

    TOPIC_EXISTS=$(aws sns get-topic-attributes \
        --topic-arn "${SNS_TOPIC_ARN}" \
        --region "${REGION}" \
        --query 'Attributes.TopicArn' \
        --output text 2>/dev/null || echo "NOT_FOUND")

    if [[ "${TOPIC_EXISTS}" == "${SNS_TOPIC_ARN}" ]]; then
        success "SNS topic exists: ${SNS_TOPIC_ARN}"
    else
        warn "SNS topic not found at expected ARN. The CDK deploy may not have completed."
    fi

    # Check Lambda subscription
    LAMBDA_SUB=$(aws sns list-subscriptions-by-topic \
        --topic-arn "${SNS_TOPIC_ARN}" \
        --region "${REGION}" \
        --query "Subscriptions[?Protocol=='lambda'].Endpoint" \
        --output text 2>/dev/null || echo "")

    if [[ -n "${LAMBDA_SUB}" ]]; then
        success "Lambda is subscribed to SNS topic"
        info "  Subscribed Lambda ARN: ${LAMBDA_SUB}"
    else
        warn "No Lambda subscription found on the SNS topic."
        warn "The CDK deploy subscribes the Lambda automatically — check CloudFormation status."
    fi

    # Check topic policy includes social-messaging.amazonaws.com
    TOPIC_POLICY=$(aws sns get-topic-attributes \
        --topic-arn "${SNS_TOPIC_ARN}" \
        --region "${REGION}" \
        --query 'Attributes.Policy' \
        --output text 2>/dev/null || echo "")

    if echo "${TOPIC_POLICY}" | grep -q "social-messaging.amazonaws.com"; then
        success "SNS topic policy includes social-messaging.amazonaws.com publish permission"
    else
        warn "social-messaging.amazonaws.com not found in SNS topic policy."
        warn "The CDK stack should have added this. Check claw-boutique-stack.ts."
    fi

    echo ""
    echo -e "${YELLOW}  Manual step required:${RESET}"
    echo "  Link your WhatsApp Business Account phone number to this SNS topic"
    echo "  in the AWS End User Messaging Social console:"
    echo ""
    echo "  1. Open: https://console.aws.amazon.com/social-messaging/home#/phone-numbers"
    echo "  2. Select your registered WhatsApp phone number."
    echo "  3. Under 'Event destinations', click 'Add destination'."
    echo "  4. Choose SNS Topic and paste:"
    echo "     ${SNS_TOPIC_ARN}"
    echo "  5. Enable event types: messages, message_deliveries, message_reads"
    echo "  6. Click Save."
    echo ""
else
    warn "SNS topic ARN not found in CDK outputs — skipping WABA validation."
    warn "Retrieve the topic ARN from CloudFormation outputs and configure manually."
fi

# =============================================================================
# STEP 12 — Open Lightsail firewall ports
# =============================================================================
step "12 of 13 — Configure Lightsail firewall"

# Get the instance name
INSTANCE_NAME=$(aws lightsail get-instances \
    --region "${REGION}" \
    --query "instances[?publicIpAddress=='${LIGHTSAIL_INSTANCE_IP}'].name" \
    --output text 2>/dev/null || echo "")

if [[ -n "${INSTANCE_NAME}" ]]; then
    info "Opening ports 8080 (web) and 8443 (OpenClaw) on Lightsail firewall..."

    aws lightsail open-instance-public-ports \
        --region "${REGION}" \
        --instance-name "${INSTANCE_NAME}" \
        --port-info fromPort=8080,toPort=8080,protocol=tcp 2>/dev/null \
        || warn "Port 8080 may already be open"

    aws lightsail open-instance-public-ports \
        --region "${REGION}" \
        --instance-name "${INSTANCE_NAME}" \
        --port-info fromPort=8443,toPort=8443,protocol=tcp 2>/dev/null \
        || warn "Port 8443 may already be open"

    success "Lightsail firewall configured"
else
    warn "Could not find Lightsail instance by IP — configure firewall manually"
    warn "Open ports: 8080 (web server), 8443 (OpenClaw gateway), 22 (SSH)"
fi

# =============================================================================
# STEP 13 — Print deployment summary
# =============================================================================
step "13 of 13 — Deployment summary"

END_TIME=$(date +%s)
ELAPSED=$(( END_TIME - START_TIME ))
ELAPSED_MIN=$(( ELAPSED / 60 ))
ELAPSED_SEC=$(( ELAPSED % 60 ))

echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${GREEN}║          Claw Boutique — Deployment Complete                 ║${RESET}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "${BOLD}Infrastructure${RESET}"
echo "  AWS Region         : ${REGION}"
echo "  CDK Stack          : ${STACK_NAME}"
echo "  SNS Topic ARN      : ${SNS_TOPIC_ARN:-<check .cdk-outputs.json>}"
echo "  Lambda Function    : ${DISPATCHER_FN:-ClawBoutiqueDispatcher}"
echo "  DB Secret          : ${DB_SECRET_ARN:-<check .cdk-outputs.json>}"
echo "  CDK Outputs File   : ${OUTPUTS_FILE}"
echo ""
echo -e "${BOLD}Database${RESET}"
echo "  Host               : ${DB_HOST}:${DB_PORT:-3306}"
echo "  Database           : ${DB_NAME}"
echo "  Schema             : applied (6 tables)"
echo "  Catalog            : seeded (20 products)"
echo ""
echo -e "${BOLD}OpenClaw (Lightsail)${RESET}"
echo "  Instance IP        : ${LIGHTSAIL_INSTANCE_IP}"
echo "  SSH User           : ${LIGHTSAIL_INSTANCE_USER}"
echo "  Config             : ~/openclaw/openclaw.json"
echo "  Environment        : ~/.env"
echo "  Gateway port       : 8443 (TLS)"
echo ""
echo -e "${BOLD}Web Server${RESET}"
echo "  Buyer Storefront   : http://${LIGHTSAIL_INSTANCE_IP}:8080"
echo "  Admin Dashboard    : http://${LIGHTSAIL_INSTANCE_IP}:8080/admin.html"
echo "  API Base URL       : http://${LIGHTSAIL_INSTANCE_IP}:8080/api"
echo ""
echo -e "${BOLD}Endpoints${RESET}"
echo "  OpenClaw Gateway   : https://${LIGHTSAIL_INSTANCE_IP}:8443"
echo "  WhatsApp inbound   : via SNS -> Lambda -> OpenClaw"
echo "  SES outbound       : ${SES_FROM_EMAIL:-<SES_FROM_EMAIL>}"
echo ""
echo -e "${BOLD}Next steps${RESET}"
echo "  1. Link WABA phone number to SNS topic (see Step 10 output above)"
echo "  2. Start OpenClaw on the Lightsail instance:"
echo "     ssh ${LIGHTSAIL_INSTANCE_USER}@${LIGHTSAIL_INSTANCE_IP}"
echo "     cd ~/openclaw && source ~/.env && ./start.sh"
echo "  3. Set Lambda environment variables (OPENCLAW_GATEWAY_URL, OPENCLAW_GATEWAY_TOKEN):"
echo "     aws lambda update-function-configuration \\"
echo "       --function-name ${DISPATCHER_FN:-ClawBoutiqueDispatcher} \\"
echo "       --environment 'Variables={OPENCLAW_GATEWAY_URL=https://${LIGHTSAIL_INSTANCE_IP}:8443,OPENCLAW_GATEWAY_TOKEN=<token>}' \\"
echo "       --region ${REGION}"
echo "  4. Activate the SES receipt rule set:"
echo "     aws ses set-active-receipt-rule-set --rule-set-name ClawBoutiqueRuleSet --region ${REGION}"
echo "  5. Verify SES domain '${SES_FROM_EMAIL:-<domain>}' (add DNS records from SES console)"
echo "  6. Run the validation script to confirm all services are healthy:"
echo "     ./scripts/validate-setup.sh"
echo ""
echo -e "${CYAN}Deployment time: ${ELAPSED_MIN}m ${ELAPSED_SEC}s${RESET}"
echo ""
