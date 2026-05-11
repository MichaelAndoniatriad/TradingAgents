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
    """POST a message to a generic webhook (Slack-compatible ``text`` field).

    Returns True on 2xx, False otherwise.
    """
    payload: dict[str, Any] = {"text": text}
    if extra:
        payload.update(extra)
    try:
        r = requests.post(url, json=payload, timeout=30)
        if 200 <= r.status_code < 300:
            return True
        logger.warning("Webhook returned %s: %s", r.status_code, r.text[:500])
        return False
    except requests.RequestException as e:
        logger.error("Webhook request failed: %s", e)
        return False
