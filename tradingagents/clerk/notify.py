# tradingagents/clerk/notify.py

from __future__ import annotations

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)


def get_clerk_webhook_url() -> Optional[str]:
    url = (os.environ.get("TRADINGAGENTS_CLERK_WEBHOOK_URL") or "").strip()
    if url:
        return url
    return (os.environ.get("TRADINGAGENTS_ADVISOR_WEBHOOK_URL") or "").strip() or None


def post_text(url: str, text: str) -> bool:
    try:
        r = requests.post(url, json={"text": text}, timeout=45)
        if 200 <= r.status_code < 300:
            return True
        logger.warning("Clerk webhook HTTP %s: %s", r.status_code, r.text[:400])
        return False
    except requests.RequestException as e:
        logger.error("Clerk webhook failed: %s", e)
        return False
