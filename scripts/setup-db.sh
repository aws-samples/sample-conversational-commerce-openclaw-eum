#!/usr/bin/env bash
# =============================================================================
# setup-db.sh — Claw Boutique database initialisation
# =============================================================================
# Creates the database (if absent), applies schema.sql, runs seed_catalog.py,
# then validates all tables and prints a summary.
#
# Usage (env vars):
#   export DB_HOST=your-lightsail-endpoint.example.com
#   export DB_USER=admin
#   export DB_PASSWORD=secret
#   export DB_NAME=claw_boutique   # optional, default: claw_boutique
#   export DB_PORT=3306             # optional, default: 3306
#   ./setup-db.sh
#
# Usage (positional args — override env vars):
#   ./setup-db.sh <DB_HOST> <DB_USER> <DB_PASSWORD> [DB_NAME] [DB_PORT]
#
# Exit codes:
#   0  — success
#   1  — missing prerequisite, bad argument, or DB error
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
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
die()     { error "$*"; exit 1; }
section() { echo -e "\n${BOLD}==> $*${RESET}"; }

# ---------------------------------------------------------------------------
# Resolve script directory so relative paths always work regardless of cwd
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Parse arguments (positional args take priority over env vars)
# ---------------------------------------------------------------------------
DB_HOST="${1:-${DB_HOST:-}}"
DB_USER="${2:-${DB_USER:-}}"
DB_PASSWORD="${3:-${DB_PASSWORD:-}}"
DB_NAME="${4:-${DB_NAME:-claw_boutique}}"
DB_PORT="${5:-${DB_PORT:-3306}}"

# ---------------------------------------------------------------------------
# Validate required parameters
# ---------------------------------------------------------------------------
section "Validating configuration"

[[ -n "${DB_HOST}"     ]] || die "DB_HOST is not set. Pass it as arg 1 or export DB_HOST."
[[ -n "${DB_USER}"     ]] || die "DB_USER is not set. Pass it as arg 2 or export DB_USER."
[[ -n "${DB_PASSWORD}" ]] || die "DB_PASSWORD is not set. Pass it as arg 3 or export DB_PASSWORD."

info "Host     : ${DB_HOST}:${DB_PORT}"
info "User     : ${DB_USER}"
info "Database : ${DB_NAME}"

# ---------------------------------------------------------------------------
# Check required CLI tools
# ---------------------------------------------------------------------------
section "Checking prerequisites"

for cmd in mysql python3; do
    if command -v "$cmd" &>/dev/null; then
        success "'$cmd' found at $(command -v "$cmd")"
    else
        die "'$cmd' is not installed or not in PATH. Please install it and retry."
    fi
done

# Verify mysql-connector-python is available
if python3 -c "import mysql.connector" 2>/dev/null; then
    success "mysql-connector-python is installed"
else
    warn "mysql-connector-python not found — attempting pip install..."
    python3 -m pip install --quiet mysql-connector-python \
        || die "Failed to install mysql-connector-python. Run: pip install mysql-connector-python"
    success "mysql-connector-python installed"
fi

# ---------------------------------------------------------------------------
# Helper: run a mysql command, exiting on failure
# ---------------------------------------------------------------------------
mysql_cmd() {
    # Accepts additional args; credentials come from this function's scope.
    mysql \
        --host="${DB_HOST}" \
        --port="${DB_PORT}" \
        --user="${DB_USER}" \
        --password="${DB_PASSWORD}" \
        --connect-timeout=10 \
        "$@"
}

# ---------------------------------------------------------------------------
# Test connectivity
# ---------------------------------------------------------------------------
section "Testing database connectivity"

if mysql_cmd --execute="SELECT 1" &>/dev/null; then
    success "Connected to ${DB_HOST}:${DB_PORT} as '${DB_USER}'"
else
    die "Cannot connect to MySQL at ${DB_HOST}:${DB_PORT}. " \
        "Check host, port, user, and password."
fi

# ---------------------------------------------------------------------------
# Create database if it does not exist
# ---------------------------------------------------------------------------
section "Ensuring database '${DB_NAME}' exists"

mysql_cmd --execute="
    CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\`
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;
" \
    || die "Failed to create database '${DB_NAME}'."

success "Database '${DB_NAME}' is ready"

# ---------------------------------------------------------------------------
# Apply schema
# ---------------------------------------------------------------------------
section "Applying schema.sql"

SCHEMA_FILE="${SCRIPT_DIR}/schema.sql"
[[ -f "${SCHEMA_FILE}" ]] || die "schema.sql not found at ${SCHEMA_FILE}"

mysql_cmd "${DB_NAME}" < "${SCHEMA_FILE}" \
    || die "schema.sql failed. Check the error above."

success "schema.sql applied successfully"

# ---------------------------------------------------------------------------
# Run seed script
# ---------------------------------------------------------------------------
section "Running seed_catalog.py"

SEED_FILE="${SCRIPT_DIR}/seed_catalog.py"
[[ -f "${SEED_FILE}" ]] || die "seed_catalog.py not found at ${SEED_FILE}"

# Export all DB_* vars so the Python script can read them.
export DB_HOST DB_PORT DB_USER DB_PASSWORD DB_NAME

python3 "${SEED_FILE}" \
    || die "seed_catalog.py exited with an error. See output above."

# ---------------------------------------------------------------------------
# Validate: confirm all expected tables exist and have at least the minimum
# number of rows we expect after seeding.
# ---------------------------------------------------------------------------
section "Validating tables and row counts"

EXPECTED_TABLES=("customers" "products" "orders" "order_items" "conversations" "escalations")
MIN_ROWS=("3" "20" "0" "0" "0" "0")  # minimum expected rows after seed

ALL_OK=true

for i in "${!EXPECTED_TABLES[@]}"; do
    TABLE="${EXPECTED_TABLES[$i]}"
    MIN="${MIN_ROWS[$i]}"

    # Check table exists
    EXISTS=$(mysql_cmd "${DB_NAME}" \
        --silent --skip-column-names \
        --execute="SELECT COUNT(*) FROM information_schema.tables
                   WHERE table_schema='${DB_NAME}' AND table_name='${TABLE}';")

    if [[ "${EXISTS}" -eq 0 ]]; then
        error "Table '${TABLE}' does not exist in '${DB_NAME}'!"
        ALL_OK=false
        continue
    fi

    # Check row count meets minimum
    COUNT=$(mysql_cmd "${DB_NAME}" \
        --silent --skip-column-names \
        --execute="SELECT COUNT(*) FROM \`${TABLE}\`;")

    if [[ "${COUNT}" -lt "${MIN}" ]]; then
        warn "Table '${TABLE}': ${COUNT} rows (expected >= ${MIN})"
        ALL_OK=false
    else
        success "Table '${TABLE}': ${COUNT} rows"
    fi
done

if ! $ALL_OK; then
    die "Validation failed. Review warnings above."
fi

# ---------------------------------------------------------------------------
# Print connection string for reference
# ---------------------------------------------------------------------------
section "Connection details"

echo -e "  ${BOLD}MySQL CLI:${RESET}"
echo    "    mysql -h ${DB_HOST} -P ${DB_PORT} -u ${DB_USER} -p ${DB_NAME}"
echo
echo -e "  ${BOLD}Python (mysql-connector-python):${RESET}"
echo    "    mysql.connector.connect("
echo    "        host='${DB_HOST}', port=${DB_PORT},"
echo    "        user='${DB_USER}', password='<DB_PASSWORD>',"
echo    "        database='${DB_NAME}'"
echo    "    )"
echo
echo -e "  ${BOLD}SQLAlchemy DSN:${RESET}"
echo    "    mysql+mysqlconnector://${DB_USER}:<DB_PASSWORD>@${DB_HOST}:${DB_PORT}/${DB_NAME}"
echo
echo -e "${GREEN}${BOLD}Setup complete. Claw Boutique database is ready.${RESET}"
