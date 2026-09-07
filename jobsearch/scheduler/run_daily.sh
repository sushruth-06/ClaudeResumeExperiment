#!/usr/bin/env bash
# Runs the full daily pipeline. Invoked by cron/launchd — see install_cron.sh
# and com.jobsearch.dailyrun.plist.example in this directory.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="$PROJECT_DIR/data/logs"
mkdir -p "$LOG_DIR"

cd "$PROJECT_DIR"
source .venv/bin/activate

exec >> "$LOG_DIR/run-$(date +%F).log" 2>&1
echo "=== run-all started at $(date -Iseconds) ==="
jobsearch run-all
echo "=== run-all finished at $(date -Iseconds) ==="
