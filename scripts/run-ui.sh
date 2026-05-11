#!/bin/sh
# Local UI without pip console scripts on PATH.
# Usage: from repo root —  sh scripts/run-ui.sh
cd "$(dirname "$0")/.." || exit 1
exec python3 -m streamlit run ui/streamlit_app.py --browser.gatherUsageStats=false "$@"
