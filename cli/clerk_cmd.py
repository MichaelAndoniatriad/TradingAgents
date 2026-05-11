# cli/clerk_cmd.py — scheduled clerk (weekly primary + monthly; daily disabled)

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.clerk.monthly import run_monthly_lookout
from tradingagents.clerk.weekly import run_weekly_clerk

console = Console()
clerk_app = typer.Typer(
    help="Clerk: daily portfolio + headlines; weekly queue for deep research; monthly candidate lookout.",
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
        help="(ignored) Daily clerk is disabled.",
    ),
    etoro: bool = typer.Option(False, "--etoro", help="(ignored)"),
    etoro_triggers: Optional[Path] = typer.Option(None, "--etoro-triggers", help="(ignored)"),
    trade_date: Optional[str] = typer.Option(None, "--date", "-d", help="(ignored)"),
    deep_research: bool = typer.Option(False, "--deep-research", help="(ignored)"),
    webhook: Optional[str] = typer.Option(None, "--webhook", help="(ignored)"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Disabled — use ``clerk weekly`` (and optional ``clerk monthly``)."""
    _log(verbose)
    console.print(
        "[yellow]Daily `clerk morning` is disabled in this project.[/yellow]\n\n"
        "Use the weekly job instead (eToro or watchlist + deep-research queue):\n"
        "  [cyan]python -m cli.main clerk weekly --etoro[/cyan]\n"
        "  [cyan]python -m cli.main clerk weekly --watchlist path/to/watchlist.json[/cyan]\n"
    )
    raise typer.Exit(2)


@clerk_app.command("weekly")
def clerk_weekly(
    watchlist: Optional[Path] = typer.Option(
        None,
        "--watchlist",
        "-w",
        exists=True,
        dir_okay=False,
        readable=True,
        help="JSON watchlist — required for the deep-research queue section.",
    ),
    etoro: bool = typer.Option(
        False,
        "--etoro",
        help="Build ticker list from eToro (same as morning); use for queue + optional deep runs.",
    ),
    etoro_triggers: Optional[Path] = typer.Option(
        None,
        "--etoro-triggers",
        exists=True,
        dir_okay=False,
        readable=True,
        help="With --etoro: optional JSON for triggers/deep_research_analysts template.",
    ),
    days: int = typer.Option(7, "--days", help="How many recent daily digests to include."),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip the weekly LLM narrative."),
    execute_deep_queue: bool = typer.Option(
        False,
        "--execute-deep-queue",
        help="Run the full graph for queued tickers (expensive; capped by --max-deep).",
    ),
    max_deep: int = typer.Option(3, "--max-deep", help="Max deep runs when --execute-deep-queue is set."),
    trade_date: Optional[str] = typer.Option(None, "--date", "-d", help="Trade date YYYY-MM-DD for deep runs."),
    webhook: Optional[str] = typer.Option(None, "--webhook"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Roll up morning logs; weekly deep-research queue; optional deep execution."""
    _log(verbose)
    cfg = DEFAULT_CONFIG.copy()
    wl_path = None
    wl_obj = None
    if etoro:
        from tradingagents.integrations.etoro.clerk_bridge import fetch_clerk_watchlist_from_etoro

        wl_obj = fetch_clerk_watchlist_from_etoro(etoro_triggers)
    elif watchlist is not None:
        wl_path = watchlist
    digest = run_weekly_clerk(
        watchlist=wl_obj or wl_path,
        days=days,
        webhook_url=webhook,
        with_llm=not no_llm,
        config=cfg,
        trade_date=trade_date,
        execute_deep_queue=execute_deep_queue,
        max_deep=max_deep,
    )
    console.print(digest)


@clerk_app.command("monthly")
def clerk_monthly(
    candidates: Path = typer.Option(
        ...,
        "--candidates",
        "-c",
        exists=True,
        dir_okay=False,
        readable=True,
        help="JSON with 'candidates': ['TICKER', ...] — see cli/static/clerk_monthly_candidates.example.json",
    ),
    max_deep: int = typer.Option(2, "--max-deep", help="How many names get a full multi-agent run."),
    trade_date: Optional[str] = typer.Option(None, "--date", "-d"),
    webhook: Optional[str] = typer.Option(None, "--webhook"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Monthly lookout: capped deep research + LLM synthesis memo."""
    _log(verbose)
    cfg = DEFAULT_CONFIG.copy()
    digest = run_monthly_lookout(
        candidates,
        trade_date=trade_date,
        max_deep=max_deep,
        webhook_url=webhook,
        config=cfg,
    )
    console.print(digest)


@clerk_app.command("example-path")
def clerk_example_path():
    p = Path(__file__).resolve().parent / "static" / "clerk_watchlist.example.json"
    console.print(str(p))
