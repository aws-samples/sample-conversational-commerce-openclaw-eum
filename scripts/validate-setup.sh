#!/usr/bin/env bash
# =============================================================================
# validate-setup.sh — Claw Boutique post-deployment validation
# =============================================================================
#
# Checks every deployed component and prints a checklist.
# Run this after deploy.sh completes to confirm the system is healthy.
#
# Usage:
#   ./scripts/validate-setup.sh
#
#   Override CDK outputs file path:
#   OUTPUTS_FILE=/path/to/.cdk-outputs.json ./scripts/validate-setup.sh
#
# Exit codes:
#   0  — all checks passed
#   1  — one or more checks failed (see checklist output)
# =============================================================================

set -uo pipefail

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
    CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; CYAN=''; BOLD=''; RESET=''
fi

# Checklist state
PASS=0
FAIL=0
WARN_COUNT=0
declare -a CHECKLIST_LINES

chk_pass() { PASS=$(( PASS + 1 ));       CHECKLIST_LINES+=("${GREEN}  [PASS]${RESET}  $*"); }
chk_fail() { FAIL=$(( FAIL + 1 ));       CHECKLIST_LINES+=("${RED}  [FAIL]${RESET}  $*"); }
chk_warn() { WARN_COUNT=$(( WARN_COUNT + 1 )); CHECKLIST_LINES+=("${YELLOW}  [WARN]${RESET}  $*"); }

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
section() { echo -e "\n${BOLD}--- $* ---${RESET}"; }

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"
OUTPUTS_FILE="${OUTPUTS_FILE:-${REPO_ROOT}/.cdk-outputs.json}"

# ---------------------------------------------------------------------------
# Load .env
# ---------------------------------------------------------------------------
if [[ -f "$ENV_FILE" ]]; then
    set -o allexport
    # shellcheck source=/dev/null
    source "$ENV_FILE"
    set +o allexport
else
    echo -e "${YELLOW}[WARN]${RESET}  .env not found at ${ENV_FILE} — some checks may fail."
fi

REGION="${AWS_REGION:-${REGION:-us-east-1}}"
STACK_NAME="${CDK_STACK_NAME:-ClawBoutiqueStack}"
EKS_CLUSTER_NAME="${EKS_CLUSTER_NAME:-claw-boutique}"
DB_HOST="${DB_HOST:-}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-}"
DB_PASSWORD="${DB_PASSWORD:-}"
DB_NAME="${DB_NAME:-claw_boutique}"

echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${CYAN}║       Claw Boutique — Post-Deployment Validation             ║${RESET}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════════════════╝${RESET}"
echo ""
info "Region      : ${REGION}"
info "Stack       : ${STACK_NAME}"
info "Outputs     : ${OUTPUTS_FILE}"
info "EKS cluster : ${EKS_CLUSTER_NAME}"
info "DB host     : ${DB_HOST:-<not set>}"
echo ""

# =============================================================================
# Parse CDK outputs (best-effort)
# =============================================================================
SNS_TOPIC_ARN=""
DISPATCHER_FN_NAME=""
DISPATCHER_FN_ARN=""
DB_SECRET_ARN=""
SES_RULE_SET=""

if [[ -f "${OUTPUTS_FILE}" ]]; then
    SNS_TOPIC_ARN=$(python3 -c "
import json
data = json.load(open('${OUTPUTS_FILE}'))
stack = data.get('${STACK_NAME}', {})
for k, v in stack.items():
    if 'InboundTopicArn' in k: print(v); exit()
" 2>/dev/null || echo "")

    DISPATCHER_FN_NAME=$(python3 -c "
import json
data = json.load(open('${OUTPUTS_FILE}'))
stack = data.get('${STACK_NAME}', {})
for k, v in stack.items():
    if 'DispatcherFunctionName' in k: print(v); exit()
" 2>/dev/null || echo "ClawBoutiqueDispatcher")

    DISPATCHER_FN_ARN=$(python3 -c "
import json
data = json.load(open('${OUTPUTS_FILE}'))
stack = data.get('${STACK_NAME}', {})
for k, v in stack.items():
    if 'DispatcherFunctionArn' in k: print(v); exit()
" 2>/dev/null || echo "")

    DB_SECRET_ARN=$(python3 -c "
import json
data = json.load(open('${OUTPUTS_FILE}'))
stack = data.get('${STACK_NAME}', {})
for k, v in stack.items():
    if 'DbCredentialsSecretArn' in k: print(v); exit()
" 2>/dev/null || echo "")

    SES_RULE_SET=$(python3 -c "
import json
data = json.load(open('${OUTPUTS_FILE}'))
stack = data.get('${STACK_NAME}', {})
for k, v in stack.items():
    if 'SesReceiptRuleSetName' in k: print(v); exit()
" 2>/dev/null || echo "ClawBoutiqueRuleSet")
else
    echo -e "${YELLOW}[WARN]${RESET}  ${OUTPUTS_FILE} not found — using defaults for CDK resource names."
fi

DISPATCHER_FN_NAME="${DISPATCHER_FN_NAME:-ClawBoutiqueDispatcher}"
SES_RULE_SET="${SES_RULE_SET:-ClawBoutiqueRuleSet}"

# =============================================================================
# CHECK 1 — SNS Topic
# =============================================================================
section "SNS Topic"

if [[ -n "${SNS_TOPIC_ARN}" ]]; then
    if aws sns get-topic-attributes \
            --topic-arn "${SNS_TOPIC_ARN}" \
            --region "${REGION}" \
            --output text --query 'Attributes.TopicArn' &>/dev/null 2>&1; then
        chk_pass "SNS Topic exists: ${SNS_TOPIC_ARN}"

        # Check EUM Social publish permission in topic policy
        TOPIC_POLICY=$(aws sns get-topic-attributes \
            --topic-arn "${SNS_TOPIC_ARN}" \
            --region "${REGION}" \
            --query 'Attributes.Policy' \
            --output text 2>/dev/null || echo "")
        if echo "${TOPIC_POLICY}" | grep -q "social-messaging.amazonaws.com"; then
            chk_pass "SNS Topic policy: social-messaging.amazonaws.com can publish"
        else
            chk_fail "SNS Topic policy: social-messaging.amazonaws.com NOT found — WABA webhooks will not arrive"
        fi

        # KMS encrypted?
        KMS_KEY=$(aws sns get-topic-attributes \
            --topic-arn "${SNS_TOPIC_ARN}" \
            --region "${REGION}" \
            --query 'Attributes.KmsMasterKeyId' \
            --output text 2>/dev/null || echo "None")
        if [[ "${KMS_KEY}" != "None" && -n "${KMS_KEY}" ]]; then
            chk_pass "SNS Topic is KMS-encrypted (key: ${KMS_KEY})"
        else
            chk_warn "SNS Topic is NOT KMS-encrypted (acceptable for dev, not recommended for production)"
        fi
    else
        chk_fail "SNS Topic NOT found: ${SNS_TOPIC_ARN}"
    fi
else
    chk_warn "SNS Topic ARN not found in CDK outputs — skipping SNS checks"
fi

# =============================================================================
# CHECK 2 — Lambda Function
# =============================================================================
section "Lambda Dispatcher"

if aws lambda get-function \
        --function-name "${DISPATCHER_FN_NAME}" \
        --region "${REGION}" \
        --output text --query 'Configuration.FunctionName' &>/dev/null 2>&1; then
    chk_pass "Lambda function exists: ${DISPATCHER_FN_NAME}"

    # Check function state
    FN_STATE=$(aws lambda get-function \
        --function-name "${DISPATCHER_FN_NAME}" \
        --region "${REGION}" \
        --query 'Configuration.State' \
        --output text 2>/dev/null || echo "Unknown")
    if [[ "${FN_STATE}" == "Active" ]]; then
        chk_pass "Lambda function state: Active"
    else
        chk_fail "Lambda function state: ${FN_STATE} (expected Active)"
    fi

    # Check SNS subscription
    if [[ -n "${SNS_TOPIC_ARN}" ]]; then
        LAMBDA_SUB=$(aws sns list-subscriptions-by-topic \
            --topic-arn "${SNS_TOPIC_ARN}" \
            --region "${REGION}" \
            --query "Subscriptions[?Protocol=='lambda'].Endpoint" \
            --output text 2>/dev/null || echo "")
        if [[ -n "${LAMBDA_SUB}" ]]; then
            chk_pass "Lambda is subscribed to SNS topic"
        else
            chk_fail "Lambda has NO subscription on SNS topic — messages will not trigger Lambda"
        fi
    fi

    # Check Lambda has OPENCLAW_GATEWAY_URL set
    GW_URL=$(aws lambda get-function-configuration \
        --function-name "${DISPATCHER_FN_NAME}" \
        --region "${REGION}" \
        --query 'Environment.Variables.OPENCLAW_GATEWAY_URL' \
        --output text 2>/dev/null || echo "None")
    if [[ "${GW_URL}" != "None" && -n "${GW_URL}" && "${GW_URL}" != "None" ]]; then
        chk_pass "Lambda env OPENCLAW_GATEWAY_URL is set: ${GW_URL}"
    else
        chk_fail "Lambda env OPENCLAW_GATEWAY_URL is NOT set — dispatcher cannot reach OpenClaw"
    fi

    GW_TOKEN=$(aws lambda get-function-configuration \
        --function-name "${DISPATCHER_FN_NAME}" \
        --region "${REGION}" \
        --query 'Environment.Variables.OPENCLAW_GATEWAY_TOKEN' \
        --output text 2>/dev/null || echo "None")
    if [[ "${GW_TOKEN}" != "None" && -n "${GW_TOKEN}" ]]; then
        chk_pass "Lambda env OPENCLAW_GATEWAY_TOKEN is set"
    else
        chk_fail "Lambda env OPENCLAW_GATEWAY_TOKEN is NOT set — requests to OpenClaw will be rejected"
    fi
else
    chk_fail "Lambda function NOT found: ${DISPATCHER_FN_NAME}"
fi

# =============================================================================
# CHECK 3 — Secrets Manager
# =============================================================================
section "Secrets Manager"

SECRET_ID="${DB_SECRET_ARN:-ClawBoutique/DbCredentials}"
if aws secretsmanager describe-secret \
        --secret-id "${SECRET_ID}" \
        --region "${REGION}" \
        --output text --query 'ARN' &>/dev/null 2>&1; then
    chk_pass "Secrets Manager secret exists: ClawBoutique/DbCredentials"

    # Check secret value is not still placeholder
    SECRET_VALUE=$(aws secretsmanager get-secret-value \
        --secret-id "${SECRET_ID}" \
        --region "${REGION}" \
        --query 'SecretString' \
        --output text 2>/dev/null || echo "")
    if echo "${SECRET_VALUE}" | grep -qi "PLACEHOLDER"; then
        chk_fail "Secret still contains PLACEHOLDER values — update with real DB credentials"
    else
        chk_pass "Secret value has been updated (no placeholder values detected)"
    fi
else
    chk_fail "Secrets Manager secret NOT found: ClawBoutique/DbCredentials"
fi

# =============================================================================
# CHECK 4 — SES Domain / Email
# =============================================================================
section "Amazon SES"

SES_FROM="${SES_FROM_EMAIL:-}"
if [[ -n "${SES_FROM}" ]]; then
    SES_DOMAIN="${SES_FROM#*@}"

    # Check domain identity
    IDENTITY_STATUS=$(aws ses get-identity-verification-attributes \
        --identities "${SES_DOMAIN}" \
        --region "${REGION}" \
        --query "VerificationAttributes.\"${SES_DOMAIN}\".VerificationStatus" \
        --output text 2>/dev/null || echo "NotFound")

    if [[ "${IDENTITY_STATUS}" == "Success" ]]; then
        chk_pass "SES domain '${SES_DOMAIN}' is verified"
    elif [[ "${IDENTITY_STATUS}" == "Pending" ]]; then
        chk_warn "SES domain '${SES_DOMAIN}' verification is PENDING — add DNS records in your registrar"
    else
        chk_fail "SES domain '${SES_DOMAIN}' is NOT verified (status: ${IDENTITY_STATUS})"
    fi

    # Check receipt rule set is active
    ACTIVE_RULE_SET=$(aws ses describe-active-receipt-rule-set \
        --region "${REGION}" \
        --query 'Metadata.Name' \
        --output text 2>/dev/null || echo "None")
    if [[ "${ACTIVE_RULE_SET}" == "${SES_RULE_SET}" ]]; then
        chk_pass "SES receipt rule set '${SES_RULE_SET}' is ACTIVE"
    elif [[ "${ACTIVE_RULE_SET}" == "None" || -z "${ACTIVE_RULE_SET}" ]]; then
        chk_fail "No active SES receipt rule set — inbound email will not be received"
    else
        chk_warn "Active SES receipt rule set is '${ACTIVE_RULE_SET}', expected '${SES_RULE_SET}'"
    fi
else
    chk_warn "SES_FROM_EMAIL not set in .env — skipping SES checks"
fi

# =============================================================================
# CHECK 5 — Database tables and schema
# =============================================================================
section "Database (${DB_HOST:-<not set>})"

EXPECTED_TABLES=("customers" "products" "orders" "order_items" "conversations" "escalations")

if [[ -n "${DB_HOST}" && -n "${DB_USER}" && -n "${DB_PASSWORD}" ]]; then
    # Test connectivity
    if mysql \
            --host="${DB_HOST}" \
            --port="${DB_PORT}" \
            --user="${DB_USER}" \
            --password="${DB_PASSWORD}" \
            --connect-timeout=10 \
            --execute="SELECT 1" &>/dev/null 2>&1; then
        chk_pass "MySQL connection OK (${DB_HOST}:${DB_PORT})"

        # Check each table
        ALL_TABLES_OK=true
        for table in "${EXPECTED_TABLES[@]}"; do
            EXISTS=$(mysql \
                --host="${DB_HOST}" \
                --port="${DB_PORT}" \
                --user="${DB_USER}" \
                --password="${DB_PASSWORD}" \
                --connect-timeout=10 \
                --silent --skip-column-names \
                "${DB_NAME}" \
                --execute="SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${DB_NAME}' AND table_name='${table}';" \
                2>/dev/null || echo "0")
            if [[ "${EXISTS}" -eq 1 ]]; then
                ROW_COUNT=$(mysql \
                    --host="${DB_HOST}" \
                    --port="${DB_PORT}" \
                    --user="${DB_USER}" \
                    --password="${DB_PASSWORD}" \
                    --connect-timeout=10 \
                    --silent --skip-column-names \
                    "${DB_NAME}" \
                    --execute="SELECT COUNT(*) FROM \`${table}\`;" \
                    2>/dev/null || echo "?")
                chk_pass "Table '${table}' exists (${ROW_COUNT} rows)"
            else
                chk_fail "Table '${table}' NOT found in database '${DB_NAME}'"
                ALL_TABLES_OK=false
            fi
        done

        # Check products are seeded
        PRODUCT_COUNT=$(mysql \
            --host="${DB_HOST}" \
            --port="${DB_PORT}" \
            --user="${DB_USER}" \
            --password="${DB_PASSWORD}" \
            --connect-timeout=10 \
            --silent --skip-column-names \
            "${DB_NAME}" \
            --execute="SELECT COUNT(*) FROM products;" \
            2>/dev/null || echo "0")
        if [[ "${PRODUCT_COUNT}" -ge 20 ]]; then
            chk_pass "Database catalog seeded (${PRODUCT_COUNT} products, expected >= 20)"
        elif [[ "${PRODUCT_COUNT}" -gt 0 ]]; then
            chk_warn "Only ${PRODUCT_COUNT} products in catalog (expected 20 — run seed_catalog.py)"
        else
            chk_fail "Products table is empty — run: python3 scripts/seed_catalog.py"
        fi
    else
        chk_fail "Cannot connect to MySQL at ${DB_HOST}:${DB_PORT} — check DB_HOST, DB_USER, DB_PASSWORD"
    fi
else
    chk_warn "DB_HOST / DB_USER / DB_PASSWORD not set — skipping database checks"
fi

# =============================================================================
# CHECK 6 — OpenClaw pods running on EKS
# =============================================================================
section "OpenClaw (EKS cluster: ${EKS_CLUSTER_NAME})"

if command -v kubectl &>/dev/null; then
    # Update kubeconfig silently
    aws eks update-kubeconfig \
        --name "${EKS_CLUSTER_NAME}" \
        --region "${REGION}" &>/dev/null 2>&1 \
        || true

    POD_LIST=$(kubectl get pods -n default -l app=openclaw \
        --no-headers 2>/dev/null || echo "")

    if [[ -n "${POD_LIST}" ]]; then
        RUNNING_COUNT=$(echo "${POD_LIST}" | grep -c "Running" || true)
        TOTAL_COUNT=$(echo "${POD_LIST}" | wc -l | tr -d ' ')
        if [[ "${RUNNING_COUNT}" -gt 0 ]]; then
            chk_pass "OpenClaw: ${RUNNING_COUNT}/${TOTAL_COUNT} pod(s) Running on EKS cluster '${EKS_CLUSTER_NAME}'"
        else
            chk_fail "OpenClaw pods found but none are Running — check: kubectl get pods -n default -l app=openclaw"
        fi
    else
        chk_fail "No OpenClaw pods found on EKS cluster '${EKS_CLUSTER_NAME}' — check CDK deploy completed successfully"
    fi
else
    chk_warn "kubectl not found — skipping EKS pod check"
fi

# =============================================================================
# CHECK 7 — CloudWatch Log Group
# =============================================================================
section "CloudWatch Logs"

LOG_GROUP="/aws/lambda/${DISPATCHER_FN_NAME}"
if aws logs describe-log-groups \
        --log-group-name-prefix "${LOG_GROUP}" \
        --region "${REGION}" \
        --query "logGroups[?logGroupName=='${LOG_GROUP}'].logGroupName" \
        --output text 2>/dev/null | grep -q "${DISPATCHER_FN_NAME}"; then
    chk_pass "CloudWatch log group exists: ${LOG_GROUP}"
else
    chk_warn "CloudWatch log group '${LOG_GROUP}' not found — Lambda may not have been invoked yet"
fi

# =============================================================================
# Print Checklist
# =============================================================================
TOTAL=$(( PASS + FAIL + WARN_COUNT ))

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║                 Validation Checklist                        ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${RESET}"
echo ""

for line in "${CHECKLIST_LINES[@]}"; do
    echo -e "$line"
done

echo ""
echo -e "${BOLD}Results: ${GREEN}${PASS} passed${RESET}  ${RED}${FAIL} failed${RESET}  ${YELLOW}${WARN_COUNT} warnings${RESET}  (${TOTAL} total checks)"
echo ""

if [[ "${FAIL}" -gt 0 ]]; then
    echo -e "${RED}${BOLD}Some checks FAILED. Review the list above and fix each failing item.${RESET}"
    echo ""
    echo "Common fixes:"
    echo "  - WABA not linked to SNS: configure in AWS End User Messaging Social console"
    echo "  - Lambda env vars missing: run 'aws lambda update-function-configuration'"
    echo "  - DB tables missing: run 'bash scripts/setup-db.sh'"
    echo "  - OpenClaw not running: check EKS pods with 'kubectl get pods -n default -l app=openclaw'"
    echo "  - SES domain pending: add CNAME/TXT/MX DNS records for your domain"
    echo ""
    exit 1
elif [[ "${WARN_COUNT}" -gt 0 ]]; then
    echo -e "${YELLOW}All critical checks passed. Review warnings above before going live.${RESET}"
    echo ""
    exit 0
else
    echo -e "${GREEN}${BOLD}All checks passed. Claw Boutique is fully deployed and operational.${RESET}"
    echo ""
    echo "Test it: send a WhatsApp message to your registered customer phone number."
    echo ""
    exit 0
fi
