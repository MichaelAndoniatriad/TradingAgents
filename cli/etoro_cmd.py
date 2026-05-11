# cli/etoro_cmd.py — read-only eToro portfolio + watchlist export for the clerk

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from tradingagents.integrations.etoro.client import EtoroClient
from tradingagents.integrations.etoro.clerk_bridge import fetch_clerk_watchlist_from_etoro
from tradingagents.integrations.etoro.portfolio import (
    dedupe_positions,
    instrument_id_from_position,
    iter_positions,
    summarize_portfolio,
)

console = Console()
etoro_app = typer.Typer(
    help="Read-only eToro Public API: portfolio snapshot and clerk watchlist export.",
    no_args_is_help=True,
)


def _log(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


@etoro_app.command("portfolio")
def etoro_portfolio(verbose: bool = typer.Option(False, "--verbose", "-v")):
    """Print open positions and balances from your eToro account (read-only)."""
    _log(verbose)
    client = EtoroClient()
    payload = client.get_portfolio_pnl()
    cp = payload.get("clientPortfolio") or {}
    positions = dedupe_positions(iter_positions(cp))
    ids: list[int] = []
    for p in positions:
        iid = instrument_id_from_position(p)
        if iid is not None:
            ids.append(iid)
    meta = client.get_instruments_metadata(ids) if ids else {}
    text, _rows = summarize_portfolio(payload, meta)
    console.print(text)


@etoro_app.command("export-watchlist")
def etoro_export_watchlist(
    out: Path = typer.Option(
        ...,
        "--out",
        "-o",
        help="Where to write clerk watchlist JSON (tickers from eToro, triggers from template or defaults).",
    ),
    triggers: Optional[Path] = typer.Option(
        None,
        "--triggers",
        "-t",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Optional JSON file whose triggers/analysts/output_language are copied (tickers are replaced from eToro).",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Write a clerk-compatible watchlist JSON using your live open positions as tickers."""
    _log(verbose)
    wl = fetch_clerk_watchlist_from_etoro(triggers)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(wl.to_json_dict(), indent=2), encoding="utf-8")
    console.print(f"[green]Wrote[/green] {out.resolve()}\nTickers: {', '.join(wl.tickers)}")
