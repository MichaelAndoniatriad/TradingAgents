# tradingagents/integrations/etoro/client.py

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, Iterable, List, Optional

import requests

DEFAULT_BASE = "https://public-api.etoro.com"

# eToro rejects `%2C` in instrumentIds; `requests` params= encodes commas — build URLs with literal `,`.
# Large batches can yield 413/414 or 5xx; start modest and bisect on failure.
_DEFAULT_INSTRUMENTS_BATCH = 25

logger = logging.getLogger(__name__)


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

    def _get_instruments_metadata_chunk(self, chunk: List[int]) -> requests.Response:
        """GET instruments for ``chunk``; query uses literal commas (eToro rejects ``%2C``)."""
        joined = ",".join(str(i) for i in chunk)
        url = f"{self.base_url}/api/v1/market-data/instruments?instrumentIds={joined}"
        return requests.get(url, headers=self._headers(), timeout=60)

    def _merge_instrument_rows(
        self, out: Dict[int, Dict[str, Any]], rows: Any
    ) -> None:
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            iid = row.get("instrumentID") or row.get("instrumentId")
            if iid is None:
                continue
            out[int(iid)] = row

    def _fetch_instruments_recursive(
        self,
        out: Dict[int, Dict[str, Any]],
        chunk: List[int],
    ) -> None:
        """Fetch metadata for ``chunk``, bisecting on 413/414/5xx; skip lone IDs that still fail."""
        if not chunk:
            return
        r = self._get_instruments_metadata_chunk(chunk)
        if r.status_code == 200:
            try:
                data = r.json()
            except ValueError:
                logger.warning("eToro instruments: invalid JSON for chunk size %s", len(chunk))
                return
            rows = data.get("instrumentDisplayDatas") or data.get("instrumentDisplayData") or []
            self._merge_instrument_rows(out, rows)
            return

        if r.status_code in (401, 403):
            r.raise_for_status()

        if r.status_code in (413, 414) or r.status_code >= 500:
            if len(chunk) > 1:
                mid = (len(chunk) + 1) // 2
                self._fetch_instruments_recursive(out, chunk[:mid])
                self._fetch_instruments_recursive(out, chunk[mid:])
                return
            logger.warning(
                "eToro instruments: skipped instrumentId %s (HTTP %s)",
                chunk[0],
                r.status_code,
            )
            return

        r.raise_for_status()

    def get_instruments_metadata(self, instrument_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """Map instrumentId → metadata row (symbolFull, display name, …).

        Uses literal commas in ``instrumentIds`` (required by eToro). Splits batches
        on 413/414/5xx so a bad ID or oversized batch does not fail the whole portfolio.
        """
        out: Dict[int, Dict[str, Any]] = {}
        ids = sorted({int(i) for i in instrument_ids if i is not None})
        for chunk in _chunks(ids, _DEFAULT_INSTRUMENTS_BATCH):
            self._fetch_instruments_recursive(out, list(chunk))
        return out
