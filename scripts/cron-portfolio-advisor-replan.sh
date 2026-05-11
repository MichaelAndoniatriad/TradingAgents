#!/bin/bash
# Full LLM reschedule (replaces pending deep-research jobs). Costs quick-model tokens.
# Use a lower frequency than the weekly check, e.g. monthly or same day earlier/later.
#
#   0 10 * * SAT /ABS/PATH/TradingAgents-main/scripts/cron-portfolio-advisor-replan.sh

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOG="${PORTFOLIO_ADVISOR_REPLAN_CRON_LOG:-$HOME/.tradingagents/logs/portfolio-advisor-replan.log}"
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
  echo "===== $(_ts) portfolio advisor replan start ====="
  set +e
  "$PY" -m cli.main advisor portfolio replan
  ec=$?
  set -e
  echo "===== $(_ts) portfolio advisor replan end (exit $ec) ====="
  exit "$ec"
} >>"$LOG" 2>&1
