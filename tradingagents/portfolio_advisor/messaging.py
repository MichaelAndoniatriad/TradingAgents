"""Single entry point for portfolio advisor outbound messages (webhook + email).

Every call to ``send_advisor_message`` also appends a row to a JSONL message
log (default ``~/.tradingagents/memory/messages.jsonl``) so the UI can show
recent notifications without depending on the user's inbox.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from tradingagents.advisor.email_notify import analysis_smtp_ready, send_plain_email
from tradingagents.advisor.notify import send_webhook

logger = logging.getLogger(__name__)


def ntfy_verdict(text: str, ticker: str) -> str:
    """Extract verdict + required action from analysis text for a short ntfy message."""
    verdict = ""
    required_action = ""
    in_verdict = False
    in_action = False
    for line in text.splitlines():
        s = line.strip()
        upper = s.upper()
        if upper == "VERDICT":
            in_verdict = True
            in_action = False
            continue
        if upper in ("REQUIRED ACTION", "REQUIRED ACTIONS"):
            in_action = True
            in_verdict = False
            continue
        if s and upper == s and len(s) > 2:
            in_verdict = False
            in_action = False
            continue
        if in_verdict and s and not verdict:
            verdict = s[:200]
        if in_action and s and not required_action and s.lower() != "none":
            required_action = s[:200]
    parts = []
    if verdict:
        parts.append(verdict)
    if required_action:
        parts.append(f"Action: {required_action}")
    if not parts:
        parts.append(text[:300])
    return "\n".join(parts)

_MAX_BODY_PERSISTED = 50000


def message_log_path(cfg: Dict[str, Any]) -> Path:
    """Resolve the JSONL message log path (sibling of memory log by default)."""
    raw = cfg.get("message_log_path")
    if isinstance(raw, str) and raw.strip():
        return Path(raw).expanduser()
    mem = cfg.get("memory_log_path")
    if isinstance(mem, str) and mem.strip():
        return Path(mem).expanduser().parent / "messages.jsonl"
    return Path.home() / ".tradingagents" / "memory" / "messages.jsonl"


def _derive_level(subject: str) -> str:
    s = (subject or "").upper()
    if "CRITICAL" in s or "FAILED" in s or "BROKEN" in s:
        return "critical"
    if "HIGH" in s or "WEAKENING" in s or "OVERDUE" in s:
        return "high"
    if "REVIEW" in s or "ATTENTION" in s:
        return "review"
    return "info"


def append_message_record(
    cfg: Dict[str, Any],
    *,
    subject: str,
    body: str,
    webhook_ok: bool,
    smtp_ok: bool,
    webhook_attempted: bool,
    smtp_attempted: bool,
) -> None:
    """Append one JSON object as a single line. Never raises."""
    path = message_log_path(cfg)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("message log mkdir failed: %s", e)
        return
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "subject": str(subject or "")[:500],
        "body": str(body or "")[:_MAX_BODY_PERSISTED],
        "level": _derive_level(str(subject or "")),
        "channels_attempted": [
            c for c, ok in (("webhook", webhook_attempted), ("smtp", smtp_attempted)) if ok
        ],
        "webhook_ok": bool(webhook_ok),
        "smtp_ok": bool(smtp_ok),
        "delivered": bool(webhook_ok or smtp_ok),
    }
    line = json.dumps(row, ensure_ascii=False) + "\n"
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError as e:
        logger.warning("message log append failed: %s", e)


def load_recent_messages(
    cfg: Dict[str, Any],
    *,
    limit: int = 200,
    level_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Newest-first window over the JSONL message log; capped for UI safety."""
    path = message_log_path(cfg)
    if not path.is_file():
        return []
    out: List[Dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines()[-5000:]:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if level_filter and row.get("level") != level_filter:
            continue
        out.append(row)
    out.reverse()
    if limit and limit > 0:
        out = out[:limit]
    return out


def send_advisor_message(cfg: Dict[str, Any], subject: str, body: str) -> bool:
    """Post to analysis webhook and/or SMTP when configured.

    Call this whenever the portfolio advisor needs to reach the user (alerts,
    weekly heartbeat, job lifecycle, manual ``portfolio alert``, etc.).
    Always appends a row to the JSONL message log (regardless of channel
    success) so the UI Messages page can render notifications offline.
    Returns True if at least one channel succeeded or was attempted with 2xx.
    """
    webhook_ok = False
    url = (cfg.get("analysis_webhook_url") or "").strip()
    webhook_attempted = bool(url)
    if url:
        try:
            webhook_ok = bool(send_webhook(url, f"*{subject}*\n\n{body[:15000]}"))
        except Exception as e:
            logger.warning("advisor webhook failed: %s", e)
    smtp_ok = False
    smtp_attempted = analysis_smtp_ready(cfg)
    if smtp_attempted:
        to_addrs = (cfg.get("analysis_email_to") or "").strip()
        smtp_user = (cfg.get("smtp_user") or "").strip()
        from_addr = (cfg.get("analysis_email_from") or "").strip() or smtp_user
        try:
            smtp_ok = bool(
                send_plain_email(
                    to_addrs=to_addrs,
                    from_addr=from_addr,
                    subject=subject,
                    body=body[:_MAX_BODY_PERSISTED],
                    smtp_host=(cfg.get("smtp_host") or "").strip(),
                    smtp_port=int(cfg.get("smtp_port") or 587),
                    smtp_user=smtp_user,
                    smtp_password=(cfg.get("smtp_password") or "").strip(),
                    use_tls=bool(cfg.get("smtp_use_tls", True)),
                )
            )
        except Exception as e:
            logger.warning("advisor SMTP failed: %s", e)
    sent = webhook_ok or smtp_ok
    if not sent and (not url) and (not smtp_attempted):
        logger.warning(
            "Portfolio advisor message not sent (configure TRADINGAGENTS_ANALYSIS_WEBHOOK_URL "
            "and/or analysis email + SMTP): %s",
            subject[:120],
        )
    try:
        append_message_record(
            cfg,
            subject=subject,
            body=body,
            webhook_ok=webhook_ok,
            smtp_ok=smtp_ok,
            webhook_attempted=webhook_attempted,
            smtp_attempted=smtp_attempted,
        )
    except Exception:
        logger.debug("message log persist skipped", exc_info=True)
    return sent
