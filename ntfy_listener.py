#!/usr/bin/env python3
"""ntfy_listener.py — Two-way ntfy.sh command listener for TradingAgents.

Polls the ntfy topic for incoming commands sent from the phone and replies
via the same topic.  Runs as a long-lived process (or a systemd user unit).

Supported commands (sent as plain message text in the ntfy app):
  /analyze TICKER   – run advisor portfolio run-due for that ticker (one-off)
  /status           – show pending advisor jobs + last replan date
  /portfolio        – summary of recent analysis reports
  /help             – list available commands
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: load .env from the project root before anything else
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env", override=False)
except ImportError:
    pass  # python-dotenv optional; fall back to environment as-is

import requests  # noqa: E402 — after dotenv so NTFY_TOPIC may be set there

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_BASE = os.environ.get("NTFY_BASE_URL", "https://ntfy.sh")
POLL_INTERVAL = int(os.environ.get("NTFY_POLL_INTERVAL", "3"))
REQUEST_TIMEOUT = 15  # seconds

LOG_DIR = Path.home() / ".tradingagents" / "logs"
LOG_FILE = LOG_DIR / "ntfy_listener.log"

# Marker used to identify our own outgoing messages so we don't echo them
# back to ourselves.  ntfy tags the server-sent messages with a "upstream"
# field only when using its cloud relay; polling messages don't include it.
# We instead store the last N message IDs we sent and skip those.
_SENT_IDS: set[str] = set()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
    logger = logging.getLogger("ntfy_listener")
    logger.setLevel(logging.DEBUG)
    # File handler
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    # Stdout handler
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


log = _setup_logging()

# ---------------------------------------------------------------------------
# ntfy helpers
# ---------------------------------------------------------------------------

def _ntfy_publish(topic: str, message: str, title: str = "TradingAgents") -> None:
    """POST a reply back to the ntfy topic.  Swallows errors and logs them."""
    url = f"{NTFY_BASE}/{topic}"
    try:
        resp = requests.post(
            url,
            data=message.encode("utf-8"),
            headers={
                "Title": title,
                "Priority": "default",
                "Content-Type": "text/plain; charset=utf-8",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        # Track the ID of our own outgoing message so we don't process it
        if isinstance(data, dict) and data.get("id"):
            _SENT_IDS.add(data["id"])
            # Keep the set bounded
            if len(_SENT_IDS) > 500:
                _SENT_IDS.discard(next(iter(_SENT_IDS)))
        log.info("SENT reply (%d chars)", len(message))
    except Exception as exc:  # noqa: BLE001
        log.error("Failed to publish ntfy reply: %s", exc)


def _poll_messages(topic: str, since: str) -> tuple[list[dict], str]:
    """Poll ntfy for new messages since the given message ID or timestamp.

    Returns (messages, new_since) where new_since is the ID of the last
    message seen (or the original since value if nothing new arrived).
    """
    url = f"{NTFY_BASE}/{topic}/json"
    params = {"poll": "1", "since": since}
    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        log.warning("Poll failed: %s", exc)
        return [], since

    messages: list[dict] = []
    new_since = since
    for line in resp.text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(msg, dict):
            continue
        msg_id = msg.get("id", "")
        # Update the cursor to the latest message we've seen
        if msg_id:
            new_since = msg_id
        messages.append(msg)
    return messages, new_since

# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _cmd_help() -> str:
    return (
        "TradingAgents ntfy commands:\n"
        "  /analyze TICKER — one-off analysis for a ticker (e.g. /analyze AAPL)\n"
        "  /status         — pending advisor jobs + last replan date\n"
        "  /portfolio      — recent analysis signal summary\n"
        "  /help           — this message"
    )


def _cmd_status() -> str:
    """Read state.json and return a compact summary."""
    state_path = Path.home() / ".tradingagents" / "portfolio_advisor" / "state.json"
    if not state_path.is_file():
        return "No advisor state found at " + str(state_path)

    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return f"Could not read state.json: {exc}"

    lines: list[str] = []
    last_replan = data.get("last_replan_iso") or "never"
    last_weekly = data.get("last_weekly_check_iso") or "never"
    lines.append(f"Last replan: {last_replan}")
    lines.append(f"Last weekly check: {last_weekly}")

    jobs = [j for j in (data.get("jobs") or []) if j.get("status") == "pending"]
    if jobs:
        lines.append(f"\nPending jobs ({len(jobs)}):")
        for j in sorted(jobs, key=lambda x: str(x.get("scheduled_at") or "")):
            ticker = j.get("ticker", "?")
            when = j.get("scheduled_at", "?")
            reason = (j.get("reason") or "")[:60]
            lines.append(f"  {ticker} @ {when}  {reason}")
    else:
        lines.append("\nNo pending jobs.")

    return "\n".join(lines)


def _cmd_portfolio() -> str:
    """Scan the results directory for recent complete_report.md files."""
    results_dir = Path.home() / ".tradingagents" / "logs"
    if not results_dir.is_dir():
        return f"Results directory not found: {results_dir}"

    # Find all complete_report.md files, newest first
    reports = sorted(
        results_dir.rglob("complete_report.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:5]  # up to 5 most recent

    if not reports:
        return "No completed analysis reports found."

    lines: list[str] = [f"Recent reports ({len(reports)}):"]
    for rpt in reports:
        # Path is typically: logs/TICKER/DATE/reports/complete_report.md
        parts = rpt.parts
        # Extract ticker + date from path components
        try:
            mtime = datetime.fromtimestamp(rpt.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            # Try to extract a "final decision" headline from the report
            text = rpt.read_text(encoding="utf-8", errors="replace")
            decision_snippet = _extract_decision(text)
            # Ticker is usually two levels up from the file
            ticker_guess = rpt.parent.parent.parent.name  # logs/TICKER/DATE/reports/
            lines.append(f"\n{ticker_guess} ({mtime})")
            if decision_snippet:
                lines.append(f"  {decision_snippet}")
        except Exception:  # noqa: BLE001
            lines.append(f"\n{rpt}")

    return "\n".join(lines)


def _extract_decision(text: str) -> str:
    """Pull a short decision snippet from a complete_report.md."""
    # Look for the Portfolio Manager Decision section heading and grab a snippet
    marker = "## V. Portfolio Manager Decision"
    idx = text.find(marker)
    if idx == -1:
        # Fallback: look for "final_trade_decision" style heading
        marker = "## Portfolio Management Decision"
        idx = text.find(marker)
    if idx == -1:
        return ""
    snippet = text[idx + len(marker):idx + len(marker) + 300].strip()
    # First non-empty line after the heading
    for line in snippet.splitlines():
        line = line.strip().lstrip("#").strip()
        if line and not line.startswith("###"):
            return line[:120]
    return ""


def _cmd_analyze(ticker: str, topic: str) -> str:
    """Trigger a one-off advisor run-due for the given ticker.

    We queue it as a subprocess so the listener loop isn't blocked.
    The completion (or failure) is announced asynchronously via a
    follow-up ntfy message posted from the subprocess wrapper below.
    """
    ticker = ticker.strip().upper()
    if not ticker or not all(c.isalnum() or c in "._-^" for c in ticker):
        return f"Invalid ticker: {ticker!r}"

    python = sys.executable
    # We launch a small inline script that runs run-due, then POSTs the result
    # back to the topic.  This keeps the listener non-blocking.
    inline = (
        f"import subprocess, requests, os\n"
        f"from pathlib import Path\n"
        f"try:\n"
        f"    from dotenv import load_dotenv\n"
        f"    load_dotenv(Path({str(_PROJECT_ROOT)!r}) / '.env', override=False)\n"
        f"except Exception:\n"
        f"    pass\n"
        f"topic = os.environ.get('NTFY_TOPIC', {topic!r})\n"
        f"base = os.environ.get('NTFY_BASE_URL', 'https://ntfy.sh')\n"
        f"cmd = ['{python}', '-m', 'cli.main', 'advisor', 'portfolio', 'run-due']\n"
        f"r = subprocess.run(cmd, capture_output=True, text=True, cwd={str(_PROJECT_ROOT)!r})\n"
        f"ok = r.returncode == 0\n"
        f"body = (r.stdout or r.stderr or '(no output)')[-600:]\n"
        f"msg = f'[{ticker}] run-due {{\"OK\" if ok else \"FAILED\"}}:\\n{{body}}'\n"
        f"requests.post(f'{{base}}/{{topic}}', data=msg.encode(), timeout=30)\n"
    )
    try:
        subprocess.Popen(
            [python, "-c", inline],
            cwd=str(_PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return f"Queued run-due for {ticker} — result will arrive shortly via ntfy."
    except Exception as exc:  # noqa: BLE001
        return f"Failed to launch analyze subprocess: {exc}"


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def _dispatch(text: str, topic: str) -> str:
    text = text.strip()
    lower = text.lower()

    if lower == "/help":
        return _cmd_help()

    if lower == "/status":
        return _cmd_status()

    if lower == "/portfolio":
        return _cmd_portfolio()

    if lower.startswith("/analyze"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            return "Usage: /analyze TICKER  (e.g. /analyze AAPL)"
        return _cmd_analyze(parts[1].strip(), topic)

    # Unknown command
    if text.startswith("/"):
        return f"Unknown command: {text!r}\nSend /help for a list of available commands."

    # Non-command messages: silently ignore
    return ""


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    if not NTFY_TOPIC:
        log.error(
            "NTFY_TOPIC environment variable is not set. "
            "Add it to your .env file or export it before starting."
        )
        sys.exit(1)

    log.info("ntfy listener starting — topic=%s poll_interval=%ds", NTFY_TOPIC, POLL_INTERVAL)
    log.info("Logs: %s", LOG_FILE)

    # Seed 'since' with the current epoch so we only process messages
    # arriving *after* we start (avoids replaying historical commands).
    since = str(int(time.time()))

    while True:
        try:
            messages, since = _poll_messages(NTFY_TOPIC, since)
            for msg in messages:
                msg_id = msg.get("id", "")
                msg_event = msg.get("event", "message")

                # Skip keepalive / open events
                if msg_event != "message":
                    continue

                # Skip messages we ourselves sent
                if msg_id in _SENT_IDS:
                    continue

                text = (msg.get("message") or "").strip()
                if not text:
                    continue

                log.info("RECV [%s] %r", msg_id, text[:120])

                reply = _dispatch(text, NTFY_TOPIC)
                if reply:
                    log.info("DISPATCH reply: %r", reply[:80])
                    _ntfy_publish(NTFY_TOPIC, reply)

        except KeyboardInterrupt:
            log.info("Interrupted — shutting down.")
            break
        except Exception as exc:  # noqa: BLE001
            log.exception("Unexpected error in main loop: %s", exc)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
