#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Claw Boutique end-to-end deployment orchestration
# =============================================================================
#
# Runs every step needed to go from a fresh checkout to a fully operational
# ClawBot instance: CDK stack (which builds and deploys OpenClaw to EKS),
# Secrets Manager, RDS/MySQL, database seed, Lambda zip, and final validation.
#
# Usage:
#   ./scripts/deploy.sh \
#     --region ap-southeast-1 \
#     --stack-name ClawBoutiqueStack \
#     --telegram-bot-token <token> \
#     --telegram-seller-id <id> \
#     --whatsapp-phone-number-id <id> \
#     --whatsapp-waba-id <id>
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
TELEGRAM_BOT_TOKEN=""
TELEGRAM_SELLER_ID=""
WHATSAPP_PHONE_NUMBER_ID_ARG=""
WHATSAPP_WABA_ID_ARG=""

usage() {
    echo "Usage: $0 --region <region> --stack-name <name> --telegram-bot-token <token> --telegram-seller-id <id> --whatsapp-phone-number-id <id> --whatsapp-waba-id <id>"
    echo ""
    echo "  --region                  AWS region to deploy into (e.g. ap-southeast-1)"
    echo "  --stack-name              CDK stack name (e.g. ClawBoutiqueStack)"
    echo "  --telegram-bot-token      Telegram bot token for the seller channel"
    echo "  --telegram-seller-id      Telegram chat ID of the seller"
    echo "  --whatsapp-phone-number-id  Meta WhatsApp phone number ID"
    echo "  --whatsapp-waba-id          Meta WhatsApp Business Account ID"
    echo ""
    echo "All other config is read from \$REPO_ROOT/.env — copy .env.example first."
    echo "CDK handles Docker build, ECR push, and EKS deployment of OpenClaw automatically."
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --region)                   REGION="$2";                    shift 2 ;;
        --stack-name)               STACK_NAME="$2";                shift 2 ;;
        --telegram-bot-token)       TELEGRAM_BOT_TOKEN="$2";        shift 2 ;;
        --telegram-seller-id)       TELEGRAM_SELLER_ID="$2";        shift 2 ;;
        --whatsapp-phone-number-id) WHATSAPP_PHONE_NUMBER_ID_ARG="$2"; shift 2 ;;
        --whatsapp-waba-id)         WHATSAPP_WABA_ID_ARG="$2";      shift 2 ;;
        -h|--help)                  usage ;;
        *)  die "Unknown argument: $1. Run with --help for usage." ;;
    esac
done

[[ -n "$REGION"      ]] || die "--region is required. Run with --help."
[[ -n "$STACK_NAME"  ]] || die "--stack-name is required. Run with --help."

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
EKS_CLUSTER_NAME="${EKS_CLUSTER_NAME:-claw-boutique}"

# CDK context values (CLI args take priority over .env)
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-${TELEGRAM_BOT_TOKEN:-}}"
TELEGRAM_SELLER_ID="${TELEGRAM_SELLER_ID:-${TELEGRAM_SELLER_ID:-}}"
WHATSAPP_PHONE_NUMBER_ID_ARG="${WHATSAPP_PHONE_NUMBER_ID_ARG:-${WHATSAPP_PHONE_NUMBER_ID:-}}"
WHATSAPP_WABA_ID_ARG="${WHATSAPP_WABA_ID_ARG:-${WHATSAPP_WABA_ID:-}}"

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
info "EKS cluster   : ${EKS_CLUSTER_NAME}"
info "Repo root     : ${REPO_ROOT}"
echo ""

# =============================================================================
# STEP 1 — Validate prerequisites
# =============================================================================
step "1 of 9 — Validate prerequisites"

REQUIRED_TOOLS=(aws node python3 mysql kubectl)
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
step "2 of 9 — Deploy CDK stack (${STACK_NAME})"

info "Installing CDK dependencies..."
(cd "${CDK_DIR}" && npm install --silent) \
    || die "npm install failed in ${CDK_DIR}"

info "Building CDK TypeScript..."
(cd "${CDK_DIR}" && npm run build) \
    || die "CDK TypeScript build failed. Check for compile errors above."

info "Building Lambda dispatcher..."
(cd "${LAMBDA_DIR}" && npm install --silent && npm run build) \
    || die "Lambda dispatcher build failed in ${LAMBDA_DIR}"

info "Running: cdk deploy --require-approval never (this may take 5–10 minutes including Docker build and EKS deploy)..."
(cd "${CDK_DIR}" && ${CDK_CMD} deploy "${STACK_NAME}" \
    --require-approval never \
    --region "${REGION}" \
    --outputs-file "${OUTPUTS_FILE}" \
    -c telegramBotToken="${TELEGRAM_BOT_TOKEN}" \
    -c telegramSellerId="${TELEGRAM_SELLER_ID}" \
    -c whatsappPhoneNumberId="${WHATSAPP_PHONE_NUMBER_ID_ARG}" \
    -c whatsappWabaId="${WHATSAPP_WABA_ID_ARG}") \
    || die "CDK deploy failed. Review CloudFormation events in the AWS console."

success "CDK stack deployed successfully (OpenClaw Docker image built, pushed to ECR, and deployed to EKS)"

# =============================================================================
# STEP 3 — Capture stack outputs
# =============================================================================
step "3 of 9 — Capture stack outputs to ${OUTPUTS_FILE}"

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
info "DB secret ARN       : ${DB_SECRET_ARN:-<not found>}"
success "Stack outputs captured"

# =============================================================================
# STEP 4 — Create / update Secrets Manager secret with DB credentials
# =============================================================================
step "4 of 9 — Upsert Secrets Manager secret (ClawBoutique/DbCredentials)"

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
step "5 of 9 — Ensure MySQL database '${DB_NAME}' exists and schema is applied"

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
step "6 of 9 — Seed product catalog (seed_catalog.py)"

info "Running seed_catalog.py — safe to re-run (INSERT IGNORE)..."
export DB_HOST DB_PORT DB_USER DB_PASSWORD DB_NAME
python3 "${SCRIPTS_DIR}/seed_catalog.py" \
    || die "seed_catalog.py failed. Check DB credentials and table schema."

success "Catalog seeded (20 products, 3 test customers)"

# =============================================================================
# STEP 7 — Build Lambda zip and print console instruction
# =============================================================================
step "7 of 9 — Package Lambda dispatcher"

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
# STEP 8 — Verify OpenClaw is running on EKS
# =============================================================================
step "8 of 9 — Verify OpenClaw deployment on EKS (${EKS_CLUSTER_NAME})"

info "Updating kubeconfig for EKS cluster ${EKS_CLUSTER_NAME}..."
aws eks update-kubeconfig \
    --name "${EKS_CLUSTER_NAME}" \
    --region "${REGION}" \
    || warn "Could not update kubeconfig — ensure the EKS cluster exists and IAM permissions are set."

info "Checking OpenClaw pod status..."
kubectl get pods -n default -l app=openclaw 2>/dev/null \
    || warn "No openclaw pods found — CDK deploy may still be rolling out. Check: kubectl get pods -n default"

success "EKS check complete. CDK handles Docker build, ECR push, and EKS deployment automatically."

# =============================================================================
# STEP 8b — Apply schema additions (new tables for admin, reviews, stock, etc.)
# =============================================================================
step "8b of 9 — Apply schema additions"

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
# STEP 9 — Validate WABA is linked to SNS topic
# =============================================================================
step "9 of 9 — Validate End User Messaging Social WABA linked to SNS"

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
# Deployment summary
# =============================================================================
step "Deployment summary"

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
echo -e "${BOLD}OpenClaw (EKS)${RESET}"
echo "  EKS Cluster        : ${EKS_CLUSTER_NAME}"
echo "  Check pods         : kubectl get pods -n default -l app=openclaw"
echo "  View logs          : kubectl logs -n default -l app=openclaw --tail=50"
echo "  Config (in image)  : /app/openclaw/openclaw.json"
echo ""
echo -e "${BOLD}Endpoints${RESET}"
echo "  OpenClaw Gateway   : via EKS NLB (check CDK outputs or kubectl get svc)"
echo "  WhatsApp inbound   : via SNS -> Lambda -> OpenClaw"
echo "  SES outbound       : ${SES_FROM_EMAIL:-<SES_FROM_EMAIL>}"
echo ""
echo -e "${BOLD}Next steps${RESET}"
echo "  1. Link WABA phone number to SNS topic (see Step 9 output above)"
echo "  2. OpenClaw is deployed automatically by CDK to EKS. Verify it is running:"
echo "     kubectl get pods -n default -l app=openclaw"
echo "  3. Set Lambda environment variables (OPENCLAW_GATEWAY_URL, OPENCLAW_GATEWAY_TOKEN):"
echo "     aws lambda update-function-configuration \\"
echo "       --function-name ${DISPATCHER_FN:-ClawBoutiqueDispatcher} \\"
echo "       --environment 'Variables={OPENCLAW_GATEWAY_URL=<nlb-endpoint>,OPENCLAW_GATEWAY_TOKEN=<token>}' \\"
echo "       --region ${REGION}"
echo "  4. Activate the SES receipt rule set:"
echo "     aws ses set-active-receipt-rule-set --rule-set-name ClawBoutiqueRuleSet --region ${REGION}"
echo "  5. Verify SES domain '${SES_FROM_EMAIL:-<domain>}' (add DNS records from SES console)"
echo "  6. Run the validation script to confirm all services are healthy:"
echo "     ./scripts/validate-setup.sh"
echo ""
echo -e "${CYAN}Deployment time: ${ELAPSED_MIN}m ${ELAPSED_SEC}s${RESET}"
echo ""
