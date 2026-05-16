from typing import Optional

from .base_client import BaseLLMClient
from .cost_logger import get_default_cost_callback

# Providers that use the OpenAI-compatible chat completions API
_OPENAI_COMPATIBLE = (
    "openai", "xai", "deepseek",
    "qwen", "qwen-cn",
    "glm", "glm-cn",
    "minimax", "minimax-cn",
    "ollama", "openrouter",
)


def _inject_cost_callback(kwargs: dict) -> dict:
    """Ensure the singleton cost-logging callback is attached to every LLM.

    Preserves any caller-supplied callbacks. Disable with
    ``TRADINGAGENTS_DISABLE_COST_LOG=1``.
    """
    import os
    if os.environ.get("TRADINGAGENTS_DISABLE_COST_LOG") == "1":
        return kwargs
    cb = get_default_cost_callback()
    existing = kwargs.get("callbacks")
    if existing is None:
        kwargs["callbacks"] = [cb]
    elif isinstance(existing, list) and cb not in existing:
        kwargs["callbacks"] = [*existing, cb]
    return kwargs


def create_llm_client(
    provider: str,
    model: str,
    base_url: Optional[str] = None,
    **kwargs,
) -> BaseLLMClient:
    """Create an LLM client for the specified provider.

    Provider modules are imported lazily so that simply importing this
    factory (e.g. during test collection) does not pull in heavy LLM SDKs
    or fail when their API keys are absent.

    Args:
        provider: LLM provider name
        model: Model name/identifier
        base_url: Optional base URL for API endpoint
        **kwargs: Additional provider-specific arguments

    Returns:
        Configured BaseLLMClient instance

    Raises:
        ValueError: If provider is not supported
    """
    provider_lower = provider.lower()
    kwargs = _inject_cost_callback(dict(kwargs))

    if provider_lower in _OPENAI_COMPATIBLE:
        from .openai_client import OpenAIClient
        return OpenAIClient(model, base_url, provider=provider_lower, **kwargs)

    if provider_lower == "anthropic":
        from .anthropic_client import AnthropicClient
        return AnthropicClient(model, base_url, **kwargs)

    if provider_lower == "google":
        from .google_client import GoogleClient
        return GoogleClient(model, base_url, **kwargs)

    if provider_lower == "azure":
        from .azure_client import AzureOpenAIClient
        return AzureOpenAIClient(model, base_url, **kwargs)

    raise ValueError(f"Unsupported LLM provider: {provider}")
