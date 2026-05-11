# tradingagents/integrations/etoro/portfolio.py

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


def _pick(d: dict, *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def iter_positions(client_portfolio: dict) -> Iterable[dict]:
    """Yield open positions from the top-level list and from copy-trading mirrors."""
    for p in client_portfolio.get("positions") or []:
        if isinstance(p, dict):
            yield p
    for m in client_portfolio.get("mirrors") or []:
        if not isinstance(m, dict):
            continue
        for p in m.get("positions") or []:
            if isinstance(p, dict):
                yield p


def dedupe_positions(raw: Iterable[dict]) -> List[dict]:
    """Drop duplicate ``positionId`` rows (mirrors can overlap with parent bookkeeping)."""
    seen: Set[int] = set()
    out: List[dict] = []
    for p in raw:
        pid = _pick(p, "positionId", "positionID")
        if pid is None:
            out.append(p)
            continue
        try:
            ip = int(pid)
        except (TypeError, ValueError):
            out.append(p)
            continue
        if ip in seen:
            continue
        seen.add(ip)
        out.append(p)
    return out


def instrument_id_from_position(p: dict) -> Optional[int]:
    v = _pick(p, "instrumentId", "instrumentID")
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def portfolio_headlines(pnl_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Balance, aggregate unrealized P&L, and open-position count for dashboards."""
    cp = pnl_payload.get("clientPortfolio") or {}
    credit = _pick(cp, "credit", "Credit")
    unreal = _pick(cp, "unrealizedPnL", "unrealizedPnl", "UnrealizedPnL")
    n_positions = len(dedupe_positions(iter_positions(cp)))
    return {
        "credit": credit,
        "unrealized_pnl": unreal,
        "open_positions": n_positions,
    }


def summarize_portfolio(
    pnl_payload: Dict[str, Any],
    instrument_meta: Dict[int, Dict[str, Any]],
) -> Tuple[str, List[Dict[str, Any]]]:
    """Human-readable summary + flat rows for export."""
    cp = pnl_payload.get("clientPortfolio") or {}
    credit = _pick(cp, "credit", "Credit")
    unreal = _pick(cp, "unrealizedPnL", "unrealizedPnl", "UnrealizedPnL")

    lines = [
        "Account snapshot (read-only)",
        f"Available balance (credit): {credit}",
        f"Unrealized P&L (aggregate): {unreal}",
        "",
        "Open positions:",
    ]
    rows: List[Dict[str, Any]] = []
    for p in dedupe_positions(iter_positions(cp)):
        iid = instrument_id_from_position(p)
        meta = instrument_meta.get(iid, {}) if iid is not None else {}
        sym = _pick(meta, "symbolFull", "SymbolFull") or (f"instrumentId:{iid}" if iid is not None else "?")
        name = _pick(meta, "instrumentDisplayName", "InstrumentDisplayName") or ""
        open_rate = _pick(p, "openRate", "OpenRate")
        units = _pick(p, "units", "Units")
        ib = _pick(p, "isBuy", "IsBuy")
        if ib is True:
            side = "long"
        elif ib is False:
            side = "short"
        else:
            side = "?"
        pnl = _pick(p, "pnL", "pnl", "PnL", "PNL")
        lines.append(
            f"  • {sym} ({name})  {side}  units={units}  open={open_rate}  uPnL={pnl}"
        )
        rows.append(
            {
                "symbolFull": sym,
                "instrumentDisplayName": name,
                "instrumentId": iid,
                "openRate": open_rate,
                "units": units,
                "isBuy": _pick(p, "isBuy", "IsBuy"),
                "unrealizedPnL": pnl,
                "positionId": _pick(p, "positionId", "positionID"),
            }
        )
    if not rows:
        lines.append("  (none)")
    return "\n".join(lines), rows
