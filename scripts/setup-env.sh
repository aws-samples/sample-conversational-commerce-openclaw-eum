#!/usr/bin/env bash
# setup-env.sh — Bootstrap local environment for Claw Boutique
#
# Usage:
#   source scripts/setup-env.sh   (exports variables into current shell)
#   bash scripts/setup-env.sh     (validates only; variables not exported to parent)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
ENV_EXAMPLE="$REPO_ROOT/.env.example"

# ── 1. Copy .env.example if .env does not exist ──────────────────────────────

if [ ! -f "$ENV_FILE" ]; then
  if [ ! -f "$ENV_EXAMPLE" ]; then
    echo "ERROR: .env.example not found at $ENV_EXAMPLE" >&2
    return 1 2>/dev/null || exit 1
  fi
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  echo "Created $ENV_FILE from .env.example — fill in your real values before deploying."
fi

# Load variables (strip comments and blank lines)
set -o allexport
# shellcheck source=/dev/null
source "$ENV_FILE"
set +o allexport

# ── 2. Validate all required variables are set ───────────────────────────────

REQUIRED_VARS=(
  AWS_REGION
  AWS_ACCOUNT_ID
  AWS_PROFILE
  CDK_STACK_NAME
  LIGHTSAIL_INSTANCE_IP
  LIGHTSAIL_INSTANCE_USER
  LIGHTSAIL_SSH_KEY_PATH
  DB_HOST
  DB_PORT
  DB_USER
  DB_PASSWORD
  DB_NAME
  WHATSAPP_PHONE_NUMBER_ID
  SES_FROM_EMAIL
  SES_FROM_NAME
  SELLER_NAME
  OPENCLAW_GATEWAY_URL
  OPENCLAW_GATEWAY_TOKEN
)

MISSING=()
for var in "${REQUIRED_VARS[@]}"; do
  val="${!var:-}"
  if [ -z "$val" ] || [[ "$val" == *"your_"* ]] || [[ "$val" == "123456789012" ]] || [[ "$val" == "1.2.3.4" ]]; then
    MISSING+=("$var")
  fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
  echo ""
  echo "ERROR: The following variables are missing or still set to placeholder values in $ENV_FILE:"
  for var in "${MISSING[@]}"; do
    echo "  - $var"
  done
  echo ""
  echo "Edit $ENV_FILE and replace all placeholder values, then re-run this script."
  return 1 2>/dev/null || exit 1
fi

# ── 3. Check AWS credentials are configured ──────────────────────────────────

if ! aws sts get-caller-identity --profile "$AWS_PROFILE" --output text --query 'Account' &>/dev/null; then
  echo ""
  echo "ERROR: AWS credentials not configured for profile '$AWS_PROFILE'."
  echo "Run: aws configure --profile $AWS_PROFILE"
  return 1 2>/dev/null || exit 1
fi

# ── 4. Check required CLI tools are available ────────────────────────────────

REQUIRED_TOOLS=(aws node python3 mysql)
MISSING_TOOLS=()
for tool in "${REQUIRED_TOOLS[@]}"; do
  if ! command -v "$tool" &>/dev/null; then
    MISSING_TOOLS+=("$tool")
  fi
done

if [ ${#MISSING_TOOLS[@]} -gt 0 ]; then
  echo ""
  echo "ERROR: The following required CLI tools were not found in PATH:"
  for tool in "${MISSING_TOOLS[@]}"; do
    echo "  - $tool"
  done
  echo ""
  echo "Install the missing tools and re-run this script."
  return 1 2>/dev/null || exit 1
fi

# ── 5. Print configuration summary ───────────────────────────────────────────

echo ""
echo "============================================================"
echo " Claw Boutique — Environment Ready"
echo "============================================================"
echo " AWS Region     : $AWS_REGION"
echo " AWS Account    : $AWS_ACCOUNT_ID"
echo " AWS Profile    : $AWS_PROFILE"
echo " CDK Stack      : $CDK_STACK_NAME"
echo ""
echo " Lightsail IP   : $LIGHTSAIL_INSTANCE_IP"
echo " SSH User       : $LIGHTSAIL_INSTANCE_USER"
echo " SSH Key        : $LIGHTSAIL_SSH_KEY_PATH"
echo ""
echo " DB Host        : $DB_HOST:$DB_PORT"
echo " DB Name        : $DB_NAME"
echo " DB User        : $DB_USER"
echo ""
echo " WhatsApp #ID   : $WHATSAPP_PHONE_NUMBER_ID"
echo " SES From       : $SES_FROM_NAME <$SES_FROM_EMAIL>"
echo ""
echo " Seller         : $SELLER_NAME"
echo " OpenClaw URL   : $OPENCLAW_GATEWAY_URL"
echo ""
echo " CLI tools      : aws $(aws --version 2>&1 | awk '{print $1}'), node $(node --version), python3 $(python3 --version 2>&1 | awk '{print $2}')"
echo "============================================================"
echo ""
echo "All checks passed. Run 'source scripts/setup-env.sh' to export"
echo "variables into your shell before running CDK or other scripts."
echo ""
