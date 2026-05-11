#!/bin/bash
# Monthly lookout: capped deep research on a candidate list + LLM synthesis.
#
# Set CLERK_MONTHLY_CANDIDATES to a JSON path (see cli/static/clerk_monthly_candidates.example.json).
#
# Crontab example (1st of month 9:00 local):
#   0 9 1 * * /path/to/TradingAgents-main/scripts/cron-clerk-monthly.sh

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOG="${CLERK_MONTHLY_CRON_LOG:-$HOME/.tradingagents/logs/clerk-monthly.log}"
mkdir -p "$(dirname "$LOG")"

PAUSE="${HOME}/.tradingagents/automation/clerk_scheduled_automation_paused"
if [[ -f "$PAUSE" ]]; then
  echo "$(date "+%Y-%m-%dT%H:%M:%S%z") clerk monthly skipped (automation paused)" >>"$LOG"
  exit 0
fi

if [[ -z "${CLERK_MONTHLY_CANDIDATES:-}" ]]; then
  echo "$(date "+%Y-%m-%dT%H:%M:%S%z") ERROR: set CLERK_MONTHLY_CANDIDATES=/path/to/candidates.json" >>"$LOG"
  exit 1
fi

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

ARGS=(clerk monthly --candidates "$CLERK_MONTHLY_CANDIDATES")
if [[ -n "${CLERK_MONTHLY_MAX_DEEP:-}" ]]; then
  ARGS+=(--max-deep "$CLERK_MONTHLY_MAX_DEEP")
fi
if [[ -n "${CLERK_WEBHOOK:-}" ]]; then
  ARGS+=(--webhook "$CLERK_WEBHOOK")
fi

_ts() { date "+%Y-%m-%dT%H:%M:%S%z"; }

{
  echo "===== $(_ts) clerk monthly start ====="
  set +e
  if [[ -x "$ROOT/.venv/bin/tradingagents" ]]; then
    "$ROOT/.venv/bin/tradingagents" "${ARGS[@]}"
  else
    "$PY" -m cli.main "${ARGS[@]}"
  fi
  ec=$?
  set -e
  echo "===== $(_ts) clerk monthly end (exit $ec) ====="
  exit "$ec"
} >>"$LOG" 2>&1
