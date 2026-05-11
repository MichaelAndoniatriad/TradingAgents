# tradingagents/integrations/etoro/client.py

from __future__ import annotations

import os
import uuid
from typing import Any, Dict, Iterable, List, Optional

import requests

DEFAULT_BASE = "https://public-api.etoro.com"


def _chunks(items: List[int], size: int) -> Iterable[List[int]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


class EtoroClient:
    """Minimal read-only client: portfolio PnL + instrument metadata."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        user_key: Optional[str] = None,
        *,
        account: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.api_key = (api_key or os.environ.get("ETORO_API_KEY") or "").strip()
        self.user_key = (user_key or os.environ.get("ETORO_USER_KEY") or "").strip()
        acct = (account or os.environ.get("ETORO_ACCOUNT") or "real").strip().lower()
        self.account = "demo" if acct in ("demo", "paper", "practice") else "real"
        self.base_url = (base_url or os.environ.get("ETORO_API_BASE") or DEFAULT_BASE).rstrip("/")

        if not self.api_key or not self.user_key:
            raise ValueError(
                "eToro API requires ETORO_API_KEY and ETORO_USER_KEY in the environment "
                "(or pass them to EtoroClient). Create keys in eToro: Settings → Trading → API Key Management."
            )

    def _headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "x-user-key": self.user_key,
            "x-request-id": str(uuid.uuid4()),
        }

    def get_portfolio_pnl(self) -> Dict[str, Any]:
        """GET /api/v1/trading/info/{real|demo}/pnl — full ``clientPortfolio`` payload."""
        url = f"{self.base_url}/api/v1/trading/info/{self.account}/pnl"
        r = requests.get(url, headers=self._headers(), timeout=60)
        r.raise_for_status()
        return r.json()

    def get_instruments_metadata(self, instrument_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """Map instrumentId → metadata row (symbolFull, display name, …)."""
        out: Dict[int, Dict[str, Any]] = {}
        ids = sorted({int(i) for i in instrument_ids if i is not None})
        for chunk in _chunks(ids, 100):
            url = f"{self.base_url}/api/v1/market-data/instruments"
            r = requests.get(
                url,
                headers=self._headers(),
                params={"instrumentIds": ",".join(str(i) for i in chunk)},
                timeout=60,
            )
            r.raise_for_status()
            data = r.json()
            rows = data.get("instrumentDisplayDatas") or data.get("instrumentDisplayData") or []
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                iid = row.get("instrumentID") or row.get("instrumentId")
                if iid is None:
                    continue
                out[int(iid)] = row
        return out
