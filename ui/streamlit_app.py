# Local web UI for TradingAgents.
#
# Run:  source .venv/bin/activate && python -m cli.main ui
#   or: sh scripts/run-ui.sh

from __future__ import annotations

import html as html_module
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

import tradingagents  # noqa: F401 — loads .env

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

PROJECT_ROOT = Path(__file__).resolve().parents[1]

ANALYST_ORDER: List[str] = ["market", "social", "news", "fundamentals"]
ANALYST_LABELS = {
    "market": "Market (technicals)",
    "social": "Sentiment",
    "news": "News",
    "fundamentals": "Fundamentals",
}
PROVIDERS = ["openrouter", "openai", "google", "anthropic", "ollama", "deepseek", "xai"]

NAV_PAGES = ["Full analysis", "Portfolio advisor", "eToro"]

# Session keys for full-width outputs below control columns
_SS_ANALYSIS = "_ui_last_analysis"
_SS_PORT_STATUS = "_ui_portfolio_advisor_status"
_SS_PORT_NOTE = "_ui_portfolio_advisor_note"


def _default_openrouter_url() -> str:
    return "https://openrouter.ai/api/v1"


def _inject_app_styles() -> None:
    """Light-touch CSS: works with Streamlit light/dark theme; do not override sidebar colors."""
    st.markdown(
        """
<style>
  .block-container { padding-top: 1rem; padding-bottom: 2.5rem; max-width: 1100px; }
  .ta-section { margin-top: 0.25rem; margin-bottom: 1rem; }
  hr.ta-soft { margin: 1.25rem 0; opacity: 0.35; }

  /* eToro portfolio strip */
  .ta-etoro-wrap {
    border-radius: 14px;
    padding: 1rem 1.1rem 1.05rem;
    margin: 0.35rem 0 1.1rem;
    background: linear-gradient(135deg, rgba(13, 148, 136, 0.07) 0%, rgba(99, 102, 241, 0.06) 100%);
    border: 1px solid color-mix(in srgb, var(--secondary-background-color) 65%, transparent);
    box-shadow: 0 1px 2px color-mix(in srgb, var(--text-color) 6%, transparent);
  }
  .ta-etoro-stats {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.75rem 1rem;
    margin-bottom: 0.85rem;
  }
  @media (max-width: 700px) {
    .ta-etoro-stats { grid-template-columns: 1fr; }
  }
  .ta-etoro-stat {
    background: color-mix(in srgb, var(--secondary-background-color) 88%, transparent);
    border-radius: 10px;
    padding: 0.65rem 0.75rem;
    border: 1px solid color-mix(in srgb, var(--secondary-background-color) 40%, transparent);
  }
  .ta-etoro-stat-label {
    display: block;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    opacity: 0.72;
    margin-bottom: 0.2rem;
  }
  .ta-etoro-stat-value {
    font-size: 1.35rem;
    font-weight: 600;
    line-height: 1.25;
    font-variant-numeric: tabular-nums;
  }
  .ta-val-pnl-up { color: #16a34a; }
  .ta-val-pnl-down { color: #dc2626; }
  .ta-val-pnl-flat { color: var(--text-color); opacity: 0.85; }

  .ta-pos-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 0.65rem;
  }
  .ta-pos-grid.ta-pos-grid--compact {
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 0.5rem;
  }
  .ta-pos-card {
    border-radius: 12px;
    padding: 0.75rem 0.85rem;
    background: var(--secondary-background-color);
    border: 1px solid color-mix(in srgb, var(--text-color) 10%, transparent);
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
  }
  .ta-pos-card:hover {
    border-color: color-mix(in srgb, var(--text-color) 18%, transparent);
    box-shadow: 0 2px 8px color-mix(in srgb, var(--text-color) 8%, transparent);
  }
  .ta-pos-card--compact { padding: 0.55rem 0.65rem; }
  .ta-pos-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.5rem;
    margin-bottom: 0.45rem;
  }
  .ta-pos-symbol {
    font-weight: 700;
    font-size: 1.05rem;
    letter-spacing: -0.02em;
  }
  .ta-pos-name {
    font-size: 0.78rem;
    opacity: 0.72;
    line-height: 1.25;
    margin-top: 0.1rem;
  }
  .ta-badge {
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    gap: 0.28rem;
    font-size: 0.68rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 0.28rem 0.45rem;
    border-radius: 999px;
    border: 1px solid transparent;
  }
  .ta-badge-long {
    background: color-mix(in srgb, #16a34a 18%, transparent);
    color: #15803d;
    border-color: color-mix(in srgb, #16a34a 35%, transparent);
  }
  .ta-badge-short {
    background: color-mix(in srgb, #dc2626 16%, transparent);
    color: #b91c1c;
    border-color: color-mix(in srgb, #dc2626 32%, transparent);
  }
  .ta-badge-unknown {
    background: color-mix(in srgb, var(--text-color) 10%, transparent);
    color: var(--text-color);
    opacity: 0.75;
  }
  .ta-pos-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem 0.75rem;
    font-size: 0.78rem;
    opacity: 0.88;
    font-variant-numeric: tabular-nums;
  }
  .ta-pos-pnl {
    margin-top: 0.5rem;
    font-size: 0.92rem;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  .ta-pos-pnl-up { color: #16a34a; }
  .ta-pos-pnl-down { color: #dc2626; }
  .ta-pos-pnl-flat { opacity: 0.8; }
  .ta-pos-pnl-sticker {
    display: inline-block;
    font-size: 0.85rem;
    line-height: 1;
    margin-right: 0.25rem;
    vertical-align: middle;
  }
  .ta-pos-pnl-sticker-up { color: #16a34a; }
  .ta-pos-pnl-sticker-down { color: #dc2626; }
  .ta-pos-pnl-sticker-flat { opacity: 0.55; }
  .ta-pos-empty {
    padding: 1rem;
    text-align: center;
    opacity: 0.7;
    font-size: 0.9rem;
  }
  .ta-etoro-page-hero {
    margin-bottom: 0.5rem;
  }
</style>
        """,
        unsafe_allow_html=True,
    )


def _page_header(title: str, subtitle: str) -> None:
    st.title(title)
    st.caption(subtitle)
    st.markdown('<hr class="ta-soft"/>', unsafe_allow_html=True)


def _build_config(side: Dict[str, Any]) -> Dict[str, Any]:
    cfg: Dict[str, Any] = DEFAULT_CONFIG.copy()
    cfg["llm_provider"] = side["provider"].lower().strip()
    cfg["deep_think_llm"] = side["deep_model"].strip()
    cfg["quick_think_llm"] = side["quick_model"].strip()
    cfg["output_language"] = side["output_language"].strip() or "English"
    cfg["max_debate_rounds"] = int(side["max_debate"])
    cfg["max_risk_discuss_rounds"] = int(side["max_risk"])
    cfg["checkpoint_enabled"] = bool(side["checkpoint"])
    bu = (side.get("backend_url") or "").strip()
    if bu:
        cfg["backend_url"] = bu
    elif cfg["llm_provider"] == "openrouter":
        cfg["backend_url"] = _default_openrouter_url()

    # Corporate hierarchy (OpenRouter per-agent): only adjustable here + DEFAULT_CONFIG.
    cfg["corporate_hierarchy_enabled"] = bool(side.get("corporate_hierarchy", True))
    or_base = (side.get("corporate_openrouter_base_url") or "").strip()
    cfg["corporate_openrouter_base_url"] = or_base or None
    cfg["llm_fallback_openrouter_model"] = (
        side.get("llm_fallback_openrouter_model") or "openai/gpt-4o-mini"
    ).strip()
    raw = (side.get("agent_llm_routing_json") or "").strip()
    if raw:
        try:
            cfg["agent_llm_routing"] = json.loads(raw)
            if not isinstance(cfg["agent_llm_routing"], dict):
                cfg["agent_llm_routing"] = {}
        except json.JSONDecodeError:
            cfg["agent_llm_routing"] = {}
    else:
        cfg["agent_llm_routing"] = {}

    dv = dict(cfg.get("data_vendors") or {})
    dv["news_data"] = side["news_vendor"]
    cfg["data_vendors"] = dv

    cfg.pop("progress_callback", None)
    return cfg


def _selected_analysts(side: Dict[str, Any]) -> List[str]:
    return [k for k in ANALYST_ORDER if side.get(f"analyst_{k}", True)]


def _etoro_env_configured() -> bool:
    return bool(
        (os.environ.get("ETORO_API_KEY") or "").strip()
        and (os.environ.get("ETORO_USER_KEY") or "").strip()
    )


def _ensure_etoro_snapshot() -> Dict[str, Any]:
    if not _etoro_env_configured():
        return {"ok": False, "err": "Set ETORO_API_KEY and ETORO_USER_KEY in `.env`."}
    if "etoro_snap" in st.session_state:
        return st.session_state["etoro_snap"]
    try:
        from tradingagents.integrations.etoro.client import EtoroClient
        from tradingagents.integrations.etoro.portfolio import (
            dedupe_positions,
            instrument_id_from_position,
            iter_positions,
            portfolio_headlines,
            summarize_portfolio,
        )

        client = EtoroClient()
        payload = client.get_portfolio_pnl()
        cp = payload.get("clientPortfolio") or {}
        positions = dedupe_positions(iter_positions(cp))
        ids: List[int] = []
        for p in positions:
            iid = instrument_id_from_position(p)
            if iid is not None:
                ids.append(iid)
        meta = client.get_instruments_metadata(ids) if ids else {}
        text, rows = summarize_portfolio(payload, meta)
        snap = {
            "ok": True,
            "text": text,
            "rows": rows,
            "headlines": portfolio_headlines(payload),
        }
        st.session_state["etoro_snap"] = snap
        return snap
    except Exception as e:
        err = {"ok": False, "err": str(e)}
        st.session_state["etoro_snap"] = err
        return err


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s or s == "—":
        return None
    s = re.sub(r"[^\d.\-+eE]", "", s.replace(",", ""))
    if not s or s in {".", "-", "+", "-.", "+."}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _pnl_class(n: Optional[float], *, prefix: str = "ta-val") -> str:
    if n is None:
        return f"{prefix}-pnl-flat"
    if n > 0:
        return f"{prefix}-pnl-up"
    if n < 0:
        return f"{prefix}-pnl-down"
    return f"{prefix}-pnl-flat"


def _side_badge_html(is_buy: Any) -> str:
    if is_buy is True:
        return (
            '<span class="ta-badge ta-badge-long" title="Long position">'
            '<span aria-hidden="true">▲</span> Long</span>'
        )
    if is_buy is False:
        return (
            '<span class="ta-badge ta-badge-short" title="Short position">'
            '<span aria-hidden="true">▼</span> Short</span>'
        )
    return '<span class="ta-badge ta-badge-unknown">?</span>'


def _render_etoro_stats_html(hl: Dict[str, Any]) -> str:
    credit = hl.get("credit")
    unreal = hl.get("unrealized_pnl")
    npos = hl.get("open_positions", "—")
    u = _safe_float(unreal)
    pnl_cls = _pnl_class(u)
    cr = html_module.escape(str(credit if credit is not None else "—"))
    if u is not None:
        pnl_display = html_module.escape(f"{u:,.4f}")
    else:
        pnl_display = html_module.escape(str(unreal if unreal is not None else "—"))
    np = html_module.escape(str(npos if npos is not None else "—"))
    return f"""
<div class="ta-etoro-stats">
  <div class="ta-etoro-stat">
    <span class="ta-etoro-stat-label">Available balance</span>
    <span class="ta-etoro-stat-value">{cr}</span>
  </div>
  <div class="ta-etoro-stat">
    <span class="ta-etoro-stat-label">Unrealized P&amp;L</span>
    <span class="ta-etoro-stat-value {pnl_cls}">{pnl_display}</span>
  </div>
  <div class="ta-etoro-stat">
    <span class="ta-etoro-stat-label">Open positions</span>
    <span class="ta-etoro-stat-value">{np}</span>
  </div>
</div>
"""


def _render_etoro_position_cards(rows: List[Dict[str, Any]], *, compact: bool) -> None:
    if not rows:
        st.markdown('<p class="ta-pos-empty">No open positions.</p>', unsafe_allow_html=True)
        return
    grid_cls = "ta-pos-grid ta-pos-grid--compact" if compact else "ta-pos-grid"
    parts: List[str] = [f'<div class="{grid_cls}">']
    card_cls = "ta-pos-card ta-pos-card--compact" if compact else "ta-pos-card"
    for r in rows:
        sym = html_module.escape(str(r.get("symbolFull") or "?"))
        name = str(r.get("instrumentDisplayName") or "").strip()
        name_h = html_module.escape(name) if name else ""
        name_block = f'<div class="ta-pos-name">{name_h}</div>' if name_h else ""
        units = html_module.escape(str(r.get("units") if r.get("units") is not None else "—"))
        op = r.get("openRate")
        op_s = html_module.escape(str(op if op is not None else "—"))
        pnl_raw = r.get("unrealizedPnL")
        pf = _safe_float(pnl_raw)
        pnl_cls = _pnl_class(pf, prefix="ta-pos")
        if pf is not None:
            if pf > 0:
                sk = '<span class="ta-pos-pnl-sticker ta-pos-pnl-sticker-up" title="Unrealized gain">●</span>'
            elif pf < 0:
                sk = '<span class="ta-pos-pnl-sticker ta-pos-pnl-sticker-down" title="Unrealized loss">●</span>'
            else:
                sk = '<span class="ta-pos-pnl-sticker ta-pos-pnl-sticker-flat" title="Flat">○</span>'
            pnl_inner = sk + html_module.escape(f" {pf:,.4f}")
        else:
            pnl_inner = html_module.escape(str(pnl_raw if pnl_raw is not None else "—"))
        badge = _side_badge_html(r.get("isBuy"))
        parts.append(f"""
<div class="{card_cls}">
  <div class="ta-pos-head">
    <div>
      <div class="ta-pos-symbol">{sym}</div>
      {name_block}
    </div>
    {badge}
  </div>
  <div class="ta-pos-meta">
    <span>Units <strong>{units}</strong></span>
    <span>Open <strong>{op_s}</strong></span>
  </div>
  <div class="ta-pos-pnl {pnl_cls}">uPnL {pnl_inner}</div>
</div>
""")
    parts.append("</div>")
    st.markdown("\n".join(parts), unsafe_allow_html=True)


def _render_etoro_portfolio_block(
    *,
    show_export: bool,
    compact_title: bool = False,
    show_section_title: bool = True,
) -> None:
    if not _etoro_env_configured():
        return

    if show_section_title:
        st.subheader("Portfolio snapshot" if compact_title else "Live portfolio (read-only)")

    c0, c1 = st.columns([4, 1])
    with c0:
        st.caption("Read-only data from your eToro API keys. This app does not send orders.")
    with c1:
        if st.button("Refresh", key=f"etoro_snap_refresh_{show_export}", use_container_width=True):
            st.session_state.pop("etoro_snap", None)
            st.rerun()

    snap = _ensure_etoro_snapshot()
    if not snap.get("ok"):
        st.warning(snap.get("err") or "Could not load eToro portfolio.")
        return

    hl = snap.get("headlines") or {}
    rows: List[Dict[str, Any]] = list(snap.get("rows") or [])
    compact_cards = not show_export

    st.markdown(
        '<div class="ta-etoro-wrap">'
        + _render_etoro_stats_html(hl)
        + "</div>",
        unsafe_allow_html=True,
    )

    exp_label = "Positions" if show_export else "Position details"
    with st.expander(exp_label, expanded=bool(show_export)):
        _render_etoro_position_cards(rows, compact=compact_cards)
        with st.expander("Table view", expanded=False):
            st.dataframe(rows, use_container_width=True, hide_index=True)
        with st.expander("Plain text summary", expanded=False):
            st.text(snap.get("text") or "")

    if show_export:
        st.divider()
        st.markdown("**Export watchlist JSON** from your open positions (for scripts or templates).")
        out_path = st.text_input(
            "Output file",
            value=str(PROJECT_ROOT / "etoro_watchlist.generated.json"),
            key="etoro_out_path",
        )
        trig_path = st.text_input(
            "Optional triggers template (JSON)",
            value="",
            key="etoro_trig_path",
            help="Copy triggers and analyst settings from this file; tickers still come from eToro.",
        )
        if st.button("Save watchlist JSON", type="primary", key="etoro_export_btn"):
            try:
                from tradingagents.integrations.etoro.clerk_bridge import (
                    fetch_clerk_watchlist_from_etoro,
                )

                tpl = Path(trig_path.strip()) if trig_path.strip() else None
                wl = fetch_clerk_watchlist_from_etoro(tpl)
                outp = Path(out_path.strip())
                outp.parent.mkdir(parents=True, exist_ok=True)
                outp.write_text(json.dumps(wl.to_json_dict(), indent=2), encoding="utf-8")
                st.success(f"Saved `{outp.resolve()}` — tickers: {', '.join(wl.tickers)}")
            except Exception as e:
                st.error(str(e))


def _render_results(final_state: Dict[str, Any], decision: Any) -> None:
    st.subheader("Final recommendation")
    st.markdown(str(decision) if decision else "_No decision._")

    tabs = st.tabs(
        ["Market", "Sentiment", "News", "Fundamentals", "Research", "Trader", "Risk / PM"]
    )
    with tabs[0]:
        st.markdown(final_state.get("market_report") or "_No report._")
    with tabs[1]:
        st.markdown(final_state.get("sentiment_report") or "_No report._")
    with tabs[2]:
        st.markdown(final_state.get("news_report") or "_No report._")
    with tabs[3]:
        st.markdown(final_state.get("fundamentals_report") or "_No report._")
    with tabs[4]:
        inv = final_state.get("investment_debate_state") or {}
        st.markdown("##### Bull\n" + (inv.get("bull_history") or "_Empty_"))
        st.markdown("##### Bear\n" + (inv.get("bear_history") or "_Empty_"))
        st.markdown("##### Research manager\n" + (inv.get("judge_decision") or "_Empty_"))
        st.markdown("##### Plan\n" + (final_state.get("investment_plan") or "_Empty_"))
    with tabs[5]:
        st.markdown(final_state.get("trader_investment_plan") or "_Empty_")
    with tabs[6]:
        r = final_state.get("risk_debate_state") or {}
        st.markdown("##### Aggressive\n" + (r.get("aggressive_history") or "_Empty_"))
        st.markdown("##### Conservative\n" + (r.get("conservative_history") or "_Empty_"))
        st.markdown("##### Neutral\n" + (r.get("neutral_history") or "_Empty_"))
        st.markdown("##### Portfolio manager\n" + (r.get("judge_decision") or "_Empty_"))
        st.markdown("##### Final decision (raw)\n" + (final_state.get("final_trade_decision") or "_Empty_"))


def _sidebar_shell() -> str:
    st.sidebar.markdown("### TradingAgents")
    st.sidebar.caption("Multi-agent research on your machine.")
    st.sidebar.divider()
    page = st.sidebar.radio(
        "Go to",
        NAV_PAGES,
        label_visibility="visible",
    )
    st.sidebar.divider()
    st.sidebar.caption("Python 3.10+ · use a venv if `pip install` is blocked (`scripts/setup-venv.sh`).")
    if not _etoro_env_configured():
        st.sidebar.caption("eToro: add `ETORO_API_KEY` + `ETORO_USER_KEY` to `.env` for the portfolio strip.")
    return page


def _page_full_analysis() -> None:
    _page_header(
        "Full analysis",
        "Run the analyst pipeline for one symbol and date. Reports are saved under your configured results directory.",
    )

    def_env_provider = os.environ.get("TRADINGAGENTS_LLM_PROVIDER", "openrouter")
    def_deep = os.environ.get("TRADINGAGENTS_DEEP_THINK_LLM", DEFAULT_CONFIG.get("deep_think_llm", ""))
    def_quick = os.environ.get("TRADINGAGENTS_QUICK_THINK_LLM", DEFAULT_CONFIG.get("quick_think_llm", ""))

    left, right = st.columns([1.1, 1], gap="large")

    with left:
        st.markdown('<p class="ta-section"><strong>Symbol and date</strong></p>', unsafe_allow_html=True)
        today = date.today().isoformat()
        ticker = st.text_input(
            "Ticker",
            value="NVDA",
            help="Include exchange suffix when needed, e.g. 7203.T, VOD.L",
        ).strip().upper()
        trade_date = st.text_input(
            "Analysis date",
            value=today,
            help="YYYY-MM-DD. Cannot be in the future.",
        )

        st.markdown('<p class="ta-section"><strong>Analysts</strong></p>', unsafe_allow_html=True)
        ac1, ac2 = st.columns(2)
        for i, k in enumerate(ANALYST_ORDER):
            target = ac1 if i < 2 else ac2
            with target:
                st.checkbox(ANALYST_LABELS[k], value=True, key=f"cb_{k}")

        st.markdown('<p class="ta-section"><strong>Models and data</strong></p>', unsafe_allow_html=True)
        provider = st.selectbox(
            "LLM provider",
            options=PROVIDERS,
            index=PROVIDERS.index(def_env_provider) if def_env_provider in PROVIDERS else 0,
        )
        backend_url = st.text_input(
            "API base URL (optional)",
            value=os.environ.get("TRADINGAGENTS_LLM_BACKEND_URL", ""),
            help="Leave blank for the provider default.",
        )
        deep_model = st.text_input("Deep / slow model", value=str(def_deep or "openai/gpt-4o"))
        quick_model = st.text_input("Quick model", value=str(def_quick or "openai/gpt-4o-mini"))
        output_language = st.text_input("Output language", value="English")
        news_vendor = st.selectbox("News data source", ["yfinance", "alpha_vantage"], index=0)

        with st.expander("Advanced graph options", expanded=False):
            max_debate = st.slider("Research debate rounds", 1, 3, int(DEFAULT_CONFIG.get("max_debate_rounds", 1)))
            max_risk = st.slider("Risk debate rounds", 1, 3, int(DEFAULT_CONFIG.get("max_risk_discuss_rounds", 1)))
            checkpoint = st.checkbox("Checkpoint resume (SQLite)", value=False)

        st.markdown('<p class="ta-section"><strong>Corporate hierarchy (OpenRouter)</strong></p>', unsafe_allow_html=True)
        st.caption(
            "Default: per-agent OpenRouter models from `DEFAULT_CORPORATE_AGENT_ROUTING`. "
            "Requires `OPENROUTER_API_KEY`. Turn off to use the legacy single-provider pair above."
        )
        corporate_hierarchy = st.checkbox(
            "Enable corporate hierarchy (per-agent OpenRouter)",
            value=bool(DEFAULT_CONFIG.get("corporate_hierarchy_enabled", True)),
            key="cb_corporate_hierarchy",
        )
        corporate_openrouter_base_url = st.text_input(
            "OpenRouter base URL (optional)",
            value="",
            help="Leave blank for https://openrouter.ai/api/v1",
            key="txt_corporate_or_url",
        )
        llm_fallback_openrouter_model = st.text_input(
            "Rate-limit fallback model (OpenRouter slug)",
            value=str(DEFAULT_CONFIG.get("llm_fallback_openrouter_model") or "openai/gpt-4o-mini"),
            key="txt_or_fallback_model",
        )
        agent_llm_routing_json = st.text_area(
            "Optional `agent_llm_routing` JSON (partial overrides per logical agent)",
            value="",
            height=120,
            placeholder='{"news_analyst": {"model": "google/gemini-2.5-flash"}}',
            key="ta_agent_llm_routing_json",
        )

    with right:
        st.markdown('<p class="ta-section"><strong>Run</strong></p>', unsafe_allow_html=True)
        if news_vendor == "alpha_vantage" and not (os.environ.get("ALPHA_VANTAGE_API_KEY") or "").strip():
            st.warning("Set `ALPHA_VANTAGE_API_KEY` in `.env` for Alpha Vantage news.")

        run = st.button("Run full analysis", type="primary", use_container_width=True, key="btn_run_analysis")
        st.caption("Large models and many analysts can take several minutes.")

    if run:
        side: Dict[str, Any] = {
            "provider": provider,
            "backend_url": backend_url,
            "deep_model": deep_model,
            "quick_model": quick_model,
            "output_language": output_language,
            "max_debate": max_debate,
            "max_risk": max_risk,
            "checkpoint": checkpoint,
            "news_vendor": news_vendor,
            "corporate_hierarchy": corporate_hierarchy,
            "corporate_openrouter_base_url": corporate_openrouter_base_url,
            "llm_fallback_openrouter_model": llm_fallback_openrouter_model,
            "agent_llm_routing_json": agent_llm_routing_json,
        }
        for k in ANALYST_ORDER:
            side[f"analyst_{k}"] = st.session_state.get(f"cb_{k}", True)

        try:
            datetime.strptime(trade_date, "%Y-%m-%d")
        except ValueError:
            st.error("Use a valid date: YYYY-MM-DD.")
            return
        if datetime.strptime(trade_date, "%Y-%m-%d").date() > date.today():
            st.error("Analysis date cannot be in the future.")
            return

        selected = _selected_analysts(side)
        if not selected:
            st.error("Select at least one analyst.")
            return

        cfg = _build_config(side)
        progress = st.empty()
        status = st.status("Running agents…", expanded=True)

        def on_progress(merged: Dict[str, Any], _delta: Dict[str, Any]) -> None:
            parts = []
            for key, label in [
                ("market_report", "Market"),
                ("sentiment_report", "Sentiment"),
                ("news_report", "News"),
                ("fundamentals_report", "Fundamentals"),
                ("investment_plan", "Research"),
                ("trader_investment_plan", "Trader"),
                ("final_trade_decision", "Done"),
            ]:
                if merged.get(key):
                    parts.append(label)
            progress.markdown("**Progress:** " + (" → ".join(parts) if parts else "Starting…"))

        cfg["progress_callback"] = on_progress

        run_ok = False
        final_state: Dict[str, Any] = {}
        decision: Any = None
        with status:
            try:
                graph = TradingAgentsGraph(
                    selected_analysts=selected,
                    debug=False,
                    config=cfg,
                )
                final_state, decision = graph.propagate(ticker, trade_date)
                run_ok = True
            except Exception as e:
                st.error(f"Run failed: {e}")
            finally:
                cfg.pop("progress_callback", None)

        if run_ok:
            status.update(label="Complete", state="complete", expanded=False)
            progress.empty()
            st.session_state[_SS_ANALYSIS] = (final_state, decision)
            st.success("Finished. Reports are on disk in your results folder.")
        else:
            st.session_state.pop(_SS_ANALYSIS, None)

    if _SS_ANALYSIS in st.session_state:
        st.divider()
        st.subheader("Results")
        fs, dec = st.session_state[_SS_ANALYSIS]
        _render_results(fs, dec)


def _page_portfolio_advisor() -> None:
    _page_header(
        "Portfolio advisor",
        "Autonomous advisor: first-run schedule, weekly light checks, optional replans, and due deep runs.",
    )
    if not _etoro_env_configured():
        st.warning("Set ETORO_API_KEY and ETORO_USER_KEY in `.env` to use portfolio advisor automation.")
        return

    st.caption(
        "Advisory only. No orders are placed. Notifications use the same webhook / SMTP "
        "analysis channels configured in `.env`."
    )

    cfg = DEFAULT_CONFIG.copy()
    weekday = int(cfg.get("portfolio_advisor_weekly_weekday", 5))
    st.markdown(
        f"**Configured weekly day:** `{weekday}` (0=Mon … 6=Sun) · "
        f"**run-due cap per invocation:** `{int(cfg.get('portfolio_advisor_run_due_max', 2))}`"
    )

    c0, c1, c2, c3 = st.columns(4)
    force_init = c0.checkbox("Force init reset", value=False, key="pa_force_init")
    force_weekly = c1.checkbox("Force weekly now", value=False, key="pa_force_weekly")
    force_replan = c2.checkbox("Force replan now", value=False, key="pa_force_replan")
    _ = c3.checkbox("Show status after actions", value=True, key="pa_show_status")

    b0, b1, b2, b3, b4 = st.columns(5)
    init_run = b0.button("Init", type="primary", use_container_width=True, key="pa_btn_init")
    weekly_run = b1.button("Weekly check", use_container_width=True, key="pa_btn_weekly")
    replan_run = b2.button("Replan", use_container_width=True, key="pa_btn_replan")
    due_run = b3.button("Run due jobs", use_container_width=True, key="pa_btn_due")
    status_refresh = b4.button("Refresh status", use_container_width=True, key="pa_btn_status")

    try:
        from tradingagents.portfolio_advisor import messaging as pa_messaging
        from tradingagents.portfolio_advisor import service as pa_service
    except Exception as e:
        st.error(f"Could not load portfolio advisor modules: {e}")
        return

    if init_run:
        try:
            pa_service.run_init(cfg, force=force_init)
            st.session_state[_SS_PORT_NOTE] = "Init complete: full portfolio scan and schedule created."
        except Exception as e:
            st.session_state[_SS_PORT_NOTE] = f"Init failed: {e}"
    if weekly_run:
        try:
            outcome = pa_service.run_weekly(cfg, ignore_weekday=force_weekly)
            st.session_state[_SS_PORT_NOTE] = f"Weekly check outcome: {outcome}"
        except Exception as e:
            st.session_state[_SS_PORT_NOTE] = f"Weekly check failed: {e}"
    if replan_run:
        try:
            outcome = pa_service.run_replan(cfg, ignore_weekday=force_replan)
            st.session_state[_SS_PORT_NOTE] = f"Replan outcome: {outcome}"
        except Exception as e:
            st.session_state[_SS_PORT_NOTE] = f"Replan failed: {e}"
    if due_run:
        try:
            n = pa_service.run_due_jobs(cfg)
            st.session_state[_SS_PORT_NOTE] = f"Run-due processed {n} job(s)."
        except Exception as e:
            st.session_state[_SS_PORT_NOTE] = f"Run-due failed: {e}"

    if status_refresh or any([init_run, weekly_run, replan_run, due_run]) or _SS_PORT_STATUS not in st.session_state:
        try:
            st.session_state[_SS_PORT_STATUS] = pa_service.status_text(cfg)
        except Exception as e:
            st.session_state[_SS_PORT_STATUS] = f"Status unavailable: {e}"

    if _SS_PORT_NOTE in st.session_state:
        note = str(st.session_state[_SS_PORT_NOTE])
        if "failed" in note.lower():
            st.error(note)
        elif "skipped" in note.lower():
            st.warning(note)
        else:
            st.success(note)

    st.divider()
    st.subheader("State and queue")
    st.text_area(
        "Portfolio advisor state",
        value=str(st.session_state.get(_SS_PORT_STATUS, "(not loaded)")),
        height=260,
        key="pa_status_area",
        label_visibility="collapsed",
        disabled=True,
    )

    st.divider()
    st.subheader("Send ad-hoc advisor message")
    msg_subj = st.text_input(
        "Subject",
        value="[TradingAgents] Portfolio advisor notice",
        key="pa_alert_subject",
    )
    msg_body = st.text_area(
        "Message body",
        value="",
        height=130,
        key="pa_alert_body",
        help="Sends through configured analysis webhook/SMTP channels.",
    )
    if st.button("Send message", use_container_width=True, key="pa_alert_send"):
        try:
            ok = pa_messaging.send_advisor_message(cfg, msg_subj.strip(), msg_body.strip())
            if ok:
                st.success("Message sent (at least one channel accepted it).")
            else:
                st.warning("No channel accepted the message. Check webhook/SMTP env vars.")
        except Exception as e:
            st.error(f"Message send failed: {e}")


def _page_etoro() -> None:
    _page_header(
        "eToro",
        "Read-only portfolio. This app does not place trades.",
    )
    if not _etoro_env_configured():
        st.info(
            "Add **ETORO_API_KEY** and **ETORO_USER_KEY** to `.env` "
            "(eToro → Settings → Trading → API Key Management), then click Refresh."
        )
    _render_etoro_portfolio_block(show_export=True, show_section_title=False)


def main() -> None:
    st.set_page_config(
        page_title="TradingAgents",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _inject_app_styles()

    page = _sidebar_shell()

    if _etoro_env_configured() and page != "eToro":
        _render_etoro_portfolio_block(show_export=False, compact_title=True, show_section_title=True)
    elif not _etoro_env_configured() and page != "eToro":
        st.caption(
            "eToro: set **ETORO_API_KEY** and **ETORO_USER_KEY** in `.env` to show a portfolio summary above."
        )

    if page == "Full analysis":
        _page_full_analysis()
    elif page == "Portfolio advisor":
        _page_portfolio_advisor()
    else:
        _page_etoro()


if __name__ == "__main__":
    main()
