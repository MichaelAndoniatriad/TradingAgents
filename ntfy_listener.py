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

import collections
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

CHAT_HISTORY_PATH = Path.home() / ".tradingagents" / "portfolio_advisor" / "ntfy_chat_history.jsonl"

# Track IDs of our own outgoing messages to avoid echo-processing them.
# deque enforces the bound automatically; the set gives O(1) membership tests.
_SENT_IDS: set[str] = set()
_SENT_IDS_QUEUE: collections.deque[str] = collections.deque(maxlen=500)

# ---------------------------------------------------------------------------
# Logging — initialised inside main() to avoid side effects on import
# ---------------------------------------------------------------------------

def _setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
    logger = logging.getLogger("ntfy_listener")
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


log = logging.getLogger("ntfy_listener")

# ---------------------------------------------------------------------------
# ntfy helpers
# ---------------------------------------------------------------------------

def _ntfy_publish(topic: str, message: str, title: str = "PM") -> None:
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
        if isinstance(data, dict) and data.get("id"):
            msg_id = data["id"]
            if len(_SENT_IDS_QUEUE) == _SENT_IDS_QUEUE.maxlen:
                _SENT_IDS.discard(_SENT_IDS_QUEUE[0])
            _SENT_IDS_QUEUE.append(msg_id)
            _SENT_IDS.add(msg_id)
        _log_chat("pm", message)
        log.info("SENT reply (%d chars)", len(message))
    except Exception as exc:  # noqa: BLE001
        log.error("Failed to publish ntfy reply: %s", exc)


def _stream_messages(topic: str, since: str):
    """Open a persistent streaming connection to ntfy and yield messages as they arrive.

    Uses the streaming JSON endpoint (no poll=1) so ntfy pushes events to us.
    One persistent connection instead of repeated polls — avoids 429 rate limits.
    Yields (msg_dict, new_since) tuples. Raises on connection error so the
    caller can reconnect with backoff.
    """
    url = f"{NTFY_BASE}/{topic}/json"
    params = {"since": since}
    with requests.get(url, params=params, stream=True, timeout=None) as resp:
        resp.raise_for_status()
        for raw in resp.iter_lines():
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict):
                continue
            msg_id = msg.get("id", "")
            new_since = msg_id if msg_id else since
            yield msg, new_since

# ---------------------------------------------------------------------------
# Chat history — log every exchange so the PM has conversation context
# ---------------------------------------------------------------------------

def _log_chat(role: str, text: str) -> None:
    """Append one message to the rolling chat history JSONL."""
    try:
        CHAT_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = json.dumps({
            "role": role,
            "text": text[:600],
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
        with open(CHAT_HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass


def _read_chat_context(n: int = 10) -> str:
    """Return the last n exchanges formatted for the PM prompt."""
    if not CHAT_HISTORY_PATH.is_file():
        return ""
    try:
        lines = CHAT_HISTORY_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    entries = []
    for line in lines[-n * 2:]:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not entries:
        return ""
    parts = [f"[{e['ts']}] {'You' if e['role'] == 'user' else 'PM'}: {e['text']}"
             for e in entries[-n:]]
    return "Recent conversation:\n" + "\n".join(parts)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _cmd_help() -> str:
    return (
        "TradingAgents ntfy commands:\n"
        "  /analyze TICKER — one-off analysis for a ticker (e.g. /analyze AAPL)\n"
        "  /status         — pending advisor jobs + last replan date\n"
        "  /portfolio      — recent analysis signal summary\n"
        "  /ask <question> — ask the Portfolio Manager anything (or just send plain text)\n"
        "  cancel          — undo the last PM action (cancels queued jobs)\n"
        "  done TICKER     — mark action item closed (e.g. done TEAM)\n"
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
        try:
            st = rpt.stat()
            mtime = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
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


_DECISION_MARKERS = (
    "## V. Portfolio Manager Decision",
    "## Portfolio Management Decision",
)


def _extract_decision(text: str) -> str:
    """Pull a short decision snippet from a complete_report.md."""
    marker = next((m for m in _DECISION_MARKERS if m in text), None)
    if marker is None:
        return ""
    idx = text.find(marker)
    snippet = text[idx + len(marker):idx + len(marker) + 300].strip()
    # First non-empty line after the heading
    for line in snippet.splitlines():
        line = line.strip().lstrip("#").strip()
        if line and not line.startswith("###"):
            return line[:120]
    return ""


def _cmd_ask(question: str, topic: str) -> str:
    """Send a freeform question to the PM and reply with its response via ntfy.

    Runs async (subprocess) so the listener loop stays unblocked.
    Sends an immediate ACK, then a follow-up with the PM's answer.
    """
    question = question.strip()
    if not question:
        return "Usage: /ask <question>  (or just type any plain-text message)"

    python = sys.executable
    q_repr = repr(question)
    topic_repr = repr(topic)
    root_repr = repr(str(_PROJECT_ROOT))

    inline = (
        f"import sys, os, json\n"
        f"from pathlib import Path\n"
        f"try:\n"
        f"    from dotenv import load_dotenv\n"
        f"    load_dotenv(Path({root_repr}) / '.env', override=False)\n"
        f"except Exception:\n"
        f"    pass\n"
        f"sys.path.insert(0, {root_repr})\n"
        f"import requests\n"
        f"topic = os.environ.get('NTFY_TOPIC', {topic_repr})\n"
        f"base = os.environ.get('NTFY_BASE_URL', 'https://ntfy.sh')\n"
        f"def post(msg, title='PM'):\n"
        f"    requests.post(f'{{base}}/{{topic}}', data=msg.encode('utf-8'),\n"
        f"        headers={{'Title': title, 'Content-Type': 'text/plain; charset=utf-8'}}, timeout=30)\n"
        f"    try:\n"
        f"        import json as _j\n"
        f"        from pathlib import Path\n"
        f"        from datetime import datetime\n"
        f"        _p = Path.home() / '.tradingagents' / 'portfolio_advisor' / 'ntfy_chat_history.jsonl'\n"
        f"        _p.parent.mkdir(parents=True, exist_ok=True)\n"
        f"        _e = _j.dumps({{'role':'pm','text':msg[:600],'ts':datetime.now().strftime('%Y-%m-%d %H:%M')}})\n"
        f"        _p.open('a').write(_e+'\\n')\n"
        f"    except Exception: pass\n"
        f"try:\n"
        f"    import tradingagents\n"
        f"    from ui.user_config import merged_app_config\n"
        f"    from tradingagents.portfolio_advisor.advisor_pm import run_pm_cycle\n"
        f"    from pathlib import Path\n"
        f"    cfg = merged_app_config()\n"
        f"    _chat_path = Path.home() / '.tradingagents' / 'portfolio_advisor' / 'ntfy_chat_history.jsonl'\n"
        f"    _chat_ctx = ''\n"
        f"    if _chat_path.is_file():\n"
        f"        import json as _json\n"
        f"        _lines = _chat_path.read_text(encoding='utf-8').splitlines()\n"
        f"        _entries = []\n"
        f"        for _l in _lines[-20:]:\n"
        f"            try: _entries.append(_json.loads(_l))\n"
        f"            except: pass\n"
        f"        _parts = [f\"[{{e['ts']}}] {{'You' if e['role']=='user' else 'PM'}}: {{e['text']}}\" for e in _entries[-10:]]\n"
        f"        if _parts: _chat_ctx = 'Recent conversation:\\n' + '\\n'.join(_parts)\n"
        f"    _full_ctx = (_chat_ctx + '\\n\\nCurrent question: ' + {q_repr}).strip() if _chat_ctx else {q_repr}\n"
        f"    result = run_pm_cycle(cfg, trigger='ntfy_question', extra_context=_full_ctx)\n"
        f"    summary = (result.executive_summary or '').strip()\n"
        f"    if len(summary) > 500:\n"
        f"        summary = summary[:497] + '...'\n"
        f"    stances = result.stances or []\n"
        f"    parts = [summary] if summary else ['(no summary)']\n"
        f"    if stances:\n"
        f"        parts.append('')\n"
        f"        for s in stances[:5]:\n"
        f"            if not isinstance(s, dict):\n"
        f"                continue\n"
        f"            tk = str(s.get('ticker') or '?')\n"
        f"            st = str(s.get('stance') or '?')\n"
        f"            ra = str(s.get('rationale') or '')[:100]\n"
        f"            parts.append(f'{{tk}} {{st}}: {{ra}}')\n"
        f"    if result.append_jobs or result.request_replan:\n"
        f"        parts.append('')\n"
        f"        parts.append('Reply CANCEL to undo.')\n"
        f"    push = (getattr(result, 'push_note', None) or '').strip()\n"
        f"    if push:\n"
        f"        parts.append('')\n"
        f"        parts.append(push[:280])\n"
        f"    post('\\n'.join(parts), title='PM')\n"
        f"except Exception as exc:\n"
        f"    post(f'PM error: {{exc}}', title='PM')\n"
    )
    try:
        subprocess.Popen(
            [python, "-c", inline],
            cwd=str(_PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return "Thinking... answer coming shortly."
    except Exception as exc:  # noqa: BLE001
        return f"Failed to launch PM subprocess: {exc}"


def _cmd_yes(topic: str) -> str:
    """No-op stub: PM cycles auto-apply; YES is not used. Returns an informational reply."""
    return (
        "YES is not used — the PM applies its own actions automatically. "
        "Reply CANCEL to undo the last PM action."
    )


def _cmd_no() -> str:
    """No-op stub: PM cycles auto-apply; NO is not used."""
    return (
        "NO is not used — the PM applies its own actions automatically. "
        "Reply CANCEL to undo the last PM action."
    )


def _cmd_cancel(topic: str) -> str:
    """Cancel the jobs queued by the last PM action."""
    python = sys.executable
    root_repr = repr(str(_PROJECT_ROOT))
    topic_repr = repr(topic)
    inline = (
        f"import sys, os\n"
        f"from pathlib import Path\n"
        f"try:\n"
        f"    from dotenv import load_dotenv\n"
        f"    load_dotenv(Path({root_repr}) / '.env', override=False)\n"
        f"except Exception:\n"
        f"    pass\n"
        f"sys.path.insert(0, {root_repr})\n"
        f"import requests\n"
        f"topic = os.environ.get('NTFY_TOPIC', {topic_repr})\n"
        f"base = os.environ.get('NTFY_BASE_URL', 'https://ntfy.sh')\n"
        f"def post(msg, title='PM'):\n"
        f"    requests.post(f'{{base}}/{{topic}}', data=msg.encode('utf-8'),\n"
        f"        headers={{'Title': title, 'Content-Type': 'text/plain; charset=utf-8'}}, timeout=30)\n"
        f"try:\n"
        f"    from ui.user_config import merged_app_config\n"
        f"    from tradingagents.portfolio_advisor.advisor_pm import cancel_last_action\n"
        f"    cfg = merged_app_config()\n"
        f"    result = cancel_last_action(cfg)\n"
        f"    post(result, title='PM')\n"
        f"except Exception as exc:\n"
        f"    post(f'Cancel error: {{exc}}', title='PM')\n"
    )
    try:
        subprocess.Popen(
            [python, "-c", inline],
            cwd=str(_PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return ""
    except Exception as exc:
        return f"Failed to launch cancel subprocess: {exc}"


def _cmd_done(ticker: str) -> str:
    """Mark open action items for a ticker as done."""
    python = sys.executable
    root_repr = repr(str(_PROJECT_ROOT))
    ticker_repr = repr(ticker.strip().upper())
    inline = (
        f"import sys\n"
        f"from pathlib import Path\n"
        f"try:\n"
        f"    from dotenv import load_dotenv\n"
        f"    load_dotenv(Path({root_repr}) / '.env', override=False)\n"
        f"except Exception:\n"
        f"    pass\n"
        f"sys.path.insert(0, {root_repr})\n"
        f"from ui.user_config import merged_app_config\n"
        f"from tradingagents.portfolio_advisor.action_log import mark_done\n"
        f"cfg = merged_app_config()\n"
        f"n = mark_done(cfg, {ticker_repr})\n"
        f"import requests, os\n"
        f"base = os.environ.get('NTFY_BASE_URL', 'https://ntfy.sh')\n"
        f"topic = os.environ.get('NTFY_TOPIC', 'default')\n"
        f"msg = f'{ticker_repr[1:-1]} done: closed {{n}} action item(s).' if n else f'No open actions found for {ticker_repr[1:-1]}.'\n"
        f"requests.post(f'{{base}}/{{topic}}', data=msg.encode(), headers={{'Title': 'PM'}}, timeout=30)\n"
    )
    try:
        subprocess.Popen(
            [python, "-c", inline],
            cwd=str(_PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return ""
    except Exception as exc:
        return f"Failed to mark done: {exc}"


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

    if lower in ("cancel", "/cancel"):
        return _cmd_cancel(topic)

    if lower in ("yes", "y", "/yes"):
        return _cmd_yes(topic)

    if lower in ("no", "n", "/no"):
        return _cmd_no()

    if lower.startswith("/done") or lower.startswith("done "):
        parts = text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            return "Usage: done TICKER  (e.g. done TEAM)"
        return _cmd_done(parts[1].strip())

    if lower.startswith("/analyze"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            return "Usage: /analyze TICKER  (e.g. /analyze AAPL)"
        return _cmd_analyze(parts[1].strip(), topic)

    if lower.startswith("/ask"):
        parts = text.split(maxsplit=1)
        question = parts[1].strip() if len(parts) > 1 else ""
        return _cmd_ask(question, topic)

    # Unknown command
    if text.startswith("/"):
        return f"Unknown command: {text!r}\nSend /help for a list of available commands."

    # Plain text (no leading slash) → route to PM as a question
    return _cmd_ask(text, topic)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    _setup_logging()
    if not NTFY_TOPIC:
        log.error(
            "NTFY_TOPIC environment variable is not set. "
            "Add it to your .env file or export it before starting."
        )
        sys.exit(1)

    log.info("ntfy listener starting (streaming mode) — topic=%s", NTFY_TOPIC)
    log.info("Logs: %s", LOG_FILE)

    # Seed 'since' with the current epoch so we only process messages
    # arriving *after* we start (avoids replaying historical commands).
    since = str(int(time.time()))
    backoff = 5  # seconds before reconnect on error

    while True:
        try:
            log.info("Connecting to ntfy stream (since=%s)…", since)
            for msg, since in _stream_messages(NTFY_TOPIC, since):
                backoff = 5  # reset on successful receive
                msg_id = msg.get("id", "")
                msg_event = msg.get("event", "message")

                if msg_event != "message":
                    continue

                # Skip our own outgoing messages (tracked by ID) and all system
                # notifications (advisor always sets a Title; user phone messages never do).
                if msg_id in _SENT_IDS:
                    continue
                if (msg.get("title") or "").strip():
                    continue

                text = (msg.get("message") or "").strip()
                if not text:
                    continue

                log.info("RECV [%s] %r", msg_id, text[:120])
                _log_chat("user", text)

                reply = _dispatch(text, NTFY_TOPIC)
                if reply:
                    log.info("DISPATCH reply: %r", reply[:80])
                    _ntfy_publish(NTFY_TOPIC, reply)

        except KeyboardInterrupt:
            log.info("Interrupted — shutting down.")
            break
        except Exception as exc:  # noqa: BLE001
            log.warning("Stream disconnected: %s — reconnecting in %ds", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)  # cap at 60s


if __name__ == "__main__":
    main()
