# tradingagents/clerk/notify.py

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def get_clerk_webhook_url() -> Optional[str]:
    url = (os.environ.get("TRADINGAGENTS_CLERK_WEBHOOK_URL") or "").strip()
    if url:
        return url
    return (os.environ.get("TRADINGAGENTS_ADVISOR_WEBHOOK_URL") or "").strip() or None


def post_text(url: str, text: str) -> bool:
    from tradingagents.advisor.notify import send_webhook
    return send_webhook(url, text)
