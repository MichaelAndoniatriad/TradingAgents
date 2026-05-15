# TradingAgents Improvement Plan

Generated from a 4-angle audit (token efficiency, code quality, architecture, data pipeline).
Work through phases in order — each phase unblocks the next.

---

## Phase 1: Reliability — Stop the Bleeding

These are production risks that can cause silent data loss, duplicate job execution, or corrupted state. Do these before anything else.

### 1.1 Fix the job claiming race condition
- **File:** `tradingagents/portfolio_advisor/service.py:383–412`
- **Problem:** `run_due_jobs()` selects jobs and claims them in two separate lock windows. Two concurrent workers can pick the same job.
- **Fix:** Hold `_state_lock` for the entire select + claim block (move the lock acquisition before `state.load_state()`).
- **Test:** Add a test that simulates two concurrent calls to `run_due_jobs()` and asserts each job is claimed exactly once.

### 1.2 Stop swallowing exceptions silently
- **Files:**
  - `service.py:332–333` — `ingest_from_analysis` failure lost silently
  - `outcome_sync.py:193–197` — unit sync failure logged only at debug
  - `advisor_pm.py:653–674` — subprocess launch failure logged at debug
- **Fix:** Change bare `except Exception: pass` and debug-level catches to `logger.warning(...)` with the ticker and exception text. Silent failures are invisible in production.

### 1.3 Make PM memory writes atomic
- **File:** `tradingagents/portfolio_advisor/advisor_pm.py:307–347`
- **Problem:** `_append_pm_memory_md` does `open(path, "a")` with no lock. Two concurrent PM cycles interleave writes and corrupt the markdown file.
- **Fix:** Add a module-level `_pm_memory_lock = threading.Lock()` and acquire it around the mkdir + write sequence.

### 1.4 Validate eToro row schema at ingest
- **File:** `tradingagents/portfolio_advisor/plan_validation.py:38–45, 79–93`
- **Problem:** `float(row.get("openRate"))` with no field existence check. A schema change returns silent 0.0.
- **Fix:** Add a `_validate_etoro_row(row)` function that checks all required fields exist and logs a warning with the raw row on mismatch.

### 1.5 Fix state double-write in outcome_sync
- **File:** `tradingagents/portfolio_advisor/outcome_sync.py:112–178`
- **Problem:** `_sync_partial_unit_changes` loads and saves state independently, overwriting concurrent mutations.
- **Fix:** Return the mutated state to the caller instead of saving internally: `def _sync_partial_unit_changes(...) -> dict`.

---

## Phase 2: Data Pipeline — Fix What Goes Into the LLM

These fixes prevent bad data from reaching the models and eliminate the most egregious prompt bloat from raw data.

### 2.1 Never return error strings as data values
- **File:** `tradingagents/dataflows/alpha_vantage_indicator.py:160–181`
- **Problem:** If the API returns malformed CSV, the function returns the string `"Error: 'time' column not found"` as the indicator value. The LLM receives this and treats it as data.
- **Fix:** Raise an exception instead. Callers should catch and handle, not receive error prose.

### 2.2 Fix silent CSV filter failure
- **File:** `tradingagents/dataflows/alpha_vantage_common.py:119–122`
- **Problem:** If date parsing fails, analysts receive 10 years of unfiltered data instead of the requested 30-day slice. Failure is printed, not raised.
- **Fix:** Raise on filter failure. Never return unfiltered data when a filter was requested.

### 2.3 Log API vendor fallback
- **File:** `tradingagents/dataflows/interface.py:159`
- **Problem:** When Alpha Vantage rate-limits and falls back to yfinance, it happens silently at debug level. No visibility into which vendor served which request.
- **Fix:** Log a `logger.warning("Alpha Vantage rate-limited for %s, falling back to yfinance", symbol)` so you can see this in production and tune your vendor config.

### 2.4 Add OHLCV cache TTL (intraday staleness)
- **File:** `tradingagents/dataflows/stockstats_utils.py:64–91`
- **Problem:** Cache key is a 5-year date window. Monday morning data is served to Wednesday afternoon runs with no freshness check.
- **Fix:** Include the trade date in the cache filename key. Invalidate if the file is older than N hours (configurable, default 6h for intraday use).

### 2.5 Summarize OHLCV before injecting into prompts
- **Files:** `tradingagents/dataflows/y_finance.py:40–48`, `tradingagents/agents/analysts/market_analyst.py:48`
- **Problem:** `get_stock_data` returns a raw CSV of 1,260+ rows (5 years of daily OHLCV) and it goes directly into the analyst prompt. This is by far the largest single data block hitting the LLM.
- **Fix:** Add a `get_stock_summary(symbol, days=60)` tool that returns: last N days of OHLCV, 52-week high/low, trend direction, average volume. Raw CSV access stays available as an opt-in tool, not the default.

### 2.6 Summarize fundamentals before injection
- **Files:** `tradingagents/dataflows/y_finance.py:325, 389`
- **Problem:** Balance sheet and income statement are converted to full multi-column CSVs and passed to the LLM.
- **Fix:** Extract 8–10 key ratios (revenue growth, gross margin, FCF, debt/equity, EPS trend) and pass those instead of raw statements. Raw data available as opt-in tool.

### 2.7 Standardize dates and prices across sources
- **Problem:** Alpha Vantage uses `YYYYMMDDTHHMM`, yfinance uses ISO 8601. Prices are rounded to 2 decimal places in yfinance but 8+ in Alpha Vantage. No currency field on fundamentals.
- **Fix:** Add a normalization layer in `interface.py` that enforces ISO 8601 dates, 2-decimal prices, and a `currency` field on all fundamental outputs before they leave the dataflows layer.

---

## Phase 3: Token Efficiency — Cut the Cost

The system wastes 40–65% of tokens on repeat context, redundant prompts, and uncompressed memory. These changes pay for themselves within days.

### 3.1 Wire Anthropic prompt caching (highest ROI, lowest effort)
- **File:** `tradingagents/llm_clients/anthropic_client.py`
- **Problem:** Zero usage of `cache_control`. Every run re-tokenizes and re-bills the static investor policy (~6,000 chars), system prompts, and analyst instructions — even when analyzing the same ticker back-to-back.
- **Fix:** Add `cache_control: {"type": "ephemeral"}` on the static investor policy block and analyst system prompts. This is a 2–3 line change per call site. **Expected savings: 50–70% on repeated ticker runs.**
- **Reference:** [Anthropic prompt caching docs](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching)

### 3.2 Replace debate message history with rolling summary
- **File:** `tradingagents/graph/trading_graph.py:454–485`
- **Problem:** The bull/bear debate accumulates full message history in state. Round N re-sends rounds 1 through N-1 verbatim. At 5 rounds this is ~37,500 tokens just for debate history.
- **Fix:** After each round, compress the prior round into a 1–2 sentence position summary stored in a separate state field (`bull_position`, `bear_position`). Pass only the current-round message + summarized positions to subsequent rounds.

### 3.3 Inject investor policy once, not per-analyst
- **Files:** `tradingagents/agents/analysts/fundamentals_analyst.py:27–32`, `market_analyst.py:23–52`, `news_analyst.py:22–26`, `sentiment_analyst.py:100–164`
- **Problem:** `get_investor_policy_full_instruction()` (~6,000 chars) is independently called and injected into each analyst's system prompt. 4 analysts × ~1,500 tokens = ~6,000 tokens of duplicate context per run.
- **Fix:** Inject the investor policy once at the graph level (stored as a shared state field). Analyst system prompts reference only their role-specific instructions.

### 3.4 Compress PM prompt context blocks
- **File:** `tradingagents/portfolio_advisor/advisor_pm.py:700–789`
- **Problem:** The PM prompt stacks 7 context blocks totaling ~27,800 chars (~7,000 tokens). Portfolio text alone is 7,000 chars as raw text.
- **Fix:**
  - **Portfolio snapshot:** Convert to structured JSON `{ticker, pct, px_chg_pct, thesis_status, days_held}` — reduces from 7,000 chars to ~800 chars.
  - **Trading memory tail:** Replace the 6,000-char raw tail with a pre-computed 3-line activity digest.
  - **Prior PM cycles:** Deduplicate — only inject if the prior summary differs from the current state (hash check).

### 3.5 Summarize memory context to 1-liners
- **Files:** `tradingagents/agents/utils/memory.py:72–155`, `tradingagents/portfolio_advisor/single_model_analysis.py:200–213`
- **Problem:** `get_past_context()` injects 5 full prior decisions (~2,000 chars each) verbatim. Event log injects 20–25 raw JSON rows.
- **Fix:**
  - Compress each prior decision to: `[2025-05-10] Buy thesis: chip shortage premium → outcome: -8.2% (broken 2025-05-15)`
  - Filter event log to only: `full_graph_decision`, `single_model_analysis`, `outcome_recorded` event types, and only extract `{ticker, verdict, date, outcome}` per row.

### 3.6 Cache single_model_analysis by (ticker, job_type, date)
- **File:** `tradingagents/portfolio_advisor/single_model_analysis.py`
- **Problem:** If a weekly_summary runs Monday and a thesis_check triggers Tuesday for the same ticker, all memory + events are re-injected and re-billed even though nothing changed.
- **Fix:** Add a simple file-based cache keyed by `(ticker, job_type, trade_date)`. Return cached result if exists and is less than N hours old.

---

## Phase 4: Architecture — Simplify the Graph

These changes reduce the structural complexity of the agent pipeline. They require more thought but have the highest long-term impact.

### 4.1 Collapse bull/bear debate into a single synthetic-argument call
- **Files:** `tradingagents/agents/researchers/bull_researcher.py`, `bear_researcher.py`, `tradingagents/agents/managers/research_manager.py`
- **Problem:** Bull and Bear researchers receive identical analyst reports and are prompted to argue opposite sides. The Research Manager immediately re-synthesizes both. This is 3 LLM calls to produce what 1 call with structured internal reasoning would produce. Token cost: ~6,000–8,000 per deep run. Signal gain: marginal.
- **Fix:** Replace the 3-node debate with a single `SynthesizerAgent` that receives all 4 analyst reports and outputs a structured `{rating, bull_case, bear_case, synthesis, confidence}`. Keep the debate path as an optional `"deep"` mode toggled by config.

### 4.2 Remove the Neutral risk debator
- **File:** `tradingagents/agents/risk_mgmt/neutral_debator.py`
- **Problem:** The Neutral analyst mediates between Aggressive and Conservative but introduces no new data or perspective — it always lands in the middle. It's the most expensive line in the risk debate with the least marginal value.
- **Fix:** Remove it. Let the Portfolio Manager arbitrate between Aggressive and Conservative directly.

### 4.3 Merge Research Manager + Trader into one agent
- **Files:** `tradingagents/agents/managers/research_manager.py`, `tradingagents/agents/trader/trader.py`
- **Problem:** The Research Manager produces an investment plan. The Trader re-reads it and converts it to a structured proposal. The Portfolio Manager then re-reads both. Research Manager and Trader are semantically redundant.
- **Fix:** Merge into a single `ResearchAndExecutionAgent` that outputs `{rating, sizing, entry_thesis, thesis_break_metrics, trade_proposal}` directly. Saves 1 LLM call per run.

### 4.4 Add quality gates to debate termination
- **File:** `tradingagents/graph/conditional_logic.py:46–67`
- **Problem:** Debate stops on a hard round counter. No intelligence about whether consensus was reached or arguments are converging.
- **Fix:** Add a convergence check before each round: if all active debaters share the same rating, stop early. If the last response is semantically similar to 2 turns ago (cosine similarity > 0.9 on embedding), stop early. Hard counter stays as the fallback.

### 4.5 Unify the two Portfolio Manager concepts
- **Files:** `tradingagents/agents/managers/portfolio_manager.py` (graph-level), `tradingagents/portfolio_advisor/advisor_pm.py` (portfolio-level)
- **Problem:** Two layers with similar names and overlapping responsibilities. Graph PM rates a single name. Advisor PM manages the portfolio. No clean handoff; decisions can conflict.
- **Fix:** Extend the graph PM's structured output to include portfolio-scope fields: `{rating, confidence, sizing, thesis, thesis_break_metrics, schedule_next_review}`. Advisor PM reads this output and acts on it rather than re-reasoning from scratch.

### 4.6 Enforce structured outputs on analyst nodes
- **Files:** All `tradingagents/agents/analysts/*.py`
- **Problem:** If an analyst LLM returns prose instead of calling tools, an empty report silently propagates through all downstream stages. No validation that the report contains expected data.
- **Fix:** Each analyst should return a structured output `{tools_called: [list], analysis: str, data_available: bool}`. Gate downstream nodes on `data_available`. If `tools_called` is empty, escalate loudly instead of proceeding with an empty report.

---

## Phase 5: Signal Quality — Make the Data Better

These are improvements to the quality of information reaching the models. Do after Phase 2 is complete.

### 5.1 Filter Reddit by engagement threshold
- **File:** `tradingagents/dataflows/reddit.py:28–54`, `tradingagents/agents/analysts/sentiment_analyst.py:128–142`
- **Fix:** Enforce a minimum upvote threshold (e.g., 20 upvotes) before including Reddit posts. Weight posts by subreddit tier (r/investing > r/stocks > r/wallstreetbets). Remove the shift of filtering responsibility to the LLM.

### 5.2 Add automated cross-source divergence detection
- **File:** `tradingagents/agents/analysts/sentiment_analyst.py:136–139`
- **Problem:** The sentiment analyst is instructed to "look for cross-source divergences" but this is manual LLM reasoning. No automated signal.
- **Fix:** Add a pre-LLM divergence check: if retail sentiment score > 80% bullish AND news sentiment < 30% bullish, inject a `[DIVERGENCE ALERT]` flag into the prompt with the exact values. Quantified divergence is more useful to the model than an instruction to look for it.

### 5.3 Remove VWMA from available tools
- **File:** `tradingagents/dataflows/alpha_vantage_indicator.py:145–149`
- **Problem:** VWMA is listed as an available tool in `market_analyst.py:46` but returns a hardcoded "not available" message. The LLM requests it and receives an apology.
- **Fix:** Remove VWMA from the tools list until it's implemented, or implement it from OHLCV data in `stockstats_utils.py`.

### 5.4 Detect and handle trading halts/gaps in price series
- **File:** `tradingagents/dataflows/stockstats_utils.py:43`
- **Problem:** `ffill().bfill()` fills halted trading days with the last close. Technical indicators calculated over this series are corrupted.
- **Fix:** Detect gaps > 1 trading day before forward-filling. Log a warning with the ticker and gap dates. Consider whether to interpolate, skip, or flag the analysis as unreliable for that period.

### 5.5 Extend caching to news and fundamentals
- **Problem:** Only OHLCV is cached. News, fundamentals, and indicators are re-fetched on every run, even when analyzing the same ticker twice in one session.
- **Fix:** Add a simple TTL cache (file-based, same pattern as OHLCV) for:
  - News: keyed by `(symbol, date)`, TTL 4 hours
  - Fundamentals: keyed by `(symbol, fiscal_quarter)`, TTL 24 hours
  - Indicators: keyed by `(symbol, indicator, date)`, TTL 4 hours

---

## Quick Reference: Priority Order

| Phase | Focus | Est. Effort | Expected Gain |
|-------|-------|-------------|---------------|
| 1 | Reliability — silent failures, race conditions | 8–12h | Stops production data loss |
| 2 | Data pipeline — errors, staleness, normalization | 10–15h | Clean data to LLMs |
| 3 | Token efficiency — caching, context compression | 12–18h | 40–65% cost reduction |
| 4 | Architecture — flatten debate, merge agents | 20–30h | Simpler, faster, cheaper |
| 5 | Signal quality — filtering, divergence, caching | 8–12h | Better model inputs |

**Start with Phase 3.1 (prompt caching)** — it requires the least code change and pays back immediately on every run.

**Start Phase 1 items in parallel** — they are isolated fixes that do not depend on each other.

---

## Files Modified Most Frequently Across All Phases

| File | Phases |
|------|--------|
| `tradingagents/portfolio_advisor/service.py` | 1, 3 |
| `tradingagents/portfolio_advisor/advisor_pm.py` | 1, 3, 4 |
| `tradingagents/graph/trading_graph.py` | 3, 4 |
| `tradingagents/graph/conditional_logic.py` | 4 |
| `tradingagents/dataflows/interface.py` | 2 |
| `tradingagents/dataflows/y_finance.py` | 2, 5 |
| `tradingagents/agents/analysts/*.py` | 3, 4, 5 |
| `tradingagents/llm_clients/anthropic_client.py` | 3 |
| `tradingagents/dataflows/stockstats_utils.py` | 2, 5 |
| `tradingagents/portfolio_advisor/single_model_analysis.py` | 3 |
