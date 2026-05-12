#!/usr/bin/env bash
# Run Streamlit for TradingAgents on a server (loads .env, survives until process exits).
# Used by systemd user service; tune STREAMLIT_* env vars as needed.
#
# Optional env:
#   STREAMLIT_BIN   — path to streamlit executable (default: miniconda env ta)
#   STREAMLIT_SERVER_ADDRESS — default 127.0.0.1 (use 0.0.0.0 + NSG if you want public)
#   STREAMLIT_SERVER_PORT    — default 8501

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT/.env"
  set +a
fi

export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"

if [[ -x "$ROOT/.venv/bin/streamlit" ]]; then
  ST="${ROOT}/.venv/bin/streamlit"
elif [[ -n "${STREAMLIT_BIN:-}" ]]; then
  ST="$STREAMLIT_BIN"
elif [[ -x "${HOME}/miniconda3/envs/ta/bin/streamlit" ]]; then
  ST="${HOME}/miniconda3/envs/ta/bin/streamlit"
else
  ST="streamlit"
fi

ADDR="${STREAMLIT_SERVER_ADDRESS:-127.0.0.1}"
PORT="${STREAMLIT_SERVER_PORT:-8501}"

exec "$ST" run ui/streamlit_app.py \
  --server.address "$ADDR" \
  --server.port "$PORT" \
  --browser.gatherUsageStats=false \
  "$@"
