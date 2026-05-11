# Local web UI for TradingAgents.
#
# Run (pick one):
#   cd …/TradingAgents-main && python3 -m streamlit run ui/streamlit_app.py
#   cd …/TradingAgents-main && sh scripts/run-ui.sh
#   cd …/TradingAgents-main && python3 -m pip install -e . && python3 -m cli.main ui
#
# If `pip` is missing, use:  python3 -m pip install -e .

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

import tradingagents  # noqa: F401 — loads .env

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CLERK_WATCHLIST = PROJECT_ROOT / "cli" / "static" / "clerk_watchlist.example.json"

ANALYST_ORDER: List[str] = ["market", "social", "news", "fundamentals"]
ANALYST_LABELS = {
    "market": "Market (technicals)",
    "social": "Sentiment",
    "news": "News",
    "fundamentals": "Fundamentals",
}
PROVIDERS = ["openrouter", "openai", "google", "anthropic", "ollama", "deepseek", "xai"]


def _default_openrouter_url() -> str:
    return "https://openrouter.ai/api/v1"


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

    dv = dict(cfg.get("data_vendors") or {})
    dv["news_data"] = side["news_vendor"]
    cfg["data_vendors"] = dv

    cfg.pop("progress_callback", None)
    return cfg


def _selected_analysts(side: Dict[str, Any]) -> List[str]:
    return [k for k in ANALYST_ORDER if side.get(f"analyst_{k}", True)]


def _render_results(final_state: Dict[str, Any], decision: Any) -> None:
    st.subheader("Final signal (processed)")
    st.code(str(decision), language="text")

    tabs = st.tabs(
        ["Market", "Sentiment", "News", "Fundamentals", "Research", "Trader", "Risk / PM"]
    )
    with tabs[0]:
        st.markdown(final_state.get("market_report") or "_Empty_")
    with tabs[1]:
        st.markdown(final_state.get("sentiment_report") or "_Empty_")
    with tabs[2]:
        st.markdown(final_state.get("news_report") or "_Empty_")
    with tabs[3]:
        st.markdown(final_state.get("fundamentals_report") or "_Empty_")
    with tabs[4]:
        inv = final_state.get("investment_debate_state") or {}
        st.markdown("### Bull\n" + (inv.get("bull_history") or "_Empty_"))
        st.markdown("### Bear\n" + (inv.get("bear_history") or "_Empty_"))
        st.markdown("### Research manager\n" + (inv.get("judge_decision") or "_Empty_"))
        st.markdown("### Plan\n" + (final_state.get("investment_plan") or "_Empty_"))
    with tabs[5]:
        st.markdown(final_state.get("trader_investment_plan") or "_Empty_")
    with tabs[6]:
        r = final_state.get("risk_debate_state") or {}
        st.markdown("### Aggressive\n" + (r.get("aggressive_history") or "_Empty_"))
        st.markdown("### Conservative\n" + (r.get("conservative_history") or "_Empty_"))
        st.markdown("### Neutral\n" + (r.get("neutral_history") or "_Empty_"))
        st.markdown("### Portfolio manager\n" + (r.get("judge_decision") or "_Empty_"))
        st.markdown("### Final decision (raw)\n" + (final_state.get("final_trade_decision") or "_Empty_"))


def _page_full_analysis() -> None:
    def_env_provider = os.environ.get("TRADINGAGENTS_LLM_PROVIDER", "openrouter")
    def_deep = os.environ.get("TRADINGAGENTS_DEEP_THINK_LLM", DEFAULT_CONFIG.get("deep_think_llm", ""))
    def_quick = os.environ.get("TRADINGAGENTS_QUICK_THINK_LLM", DEFAULT_CONFIG.get("quick_think_llm", ""))

    with st.sidebar:
        st.header("Model settings")
        provider = st.selectbox(
            "LLM provider",
            options=PROVIDERS,
            index=PROVIDERS.index(def_env_provider) if def_env_provider in PROVIDERS else 0,
        )
        backend_url = st.text_input(
            "API base URL (optional)",
            value=os.environ.get("TRADINGAGENTS_LLM_BACKEND_URL", ""),
            help="Leave blank for provider default. For OpenRouter, https://openrouter.ai/api/v1 is used if empty.",
        )
        deep_model = st.text_input("Deep / slow model", value=str(def_deep or "openai/gpt-4o"))
        quick_model = st.text_input("Quick model", value=str(def_quick or "openai/gpt-4o-mini"))
        output_language = st.text_input("Report language", value="English")
        max_debate = st.slider("Research debate rounds", 1, 3, int(DEFAULT_CONFIG.get("max_debate_rounds", 1)))
        max_risk = st.slider("Risk debate rounds", 1, 3, int(DEFAULT_CONFIG.get("max_risk_discuss_rounds", 1)))
        checkpoint = st.checkbox("Checkpoint resume (SQLite)", value=False)
        news_vendor = st.selectbox("News data source", ["yfinance", "alpha_vantage"], index=0)
        st.divider()
        st.header("Analysts")
        for k in ANALYST_ORDER:
            st.checkbox(ANALYST_LABELS[k], value=True, key=f"cb_{k}")

    today = date.today().isoformat()
    col1, col2 = st.columns(2)
    with col1:
        _t = st.text_input(
            "Ticker",
            value="NVDA",
            help="Include exchange suffix if needed, e.g. 7203.T",
        )
        ticker = _t.strip().upper()
    with col2:
        trade_date = st.text_input("Analysis date (YYYY-MM-DD)", value=today)

    if news_vendor == "alpha_vantage" and not (os.environ.get("ALPHA_VANTAGE_API_KEY") or "").strip():
        st.warning("News is set to Alpha Vantage but `ALPHA_VANTAGE_API_KEY` is missing from `.env`.")

    run = st.button("Run analysis", type="primary", use_container_width=True, key="btn_run_analysis")

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
        }
        for k in ANALYST_ORDER:
            side[f"analyst_{k}"] = st.session_state.get(f"cb_{k}", True)

        try:
            datetime.strptime(trade_date, "%Y-%m-%d")
        except ValueError:
            st.error("Date must be YYYY-MM-DD.")
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
                ("market_report", "market"),
                ("sentiment_report", "sentiment"),
                ("news_report", "news"),
                ("fundamentals_report", "fundamentals"),
                ("investment_plan", "research"),
                ("trader_investment_plan", "trader"),
                ("final_trade_decision", "done"),
            ]:
                if merged.get(key):
                    parts.append(label)
            progress.markdown("**Progress:** " + (" → ".join(parts) if parts else "starting…"))

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
            st.success(
                "Analysis finished. Reports are also saved under your configured results directory."
            )
            _render_results(final_state, decision)


def _page_clerk() -> None:
    st.subheader("Clerk — daily scan & weekly roll-up")
    st.markdown(
        "Uses headline diffs (and optional deep research when triggers hit). "
        "Webhook: set `TRADINGAGENTS_CLERK_WEBHOOK_URL` in `.env`."
    )

    use_etoro = st.checkbox("Use live eToro open positions as tickers", value=False)
    watch_path = st.text_input(
        "Watchlist JSON path",
        value=str(DEFAULT_CLERK_WATCHLIST),
        help="Ignored when ‘Use eToro’ is checked (unless you set triggers-only path below).",
    )
    etoro_triggers = st.text_input(
        "Optional: triggers JSON path (copy triggers/analysts; tickers from eToro)",
        value="",
        help="Leave empty for defaults. Used with eToro mode.",
    )
    trade_date = st.text_input("As-of date for deep research (YYYY-MM-DD)", value=date.today().isoformat())
    deep_research = st.checkbox("Run full agent graph when triggers fire (costs API calls)", value=False)
    webhook = st.text_input("Webhook URL (optional, overrides env for this run)", value="")

    st.divider()
    st.markdown("### Weekly roll-up")
    w_days = st.number_input("Days of morning logs to include", min_value=1, max_value=30, value=7)
    w_no_llm = st.checkbox("Skip weekly LLM summary", value=False)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Run morning clerk", use_container_width=True):
            from tradingagents.clerk.morning import run_morning_clerk
            from tradingagents.integrations.etoro.clerk_bridge import fetch_clerk_watchlist_from_etoro

            cfg = DEFAULT_CONFIG.copy()
            digest: Optional[str] = None
            ran: List[str] = []
            try:
                if use_etoro:
                    tpl = Path(etoro_triggers.strip()) if etoro_triggers.strip() else None
                    wl = fetch_clerk_watchlist_from_etoro(tpl)
                    digest, ran = run_morning_clerk(
                        wl,
                        trade_date=trade_date.strip() or None,
                        webhook_url=webhook.strip() or None,
                        deep_research=deep_research,
                        config=cfg,
                    )
                else:
                    p = Path(watch_path.strip())
                    if not p.is_file():
                        st.error(f"Watchlist file not found: {p}")
                    else:
                        digest, ran = run_morning_clerk(
                            p,
                            trade_date=trade_date.strip() or None,
                            webhook_url=webhook.strip() or None,
                            deep_research=deep_research,
                            config=cfg,
                        )
                if digest is not None:
                    st.text_area("Morning digest", value=digest, height=400)
                    if ran:
                        st.success("Deep research ran for: " + ", ".join(ran))
            except Exception as e:
                st.error(str(e))

    with c2:
        if st.button("Run weekly clerk", use_container_width=True):
            from tradingagents.clerk.weekly import run_weekly_clerk

            cfg = DEFAULT_CONFIG.copy()
            try:
                digest = run_weekly_clerk(
                    days=int(w_days),
                    webhook_url=webhook.strip() or None,
                    with_llm=not w_no_llm,
                    config=cfg,
                )
                st.text_area("Weekly digest", value=digest, height=400)
            except Exception as e:
                st.error(str(e))


def _page_etoro() -> None:
    st.subheader("eToro (read-only)")
    st.markdown("Needs `ETORO_API_KEY` and `ETORO_USER_KEY` in `.env`. Does not place trades.")

    if st.button("Fetch portfolio snapshot", use_container_width=True):
        try:
            from tradingagents.integrations.etoro.client import EtoroClient
            from tradingagents.integrations.etoro.portfolio import (
                dedupe_positions,
                instrument_id_from_position,
                iter_positions,
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
            st.text(text)
            st.dataframe(rows, use_container_width=True)
        except Exception as e:
            st.error(str(e))

    st.divider()
    st.markdown("### Export clerk watchlist JSON from open positions")
    out_path = st.text_input(
        "Output file path",
        value=str(PROJECT_ROOT / "etoro_watchlist.generated.json"),
    )
    trig_path = st.text_input("Optional triggers template JSON path", value="")
    if st.button("Export watchlist", use_container_width=True):
        try:
            from tradingagents.integrations.etoro.clerk_bridge import fetch_clerk_watchlist_from_etoro

            tpl = Path(trig_path.strip()) if trig_path.strip() else None
            wl = fetch_clerk_watchlist_from_etoro(tpl)
            outp = Path(out_path.strip())
            outp.parent.mkdir(parents=True, exist_ok=True)
            outp.write_text(json.dumps(wl.to_json_dict(), indent=2), encoding="utf-8")
            st.success(f"Wrote {outp.resolve()}\nTickers: {', '.join(wl.tickers)}")
        except Exception as e:
            st.error(str(e))


def main() -> None:
    st.set_page_config(page_title="TradingAgents", layout="wide", initial_sidebar_state="expanded")
    st.title("TradingAgents")
    st.caption(
        "Runs locally. Needs **Python 3.10+** (not Apple’s 3.9). Install: "
        "`python3 -m pip install --upgrade pip` then `python3 -m pip install -e .`  ·  "
        "Open UI: `python3 -m streamlit run ui/streamlit_app.py` or `python3 -m cli.main ui` or `sh scripts/run-ui.sh`"
    )

    page = st.radio(
        "Section",
        ["Full analysis", "Clerk", "eToro"],
        horizontal=True,
        label_visibility="collapsed",
    )
    st.divider()

    if page == "Full analysis":
        _page_full_analysis()
    elif page == "Clerk":
        _page_clerk()
    else:
        _page_etoro()


if __name__ == "__main__":
    main()
