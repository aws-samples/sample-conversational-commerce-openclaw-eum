#!/usr/bin/env bash
# validate-env.sh — Deep validation of Claw Boutique environment variables
#
# Checks live connectivity and service state, not just presence of values.
# Run this after setup-env.sh passes, before your first deployment.
#
# Usage:
#   bash scripts/validate-env.sh

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: $ENV_FILE not found. Run 'source scripts/setup-env.sh' first." >&2
  exit 1
fi

# Load variables
set -o allexport
# shellcheck source=/dev/null
source "$ENV_FILE"
set +o allexport

PASS=0
FAIL=0
WARN=0

pass() { echo "  [PASS] $1"; ((PASS++)); }
fail() { echo "  [FAIL] $1"; ((FAIL++)); }
warn() { echo "  [WARN] $1"; ((WARN++)); }
header() { echo ""; echo "-- $1 --"; }

# ── 1. Database reachability ─────────────────────────────────────────────────

header "Database (MySQL)"

if command -v mysql &>/dev/null; then
  # Attempt a no-op query with a short timeout
  if mysql \
      --host="$DB_HOST" \
      --port="$DB_PORT" \
      --user="$DB_USER" \
      --password="$DB_PASSWORD" \
      --database="$DB_NAME" \
      --connect-timeout=5 \
      --execute="SELECT 1;" &>/dev/null 2>&1; then
    pass "DB_HOST $DB_HOST:$DB_PORT is reachable and credentials are valid"
  else
    fail "Cannot connect to MySQL at $DB_HOST:$DB_PORT as $DB_USER — check DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME"
  fi
else
  warn "mysql CLI not found — skipping database reachability check"
fi

# ── 2. AWS account ID matches current credentials ────────────────────────────

header "AWS Credentials"

ACTUAL_ACCOUNT=""
if ACTUAL_ACCOUNT=$(aws sts get-caller-identity \
    --profile "$AWS_PROFILE" \
    --query 'Account' \
    --output text 2>/dev/null); then
  if [ "$ACTUAL_ACCOUNT" = "$AWS_ACCOUNT_ID" ]; then
    pass "AWS_ACCOUNT_ID ($AWS_ACCOUNT_ID) matches active credentials (profile: $AWS_PROFILE)"
  else
    fail "AWS_ACCOUNT_ID mismatch: .env says '$AWS_ACCOUNT_ID' but active credentials belong to account '$ACTUAL_ACCOUNT'"
  fi
else
  fail "Cannot call sts:GetCallerIdentity for profile '$AWS_PROFILE' — run 'aws configure --profile $AWS_PROFILE'"
fi

# ── 3. SES from-address is verified ──────────────────────────────────────────

header "SES Email Verification"

SES_STATUS=""
if SES_STATUS=$(aws ses get-identity-verification-attributes \
    --profile "$AWS_PROFILE" \
    --region "$AWS_REGION" \
    --identities "$SES_FROM_EMAIL" \
    --query "VerificationAttributes.\"$SES_FROM_EMAIL\".VerificationStatus" \
    --output text 2>/dev/null); then
  if [ "$SES_STATUS" = "Success" ]; then
    pass "SES_FROM_EMAIL $SES_FROM_EMAIL is verified in $AWS_REGION"
  elif [ "$SES_STATUS" = "Pending" ]; then
    fail "SES_FROM_EMAIL $SES_FROM_EMAIL verification is Pending — check your inbox for the AWS verification email or add DNS records for domain verification"
  elif [ "$SES_STATUS" = "None" ] || [ -z "$SES_STATUS" ]; then
    fail "SES_FROM_EMAIL $SES_FROM_EMAIL is not registered — verify it in the SES console: https://console.aws.amazon.com/ses/home?region=$AWS_REGION"
  else
    warn "SES_FROM_EMAIL $SES_FROM_EMAIL has unexpected status: $SES_STATUS"
  fi

  # Also try domain-level verification (the domain part of the email)
  SES_DOMAIN="${SES_FROM_EMAIL##*@}"
  DOMAIN_STATUS=""
  if DOMAIN_STATUS=$(aws ses get-identity-verification-attributes \
      --profile "$AWS_PROFILE" \
      --region "$AWS_REGION" \
      --identities "$SES_DOMAIN" \
      --query "VerificationAttributes.\"$SES_DOMAIN\".VerificationStatus" \
      --output text 2>/dev/null) && [ "$DOMAIN_STATUS" = "Success" ]; then
    pass "SES sending domain $SES_DOMAIN is also verified (domain-level verification found)"
  fi
else
  warn "Could not query SES verification status — check AWS credentials and region"
fi

# ── Summary ───────────────────────────────────────────────────────────────────

echo ""
echo "============================================================"
echo " Validation Summary"
echo "============================================================"
echo "  Passed : $PASS"
echo "  Warned : $WARN"
echo "  Failed : $FAIL"
echo "============================================================"
echo ""

if [ "$FAIL" -gt 0 ]; then
  echo "One or more critical checks failed. Fix the issues above before deploying."
  exit 1
elif [ "$WARN" -gt 0 ]; then
  echo "All critical checks passed with $WARN warning(s). Review warnings before deploying to production."
  exit 0
else
  echo "All checks passed. You are ready to deploy."
  exit 0
fi
