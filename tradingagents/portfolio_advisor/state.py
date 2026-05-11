"""JSON persistence for portfolio advisor jobs and scan metadata."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List


def advisor_dir(cfg: Dict[str, Any]) -> Path:
    raw = cfg.get("portfolio_advisor_dir")
    if isinstance(raw, str) and raw.strip():
        return Path(raw).expanduser()
    home = os.path.join(os.path.expanduser("~"), ".tradingagents", "portfolio_advisor")
    return Path(home)


def state_path(cfg: Dict[str, Any]) -> Path:
    raw = cfg.get("portfolio_advisor_state_path")
    if isinstance(raw, str) and raw.strip():
        return Path(raw).expanduser()
    return advisor_dir(cfg) / "state.json"


def default_state() -> Dict[str, Any]:
    return {
        "version": 1,
        "first_scan_complete": False,
        "last_init_iso": None,
        "last_weekly_scan_iso": None,
        "last_weekly_check_iso": None,
        "last_replan_iso": None,
        "last_replan_skip_iso": None,
        "last_catalyst_digest": None,
        "last_portfolio_text_hash": None,
        "last_bootstrap_iso": None,
        "last_portfolio_tickers": [],
        # Total eToro units per normalized ticker from last successful portfolio row fetch.
        "last_book_units_by_ticker": {},
        "jobs": [],
    }


def load_state(cfg: Dict[str, Any]) -> Dict[str, Any]:
    path = state_path(cfg)
    base = default_state()
    if not path.is_file():
        advisor_dir(cfg).mkdir(parents=True, exist_ok=True)
        return base
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return base
    if not isinstance(data, dict):
        return base
    out = deepcopy(base)
    for k, v in data.items():
        if k == "jobs" and not isinstance(v, list):
            continue
        out[k] = v
    return out


def save_state(cfg: Dict[str, Any], state: Dict[str, Any]) -> None:
    path = state_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    payload = json.dumps(state, indent=2, ensure_ascii=False)
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def list_pending_jobs(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    jobs = state.get("jobs") or []
    return [j for j in jobs if isinstance(j, dict) and j.get("status") == "pending"]


def cancel_job(state: Dict[str, Any], job_id: str, reason: str = "") -> bool:
    jobs: List[Dict[str, Any]] = state.get("jobs") or []
    for j in jobs:
        if j.get("id") == job_id and j.get("status") == "pending":
            j["status"] = "cancelled"
            j["cancel_reason"] = reason
            return True
    return False


def cancel_all_pending(state: Dict[str, Any], reason: str) -> int:
    n = 0
    for j in state.get("jobs") or []:
        if j.get("status") == "pending":
            j["status"] = "cancelled"
            j["cancel_reason"] = reason
            n += 1
    return n


def append_jobs(state: Dict[str, Any], new_jobs: List[Dict[str, Any]]) -> None:
    jobs = state.setdefault("jobs", [])
    jobs.extend(new_jobs)
