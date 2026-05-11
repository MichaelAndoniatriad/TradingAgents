#!/bin/bash
# Autonomous weekly clerk roll-up (cron / launchd). Uses .venv and loads .env.
#
# Environment (optional):
#   CLERK_MODE=etoro|watchlist   (default etoro — same as morning; needs eToro keys)
#   CLERK_WATCHLIST=/path.json (required if CLERK_MODE=watchlist)
#   CLERK_ETORO_TRIGGERS=/path.json
#   CLERK_WEEKLY_DAYS=7
#   CLERK_WEEKLY_NO_LLM=1     (skip LLM summary)
#   CLERK_WEEKLY_EXECUTE_DEEP=1  (run full graph for queued tickers; costs $; use CLERK_WEEKLY_MAX_DEEP)
#   CLERK_WEEKLY_MAX_DEEP=3
#   CLERK_WEBHOOK=https://...
#   CLERK_WEEKLY_CRON_LOG=~/.../clerk-weekly.log
#
# Pause: Clerk UI, or touch ~/.tradingagents/automation/clerk_scheduled_automation_paused
#
# Crontab example (Sunday 8:00):
#   0 8 * * SUN /path/to/TradingAgents-main/scripts/cron-clerk-weekly.sh

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOG="${CLERK_WEEKLY_CRON_LOG:-$HOME/.tradingagents/logs/clerk-weekly.log}"
mkdir -p "$(dirname "$LOG")"

PAUSE="${HOME}/.tradingagents/automation/clerk_scheduled_automation_paused"
if [[ -f "$PAUSE" ]]; then
  echo "$(date "+%Y-%m-%dT%H:%M:%S%z") clerk weekly skipped (automation paused)" >>"$LOG"
  exit 0
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

MODE="${CLERK_MODE:-etoro}"
DAYS="${CLERK_WEEKLY_DAYS:-7}"
ARGS=(clerk weekly --days "$DAYS")
if [[ "$MODE" == "etoro" ]]; then
  ARGS+=(--etoro)
  if [[ -n "${CLERK_ETORO_TRIGGERS:-}" ]]; then
    ARGS+=(--etoro-triggers "$CLERK_ETORO_TRIGGERS")
  fi
elif [[ "$MODE" == "watchlist" ]]; then
  if [[ -z "${CLERK_WATCHLIST:-}" ]]; then
    echo "$(date "+%Y-%m-%dT%H:%M:%S%z") ERROR: CLERK_WATCHLIST required when CLERK_MODE=watchlist" >>"$LOG"
    exit 1
  fi
  ARGS+=(--watchlist "$CLERK_WATCHLIST")
else
  echo "$(date "+%Y-%m-%dT%H:%M:%S%z") ERROR: CLERK_MODE must be etoro or watchlist" >>"$LOG"
  exit 1
fi
if [[ -n "${CLERK_WEEKLY_NO_LLM:-}" ]]; then
  ARGS+=(--no-llm)
fi
if [[ -n "${CLERK_WEEKLY_EXECUTE_DEEP:-}" ]]; then
  ARGS+=(--execute-deep-queue)
fi
if [[ -n "${CLERK_WEEKLY_MAX_DEEP:-}" ]]; then
  ARGS+=(--max-deep "$CLERK_WEEKLY_MAX_DEEP")
fi
if [[ -n "${CLERK_WEBHOOK:-}" ]]; then
  ARGS+=(--webhook "$CLERK_WEBHOOK")
fi

_ts() { date "+%Y-%m-%dT%H:%M:%S%z"; }

{
  echo "===== $(_ts) clerk weekly start ====="
  set +e
  if [[ -x "$ROOT/.venv/bin/tradingagents" ]]; then
    "$ROOT/.venv/bin/tradingagents" "${ARGS[@]}"
  else
    "$PY" -m cli.main "${ARGS[@]}"
  fi
  ec=$?
  set -e
  echo "===== $(_ts) clerk weekly end (exit $ec) ====="
  exit "$ec"
} >>"$LOG" 2>&1
