"""
LLM Factory
-----------
Single place to configure which LLM provider each agent uses.

Priority order for provider resolution:
  1. explicit provider argument
  2. CREWAI_LLM_PROVIDER env var
  3. auto-detect from available API keys
  4. mock (no API calls)

Supported providers:
  - mock        : no API calls, structured placeholders (default)
  - mistral     : Mistral AI  (MISTRAL_API_KEY)
  - anthropic   : Claude      (ANTHROPIC_API_KEY)
  - openai      : ChatGPT     (OPENAI_API_KEY)
  - perplexity  : Perplexity  (PERPLEXITY_API_KEY)  via LiteLLM
  - gemini      : Gemini      (GEMINI_API_KEY)       via LiteLLM
  - grok        : xAI Grok    (XAI_API_KEY)          via LiteLLM
  - deepseek    : DeepSeek    (DEEPSEEK_API_KEY)     via LiteLLM

Default models per provider (override with CREWAI_LLM_MODEL env var):
  mistral    → mistral-small-latest   (free tier, fast, good JSON)
  anthropic  → claude-sonnet-4-6
  openai     → gpt-4o
  perplexity → perplexity/sonar-pro
  gemini     → gemini/gemini-1.5-pro
  grok       → openai/grok-3
  deepseek   → deepseek/deepseek-chat

Usage:
  llm = make_llm()                       # auto-resolves from env
  llm = make_llm(provider="mistral")     # force provider
  llm = make_llm(model="mistral-medium") # force model
"""
from __future__ import annotations

import os
from typing import Optional


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def make_llm(provider: Optional[str] = None, model: Optional[str] = None):
    """
    Returns a CrewAI-compatible LLM object.
    Falls back to mock if provider is unknown or credentials are missing.
    """
    resolved_provider = (provider or _resolve_provider()).lower().strip()
    resolved_model = model or os.environ.get("CREWAI_LLM_MODEL", "")

    if resolved_provider in ("mock", ""):
        return None

    builder = _PROVIDERS.get(resolved_provider)
    if builder is None:
        _warn(f"Unknown provider '{resolved_provider}' — falling back to mock.")
        return None

    return builder(resolved_model or None)


def active_provider() -> str:
    """Returns the currently active provider name (for logging/reporting)."""
    return _resolve_provider()


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------

def _resolve_provider() -> str:
    """
    Resolves provider in priority order:
    1. CREWAI_LLM_PROVIDER env var
    2. Auto-detect from available API keys
    3. 'mock'
    """
    explicit = os.environ.get("CREWAI_LLM_PROVIDER", "").lower().strip()
    if explicit:
        return explicit

    # Auto-detect: first key found wins
    if os.environ.get("MISTRAL_API_KEY"):
        return "mistral"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("PERPLEXITY_API_KEY"):
        return "perplexity"
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    if os.environ.get("XAI_API_KEY"):
        return "grok"
    if os.environ.get("DEEPSEEK_API_KEY"):
        return "deepseek"

    return "mock"


# ---------------------------------------------------------------------------
# Provider builders
# ---------------------------------------------------------------------------

def _make_mistral(model: Optional[str] = None):
    """Mistral AI via LiteLLM wrapper.

    crewai 1.14.5 LLM.__new__ strips the 'mistral/' prefix when routing to
    LiteLLM, so litellm receives 'mistral-small-latest' without provider context
    and returns None. Fix: use a MistralLiteLLMWrapper that calls litellm
    directly with the full 'mistral/mistral-small-latest' model string.
    """
    api_key = os.environ.get("MISTRAL_API_KEY", "")
    if not api_key:
        _warn("MISTRAL_API_KEY not set — falling back to mock.")
        return None

    resolved = model or "mistral-small-latest"
    WrapperClass = _build_mistral_wrapper()
    return WrapperClass(
        model=f"mistral/{resolved}",
        api_key=api_key,
        temperature=0.2,
        max_tokens=2048,
    )


class MistralLiteLLMWrapper:
    """
    Thin wrapper around litellm.completion that is a proper subclass of
    crewai's BaseLLM — required because Agent validates llm: str | BaseLLM.

    Bypasses crewai.LLM.__new__ which strips the 'mistral/' prefix and
    breaks litellm provider routing (litellm needs the full 'mistral/model' string).
    """
    # We build this dynamically after import to avoid circular import issues
    pass


def _build_mistral_wrapper():
    """Builds MistralLiteLLMWrapper as a proper BaseLLM subclass at call time."""
    from crewai.llms.base_llm import BaseLLM
    from typing import Any

    class _MistralWrapper(BaseLLM):
        llm_type: str = "mistral_litellm"
        max_tokens: int = 2048
        context_window_size: int = 32768

        model_config = {"arbitrary_types_allowed": True, "populate_by_name": True}

        def call(
            self,
            messages,
            tools=None,
            callbacks=None,
            available_functions=None,
            from_task=None,
            from_agent=None,
            response_model=None,
        ) -> str:
            import litellm
            msgs = messages if isinstance(messages, list) else [{"role": "user", "content": str(messages)}]
            # Strip crewai-internal fields that Mistral rejects (e.g. cache_breakpoint)
            clean_msgs = [
                {k: v for k, v in (m.items() if isinstance(m, dict) else vars(m).items())
                 if k in ("role", "content", "name", "tool_calls", "tool_call_id")}
                for m in msgs
            ]
            response = litellm.completion(
                model=self.model,          # full 'mistral/mistral-small-latest'
                messages=clean_msgs,
                api_key=self.api_key,
                temperature=self.temperature or 0.2,
                max_tokens=self.max_tokens,
            )
            return response.choices[0].message.content or ""

        def supports_function_calling(self) -> bool:
            return False

        def get_context_window_size(self) -> int:
            return self.context_window_size

        def get_supported_openai_params(self, model: str) -> list[str]:
            return ["temperature", "max_tokens", "stop"]

    return _MistralWrapper


def _make_anthropic(model: Optional[str] = None):
    try:
        from crewai import LLM
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            _warn("ANTHROPIC_API_KEY not set — falling back to mock.")
            return None
        return LLM(
            model=f"anthropic/{model or 'claude-sonnet-4-6'}",
            api_key=api_key,
            temperature=0.2,
            max_tokens=2048,
        )
    except Exception as exc:
        _warn(f"Anthropic init failed: {exc}")
        return None


def _make_openai(model: Optional[str] = None):
    try:
        from crewai import LLM
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            _warn("OPENAI_API_KEY not set — falling back to mock.")
            return None
        return LLM(
            model=model or "gpt-4o",
            api_key=api_key,
            temperature=0.2,
            max_tokens=2048,
        )
    except Exception as exc:
        _warn(f"OpenAI init failed: {exc}")
        return None


def _make_litellm(default_model: str):
    """Generic LiteLLM builder for Perplexity, Gemini, Grok, DeepSeek."""
    def builder(model: Optional[str] = None):
        try:
            from crewai import LLM
            return LLM(
                model=model or default_model,
                temperature=0.2,
                max_tokens=2048,
            )
        except Exception as exc:
            _warn(f"LiteLLM init failed ({default_model}): {exc}")
            return None
    return builder


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

_PROVIDERS = {
    "mistral":    _make_mistral,
    "anthropic":  _make_anthropic,
    "openai":     _make_openai,
    "perplexity": _make_litellm("perplexity/sonar-pro"),
    "gemini":     _make_litellm("gemini/gemini-1.5-pro"),
    "grok":       _make_litellm("openai/grok-3"),
    "deepseek":   _make_litellm("deepseek/deepseek-chat"),
}


def _warn(msg: str) -> None:
    import sys
    print(f"[llm_factory] WARNING: {msg}", file=sys.stderr)
