#!/bin/sh
# Local UI. Uses .venv if present (recommended — see scripts/setup-venv.sh).
# Usage: from repo root —  sh scripts/run-ui.sh
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
else
  PY="python3"
fi
exec "$PY" -m streamlit run ui/streamlit_app.py --browser.gatherUsageStats=false "$@"
