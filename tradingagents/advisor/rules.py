# tradingagents/advisor/rules.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

from tradingagents.advisor.earnings import next_earnings_from_yfinance, parse_iso_date
from tradingagents.advisor.positions import PositionSpec


@dataclass(frozen=True)
class AdvisorAlert:
    """A single actionable alert for one position."""

    ticker: str
    trigger_code: str
    severity: str  # "critical" | "warning" | "info"
    title: str
    body: str
    suggested_action: str


def _pct_gain(entry: float, price: float) -> float:
    if entry <= 0:
        return 0.0
    return (price - entry) / entry * 100.0


def _pct_drawdown(entry: float, price: float) -> float:
    if entry <= 0:
        return 0.0
    return (entry - price) / entry * 100.0


def resolve_earnings_date(pos: PositionSpec) -> Optional[date]:
    if pos.next_earnings_date:
        return parse_iso_date(pos.next_earnings_date)
    if pos.fetch_earnings_from_yfinance:
        return next_earnings_from_yfinance(pos.ticker)
    return None


def evaluate_position_rules(
    pos: PositionSpec,
    current_price: float,
    as_of: date,
) -> List[AdvisorAlert]:
    """Apply standardized exit-style rules (price / earnings proximity).

    Trigger codes:
    - ``t1_pre_earnings_trim``: +15% vs entry within window before earnings
    - ``t3_double_half``: price >= 2x entry
    - ``dd40``: >=40% drawdown from entry (full exit)
    - ``dd30``: >=30% drawdown (review window / next earnings)
    - ``t2_thesis_reminder``: reminder to check thesis-break metrics before earnings
    """
    alerts: List[AdvisorAlert] = []
    t = pos.ticker
    entry = pos.entry_price

    gain = _pct_gain(entry, current_price)
    dd = _pct_drawdown(entry, current_price)

    # Most severe first so notifications read clearly
    if dd >= 40:
        alerts.append(
            AdvisorAlert(
                ticker=t,
                trigger_code="dd40",
                severity="critical",
                title=f"{t}: 40% drawdown floor",
                body=(
                    f"Price {current_price:.4f} is ~{dd:.1f}% below entry {entry:.4f}. "
                    "Policy: exit the full position within 48 hours regardless of thesis."
                ),
                suggested_action="Exit 100% of the position (binding drawdown rule).",
            )
        )
        return alerts

    if current_price >= 2.0 * entry:
        alerts.append(
            AdvisorAlert(
                ticker=t,
                trigger_code="t3_double_half",
                severity="warning",
                title=f"{t}: 2x from entry",
                body=(
                    f"Price {current_price:.4f} is at or above 2x entry {entry:.4f}. "
                    "Policy: sell half; let the remainder run (capital recovered)."
                ),
                suggested_action="Sell 50% of the position at market or your usual execution style.",
            )
        )

    if dd >= 30:
        alerts.append(
            AdvisorAlert(
                ticker=t,
                trigger_code="dd30",
                severity="warning",
                title=f"{t}: 30% drawdown — review window",
                body=(
                    f"Price {current_price:.4f} is ~{dd:.1f}% below entry {entry:.4f}. "
                    "If thesis is unchanged, allow one review at the next scheduled earnings; "
                    "otherwise treat as thesis risk."
                ),
                suggested_action="Schedule a thesis review before next earnings; do not average down by default.",
            )
        )

    earn = resolve_earnings_date(pos)
    if earn is not None:
        days_to = (earn - as_of).days
        if 0 <= days_to <= 7:
            if gain >= 15.0:
                alerts.append(
                    AdvisorAlert(
                        ticker=t,
                        trigger_code="t1_pre_earnings_trim",
                        severity="warning",
                        title=f"{t}: pre-earnings trim (Trigger 1)",
                        body=(
                            f"Earnings on {earn.isoformat()} (in {days_to} day(s)). "
                            f"Position is ~{gain:.1f}% above entry. "
                            "Policy: sell half before the print; hold half through."
                        ),
                        suggested_action="Sell 50% before the earnings event; keep 50% through the print.",
                    )
                )
            if pos.thesis_break_metrics and 0 <= days_to <= 3:
                metrics = "; ".join(pos.thesis_break_metrics)
                alerts.append(
                    AdvisorAlert(
                        ticker=t,
                        trigger_code="t2_thesis_reminder",
                        severity="info",
                        title=f"{t}: thesis-break checklist before earnings",
                        body=(
                            f"Earnings on {earn.isoformat()}. Verify defined thesis-break metrics: {metrics}. "
                            "If any break on the print or material news, exit full within 48 hours."
                        ),
                        suggested_action="Compare the release to your written thesis-break metrics; prepare to exit if broken.",
                    )
                )

    return alerts


def format_digest_text(
    as_of: date,
    prices: dict[str, float],
    all_alerts: List[AdvisorAlert],
) -> str:
    """Plain-text digest for console / webhook."""
    lines = [
        f"TradingAgents position advisor — {as_of.isoformat()}",
        "",
    ]
    if not all_alerts:
        lines.append("No rule-based alerts at this check.")
        return "\n".join(lines)

    for a in all_alerts:
        lines.append(f"[{a.severity.upper()}] {a.title}")
        lines.append(a.body)
        lines.append(f"→ {a.suggested_action}")
        lines.append("")

    return "\n".join(lines).rstrip()
