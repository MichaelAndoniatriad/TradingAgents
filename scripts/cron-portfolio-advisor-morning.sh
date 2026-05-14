#!/bin/bash
# Send morning digest of open portfolio action items via ntfy.
# Run from cron at 6 AM UTC daily (= 10 AM Gulf / UAE time).
#
#   0 6 * * * /opt/tradingagents/scripts/cron-portfolio-advisor-morning.sh

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LOG="$HOME/.tradingagents/logs/portfolio-advisor-morning.log"
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
  source "$ROOT/.env"
  set +a
fi

export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"

_ts() { date "+%Y-%m-%dT%H:%M:%S%z"; }

{
  echo "===== $(_ts) portfolio advisor morning-digest start ====="
  set +e
  "$PY" -m cli.main advisor portfolio morning-digest
  ec=$?
  set -e
  echo "===== $(_ts) portfolio advisor morning-digest end (exit $ec) ====="
  exit "$ec"
} >>"$LOG" 2>&1
