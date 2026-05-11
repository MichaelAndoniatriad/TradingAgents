#!/bin/bash
# Weekly **light** portfolio check (eToro snapshot vs saved state, overdue/stale jobs,
# auto-cancel jobs for sold tickers). Does **not** run a full LLM replan — use
# cron-portfolio-advisor-replan.sh for that (same or different weekday).
# Default: only runs on TRADINGAGENTS_PORTFOLIO_ADVISOR_WEEKDAY (5=Saturday).
#
# Env:
#   PORTFOLIO_ADVISOR_CRON_LOG=~/.../portfolio-advisor-weekly.log
#   TRADINGAGENTS_PORTFOLIO_ADVISOR_WEEKDAY=6   # Sunday
#   PORTFOLIO_ADVISOR_WEEKLY_FORCE=1            # ignore weekday gate
# Requires: ETORO_* keys, LLM keys, optional TRADINGAGENTS_ANALYSIS_* email / webhook
#
# Crontab (Saturday 9:00):
#   0 9 * * SAT /ABS/PATH/TradingAgents-main/scripts/cron-portfolio-advisor-weekly.sh

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOG="${PORTFOLIO_ADVISOR_CRON_LOG:-$HOME/.tradingagents/logs/portfolio-advisor-weekly.log}"
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

{
  echo "===== $(_ts) portfolio advisor weekly start ====="
  set +e
  if [[ -n "${PORTFOLIO_ADVISOR_WEEKLY_FORCE:-}" ]]; then
    "$PY" -m cli.main advisor portfolio weekly --force
  else
    "$PY" -m cli.main advisor portfolio weekly
  fi
  ec=$?
  set -e
  echo "===== $(_ts) portfolio advisor weekly end (exit $ec) ====="
  exit "$ec"
} >>"$LOG" 2>&1
