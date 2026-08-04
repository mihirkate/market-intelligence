#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$PROJECT_DIR"
source .venv/bin/activate

python -m app.scheduler.cron install
python -m app.scheduler.cron status
