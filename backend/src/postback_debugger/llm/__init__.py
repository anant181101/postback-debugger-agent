"""LLM providers behind one interface. Pick one with LLM_PROVIDER (gemini or claude)."""

import os

from postback_debugger.llm.base import (
    LLMError,
    LLMProvider,
    QuotaExceededError,
    StructuredResult,
    TextResult,
    Usage,
)
from postback_debugger.llm.claude import DEFAULT_MODEL as CLAUDE_DEFAULT_MODEL
from postback_debugger.llm.claude import ClaudeProvider
from postback_debugger.llm.gemini import DEFAULT_MODEL as GEMINI_DEFAULT_MODEL
from postback_debugger.llm.gemini import GeminiProvider

PROVIDERS: dict[str, type[GeminiProvider] | type[ClaudeProvider]] = {
    "gemini": GeminiProvider,
    "claude": ClaudeProvider,
}
DEFAULT_PROVIDER = "gemini"


def _models(list_var: str, default_var: str, builtin: tuple[str, ...]) -> tuple[str, ...]:
    """Models the web UI may pick for one provider, with the configured default first.

    Quotas are per model, so offering a few lets a user switch when one is exhausted.
    Override the list with e.g. GEMINI_MODELS=a,b,c and the default with GEMINI_MODEL.
    """
    configured = tuple(m.strip() for m in (os.environ.get(list_var) or "").split(",") if m.strip())
    models = configured or builtin  # GEMINI_MODELS="," must not leave an empty list
    default = os.environ.get(default_var) or models[0]
    return (default, *(m for m in models if m != default))


AVAILABLE_MODELS: dict[str, tuple[str, ...]] = {
    "gemini": _models(
        "GEMINI_MODELS",
        "GEMINI_MODEL",
        (
            GEMINI_DEFAULT_MODEL,
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-3.8-flash",
        ),
    ),
    "claude": _models(
        "CLAUDE_MODELS",
        "CLAUDE_MODEL",
        (CLAUDE_DEFAULT_MODEL, "claude-haiku-5-5", "claude-opus-5-5"),
    ),
}
CREDENTIAL_ENV_VARS = {
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "claude": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
}


def configured_providers() -> list[str]:
    """Providers whose API key is present in the environment."""
    return [
        name
        for name, env_vars in CREDENTIAL_ENV_VARS.items()
        if any(os.environ.get(var) for var in env_vars)
    ]


def get_provider(name: str | None = None, model: str | None = None) -> LLMProvider:
    name = name or os.environ.get("LLM_PROVIDER") or DEFAULT_PROVIDER
    if name not in PROVIDERS:
        raise ValueError(f"unknown provider {name!r}; choose one of: {', '.join(PROVIDERS)}")
    return PROVIDERS[name](model=model)


__all__ = [
    "AVAILABLE_MODELS",
    "DEFAULT_PROVIDER",
    "LLMError",
    "LLMProvider",
    "PROVIDERS",
    "QuotaExceededError",
    "StructuredResult",
    "TextResult",
    "Usage",
    "configured_providers",
    "get_provider",
]
