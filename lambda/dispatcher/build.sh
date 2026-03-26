#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# build.sh — Build and package the Lambda dispatcher for deployment
#
# Usage:
#   ./build.sh            # incremental build (skips npm install if node_modules exists)
#   ./build.sh --clean    # remove dist/ and node_modules first, then build
#
# Output:
#   claw-boutique-dispatcher.zip   (dist/index.js + node_modules, ready to upload)
# ------------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ZIP_NAME="claw-boutique-dispatcher.zip"

# ---------------------------------------------------------------------------
# Optional --clean flag
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--clean" ]]; then
  echo "[build] --clean: removing dist/ and node_modules..."
  rm -rf dist node_modules "$ZIP_NAME"
fi

# ---------------------------------------------------------------------------
# 1. Install production + dev dependencies (idempotent – skipped if present)
# ---------------------------------------------------------------------------
if [[ ! -d node_modules ]]; then
  echo "[build] node_modules not found – running npm install..."
  npm install
else
  echo "[build] node_modules present – skipping npm install"
fi

# ---------------------------------------------------------------------------
# 2. Compile TypeScript → dist/
# ---------------------------------------------------------------------------
echo "[build] Compiling TypeScript..."
npx tsc --project tsconfig.json

echo "[build] Compilation complete: dist/"

# ---------------------------------------------------------------------------
# 3. Create deployment ZIP
#    Contents: dist/  +  node_modules/  (production deps only)
#
#    We exclude devDependencies by re-running npm install --omit=dev into a
#    temporary directory so the ZIP stays as small as possible.
# ---------------------------------------------------------------------------
echo "[build] Preparing production node_modules..."

PROD_MODULES_DIR="$(mktemp -d)"
# Copy package files and install prod-only deps into the temp dir
cp package.json package-lock.json "$PROD_MODULES_DIR/"
npm install --prefix "$PROD_MODULES_DIR" --omit=dev --no-package-lock 2>/dev/null \
  || npm install --prefix "$PROD_MODULES_DIR" --production --no-package-lock

echo "[build] Creating deployment ZIP: $ZIP_NAME"
rm -f "$ZIP_NAME"

# Create a _deploy/ directory with index.js at root (required by Lambda handler "index.handler")
DEPLOY_DIR="$SCRIPT_DIR/_deploy"
rm -rf "$DEPLOY_DIR"
mkdir -p "$DEPLOY_DIR"
cp -r "$SCRIPT_DIR/dist/"* "$DEPLOY_DIR/"
cp -r "$PROD_MODULES_DIR/node_modules" "$DEPLOY_DIR/"

# Create ZIP from _deploy/ so index.js is at the root (not under dist/)
(cd "$DEPLOY_DIR" && zip -r "$SCRIPT_DIR/$ZIP_NAME" . -x "*.map" "*.d.ts" "*.d.ts.map")

# Cleanup temp dir
rm -rf "$PROD_MODULES_DIR"

# ---------------------------------------------------------------------------
# 4. Report
# ---------------------------------------------------------------------------
ZIP_PATH="$SCRIPT_DIR/$ZIP_NAME"

if command -v du &>/dev/null; then
  ZIP_SIZE=$(du -sh "$ZIP_PATH" | cut -f1)
else
  ZIP_SIZE="$(wc -c < "$ZIP_PATH") bytes"
fi

echo ""
echo "------------------------------------------------------------"
echo "  Deployment package ready"
echo "  Path : $ZIP_PATH"
echo "  Size : $ZIP_SIZE"
echo "------------------------------------------------------------"
echo ""
echo "Deploy via AWS CLI:"
echo "  aws lambda update-function-code \\"
echo "    --function-name ClawBoutiqueDispatcher \\"
echo "    --zip-file fileb://$ZIP_PATH \\"
echo "    --region <your-region>"
echo ""
echo "Or upload manually in the Lambda console:"
echo "  Lambda > Functions > ClawBoutiqueDispatcher > Code > Upload from > .zip file"
echo ""
