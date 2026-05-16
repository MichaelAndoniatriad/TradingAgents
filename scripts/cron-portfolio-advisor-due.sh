#!/bin/bash
# Run pending portfolio-advisor deep-research jobs whose scheduled time has passed.
# Run from cron every 10–30 minutes (see PORTFOLIO_ADVISOR_RUN_DUE_MAX in default_config).
#
#   */15 * * * * /ABS/PATH/TradingAgents-main/scripts/cron-portfolio-advisor-due.sh

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOG="${PORTFOLIO_ADVISOR_DUE_CRON_LOG:-$HOME/.tradingagents/logs/portfolio-advisor-due.log}"
mkdir -p "$(dirname "$LOG")"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
elif command -v python3.12 &>/dev/null; then
  PY="$(command -v python3.12)"
else
  PY="python3"
fi

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT/.env"
  set +a
fi

export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"

_ts() { date "+%Y-%m-%dT%H:%M:%S%z"; }

LOCK="$HOME/.tradingagents/run/cron-portfolio-advisor-due.lock"
mkdir -p "$(dirname "$LOCK")"
exec 200>"$LOCK"
if ! flock -n 200; then
  echo "$(_ts) cron-portfolio-advisor-due: another instance is holding the lock; exiting" >>"$LOG"
  exit 0
fi

{
  echo "===== $(_ts) portfolio advisor run-due start ====="
  set +e
  "$PY" -m cli.main advisor portfolio run-due
  ec=$?
  set -e
  echo "===== $(_ts) portfolio advisor run-due end (exit $ec) ====="
  exit "$ec"
} >>"$LOG" 2>&1
