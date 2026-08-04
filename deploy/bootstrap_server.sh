#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip curl cron
sudo systemctl enable --now cron

cd "$PROJECT_DIR"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

mkdir -p data/raw data/parquet data/processed data/twscrape logs reports

echo "Bootstrap complete for $PROJECT_DIR"
