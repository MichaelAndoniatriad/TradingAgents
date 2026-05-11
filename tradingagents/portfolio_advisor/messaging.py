"""Single entry point for portfolio advisor outbound messages (webhook + email)."""

from __future__ import annotations

import logging
from typing import Any, Dict

from tradingagents.advisor.email_notify import analysis_smtp_ready, send_plain_email
from tradingagents.advisor.notify import send_webhook

logger = logging.getLogger(__name__)


def send_advisor_message(cfg: Dict[str, Any], subject: str, body: str) -> bool:
    """Post to analysis webhook and/or SMTP when configured.

    Call this whenever the portfolio advisor needs to reach the user (alerts,
    weekly heartbeat, job lifecycle, manual ``portfolio alert``, etc.).
    Returns True if at least one channel succeeded or was attempted with 2xx.
    """
    webhook_ok = False
    url = (cfg.get("analysis_webhook_url") or "").strip()
    if url:
        try:
            webhook_ok = bool(send_webhook(url, f"*{subject}*\n\n{body[:15000]}"))
        except Exception as e:
            logger.warning("advisor webhook failed: %s", e)
    smtp_ok = False
    if analysis_smtp_ready(cfg):
        to_addrs = (cfg.get("analysis_email_to") or "").strip()
        smtp_user = (cfg.get("smtp_user") or "").strip()
        from_addr = (cfg.get("analysis_email_from") or "").strip() or smtp_user
        try:
            smtp_ok = bool(
                send_plain_email(
                    to_addrs=to_addrs,
                    from_addr=from_addr,
                    subject=subject,
                    body=body[:50000],
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
    if not sent and (not url) and (not analysis_smtp_ready(cfg)):
        logger.warning(
            "Portfolio advisor message not sent (configure TRADINGAGENTS_ANALYSIS_WEBHOOK_URL "
            "and/or analysis email + SMTP): %s",
            subject[:120],
        )
    return sent
