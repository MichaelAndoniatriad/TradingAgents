#!/bin/bash
# Daily clerk is **disabled** — use `scripts/cron-clerk-weekly.sh` only.
#
# This script remains as a no-op so existing crontab lines that still point here
# do not error; it logs once and exits 0.
#
# To remove the cron line entirely: `crontab -e` and delete the morning entry.

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${CLERK_CRON_LOG:-$HOME/.tradingagents/logs/clerk-morning.log}"
mkdir -p "$(dirname "$LOG")"
echo "$(date "+%Y-%m-%dT%H:%M:%S%z") clerk morning disabled — use weekly only ($ROOT/scripts/cron-clerk-weekly.sh)" >>"$LOG"
exit 0
