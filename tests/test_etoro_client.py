# tests/test_etoro_client.py

from __future__ import annotations

from typing import Any, Dict, List

from tradingagents.integrations.etoro.client import EtoroClient


class _FakeResp:
    def __init__(self, status_code: int, payload: Dict[str, Any] | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> Dict[str, Any]:
        return dict(self._payload)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(response=self)


def test_instruments_request_url_uses_literal_comma_not_pct2c(monkeypatch):
    urls: List[str] = []

    def fake_get(url: str, headers=None, timeout=None):
        urls.append(url)
        return _FakeResp(
            200,
            {
                "instrumentDisplayDatas": [
                    {"instrumentID": 1135, "symbolFull": "X", "instrumentDisplayName": "Y"}
                ]
            },
        )

    monkeypatch.setattr("tradingagents.integrations.etoro.client.requests.get", fake_get)

    client = EtoroClient(api_key="test-api", user_key="test-user")
    out = client.get_instruments_metadata([1135, 1137])

    assert len(urls) == 1
    assert "%2C" not in urls[0], "eToro rejects percent-encoded commas in instrumentIds"
    assert "instrumentIds=1135,1137" in urls[0]
    assert out[1135]["symbolFull"] == "X"


def test_instruments_bisects_on_500_then_succeeds(monkeypatch):
    calls: List[str] = []

    def fake_get(url: str, headers=None, timeout=None):
        calls.append(url)
        if "," in url.split("instrumentIds=", 1)[-1] and url.count(",") >= 1:
            ids = url.split("instrumentIds=", 1)[-1].split(",")
            if len(ids) > 1:
                return _FakeResp(500)
        iid = int(url.split("instrumentIds=", 1)[-1])
        return _FakeResp(
            200,
            {
                "instrumentDisplayDatas": [
                    {
                        "instrumentID": iid,
                        "symbolFull": f"S{iid}",
                        "instrumentDisplayName": "N",
                    }
                ]
            },
        )

    monkeypatch.setattr("tradingagents.integrations.etoro.client.requests.get", fake_get)

    client = EtoroClient(api_key="a", user_key="b")
    out = client.get_instruments_metadata([10, 20])
    assert out[10]["symbolFull"] == "S10"
    assert out[20]["symbolFull"] == "S20"
    assert len(calls) >= 3  # batched 500, then per-id successes
