"""Launch the local Streamlit UI (``tradingagents-ui`` console script)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    ui = root / "ui" / "streamlit_app.py"
    if not ui.is_file():
        sys.stderr.write(f"UI file not found: {ui}\n")
        sys.exit(1)
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(ui),
        "--browser.gatherUsageStats=false",
        "--server.fileWatcherType=none",
    ]
    raise SystemExit(subprocess.call(cmd, cwd=str(root)))


if __name__ == "__main__":
    main()
