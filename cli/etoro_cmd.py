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


def _mask_secret(value: str, label: str) -> str:
    v = (value or "").strip()
    if not v:
        return f"[red]{label} is empty[/red]"
    if len(v) <= 10:
        return f"{label}: [green]set[/green] ({len(v)} chars, hidden)"
    return f"{label}: [green]set[/green] ({len(v)} chars, {v[:4]}…{v[-4:]})"


def _log(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


@etoro_app.command("verify")
def etoro_verify():
    """Check that keys are loaded and the Public API answers (PnL + instrument names).

    Uses the same env vars as the app: ``ETORO_API_KEY`` (sent as ``x-api-key``) and
    ``ETORO_USER_KEY`` (sent as ``x-user-key``). If PnL returns 401/403, the values
    are often **swapped** or ``ETORO_ACCOUNT`` (real vs demo) does not match the key.
    """
    import os

    import requests

    from tradingagents.integrations.etoro.portfolio import (
        instrument_id_from_position,
        iter_positions,
        portfolio_headlines,
    )

    console.print("[bold]eToro API verify[/bold]\n")
    base = (os.environ.get("ETORO_API_BASE") or "https://public-api.etoro.com").rstrip("/")
    acct = (os.environ.get("ETORO_ACCOUNT") or "real").strip().lower()
    env_path = "demo" if acct in ("demo", "paper", "practice") else "real"
    console.print(f"  ETORO_API_BASE: {base}")
    console.print(f"  ETORO_ACCOUNT: {acct!r} → requests use [cyan]/trading/info/{env_path}/pnl[/cyan]")
    console.print(f"  {_mask_secret(os.environ.get('ETORO_API_KEY', ''), 'ETORO_API_KEY')}  → header [cyan]x-api-key[/cyan]")
    console.print(f"  {_mask_secret(os.environ.get('ETORO_USER_KEY', ''), 'ETORO_USER_KEY')}  → header [cyan]x-user-key[/cyan]")
    console.print(
        "\n[yellow]In eToro: Settings → Trading → API Key Management[/yellow] you get a **pair** of keys. "
        "They must map exactly as above (do not swap). The “user” / personal key is never the same string as the app key.\n"
    )

    try:
        client = EtoroClient()
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    url_pnl = f"{client.base_url}/api/v1/trading/info/{client.account}/pnl"
    console.print(f"[bold]Step 1 — PnL snapshot[/bold]\n  GET {url_pnl}")
    try:
        payload = client.get_portfolio_pnl()
    except requests.HTTPError as e:
        r = e.response
        body = (r.text if r is not None else "")[:500]
        code = r.status_code if r is not None else "?"
        console.print(f"  [red]HTTP {code}[/red]")
        if body:
            console.print(f"  [dim]{body}[/dim]")
        console.print(
            "\n[bold]What to try[/bold]\n"
            "  • Swap ``ETORO_API_KEY`` and ``ETORO_USER_KEY`` in ``.env`` (common fix for 401).\n"
            "  • If this key is for **practice / virtual**, set ``ETORO_ACCOUNT=demo`` and restart.\n"
            "  • If it is **live** money, use ``ETORO_ACCOUNT=real`` (default).\n"
            "  • Regenerate the key pair in eToro if you are unsure anything was copied wrong.\n"
        )
        raise typer.Exit(1) from e
    except requests.RequestException as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    hl = portfolio_headlines(payload)
    console.print(
        f"  [green]OK[/green] — available/credit: {hl.get('credit')!r}, "
        f"unrealized P&L: {hl.get('unrealized_pnl')!r}, "
        f"open positions (deduped): {hl.get('open_positions')}"
    )

    cp = payload.get("clientPortfolio") or {}
    ids: list[int] = []
    for p in iter_positions(cp):
        if not isinstance(p, dict):
            continue
        iid = instrument_id_from_position(p)
        if iid is not None:
            ids.append(iid)
    ids = sorted(set(ids))[:5]

    console.print(f"\n[bold]Step 2 — Instrument metadata[/bold] (symbol names; up to {len(ids)} IDs from your book)")
    if not ids:
        console.print("  [dim]No instrument IDs in open positions — skipping instruments call.[/dim]")
        console.print("\n[green]Verify finished successfully.[/green]")
        return
    try:
        meta = client.get_instruments_metadata(ids)
    except requests.HTTPError as e:
        r = e.response
        body = (r.text if r is not None else "")[:500]
        console.print(f"  [red]HTTP {r.status_code if r is not None else '?'}[/red] {body}")
        raise typer.Exit(1) from e
    except requests.RequestException as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    if not meta:
        console.print(
            "  [yellow]Warning:[/yellow] PnL worked but no instrument rows returned "
            "(names may be missing in the UI; positions still load by ID)."
        )
    else:
        for iid, row in list(meta.items())[:5]:
            sym = row.get("symbolFull") or row.get("SymbolFull") or "?"
            name = row.get("instrumentDisplayName") or row.get("InstrumentDisplayName") or ""
            console.print(f"  [green]OK[/green] id {iid} → {sym} ({name})".rstrip())

    console.print("\n[green]Verify finished successfully.[/green] If the Streamlit UI still fails, click **Refresh** or restart Streamlit (cached errors clear).")


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
