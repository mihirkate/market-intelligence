#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://127.0.0.1:8000/health}"
DASHBOARD_URL="${DASHBOARD_URL:-http://127.0.0.1:8501}"

echo "Checking API: $API_URL"
curl --fail --silent --show-error "$API_URL"
echo

echo "Checking dashboard: $DASHBOARD_URL"
curl --fail --silent --show-error --head "$DASHBOARD_URL"
echo

echo "Live check passed"
