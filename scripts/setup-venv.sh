#!/bin/sh
# Create a project virtual env and install TradingAgents (avoids Homebrew PEP 668 errors).
# Usage:  sh scripts/setup-venv.sh
#         sh scripts/setup-venv.sh python3.12
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${1:-python3.12}"
if ! command -v "$PY" >/dev/null 2>&1; then
  PY="python3"
fi

echo "Using: $PY"
"$PY" -m venv .venv
# shellcheck source=/dev/null
. .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .

echo ""
echo "Done. Every new terminal session:"
echo "  cd \"$ROOT\""
echo "  source .venv/bin/activate"
echo "  python -m cli.main ui          # browser UI"
echo "  python -m streamlit run ui/streamlit_app.py   # same UI"
echo "  tradingagents analyze            # terminal wizard"
