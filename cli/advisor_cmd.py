# cli/advisor_cmd.py — live position advisor CLI

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.advisor.runner import run_advisor_loop, run_advisor_once
from tradingagents.portfolio_advisor import messaging as portfolio_messaging
from tradingagents.portfolio_advisor import service as portfolio_advisor_service

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


portfolio_app = typer.Typer(
    help=(
        "Autonomous eToro portfolio advisor: init/replan builds an LLM schedule; weekly is a "
        "light portfolio check; run-due executes scheduled deep research; catalogue exports jobs/timestamps. "
        "All advisory only."
    ),
    no_args_is_help=True,
)
advisor_app.add_typer(portfolio_app, name="portfolio")


@portfolio_app.command("init")
def portfolio_advisor_init(
    force: bool = typer.Option(
        False,
        "--force",
        help="Reset advisor state and rebuild the schedule from scratch.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """First deployment: full eToro scan + LLM schedule + notifications."""
    _configure_logging(verbose)
    cfg = DEFAULT_CONFIG.copy()
    try:
        portfolio_advisor_service.run_init(cfg, force=force)
        console.print("[green]Portfolio advisor init complete.[/green]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e


@portfolio_app.command("weekly")
def portfolio_advisor_weekly(
    force: bool = typer.Option(
        False,
        "--force",
        help="Run even if today is not the configured weekday (for testing).",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Light weekly check: positions vs snapshot, overdue jobs, orphan job cleanup (not a full replan)."""
    _configure_logging(verbose)
    cfg = DEFAULT_CONFIG.copy()
    try:
        outcome = portfolio_advisor_service.run_weekly(cfg, ignore_weekday=force)
        if outcome == "skipped_weekday":
            console.print(
                "[dim]Weekly check skipped (not your configured weekday; "
                "use --force to run anyway).[/dim]"
            )
        else:
            console.print("[green]Weekly portfolio check complete.[/green]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e


@portfolio_app.command("replan")
def portfolio_advisor_replan(
    force: bool = typer.Option(
        False,
        "--force",
        help="Run even if today is not the configured weekday (for testing).",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Full LLM reschedule (replaces pending jobs). Same weekday gate as weekly by default."""
    _configure_logging(verbose)
    cfg = DEFAULT_CONFIG.copy()
    try:
        outcome = portfolio_advisor_service.run_replan(cfg, ignore_weekday=force)
        if outcome == "skipped_weekday":
            console.print(
                "[dim]Replan skipped (weekday gate). Use --force to run anyway.[/dim]"
            )
        else:
            console.print("[green]Portfolio advisor replan complete.[/green]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e


@portfolio_app.command("alert")
def portfolio_advisor_alert(
    subject: str = typer.Option(..., "--subject", "-s", help="Email / webhook subject line."),
    body: str = typer.Option(..., "--body", "-b", help="Message body (advisory text)."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Send an ad-hoc advisor message via the same webhook + SMTP as other portfolio notices."""
    _configure_logging(verbose)
    cfg = DEFAULT_CONFIG.copy()
    # Manual `portfolio alert` is user-initiated; always deliver regardless of window.
    ok = portfolio_messaging.send_advisor_message(cfg, subject, body, urgent=True)
    if ok:
        console.print("[green]Message sent (at least one channel).[/green]")
    else:
        console.print("[yellow]No channel accepted the message; check webhook + SMTP env.[/yellow]")


@portfolio_app.command("run-due")
def portfolio_advisor_run_due(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Execute pending scheduled deep runs (cron every 10–30 minutes)."""
    _configure_logging(verbose)
    cfg = DEFAULT_CONFIG.copy()
    try:
        n = portfolio_advisor_service.run_due_jobs(cfg)
        console.print(f"[cyan]Advisor run-due:[/cyan] processed {n} job(s).")
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e


@portfolio_app.command("morning-digest")
def portfolio_morning_digest(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Send morning digest of open action items via ntfy."""
    _configure_logging(verbose)
    cfg = DEFAULT_CONFIG.copy()
    try:
        from tradingagents.portfolio_advisor.action_log import run_morning_digest
        sent = run_morning_digest(cfg)
        if sent:
            console.print("[green]Morning digest sent.[/green]")
        else:
            console.print("[yellow]No open action items — nothing sent.[/yellow]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e


@portfolio_app.command("watchdog")
def portfolio_advisor_watchdog(
    force: bool = typer.Option(
        False,
        "--force",
        help="Run even outside the default 13:30 to 20:00 UTC weekday window (for tests).",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Price only rule sweep: no LLM. Use a 5 to 10 minute cron during US equity hours."""
    _configure_logging(verbose)
    cfg = DEFAULT_CONFIG.copy()
    try:
        n = portfolio_advisor_service.run_watchdog(cfg, ignore_market_hours=force)
        console.print(f"[cyan]Advisor watchdog:[/cyan] critical alert count {n}.")
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e


@portfolio_app.command("bootstrap")
def portfolio_advisor_bootstrap(
    delay: float = typer.Option(
        45.0,
        "--delay",
        "-d",
        help="Seconds to sleep between tickers (rate limits / provider throttling).",
    ),
    max_positions: Optional[int] = typer.Option(
        None,
        "--max",
        "-m",
        help="Optional cap on how many holdings to analyze (default: all).",
    ),
    trade_date: Optional[str] = typer.Option(
        None,
        "--date",
        help="YYYY-MM-DD as-of for saved reports (default: local today's date).",
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Skip tickers that already have clerk_deep/<SYM>/<date>_clerk_triggered.md for that date.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Run full LangGraph analysis for each live eToro holding (explicit, costly)."""
    _configure_logging(verbose)
    cfg = DEFAULT_CONFIG.copy()
    try:
        out = portfolio_advisor_service.run_bootstrap(
            cfg,
            delay_seconds=delay,
            max_positions=max_positions,
            trade_date=trade_date,
            resume=resume,
        )
        console.print(f"[green]Bootstrap finished:[/green] {out.get('results')}")
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e


@portfolio_app.command("memory-review")
def portfolio_advisor_memory_review(
    days: int = typer.Option(120, "--days", help="Event log lookback window."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Summarize JSONL event log + optional reasoning narrative (emailed)."""
    _configure_logging(verbose)
    cfg = DEFAULT_CONFIG.copy()
    try:
        text = portfolio_advisor_service.run_memory_review(cfg, lookback_days=days)
        console.print(text[:4000])
        console.print("[green]Memory review sent.[/green]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e


@portfolio_app.command("post-earnings")
def portfolio_advisor_post_earnings(
    ticker: str = typer.Option(..., "--ticker", "-t", help="Symbol in your current eToro export."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """One-shot post-earnings verdict email (reasoning model; advisory only)."""
    _configure_logging(verbose)
    cfg = DEFAULT_CONFIG.copy()
    try:
        text = portfolio_advisor_service.run_post_earnings(cfg, ticker)
        console.print("[green]Post-earnings verdict sent.[/green]")
        console.print(text[:2000])
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e


@portfolio_app.command("status")
def portfolio_advisor_status():
    """Show persisted advisor jobs and last scan timestamps."""
    cfg = DEFAULT_CONFIG.copy()
    console.print(portfolio_advisor_service.status_text(cfg))


@portfolio_app.command("catalogue")
def portfolio_advisor_catalogue(
    out: Optional[str] = typer.Option(
        None,
        "--out",
        "-o",
        help="Markdown output path (default: ~/.tradingagents/portfolio_advisor/advisor_jobs_catalogue.md).",
    ),
    json: bool = typer.Option(
        False,
        "--json",
        help="Also write a machine-readable JSON snapshot (same stem as the Markdown file).",
    ),
):
    """Write a Markdown catalogue of advisor timestamps and all jobs (plus optional JSON)."""
    cfg = DEFAULT_CONFIG.copy()
    try:
        from tradingagents.portfolio_advisor.catalogue import write_advisor_catalogue

        paths = write_advisor_catalogue(
            cfg,
            markdown_path=Path(out).expanduser() if out else None,
            write_json=json,
        )
        console.print("[green]Catalogue written:[/green]")
        for k, v in paths.items():
            console.print(f"  {k}: {v}")
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e


@portfolio_app.command("pm-cycle")
def portfolio_advisor_pm_cycle(
    trigger: str = typer.Option(
        "manual",
        "--trigger",
        "-t",
        help="Label stored in logs (e.g. manual, after_bootstrap, cron).",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Run one advisor-level portfolio manager cycle (structured memo + stances + tasks + memory)."""
    _configure_logging(verbose)
    cfg = DEFAULT_CONFIG.copy()
    try:
        from tradingagents.portfolio_advisor.advisor_pm import run_pm_cycle

        out = run_pm_cycle(cfg, trigger=trigger)
        console.print("[green]PM cycle complete.[/green]")
        console.print(out.executive_summary[:2000])
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e


@portfolio_app.command("cost-report")
def portfolio_cost_report(
    days: int = typer.Option(7, "--days", help="Lookback window in days (default 7)."),
):
    """Show LLM spend: daily totals, top models, top individual calls."""
    from rich.table import Table
    from rich import box
    from tradingagents.llm_clients.cost_report import (
        load_records,
        daily_spend,
        model_spend,
        top_calls,
        null_cost_count,
        total_spend,
    )

    records = load_records(days=days)
    if not records:
        console.print(f"[yellow]No cost records found for the last {days} day(s).[/yellow]")
        return

    null_count = null_cost_count(records)
    grand_total = total_spend(records)

    console.print(f"\n[bold]LLM Cost Report[/bold] — last {days} day(s)\n")
    if null_count:
        console.print(
            f"[yellow]Warning:[/yellow] {null_count} call(s) have null cost_usd "
            "(model not in pricing table).\n"
        )

    # Total and per-day breakdown
    console.print(f"[bold]Total spend:[/bold] ${grand_total:.4f}")
    day_totals = daily_spend(records)
    if day_totals:
        day_table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold magenta")
        day_table.add_column("Date", style="cyan")
        day_table.add_column("Spend (USD)", justify="right")
        for day, cost in day_totals.items():
            day_table.add_row(day, f"${cost:.4f}")
        console.print(day_table)

    # Top 5 models
    console.print("\n[bold]Top 5 models by cost:[/bold]")
    model_table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold magenta")
    model_table.add_column("Model", style="cyan")
    model_table.add_column("Calls", justify="right")
    model_table.add_column("Total (USD)", justify="right")
    for model, count, cost in model_spend(records)[:5]:
        model_table.add_row(model, str(count), f"${cost:.4f}")
    console.print(model_table)

    # Top 5 individual calls
    console.print("\n[bold]Top 5 most expensive calls:[/bold]")
    call_table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold magenta")
    call_table.add_column("Timestamp", style="cyan")
    call_table.add_column("Model")
    call_table.add_column("Tokens", justify="right")
    call_table.add_column("Cost (USD)", justify="right")
    for rec in top_calls(records, 5):
        cost_str = f"${rec['cost_usd']:.4f}" if rec.get("cost_usd") is not None else "null"
        call_table.add_row(
            str(rec.get("ts", ""))[:19],
            str(rec.get("model", "")),
            str(rec.get("total_tokens", 0)),
            cost_str,
        )
    console.print(call_table)
    console.print(f"\n[dim]Calls with unknown pricing: {null_count}[/dim]")


@portfolio_app.command("telegram-listen")
def portfolio_advisor_telegram_listen(
    once: bool = typer.Option(False, "--once", help="Poll once and exit."),
    interval: float = typer.Option(2.0, "--interval", help="Sleep seconds between long-poll requests."),
    timeout: int = typer.Option(25, "--timeout", help="Telegram long-poll timeout seconds."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Listen for Telegram bot messages and answer with the advisor PM."""
    _configure_logging(verbose)
    cfg = DEFAULT_CONFIG.copy()
    try:
        from tradingagents.portfolio_advisor.telegram_bot import poll_once, run_poll_loop

        if once:
            n = poll_once(cfg, timeout=timeout)
            console.print(f"[cyan]Telegram listener:[/cyan] processed {n} message(s).")
        else:
            console.print("[cyan]Telegram listener running.[/cyan] Ctrl+C to stop.")
            run_poll_loop(cfg, interval_seconds=interval, timeout=timeout)
    except KeyboardInterrupt:
        console.print("[yellow]Telegram listener stopped.[/yellow]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
