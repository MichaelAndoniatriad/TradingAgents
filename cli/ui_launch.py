"""Launch the local Streamlit UI (``tradingagents-ui`` console script)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _python_for_ui(root: Path) -> str:
    """Prefer the project ``.venv`` interpreter so UI works after ``setup-venv.sh``."""
    candidates = [
        root / ".venv" / "bin" / "python",
        root / ".venv" / "bin" / "python3",
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    return sys.executable


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    ui = root / "ui" / "streamlit_app.py"
    if not ui.is_file():
        sys.stderr.write(f"UI file not found: {ui}\n")
        sys.exit(1)
    py = _python_for_ui(root)
    cmd = [
        py,
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
