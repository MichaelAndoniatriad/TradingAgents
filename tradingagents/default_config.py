import os
import json

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

# Single source of truth for env-var → config-key overrides. To expose
# a new config key for environment-based override, add a row here — no
# entry-point script changes required. Coercion is driven by the type
# of the existing default, so users can keep writing plain strings in
# their .env file.
_ENV_OVERRIDES = {
    "TRADINGAGENTS_LLM_PROVIDER":         "llm_provider",
    "TRADINGAGENTS_DEEP_THINK_LLM":       "deep_think_llm",
    "TRADINGAGENTS_QUICK_THINK_LLM":      "quick_think_llm",
    "TRADINGAGENTS_LLM_BACKEND_URL":      "backend_url",
    "TRADINGAGENTS_OUTPUT_LANGUAGE":      "output_language",
    "TRADINGAGENTS_MAX_DEBATE_ROUNDS":    "max_debate_rounds",
    "TRADINGAGENTS_MAX_RISK_ROUNDS":      "max_risk_discuss_rounds",
    "TRADINGAGENTS_CHECKPOINT_ENABLED":   "checkpoint_enabled",
    "TRADINGAGENTS_BENCHMARK_TICKER":     "benchmark_ticker",
    "TRADINGAGENTS_LEARNED_RULES_ENABLED": "learned_rules_enabled",
    "TRADINGAGENTS_LEARNED_RULES_PATH":   "learned_rules_path",
    "TRADINGAGENTS_ANALYSIS_WEBHOOK_URL": "analysis_webhook_url",
    "TRADINGAGENTS_PORTFOLIO_ADVISOR_DIR": "portfolio_advisor_dir",
    "TRADINGAGENTS_PORTFOLIO_ADVISOR_STATE_PATH": "portfolio_advisor_state_path",
    "TRADINGAGENTS_PORTFOLIO_ADVISOR_WEEKDAY": "portfolio_advisor_weekly_weekday",
    "TRADINGAGENTS_PORTFOLIO_ADVISOR_MAX_JOBS": "portfolio_advisor_max_jobs_per_plan",
    "TRADINGAGENTS_PORTFOLIO_ADVISOR_RUN_DUE_MAX": "portfolio_advisor_run_due_max",
    "TRADINGAGENTS_PORTFOLIO_ADVISOR_WEEKLY_LLM": "portfolio_advisor_weekly_llm",
    "TRADINGAGENTS_PORTFOLIO_ADVISOR_WEEKLY_ALWAYS_EMAIL": "portfolio_advisor_weekly_always_email",
    "TRADINGAGENTS_ANALYSIS_EMAIL_TO": "analysis_email_to",
    "TRADINGAGENTS_ANALYSIS_EMAIL_FROM": "analysis_email_from",
    "TRADINGAGENTS_SMTP_HOST": "smtp_host",
    "TRADINGAGENTS_SMTP_PORT": "smtp_port",
    "TRADINGAGENTS_SMTP_USER": "smtp_user",
    "TRADINGAGENTS_SMTP_PASSWORD": "smtp_password",
    "TRADINGAGENTS_SMTP_USE_TLS": "smtp_use_tls",
    "TRADINGAGENTS_MODEL_PRICING_JSON": "model_pricing",
    "TRADINGAGENTS_OPENAI_VAULT_MAX_COMPLETION_TOKENS": "openai_vault_max_completion_tokens",
}


def _coerce(value: str, reference):
    """Coerce env-var string to the type of the existing default value."""
    if isinstance(reference, bool):
        return value.strip().lower() in ("true", "1", "yes", "on")
    if isinstance(reference, int) and not isinstance(reference, bool):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    if isinstance(reference, (dict, list)):
        try:
            return json.loads(value)
        except Exception:
            return reference
    return value


def _apply_env_overrides(config: dict) -> dict:
    """Apply TRADINGAGENTS_* env vars to the config dict in-place."""
    for env_var, key in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            continue
        config[key] = _coerce(raw, config.get(key))
    return config


DEFAULT_CONFIG = _apply_env_overrides({
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", os.path.join(_TRADINGAGENTS_HOME, "logs")),
    "data_cache_dir": os.getenv("TRADINGAGENTS_CACHE_DIR", os.path.join(_TRADINGAGENTS_HOME, "cache")),
    "memory_log_path": os.getenv("TRADINGAGENTS_MEMORY_LOG_PATH", os.path.join(_TRADINGAGENTS_HOME, "memory", "trading_memory.md")),
    # After a pending decision is resolved with returns, the quick LLM may append
    # short rules to learned_rules.md (default: sibling of trading_memory.md).
    "learned_rules_enabled": True,
    "learned_rules_path": None,
    # Optional Slack-style webhook (JSON `{"text":...}`) after each successful
    # full-graph run — posts the advisory PM memo (truncated), not an order.
    "analysis_webhook_url": None,
    # Autonomous portfolio advisor (eToro positions → LLM schedule → due deep runs).
    # portfolio_advisor_weekly_weekday: 0=Mon … 5=Sat, 6=Sun (default Saturday).
    "portfolio_advisor_dir": None,
    "portfolio_advisor_state_path": None,
    "portfolio_advisor_weekly_weekday": 5,
    "portfolio_advisor_max_jobs_per_plan": 15,
    "portfolio_advisor_run_due_max": 2,
    "portfolio_advisor_deep_analysts": ["news", "fundamentals", "market"],
    # Weekly ``advisor portfolio weekly`` = lightweight check only (no full replan).
    "portfolio_advisor_weekly_llm": False,
    "portfolio_advisor_weekly_always_email": True,
    # Optional: email advisory memo after each successful full-graph run (SMTP).
    "analysis_email_to": None,
    "analysis_email_from": None,
    "smtp_host": None,
    "smtp_port": 587,
    "smtp_user": None,
    "smtp_password": None,
    "smtp_use_tls": True,
    # Optional per-model price table used by CLI runtime cost estimates.
    # Format:
    # {
    #   "model-id": {"input_per_1m": 0.15, "output_per_1m": 0.60}
    # }
    # You can also provide this as TRADINGAGENTS_MODEL_PRICING_JSON.
    "model_pricing": {},
    # Corporate hierarchy: per-agent routing through OpenRouter only (see
    # model_catalog.DEFAULT_CORPORATE_AGENT_ROUTING). When True, the main graph
    # ignores ``llm_provider`` / ``quick_think_llm`` / ``deep_think_llm``.
    # Tuned only via this dict or Streamlit settings — not TRADINGAGENTS_* env.
    "corporate_hierarchy_enabled": True,
    # Optional partial overrides: logical agent key -> {model, extra_body?}
    # (``provider`` is always openrouter; any ``provider`` key in overrides is ignored.)
    "agent_llm_routing": {},
    # OpenRouter API base URL for corporate mode only (None = library default).
    "corporate_openrouter_base_url": None,
    "llm_rate_limit_fallback_enabled": True,
    "llm_fallback_openrouter_model": "openai/gpt-4o-mini",
    "openai_vault_max_completion_tokens": 16000,
    # Optional cap on the number of resolved memory log entries. When set,
    # the oldest resolved entries are pruned once this limit is exceeded.
    # Pending entries are never pruned. None disables rotation entirely.
    "memory_log_max_entries": None,
    # LLM settings (legacy single-provider graph when corporate_hierarchy_enabled is False)
    "llm_provider": "openrouter",
    "deep_think_llm": "openai/gpt-4o",
    "quick_think_llm": "openai/gpt-4o-mini",
    # When None, each provider's client falls back to its own default endpoint
    # (api.openai.com for OpenAI, generativelanguage.googleapis.com for Gemini, ...).
    # The CLI overrides this per provider when the user picks one. Keeping a
    # provider-specific URL here would leak (e.g. OpenAI's /v1 was previously
    # being forwarded to Gemini, producing malformed request URLs).
    "backend_url": None,
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    "anthropic_effort": None,           # "high", "medium", "low"
    # Checkpoint/resume: when True, LangGraph saves state after each node
    # so a crashed run can resume from the last successful step.
    "checkpoint_enabled": False,
    # Output language for analyst reports and final decision
    # Internal agent debate stays in English for reasoning quality
    "output_language": "English",
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # News / data fetching parameters
    # Increase for longer lookback strategies or to broaden macro coverage;
    # decrease to reduce token usage in agent prompts.
    "news_article_limit": 20,             # max articles per ticker (ticker-news)
    "global_news_article_limit": 10,      # max articles for global/macro news
    "global_news_lookback_days": 7,       # macro news lookback window
    # Search queries used by get_global_news for macro headlines. Extend or
    # replace to broaden geographic / sector coverage.
    "global_news_queries": [
        "Federal Reserve interest rates inflation",
        "S&P 500 earnings GDP economic outlook",
        "geopolitical risk trade war sanctions",
        "ECB Bank of England BOJ central bank policy",
        "oil commodities supply chain energy",
    ],
    # Data vendor configuration
    # Category-level configuration (default for all tools in category)
    "data_vendors": {
        "core_stock_apis": "yfinance",       # Options: alpha_vantage, yfinance
        "technical_indicators": "yfinance",  # Options: alpha_vantage, yfinance
        "fundamental_data": "yfinance",      # Options: alpha_vantage, yfinance
        "news_data": "yfinance",             # Options: alpha_vantage, yfinance
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
    # Benchmark for alpha calculation in the reflection layer.
    # ``benchmark_ticker`` (when set) overrides the suffix map for all
    # tickers; leave it None to use ``benchmark_map`` for auto-detection
    # based on the ticker's exchange suffix. SPY remains the US default
    # so the reflection label keeps reading "Alpha vs SPY" for US tickers
    # while non-US tickers get their regional index automatically.
    "benchmark_ticker": None,
    "benchmark_map": {
        ".NS":  "^NSEI",    # NSE India (Nifty 50)
        ".BO":  "^BSESN",   # BSE India (Sensex)
        ".T":   "^N225",    # Tokyo (Nikkei 225)
        ".HK":  "^HSI",     # Hong Kong (Hang Seng)
        ".L":   "^FTSE",    # London (FTSE 100)
        ".TO":  "^GSPTSE",  # Toronto (TSX Composite)
        ".AX":  "^AXJO",    # Australia (ASX 200)
        "":     "SPY",      # default for US-listed tickers (no suffix)
    },
})
