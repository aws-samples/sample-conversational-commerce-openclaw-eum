#!/usr/bin/env bash
# =============================================================================
# health-check.sh — Claw Boutique System Health Check
# =============================================================================
# Verifies each component in the stack is configured and reachable:
#
#   1. SNS topic exists and is reachable (ClawBoutiqueInbound)
#   2. Lambda dispatcher exists and has the correct execution role
#   3. Database connectivity (MySQL SELECT 1)
#   4. OpenClaw gateway is reachable (HTTP health check or port check)
#   5. SES domain identity is verified
#
# Usage:
#   ./health-check.sh [options]
#
# Options:
#   --openclaw-url   <url>   OpenClaw gateway base URL (for HTTP reachability)
#   --db-host        <host>  MySQL host
#   --db-user        <user>  MySQL user
#   --db-password    <pass>  MySQL password
#   --db-name        <name>  MySQL database name (default: claw_boutique)
#   --sns-topic-arn  <arn>   Override auto-detected SNS topic ARN
#   --lambda-name    <name>  Override Lambda function name (default: ClawBoutiqueDispatcher)
#   --ses-domain     <dom>   Override SES domain to check (default: clawboutique.example.com)
#   --aws-region     <rgn>   AWS region (default: us-east-1)
#   --help                   Show this help
#
# Exit codes:
#   0 — all checks passed
#   1 — one or more checks failed
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    CYAN='\033[0;36m'
    BOLD='\033[1m'
    DIM='\033[2m'
    RESET='\033[0m'
else
    RED='' GREEN='' YELLOW='' CYAN='' BOLD='' DIM='' RESET=''
fi

ok()    { echo -e "  ${GREEN}🟢${RESET} $*"; }
fail()  { echo -e "  ${RED}🔴${RESET} ${RED}Issue:${RESET} $*"; }
skip()  { echo -e "  ${YELLOW}⚪${RESET} ${YELLOW}Skipped:${RESET} $*"; }
info()  { echo -e "     ${DIM}${CYAN}→${RESET} ${DIM}$*${RESET}"; }
blank() { echo ""; }
section() { echo -e "\n${BOLD}${CYAN}[ $* ]${RESET}"; }

# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------
PASS=0
FAIL=0
SKIP=0

pass() { PASS=$(( PASS + 1 )); ok "$*"; }
issue() { FAIL=$(( FAIL + 1 )); fail "$*"; }
skipped() { SKIP=$(( SKIP + 1 )); skip "$*"; }

# ---------------------------------------------------------------------------
# Load .env
# ---------------------------------------------------------------------------
for env_file in "${REPO_ROOT}/.env" "${SCRIPT_DIR}/.env"; do
    if [[ -f "${env_file}" ]]; then
        info "Loaded env from ${env_file}"
        set -a
        # shellcheck disable=SC1090
        source <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "${env_file}" | grep -v '^#')
        set +a
        break
    fi
done

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
OPENCLAW_URL="${OPENCLAW_URL:-}"
OPENCLAW_TOKEN="${OPENCLAW_TOKEN:-}"
DB_HOST="${DB_HOST:-}"
DB_USER="${DB_USER:-}"
DB_PASSWORD="${DB_PASSWORD:-}"
DB_NAME="${DB_NAME:-claw_boutique}"
DB_PORT="${DB_PORT:-3306}"
SNS_TOPIC_ARN="${SNS_TOPIC_ARN:-}"
LAMBDA_NAME="${LAMBDA_NAME:-ClawBoutiqueDispatcher}"
LAMBDA_ROLE_NAME="${LAMBDA_ROLE_NAME:-ClawBoutiqueDispatcherLambdaRole}"
SES_DOMAIN="${SES_DOMAIN:-clawboutique.example.com}"
AWS_REGION="${AWS_REGION:-us-east-1}"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --openclaw-url)   OPENCLAW_URL="$2";   shift 2 ;;
        --db-host)        DB_HOST="$2";        shift 2 ;;
        --db-user)        DB_USER="$2";        shift 2 ;;
        --db-password)    DB_PASSWORD="$2";    shift 2 ;;
        --db-name)        DB_NAME="$2";        shift 2 ;;
        --sns-topic-arn)  SNS_TOPIC_ARN="$2";  shift 2 ;;
        --lambda-name)    LAMBDA_NAME="$2";    shift 2 ;;
        --ses-domain)     SES_DOMAIN="$2";     shift 2 ;;
        --aws-region)     AWS_REGION="$2";     shift 2 ;;
        --help|-h)
            sed -n '2,35p' "${BASH_SOURCE[0]}" | grep '^#' | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "Unknown argument: $1  (run with --help)"
            exit 1
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
blank
echo -e "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}${CYAN}  Claw Boutique — Health Check${RESET}"
echo -e "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "  ${DIM}$(date '+%Y-%m-%d %H:%M:%S %Z')${RESET}"
blank

# ============================================================================
# CHECK 1 — SNS Topic
# ============================================================================
section "1. SNS Topic (ClawBoutiqueInbound)"

if ! command -v aws &>/dev/null; then
    skipped "AWS CLI not installed — cannot check SNS"
else
    # Try to find the topic ARN if not explicitly set
    if [[ -z "${SNS_TOPIC_ARN}" ]]; then
        info "No SNS_TOPIC_ARN set — searching for ClawBoutiqueInbound..."
        SNS_TOPIC_ARN=$(aws sns list-topics \
            --region "${AWS_REGION}" \
            --output text \
            --query 'Topics[*].TopicArn' 2>/dev/null \
            | tr '\t' '\n' \
            | grep -i "ClawBoutiqueInbound" \
            | head -1 || true)
    fi

    if [[ -z "${SNS_TOPIC_ARN}" ]]; then
        issue "SNS topic 'ClawBoutiqueInbound' not found in region ${AWS_REGION}"
        info "Run: aws sns list-topics --region ${AWS_REGION}"
        info "Make sure the CDK stack has been deployed: cd cdk && npx cdk deploy"
    else
        # Verify we can get topic attributes (proves real access, not just list)
        TOPIC_ATTRS=$(aws sns get-topic-attributes \
            --region "${AWS_REGION}" \
            --topic-arn "${SNS_TOPIC_ARN}" \
            --output json 2>/dev/null || echo "")

        if [[ -z "${TOPIC_ATTRS}" ]]; then
            issue "Cannot read attributes for topic ${SNS_TOPIC_ARN}"
            info "Check IAM permissions: sns:GetTopicAttributes"
        else
            SUBSCRIPTION_COUNT=$(echo "${TOPIC_ATTRS}" | \
                python3 -c "import json,sys; a=json.load(sys.stdin)['Attributes']; print(a.get('SubscriptionsConfirmed','0'))" 2>/dev/null || echo "?")
            pass "SNS topic reachable: ${SNS_TOPIC_ARN}"
            info "Confirmed subscriptions: ${SUBSCRIPTION_COUNT}"
            if [[ "${SUBSCRIPTION_COUNT}" == "0" ]]; then
                echo -e "     ${YELLOW}⚠${RESET}  ${YELLOW}No confirmed subscriptions — Lambda may not be subscribed yet${RESET}"
            fi
        fi
    fi
fi

# ============================================================================
# CHECK 2 — Lambda Dispatcher
# ============================================================================
section "2. Lambda Dispatcher (${LAMBDA_NAME})"

if ! command -v aws &>/dev/null; then
    skipped "AWS CLI not installed — cannot check Lambda"
else
    LAMBDA_CONFIG=$(aws lambda get-function-configuration \
        --region "${AWS_REGION}" \
        --function-name "${LAMBDA_NAME}" \
        --output json 2>/dev/null || echo "")

    if [[ -z "${LAMBDA_CONFIG}" ]]; then
        issue "Lambda function '${LAMBDA_NAME}' not found in region ${AWS_REGION}"
        info "Deploy the CDK stack first: cd cdk && npx cdk deploy"
    else
        LAMBDA_STATE=$(echo "${LAMBDA_CONFIG}" | \
            python3 -c "import json,sys; print(json.load(sys.stdin).get('State','Unknown'))" 2>/dev/null || echo "Unknown")
        LAMBDA_ROLE=$(echo "${LAMBDA_CONFIG}" | \
            python3 -c "import json,sys; print(json.load(sys.stdin).get('Role',''))" 2>/dev/null || echo "")
        LAMBDA_RUNTIME=$(echo "${LAMBDA_CONFIG}" | \
            python3 -c "import json,sys; print(json.load(sys.stdin).get('Runtime',''))" 2>/dev/null || echo "")
        LAMBDA_TIMEOUT=$(echo "${LAMBDA_CONFIG}" | \
            python3 -c "import json,sys; print(json.load(sys.stdin).get('Timeout','?'))" 2>/dev/null || echo "?")
        LAST_MODIFIED=$(echo "${LAMBDA_CONFIG}" | \
            python3 -c "import json,sys; print(json.load(sys.stdin).get('LastModified','?')[:19])" 2>/dev/null || echo "?")

        if [[ "${LAMBDA_STATE}" == "Active" ]]; then
            pass "Lambda function exists and is Active"
        else
            issue "Lambda function state is '${LAMBDA_STATE}' (expected Active)"
        fi

        info "Runtime      : ${LAMBDA_RUNTIME}"
        info "Timeout      : ${LAMBDA_TIMEOUT}s"
        info "Last modified: ${LAST_MODIFIED}"

        # Check the role name matches what CDK creates
        if echo "${LAMBDA_ROLE}" | grep -q "${LAMBDA_ROLE_NAME}"; then
            pass "Lambda execution role is correct (${LAMBDA_ROLE_NAME})"
        else
            ACTUAL_ROLE_NAME=$(basename "${LAMBDA_ROLE}")
            issue "Lambda role mismatch — expected '${LAMBDA_ROLE_NAME}', got '${ACTUAL_ROLE_NAME}'"
            info "Full role ARN: ${LAMBDA_ROLE}"
        fi

        # Check environment variables are set
        GATEWAY_URL_SET=$(echo "${LAMBDA_CONFIG}" | \
            python3 -c "
import json, sys
cfg = json.load(sys.stdin)
env = cfg.get('Environment', {}).get('Variables', {})
print('yes' if env.get('OPENCLAW_GATEWAY_URL','') else 'no')
" 2>/dev/null || echo "no")

        if [[ "${GATEWAY_URL_SET}" == "yes" ]]; then
            pass "OPENCLAW_GATEWAY_URL environment variable is set"
        else
            issue "OPENCLAW_GATEWAY_URL not set on Lambda — dispatcher will fail to route events"
            info "Update via: aws lambda update-function-configuration \\"
            info "  --function-name ${LAMBDA_NAME} \\"
            info "  --environment 'Variables={OPENCLAW_GATEWAY_URL=https://...,OPENCLAW_GATEWAY_TOKEN=...}'"
        fi
    fi
fi

# ============================================================================
# CHECK 3 — Database Connectivity
# ============================================================================
section "3. Database Connectivity (MySQL)"

if [[ -z "${DB_HOST}" || -z "${DB_USER}" || -z "${DB_PASSWORD}" ]]; then
    skipped "DB credentials not set (DB_HOST / DB_USER / DB_PASSWORD)"
    info "Set them in .env or pass --db-host / --db-user / --db-password"
elif ! command -v mysql &>/dev/null; then
    skipped "mysql CLI not installed — cannot check DB"
    info "Install MySQL client: brew install mysql-client (macOS) or apt-get install mysql-client"
else
    # Basic connectivity
    if mysql \
        --host="${DB_HOST}" \
        --port="${DB_PORT}" \
        --user="${DB_USER}" \
        --password="${DB_PASSWORD}" \
        --connect-timeout=10 \
        --execute="SELECT 1;" \
        &>/dev/null 2>&1; then
        pass "Database reachable at ${DB_HOST}:${DB_PORT}"

        # Check target database exists
        DB_EXISTS=$(mysql \
            --host="${DB_HOST}" \
            --port="${DB_PORT}" \
            --user="${DB_USER}" \
            --password="${DB_PASSWORD}" \
            --connect-timeout=10 \
            --silent --skip-column-names \
            --execute="SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name='${DB_NAME}';" \
            2>/dev/null || echo "0")

        if [[ "${DB_EXISTS}" -ge 1 ]]; then
            pass "Database '${DB_NAME}' exists"

            # Check all expected tables
            EXPECTED_TABLES=("customers" "products" "orders" "order_items" "conversations" "escalations")
            ALL_TABLES_OK=true
            for table in "${EXPECTED_TABLES[@]}"; do
                EXISTS=$(mysql \
                    --host="${DB_HOST}" --port="${DB_PORT}" \
                    --user="${DB_USER}" --password="${DB_PASSWORD}" \
                    --database="${DB_NAME}" --connect-timeout=10 \
                    --silent --skip-column-names \
                    --execute="SELECT COUNT(*) FROM information_schema.tables
                               WHERE table_schema='${DB_NAME}' AND table_name='${table}';" \
                    2>/dev/null || echo "0")
                if [[ "${EXISTS}" -ge 1 ]]; then
                    ROW_COUNT=$(mysql \
                        --host="${DB_HOST}" --port="${DB_PORT}" \
                        --user="${DB_USER}" --password="${DB_PASSWORD}" \
                        --database="${DB_NAME}" --connect-timeout=10 \
                        --silent --skip-column-names \
                        --execute="SELECT COUNT(*) FROM \`${table}\`;" \
                        2>/dev/null || echo "?")
                    info "Table '${table}': ${ROW_COUNT} rows"
                else
                    echo -e "     ${RED}✗${RESET}  Table '${table}' missing — run setup-db.sh"
                    ALL_TABLES_OK=false
                fi
            done

            if $ALL_TABLES_OK; then
                pass "All 6 schema tables present"
            else
                issue "One or more tables missing — run: ./scripts/setup-db.sh"
            fi
        else
            issue "Database '${DB_NAME}' does not exist"
            info "Run: ./scripts/setup-db.sh to initialise the database"
        fi
    else
        issue "Cannot connect to MySQL at ${DB_HOST}:${DB_PORT} as '${DB_USER}'"
        info "Check: host, port, user, password, and firewall rules"
    fi
fi

# ============================================================================
# CHECK 4 — OpenClaw Gateway
# ============================================================================
section "4. OpenClaw Gateway"

if [[ -z "${OPENCLAW_URL}" ]]; then
    skipped "OPENCLAW_URL not set"
    info "Set --openclaw-url or OPENCLAW_URL in .env"
elif ! command -v curl &>/dev/null; then
    skipped "curl not installed — cannot check gateway"
else
    # Normalise URL — strip trailing slash
    OPENCLAW_URL="${OPENCLAW_URL%/}"

    # Try a health endpoint first, then fall back to root
    HEALTH_STATUS=""
    for path in "/health" "/healthz" "/status" "/"; do
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
            --connect-timeout 8 \
            --max-time 12 \
            -H "Authorization: Bearer ${OPENCLAW_TOKEN:-}" \
            "${OPENCLAW_URL}${path}" 2>/dev/null || echo "000")

        if [[ "${HTTP_CODE}" =~ ^[23] ]]; then
            HEALTH_STATUS="${HTTP_CODE}"
            HEALTH_PATH="${path}"
            break
        elif [[ "${HTTP_CODE}" =~ ^[45] ]]; then
            # Got a real HTTP error (not a connection failure) — gateway is up
            HEALTH_STATUS="${HTTP_CODE}"
            HEALTH_PATH="${path}"
            break
        fi
    done

    if [[ -z "${HEALTH_STATUS}" || "${HEALTH_STATUS}" == "000" ]]; then
        issue "OpenClaw gateway unreachable at ${OPENCLAW_URL}"
        info "Check: the gateway is running, the URL is correct, and network/firewall allow access"
    elif [[ "${HEALTH_STATUS}" =~ ^[23] ]]; then
        pass "OpenClaw gateway is reachable (HTTP ${HEALTH_STATUS} at ${HEALTH_PATH})"
        info "URL: ${OPENCLAW_URL}"
    elif [[ "${HEALTH_STATUS}" == "401" || "${HEALTH_STATUS}" == "403" ]]; then
        pass "OpenClaw gateway is reachable (HTTP ${HEALTH_STATUS} — auth required, gateway is up)"
        if [[ -z "${OPENCLAW_TOKEN:-}" ]]; then
            echo -e "     ${YELLOW}⚠${RESET}  ${YELLOW}OPENCLAW_TOKEN not set — set it in .env or pass --openclaw-token${RESET}"
        fi
        info "URL: ${OPENCLAW_URL}"
    else
        issue "OpenClaw gateway returned unexpected HTTP ${HEALTH_STATUS} at ${OPENCLAW_URL}${HEALTH_PATH}"
    fi
fi

# ============================================================================
# CHECK 5 — SES Domain Verification
# ============================================================================
section "5. SES Domain Verification (${SES_DOMAIN})"

if ! command -v aws &>/dev/null; then
    skipped "AWS CLI not installed — cannot check SES"
else
    # SES v1 API still works for identity checks
    SES_STATUS=$(aws ses get-identity-verification-attributes \
        --region "${AWS_REGION}" \
        --identities "${SES_DOMAIN}" \
        --output json 2>/dev/null || echo "")

    if [[ -z "${SES_STATUS}" ]]; then
        issue "Could not query SES — check AWS credentials and region (${AWS_REGION})"
    else
        VERIFICATION_STATUS=$(echo "${SES_STATUS}" | \
            python3 -c "
import json, sys
data = json.load(sys.stdin)
attrs = data.get('VerificationAttributes', {})
domain_attrs = attrs.get('${SES_DOMAIN}', {})
print(domain_attrs.get('VerificationStatus', 'NotFound'))
" 2>/dev/null || echo "NotFound")

        if [[ "${VERIFICATION_STATUS}" == "Success" ]]; then
            pass "SES domain '${SES_DOMAIN}' is verified"

            # Check DKIM
            DKIM_ENABLED=$(echo "${SES_STATUS}" | \
                python3 -c "
import json, sys
data = json.load(sys.stdin)
attrs = data.get('VerificationAttributes', {})
domain_attrs = attrs.get('${SES_DOMAIN}', {})
print(str(domain_attrs.get('DkimEnabled', False)).lower())
" 2>/dev/null || echo "false")

            if [[ "${DKIM_ENABLED}" == "true" ]]; then
                pass "DKIM signing is enabled for ${SES_DOMAIN}"
            else
                echo -e "     ${YELLOW}⚠${RESET}  ${YELLOW}DKIM not enabled — enable for better deliverability${RESET}"
                info "Run: aws ses set-identity-dkim-enabled --identity ${SES_DOMAIN} --dkim-enabled"
            fi
        elif [[ "${VERIFICATION_STATUS}" == "Pending" ]]; then
            issue "SES domain '${SES_DOMAIN}' verification is Pending"
            info "Add the DNS TXT record provided by SES and wait for propagation"
            info "Run: aws ses get-identity-verification-attributes --identities ${SES_DOMAIN}"
        elif [[ "${VERIFICATION_STATUS}" == "NotFound" ]]; then
            issue "SES domain '${SES_DOMAIN}' has not been added to SES"
            info "Run: aws ses verify-domain-identity --domain ${SES_DOMAIN} --region ${AWS_REGION}"
            info "Then add the returned TXT record to your DNS zone"
        else
            issue "SES domain '${SES_DOMAIN}' verification status: ${VERIFICATION_STATUS}"
        fi
    fi

    # Also check SES receipt rule set is active
    ACTIVE_RULE_SET=$(aws ses describe-active-receipt-rule-set \
        --region "${AWS_REGION}" \
        --output json 2>/dev/null || echo "")

    if [[ -z "${ACTIVE_RULE_SET}" ]]; then
        echo -e "     ${YELLOW}⚠${RESET}  ${YELLOW}No active SES receipt rule set — inbound email will not work${RESET}"
        info "Activate it: aws ses set-active-receipt-rule-set --rule-set-name ClawBoutiqueRuleSet --region ${AWS_REGION}"
    else
        ACTIVE_RULE_SET_NAME=$(echo "${ACTIVE_RULE_SET}" | \
            python3 -c "import json,sys; m=json.load(sys.stdin).get('Metadata',{}); print(m.get('Name','?'))" 2>/dev/null || echo "?")
        if echo "${ACTIVE_RULE_SET_NAME}" | grep -qi "clawboutique"; then
            pass "Active SES receipt rule set: ${ACTIVE_RULE_SET_NAME}"
        else
            echo -e "     ${YELLOW}⚠${RESET}  ${YELLOW}Active receipt rule set is '${ACTIVE_RULE_SET_NAME}' (expected ClawBoutiqueRuleSet)${RESET}"
            info "Activate: aws ses set-active-receipt-rule-set --rule-set-name ClawBoutiqueRuleSet --region ${AWS_REGION}"
        fi
    fi
fi

# ============================================================================
# FINAL SUMMARY
# ============================================================================
blank
echo -e "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${BOLD}${CYAN}  Health Check Summary${RESET}"
echo -e "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
blank

TOTAL=$(( PASS + FAIL + SKIP ))

echo -e "  Checks passed : ${GREEN}${BOLD}${PASS}${RESET}"
echo -e "  Checks failed : ${RED}${BOLD}${FAIL}${RESET}"
echo -e "  Checks skipped: ${YELLOW}${BOLD}${SKIP}${RESET}"
echo -e "  Total checks  : ${BOLD}${TOTAL}${RESET}"
blank

if [[ "${FAIL}" -eq 0 && "${PASS}" -gt 0 ]]; then
    echo -e "  ${GREEN}${BOLD}🟢 All systems operational${RESET}"
elif [[ "${FAIL}" -eq 0 && "${PASS}" -eq 0 ]]; then
    echo -e "  ${YELLOW}${BOLD}⚪ All checks were skipped — set credentials to run full check${RESET}"
else
    echo -e "  ${RED}${BOLD}🔴 ${FAIL} system(s) need attention — review issues above${RESET}"
fi

blank
echo -e "${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
blank

[[ "${FAIL}" -eq 0 ]]
