# tradingagents/advisor/email_notify.py
"""Optional SMTP email for advisory outputs (e.g. after a full graph run)."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Any, Dict

logger = logging.getLogger(__name__)


def analysis_smtp_ready(cfg: Dict[str, Any]) -> bool:
    to = (cfg.get("analysis_email_to") or "").strip()
    host = (cfg.get("smtp_host") or "").strip()
    user = (cfg.get("smtp_user") or "").strip()
    pw = (cfg.get("smtp_password") or "").strip()
    return bool(to and host and user and pw)


def send_plain_email(
    *,
    to_addrs: str,
    from_addr: str,
    subject: str,
    body: str,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    use_tls: bool = True,
) -> bool:
    """Send one plain-text email. ``to_addrs`` may be comma-separated."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addrs.replace(";", ",")
    msg.set_content(body)
    try:
        with smtplib.SMTP(smtp_host, int(smtp_port), timeout=45) as server:
            if use_tls:
                server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        return True
    except Exception as e:
        logger.warning("SMTP send failed: %s", e)
        return False


def send_analysis_advisory_email(
    cfg: Dict[str, Any],
    *,
    ticker: str,
    trade_date: str,
    decision_text: str,
    rating: str,
) -> bool:
    """Email the advisory PM memo if SMTP + recipient are configured."""
    if not analysis_smtp_ready(cfg):
        return False
    to_addrs = (cfg.get("analysis_email_to") or "").strip()
    smtp_user = (cfg.get("smtp_user") or "").strip()
    from_addr = (cfg.get("analysis_email_from") or "").strip() or smtp_user
    subject = f"[TradingAgents] Advisory — {ticker} — {trade_date} — {rating}"
    headline = (
        f"Advisory plan (not a trade; for your review)\n"
        f"Ticker: {ticker}\n"
        f"Date: {trade_date}\n"
        f"Rating: {rating}\n"
        f"\n---\n\n"
    )
    body = headline + (decision_text or "")[:50000]
    return send_plain_email(
        to_addrs=to_addrs,
        from_addr=from_addr,
        subject=subject,
        body=body,
        smtp_host=(cfg.get("smtp_host") or "").strip(),
        smtp_port=int(cfg.get("smtp_port") or 587),
        smtp_user=smtp_user,
        smtp_password=(cfg.get("smtp_password") or "").strip(),
        use_tls=bool(cfg.get("smtp_use_tls", True)),
    )
