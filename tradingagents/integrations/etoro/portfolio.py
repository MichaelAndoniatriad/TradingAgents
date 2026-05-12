# tradingagents/integrations/etoro/portfolio.py

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


def _pick(d: dict, *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _pick_ci(d: dict, *candidates: str) -> Any:
    """First non-None value whose key matches one of ``candidates`` case-insensitively."""
    if not isinstance(d, dict) or not candidates:
        return None
    want = {str(c).lower() for c in candidates}
    for k, v in d.items():
        if v is None:
            continue
        if str(k).lower() in want:
            return v
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


def position_unrealized_pnl(p: dict) -> Any:
    """Per-position unrealized P&L (USD).

    The PnL endpoint usually exposes ``unrealizedPnL.pnL`` or a flat ``pnL`` field; casing varies
    on the wire. When those are absent, use ``unitsBaseValueDollars - initialAmountInDollars`` (see
    eToro OpenAPI Position on the PnL response) as a practical fallback for dashboards.
    """
    if not isinstance(p, dict):
        return None

    nested = _pick_ci(
        p,
        "unrealizedPnL",
        "unrealizedPnl",
        "UnrealizedPnL",
        "UnrealizedPnl",
        "unrealizedPNL",
    )
    if isinstance(nested, dict):
        v = _pick_ci(nested, "pnL", "pnl", "PnL", "PNL", "value", "dollars", "amount")
        if v is not None and not isinstance(v, (dict, list)):
            return v
        if len(nested) == 1:
            only = next(iter(nested.values()))
            if isinstance(only, (int, float)) and not isinstance(only, bool):
                return only
            if isinstance(only, dict):
                v2 = _pick_ci(only, "pnL", "pnl", "PnL", "PNL", "value")
                if v2 is not None and not isinstance(v2, (dict, list)):
                    return v2
    elif nested is not None and not isinstance(nested, (dict, list)):
        return nested

    for leaf in ("pnL", "pnl", "PnL", "PNL", "unrealizedProfit", "profitLoss", "grossPnL"):
        v = _pick_ci(p, leaf)
        if v is not None and not isinstance(v, (dict, list)):
            return v

    ubv = _pick(p, "unitsBaseValueDollars", "UnitsBaseValueDollars")
    init = _pick(p, "initialAmountInDollars", "InitialAmountInDollars")
    if ubv is not None and init is not None:
        try:
            return float(ubv) - float(init)
        except (TypeError, ValueError):
            pass
    return None


def position_invested_usd(p: dict) -> Optional[float]:
    """USD capital in the open position at open (excludes unrealized P&amp;L): ``amount`` else |units|×openRate."""
    amt = _pick(p, "amount", "Amount")
    if amt is not None:
        try:
            a = float(amt)
            if a > 0:
                return a
        except (TypeError, ValueError):
            pass
    u = _pick(p, "units", "Units")
    op = _pick(p, "openRate", "OpenRate")
    if u is None or op is None:
        return None
    try:
        fu = float(u)
        fo = float(op)
    except (TypeError, ValueError):
        return None
    inv = abs(fu) * abs(fo)
    return inv if inv > 0 else None


def portfolio_headlines(pnl_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Balance, aggregate unrealized P&L, open-position count, and summed capital in open positions."""
    cp = pnl_payload.get("clientPortfolio") or {}
    credit = _pick(cp, "credit", "Credit")
    unreal = _pick(cp, "unrealizedPnL", "unrealizedPnl", "UnrealizedPnL")
    book = dedupe_positions(iter_positions(cp))
    n_positions = len(book)
    inv_sum = 0.0
    inv_n = 0
    for p in book:
        v = position_invested_usd(p)
        if v is not None:
            inv_sum += v
            inv_n += 1
    if n_positions == 0:
        total_invested_open_usd = 0.0
    elif inv_n == 0:
        total_invested_open_usd = None
    else:
        total_invested_open_usd = inv_sum
    return {
        "credit": credit,
        "unrealized_pnl": unreal,
        "open_positions": n_positions,
        "total_invested_open_usd": total_invested_open_usd,
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
        pnl = position_unrealized_pnl(p)
        amt = _pick(p, "amount", "Amount")
        ubv = _pick(p, "unitsBaseValueDollars", "UnitsBaseValueDollars")
        init_usd = _pick(p, "initialAmountInDollars", "InitialAmountInDollars")
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
                "amount": amt,
                "unitsBaseValueDollars": ubv,
                "initialAmountInDollars": init_usd,
                "isBuy": _pick(p, "isBuy", "IsBuy"),
                "unrealizedPnL": pnl,
                "positionId": _pick(p, "positionId", "positionID"),
            }
        )
    if not rows:
        lines.append("  (none)")
    return "\n".join(lines), rows
