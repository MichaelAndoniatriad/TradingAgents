#!/bin/bash
# Autonomous daily clerk run (cron / launchd). Uses project .venv and loads .env.
#
# Install once:
#   sh scripts/setup-venv.sh
#
# Environment (optional):
#   CLERK_MODE=etoro|watchlist     (default: etoro — tickers from eToro open positions)
#   CLERK_WATCHLIST=/path.json     (required if CLERK_MODE=watchlist)
#   CLERK_ETORO_TRIGGERS=/path.json  (optional; copy triggers/analysts from this file)
#   CLERK_DEEP_RESEARCH=1          (set to run full graph when triggers hit; costs $)
#   CLERK_WEBHOOK=https://...      (optional; overrides TRADINGAGENTS_CLERK_WEBHOOK_URL)
#   CLERK_CRON_LOG=~/.../clerk-morning.log
#
# Pause: use the Clerk page in the UI (Pause), or touch:
#   ~/.tradingagents/automation/clerk_scheduled_automation_paused
#
# Crontab example (7:00 daily):
#   0 7 * * * /path/to/TradingAgents-main/scripts/cron-clerk-morning.sh

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOG="${CLERK_CRON_LOG:-$HOME/.tradingagents/logs/clerk-morning.log}"
mkdir -p "$(dirname "$LOG")"

PAUSE="${HOME}/.tradingagents/automation/clerk_scheduled_automation_paused"
if [[ -f "$PAUSE" ]]; then
  echo "$(date "+%Y-%m-%dT%H:%M:%S%z") clerk morning skipped (automation paused — remove $PAUSE or use UI Continue)" >>"$LOG"
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
ARGS=(clerk morning)

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

if [[ -n "${CLERK_DEEP_RESEARCH:-}" ]]; then
  ARGS+=(--deep-research)
fi
if [[ -n "${CLERK_WEBHOOK:-}" ]]; then
  ARGS+=(--webhook "$CLERK_WEBHOOK")
fi

_ts() { date "+%Y-%m-%dT%H:%M:%S%z"; }

{
  echo "===== $(_ts) clerk morning start ====="
  set +e
  if [[ -x "$ROOT/.venv/bin/tradingagents" ]]; then
    "$ROOT/.venv/bin/tradingagents" "${ARGS[@]}"
  else
    "$PY" -m cli.main "${ARGS[@]}"
  fi
  ec=$?
  set -e
  echo "===== $(_ts) clerk morning end (exit $ec) ====="
  exit "$ec"
} >>"$LOG" 2>&1
