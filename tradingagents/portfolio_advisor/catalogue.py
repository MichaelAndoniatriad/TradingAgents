"""Write a Markdown (+ optional JSON) catalogue of advisor timestamps and jobs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from tradingagents.portfolio_advisor import state

_TIMESTAMP_KEYS = (
    "last_init_iso",
    "last_weekly_scan_iso",
    "last_weekly_check_iso",
    "last_replan_iso",
    "last_replan_skip_iso",
    "last_bootstrap_iso",
)


def _md_escape_cell(text: str, *, max_len: int = 120) -> str:
    s = str(text or "").replace("\n", " ").replace("|", "\\|").strip()
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def _job_sort_key(j: Dict[str, Any]) -> str:
    st = str(j.get("status") or "")
    if st == "pending":
        return str(j.get("scheduled_at") or "")
    return str(j.get("completed_at") or j.get("created_at") or "")


def build_catalogue_markdown(cfg: Dict[str, Any], st: Dict[str, Any]) -> str:
    """Human-readable catalogue (tables + sections)."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    sp = state.state_path(cfg)
    lines: List[str] = [
        "# Portfolio advisor — jobs & timestamps catalogue",
        "",
        f"_Generated: **{now}**_",
        "",
        "## State file",
        "",
        f"`{sp}`",
        "",
        "## Timestamps",
        "",
        "| Field | Value |",
        "| --- | --- |",
    ]
    for key in _TIMESTAMP_KEYS:
        val = st.get(key)
        lines.append(f"| `{key}` | {_md_escape_cell(str(val) if val is not None else '—', max_len=200)} |")

    digest = st.get("last_catalyst_digest")
    dprev = str(digest or "")[:48] + ("…" if digest and len(str(digest)) > 48 else "")
    lines.append(f"| `last_catalyst_digest` (preview) | {_md_escape_cell(dprev or '—', max_len=200)} |")

    h = st.get("last_portfolio_text_hash")
    hp = (str(h)[:20] + "…") if h and len(str(h)) > 20 else (str(h) if h else "—")
    lines.append(f"| `last_portfolio_text_hash` (prefix) | `{_md_escape_cell(hp)}` |")

    tickers = st.get("last_portfolio_tickers") or []
    if isinstance(tickers, list) and tickers:
        tline = ", ".join(str(x).strip().upper() for x in tickers[:40])
        if len(tickers) > 40:
            tline += f" (+{len(tickers) - 40} more)"
    else:
        tline = "—"
    lines.append(f"| `last_portfolio_tickers` | {_md_escape_cell(tline, max_len=240)} |")

    summ = st.get("last_bootstrap_summary")
    if isinstance(summ, dict) and summ:
        lines.append("| `last_bootstrap_summary` | see JSON export or advisor UI |")
    else:
        lines.append("| `last_bootstrap_summary` | — |")

    units = st.get("last_book_units_by_ticker")
    if isinstance(units, dict) and units:
        lines.append(f"| `last_book_units_by_ticker` | _{len(units)} ticker(s) in state_ |")
    else:
        lines.append("| `last_book_units_by_ticker` | — |")

    jobs_raw = st.get("jobs") or []
    jobs: List[Dict[str, Any]] = [j for j in jobs_raw if isinstance(j, dict)]
    jobs_sorted = sorted(jobs, key=_job_sort_key)

    lines.extend(["", f"## Jobs ({len(jobs_sorted)} rows)", ""])

    if not jobs_sorted:
        lines.append("_No job rows in state._")
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "| # | id | ticker | status | scheduled_at | created_at | completed_at | tier | job_type |",
            "| ---: | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for i, j in enumerate(jobs_sorted, start=1):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(i),
                    _md_escape_cell(str(j.get("id") or ""), max_len=36),
                    _md_escape_cell(str(j.get("ticker") or ""), max_len=12),
                    _md_escape_cell(str(j.get("status") or ""), max_len=14),
                    _md_escape_cell(str(j.get("scheduled_at") or ""), max_len=32),
                    _md_escape_cell(str(j.get("created_at") or ""), max_len=32),
                    _md_escape_cell(str(j.get("completed_at") or ""), max_len=32),
                    _md_escape_cell(str(j.get("execution_tier") or ""), max_len=18),
                    _md_escape_cell(str(j.get("job_type") or ""), max_len=22),
                ]
            )
            + " |"
        )

    lines.extend(["", "### Job notes (reason / errors)", ""])
    for j in jobs_sorted:
        jid = str(j.get("id") or "")
        tk = str(j.get("ticker") or "")
        rs = str(j.get("reason") or "").strip()
        cr = str(j.get("cancel_reason") or "").strip()
        err = str(j.get("error") or "").strip()
        if not (rs or cr or err):
            continue
        lines.append(f"- **{tk}** `{jid}`")
        if rs:
            lines.append(f"  - reason: {_md_escape_cell(rs, max_len=400)}")
        if cr:
            lines.append(f"  - cancel: {_md_escape_cell(cr, max_len=400)}")
        if err:
            lines.append(f"  - error: {_md_escape_cell(err, max_len=400)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_catalogue_payload(cfg: Dict[str, Any], st: Dict[str, Any]) -> Dict[str, Any]:
    """Structured snapshot for JSON export."""
    jobs_raw = st.get("jobs") or []
    jobs = [j for j in jobs_raw if isinstance(j, dict)]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state_path": str(state.state_path(cfg)),
        "first_scan_complete": st.get("first_scan_complete"),
        "timestamps": {k: st.get(k) for k in _TIMESTAMP_KEYS},
        "last_catalyst_digest": st.get("last_catalyst_digest"),
        "last_portfolio_text_hash": st.get("last_portfolio_text_hash"),
        "last_portfolio_tickers": st.get("last_portfolio_tickers"),
        "last_bootstrap_summary": st.get("last_bootstrap_summary"),
        "last_book_units_by_ticker": st.get("last_book_units_by_ticker"),
        "jobs": sorted(jobs, key=_job_sort_key),
    }


def default_catalogue_paths(cfg: Dict[str, Any]) -> Tuple[Path, Path]:
    """Default `<advisor_dir>/advisor_jobs_catalogue.md` and `.json` siblings."""
    base = state.advisor_dir(cfg) / "advisor_jobs_catalogue"
    return base.with_suffix(".md"), base.with_suffix(".json")


def write_advisor_catalogue(
    cfg: Dict[str, Any],
    *,
    markdown_path: Path | None = None,
    write_json: bool = False,
) -> Dict[str, str]:
    """Persist catalogue files. Returns paths written under keys ``markdown``, ``json`` (if any)."""
    st = state.load_state(cfg)
    md_path, json_path = default_catalogue_paths(cfg)
    if markdown_path is not None:
        md_path = Path(markdown_path).expanduser()
    out: Dict[str, str] = {}
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_body = build_catalogue_markdown(cfg, st)
    md_path.write_text(md_body, encoding="utf-8")
    out["markdown"] = str(md_path.resolve())
    if write_json:
        payload = build_catalogue_payload(cfg, st)
        jp = md_path.with_suffix(".json") if markdown_path is not None else json_path
        jp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        out["json"] = str(jp.resolve())
    return out
