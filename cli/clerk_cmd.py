# cli/clerk_cmd.py — scheduled clerk (daily scan, weekly roll-up, optional deep graph)

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.clerk.morning import run_morning_clerk
from tradingagents.clerk.weekly import run_weekly_clerk

console = Console()
clerk_app = typer.Typer(
    help="Clerk: lightweight daily scans; deep multi-agent research only when triggers match.",
    no_args_is_help=True,
)


def _log(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


@clerk_app.command("morning")
def clerk_morning(
    watchlist: Optional[Path] = typer.Option(
        None,
        "--watchlist",
        "-w",
        exists=True,
        dir_okay=False,
        readable=True,
        help="JSON watchlist (see cli/static/clerk_watchlist.example.json).",
    ),
    etoro: bool = typer.Option(
        False,
        "--etoro",
        help="Build ticker list from live eToro open positions (needs ETORO_API_KEY + ETORO_USER_KEY).",
    ),
    etoro_triggers: Optional[Path] = typer.Option(
        None,
        "--etoro-triggers",
        exists=True,
        dir_okay=False,
        readable=True,
        help="With --etoro: optional JSON to copy triggers/analysts from (tickers still come from eToro).",
    ),
    trade_date: Optional[str] = typer.Option(
        None,
        "--date",
        "-d",
        help="As-of date for deep research YYYY-MM-DD (default: today).",
    ),
    deep_research: bool = typer.Option(
        False,
        "--deep-research",
        help="When triggers fire, run the full TradingAgents graph (API cost).",
    ),
    webhook: Optional[str] = typer.Option(
        None,
        "--webhook",
        help="Override TRADINGAGENTS_CLERK_WEBHOOK_URL for this run.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Daily headline diff + optional deep research; writes ~/.tradingagents/cache/clerk/daily/."""
    _log(verbose)
    cfg = DEFAULT_CONFIG.copy()
    if etoro:
        from tradingagents.integrations.etoro.clerk_bridge import fetch_clerk_watchlist_from_etoro

        wl = fetch_clerk_watchlist_from_etoro(etoro_triggers)
        digest, ran = run_morning_clerk(
            wl,
            trade_date=trade_date,
            webhook_url=webhook,
            deep_research=deep_research,
            config=cfg,
        )
    else:
        if watchlist is None:
            console.print("[red]Either pass --watchlist … or use --etoro[/red]")
            raise typer.Exit(1)
        digest, ran = run_morning_clerk(
            watchlist,
            trade_date=trade_date,
            webhook_url=webhook,
            deep_research=deep_research,
            config=cfg,
        )
    console.print(digest)
    if ran:
        console.print(f"\n[bold green]Deep research ran for:[/bold green] {', '.join(ran)}")
    else:
        console.print("\n[dim]No deep research this pass (no triggers or baseline day).[/dim]")


@clerk_app.command("weekly")
def clerk_weekly(
    days: int = typer.Option(7, "--days", help="How many recent daily digests to include."),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip the weekly LLM narrative."),
    webhook: Optional[str] = typer.Option(None, "--webhook"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Roll up morning logs (Sat/Sun cron); writes ~/.tradingagents/cache/clerk/weekly/."""
    _log(verbose)
    cfg = DEFAULT_CONFIG.copy()
    digest = run_weekly_clerk(
        days=days,
        webhook_url=webhook,
        with_llm=not no_llm,
        config=cfg,
    )
    console.print(digest)


@clerk_app.command("example-path")
def clerk_example_path():
    p = Path(__file__).resolve().parent / "static" / "clerk_watchlist.example.json"
    console.print(str(p))
