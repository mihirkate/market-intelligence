#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="${SERVICE_USER:-$(id -un)}"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_DIR/.venv/bin/python}"
STREAMLIT_BIN="${STREAMLIT_BIN:-$PROJECT_DIR/.venv/bin/streamlit}"
API_SERVICE="market-intelligence-api.service"
DASHBOARD_SERVICE="market-intelligence-dashboard.service"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

if [[ ! -f "$PROJECT_DIR/.env" ]]; then
  echo "Missing $PROJECT_DIR/.env"
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing python executable at $PYTHON_BIN"
  exit 1
fi

if [[ ! -x "$STREAMLIT_BIN" ]]; then
  echo "Missing streamlit executable at $STREAMLIT_BIN"
  exit 1
fi

render_template() {
  local template_path="$1"
  local output_path="$2"

  sed \
    -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    -e "s|__SERVICE_USER__|$SERVICE_USER|g" \
    -e "s|__PYTHON_BIN__|$PYTHON_BIN|g" \
    -e "s|__STREAMLIT_BIN__|$STREAMLIT_BIN|g" \
    "$template_path" > "$output_path"
}

render_template \
  "$PROJECT_DIR/deploy/systemd/market-intelligence-api.service.template" \
  "$TMP_DIR/$API_SERVICE"

render_template \
  "$PROJECT_DIR/deploy/systemd/market-intelligence-dashboard.service.template" \
  "$TMP_DIR/$DASHBOARD_SERVICE"

sudo cp "$TMP_DIR/$API_SERVICE" "/etc/systemd/system/$API_SERVICE"
sudo cp "$TMP_DIR/$DASHBOARD_SERVICE" "/etc/systemd/system/$DASHBOARD_SERVICE"

sudo systemctl daemon-reload
sudo systemctl enable --now "$API_SERVICE"
sudo systemctl enable --now "$DASHBOARD_SERVICE"

sudo systemctl status "$API_SERVICE" --no-pager
sudo systemctl status "$DASHBOARD_SERVICE" --no-pager
