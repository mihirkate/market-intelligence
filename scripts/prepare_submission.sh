#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

delete_generated_files() {
  local target_dir="$1"
  if [[ -d "$target_dir" ]]; then
    find "$target_dir" -type f ! -name ".gitkeep" -delete
  fi
}

echo "Cleaning generated runtime artifacts from $PROJECT_DIR"

delete_generated_files "logs"
delete_generated_files "data/raw"
delete_generated_files "data/processed"
delete_generated_files "data/parquet"
delete_generated_files "data/twscrape"

rm -f reports/*.json
rm -rf data/raw/debug
find . -type d \( -name "__pycache__" -o -name ".pytest_cache" -o -name ".mypy_cache" \) -prune -exec rm -rf {} +

echo
echo "Submission cleanup complete."
echo "Review these local-only sensitive files before pushing:"

for sensitive_file in .env .env.local .env.production market-intelligence.pem; do
  if [[ -f "$sensitive_file" ]]; then
    echo "  - $sensitive_file"
  fi
done

find . -maxdepth 2 -type f \( -name "*.pem" -o -name "*.key" -o -name "*.crt" \) -print | sed 's/^/  - /'

echo
echo "Next steps:"
echo "  1. git status"
echo "  2. confirm .env is not tracked and live secrets are not staged"
echo "  3. add only sanitized sample outputs you explicitly want in the submission"
