#!/bin/bash
# Price-only portfolio watchdog (no LLM). Skips outside the US equity watch window
# unless you pass --force via PORTFOLIO_ADVISOR_WATCHDOG_FORCE=1 (not recommended for cron).
# Typical cadence: every 5 minutes on weekdays (same idea as .github/workflows/advisor-watchdog.yml).
#
#   */5 * * * 1-5 /ABS/PATH/TradingAgents-main/scripts/cron-portfolio-advisor-watchdog.sh
#
# Env:
#   PORTFOLIO_ADVISOR_WATCHDOG_CRON_LOG=~/.../portfolio-advisor-watchdog.log
#   PORTFOLIO_ADVISOR_WATCHDOG_FORCE=1   # optional: ignore market-hours gate

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOG="${PORTFOLIO_ADVISOR_WATCHDOG_CRON_LOG:-$HOME/.tradingagents/logs/portfolio-advisor-watchdog.log}"
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
  echo "===== $(_ts) portfolio advisor watchdog start ====="
  set +e
  if [[ -n "${PORTFOLIO_ADVISOR_WATCHDOG_FORCE:-}" ]]; then
    "$PY" -m cli.main advisor portfolio watchdog --force
  else
    "$PY" -m cli.main advisor portfolio watchdog
  fi
  ec=$?
  set -e
  echo "===== $(_ts) portfolio advisor watchdog end (exit $ec) ====="
  exit "$ec"
} >>"$LOG" 2>&1
