# cli/advisor_cmd.py — live position advisor CLI

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.advisor.runner import run_advisor_loop, run_advisor_once

console = Console()
advisor_app = typer.Typer(
    help=(
        "Optional position rule alerts (e.g. drawdown / earnings trims). "
        "For scheduled headline + calendar-driven scans without price triggers, use `tradingagents clerk`."
    ),
    no_args_is_help=True,
)


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


@advisor_app.command("run")
def advisor_run(
    positions: Path = typer.Option(
        ...,
        "--positions",
        "-p",
        exists=True,
        dir_okay=False,
        readable=True,
        help="JSON file with a top-level 'positions' array (see cli/static/advisor_positions.example.json).",
    ),
    webhook: Optional[str] = typer.Option(
        None,
        "--webhook",
        "-w",
        help="Override TRADINGAGENTS_ADVISOR_WEBHOOK_URL for this run.",
    ),
    interval: int = typer.Option(
        0,
        "--interval",
        "-i",
        help="If >0, re-run every N seconds (daemon-style loop on this machine).",
    ),
    llm_digest: bool = typer.Option(
        False,
        "--llm-digest",
        help="Append a one-shot quick-model narrative using your configured LLM provider.",
    ),
    no_dedupe: bool = typer.Option(
        False,
        "--no-dedupe",
        help="Send a webhook on every tick even if the same alert was already sent today.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging."),
):
    """Evaluate positions, print a digest, and POST alerts to a webhook when configured."""
    _configure_logging(verbose)
    cfg = DEFAULT_CONFIG.copy()

    if interval and interval > 0:
        console.print(
            f"[cyan]Advisor loop[/cyan] every {interval}s — Ctrl+C to stop. "
            f"Positions: {positions.resolve()}"
        )
        run_advisor_loop(
            positions,
            interval_seconds=interval,
            webhook_url=webhook,
            use_dedupe=not no_dedupe,
            with_llm_digest=llm_digest,
            config=cfg,
        )
        return

    text, alerts = run_advisor_once(
        positions,
        webhook_url=webhook,
        use_dedupe=not no_dedupe,
        with_llm_digest=llm_digest,
        config=cfg,
    )
    console.print(text)
    if alerts:
        console.print(f"\n[bold]{len(alerts)} alert(s)[/bold] evaluated this tick.")
    else:
        console.print("\n[dim]No rule-based alerts this tick.[/dim]")


@advisor_app.command("example-path")
def advisor_example_path():
    """Print the path to the bundled example positions JSON."""
    here = Path(__file__).resolve().parent / "static" / "advisor_positions.example.json"
    console.print(str(here))
