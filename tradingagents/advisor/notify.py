# tradingagents/advisor/notify.py

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


def get_webhook_url() -> Optional[str]:
    return (os.environ.get("TRADINGAGENTS_ADVISOR_WEBHOOK_URL") or "").strip() or None


def send_webhook(url: str, text: str, extra: Optional[dict[str, Any]] = None) -> bool:
    """POST a message to a webhook.

    Detects ntfy.sh URLs and sends plain text (which ntfy.sh displays cleanly).
    All other URLs get Slack-compatible JSON (``{"text": "..."}``.
    Returns True on 2xx, False otherwise.
    """
    try:
        if "ntfy.sh" in url:
            # ntfy.sh wants plain text; hard limit is 4096 bytes — truncate or it becomes a file attachment
            title = (extra or {}).get("title", "TradingAgents")
            body = text[:4000] + ("\n\n[truncated — see dashboard for full text]" if len(text) > 4000 else "")
            r = requests.post(
                url,
                data=body.encode("utf-8"),
                headers={"Title": str(title), "Priority": "default"},
                timeout=30,
            )
        else:
            payload: dict[str, Any] = {"text": text}
            if extra:
                payload.update(extra)
            r = requests.post(url, json=payload, timeout=30)

        if 200 <= r.status_code < 300:
            return True
        logger.warning("Webhook returned %s: %s", r.status_code, r.text[:500])
        return False
    except requests.RequestException as e:
        logger.error("Webhook request failed: %s", e)
        return False
