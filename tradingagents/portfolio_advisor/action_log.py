"""Persistent action log — open items the human needs to act on.

Updated by PM stance changes and analysis REQUIRED ACTION sections.
Read by the morning digest cron and the Streamlit dashboard.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _action_log_path(cfg: Dict[str, Any]) -> Path:
    from tradingagents.portfolio_advisor.state import advisor_dir
    return advisor_dir(cfg) / "action_log.json"


def _load(cfg: Dict[str, Any]) -> Dict[str, Any]:
    p = _action_log_path(cfg)
    if not p.is_file():
        return {"items": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"items": []}


def _save(cfg: Dict[str, Any], data: Dict[str, Any]) -> None:
    p = _action_log_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def upsert_action(
    cfg: Dict[str, Any],
    ticker: str,
    action: str,
    rationale: str,
    source: str,
) -> None:
    """Add or update an open action item. Deduplicates by ticker+action."""
    data = _load(cfg)
    now = datetime.now(timezone.utc).isoformat()
    for item in data["items"]:
        if (
            item.get("ticker") == ticker
            and item.get("action") == action
            and item.get("status") == "open"
        ):
            item["rationale"] = rationale[:300]
            item["updated_at"] = now
            item["source"] = source
            _save(cfg, data)
            return
    data["items"].append(
        {
            "id": uuid.uuid4().hex[:12],
            "ticker": ticker,
            "action": action,
            "rationale": rationale[:300],
            "source": source,
            "created_at": now,
            "updated_at": now,
            "status": "open",
        }
    )
    _save(cfg, data)


def mark_done(cfg: Dict[str, Any], ticker: str, action: Optional[str] = None) -> int:
    """Mark open action item(s) for ticker as done. Returns count closed."""
    data = _load(cfg)
    now = datetime.now(timezone.utc).isoformat()
    changed = 0
    for item in data["items"]:
        if item.get("ticker") == ticker and item.get("status") == "open":
            if action is None or item.get("action") == action:
                item["status"] = "done"
                item["updated_at"] = now
                changed += 1
    if changed:
        _save(cfg, data)
    return changed


def load_open_actions(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = _load(cfg)
    return [i for i in data["items"] if i.get("status") == "open"]


def ingest_from_analysis(cfg: Dict[str, Any], ticker: str, text: str, source: str) -> None:
    """Extract REQUIRED ACTION from analysis text and write to log if found."""
    required_action = ""
    in_action = False
    for line in text.splitlines():
        s = line.strip()
        upper = s.upper()
        if upper in ("REQUIRED ACTION", "REQUIRED ACTIONS"):
            in_action = True
            continue
        if s and upper == s and len(s) > 2:
            in_action = False
            continue
        if in_action and s and s.lower() not in ("none", "n/a", ""):
            required_action = s
            break
    if not required_action:
        return
    lower = required_action.lower()
    if any(w in lower for w in ("exit", "sell", "close", "full exit")):
        action = "sell"
    elif any(w in lower for w in ("trim", "reduce", "cut")):
        action = "trim"
    else:
        action = "review"
    upsert_action(cfg, ticker, action, required_action, source=source)


def format_digest(cfg: Dict[str, Any]) -> str:
    """Format open action items for a short ntfy message."""
    items = load_open_actions(cfg)
    if not items:
        return ""
    lines = ["Open actions:"]
    for item in sorted(items, key=lambda x: x.get("ticker", "")):
        age = ""
        try:
            created = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
            days = (datetime.now(timezone.utc) - created).days
            if days > 0:
                age = f" ({days}d)"
        except Exception:
            pass
        lines.append(
            f"- {item['ticker']} {item['action'].upper()}{age}: {item['rationale'][:120]}"
        )
    return "\n".join(lines)


def run_morning_digest(cfg: Dict[str, Any]) -> bool:
    """Send morning digest of open action items. Returns True if anything was sent."""
    from tradingagents.portfolio_advisor import messaging
    body = format_digest(cfg)
    if not body:
        return False
    messaging.send_advisor_message(cfg, "Morning action digest", body)
    return True
