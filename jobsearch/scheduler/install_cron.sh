#!/usr/bin/env bash
# Installs a cron entry that runs the pipeline every morning at 7:00 local time.
# Linux/macOS with cron available. For macOS, launchd (see
# com.jobsearch.dailyrun.plist.example) is more reliable across sleep/wake
# than cron, but cron works fine if the machine is generally awake at 7am.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUN_SCRIPT="$PROJECT_DIR/jobsearch/scheduler/run_daily.sh"
chmod +x "$RUN_SCRIPT"

CRON_LINE="0 7 * * * $RUN_SCRIPT"
CRON_TAG="# jobsearch-daily-digest"

( crontab -l 2>/dev/null | grep -v -F "$CRON_TAG" ; echo "$CRON_LINE $CRON_TAG" ) | crontab -

echo "Installed cron job:"
crontab -l | grep -F "$CRON_TAG"
echo
echo "Logs will be written to $PROJECT_DIR/data/logs/"
echo "To remove: crontab -l | grep -v -F '$CRON_TAG' | crontab -"
