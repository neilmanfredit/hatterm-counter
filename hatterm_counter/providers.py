# Copyright 2026 Neil Manfred
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

# Token pricing per million tokens (USD) as of October 2026.
# Cloud provider pricing; local models have zero cost.
PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet": {
        "input": 3.00,
        "output": 15.00,
        "cache_write": 3.75,
        "cache_read": 0.30,
    },
    "claude-opus": {
        "input": 15.00,
        "output": 75.00,
        "cache_write": 18.75,
        "cache_read": 1.50,
    },
    "claude-haiku": {
        "input": 0.80,
        "output": 4.00,
        "cache_write": 1.00,
        "cache_read": 0.08,
    },
    "gemini-flash": {
        "input": 0.075,
        "output": 0.30,
        "cached": 0.01875,
    },
    "gemini-pro": {
        "input": 1.25,
        "output": 5.00,
        "cached": 0.3125,
    },
    "gpt-4o": {
        "input": 2.50,
        "output": 10.00,
    },
    "gpt-4o-mini": {
        "input": 0.15,
        "output": 0.60,
    },
    "gpt-4.1": {
        "input": 2.00,
        "output": 8.00,
    },
    "local": {
        "input": 0.00,
        "output": 0.00,
    },
}

# Providers that use the Anthropic Messages API natively.
ANTHROPIC_PROVIDERS = frozenset({"anthropic"})

# Providers that use OpenAI-compatible chat completions.
OPENAI_COMPAT_PROVIDERS = frozenset({
    "openai", "groq", "openrouter", "nanogpt", "mistral",
    "xai", "deepseek", "cohere", "perplexity", "together",
    "azure", "azure-legacy", "custom",
    "ollama", "lmstudio", "llamacpp", "vllm", "localai",
})

# Providers considered "local" (no API cost).
LOCAL_PROVIDERS = frozenset({"ollama", "lmstudio", "llamacpp", "vllm", "localai"})


def classify_claude_model(model: str) -> str:
    """Returns the PRICING key for a given Claude model name."""
    m = model.lower()
    if "opus" in m:
        return "claude-opus"
    if "haiku" in m:
        return "claude-haiku"
    return "claude-sonnet"


def classify_gemini_model(model: str) -> str:
    """Returns the PRICING key for a given Gemini model name."""
    return "gemini-pro" if "pro" in model.lower() else "gemini-flash"


def classify_openai_model(model: str) -> str:
    """Returns the PRICING key for a given OpenAI model name."""
    m = model.lower()
    if "4o-mini" in m or "4.1-mini" in m:
        return "gpt-4o-mini"
    if "4.1" in m:
        return "gpt-4.1"
    if "4o" in m:
        return "gpt-4o"
    return "gpt-4o"
