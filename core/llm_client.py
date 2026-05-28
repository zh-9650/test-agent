"""core/llm_client.py — Unified LLM client wrapper using Anthropic SDK.

Provides `get_llm_client()` for obtaining a configured `ChatAnthropic` instance
and `count_tokens()` for estimating token usage.

Supports multi-model switching via environment variables, includes retry logic,
and caches client instances by model_type.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AnyMessage

if TYPE_CHECKING:
    pass

# Cache for LLM client instances, keyed by model_type.
_client_cache: dict[str, ChatAnthropic] = {}

# Model type → environment variable name mapping.
_MODEL_ENV_MAP = {
    "default": "ANTHROPIC_MODEL",
    "haiku": "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "sonnet": "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "opus": "ANTHROPIC_DEFAULT_OPUS_MODEL",
}


def _get_required_env(name: str) -> str:
    """Fetch an environment variable; raise EnvironmentError if missing."""
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(
            f"Missing required environment variable: {name}. "
            f"Please set it in your .env file."
        )
    return value


def get_llm_client(model_type: str = "default") -> ChatAnthropic:
    """获取 LLM 客户端实例。

    通过环境变量配置：
    - ANTHROPIC_AUTH_TOKEN: API Key
    - ANTHROPIC_BASE_URL: API 地址
    - ANTHROPIC_MODEL: 主模型（qwen3.7-max）
    - ANTHROPIC_DEFAULT_HAIKU_MODEL: 轻量模型（deepseek-v4-flash）
    - ANTHROPIC_DEFAULT_SONNET_MODEL: 中等模型（kimi-k2.6）
    - ANTHROPIC_DEFAULT_OPUS_MODEL: 强力模型（glm-5.1）

    Args:
        model_type: "default" | "haiku" | "sonnet" | "opus"

    Returns:
        ChatAnthropic 实例，已配置 base_url 和 api_key
    """
    # Return cached instance if available.
    if model_type in _client_cache:
        return _client_cache[model_type]

    # Validate model_type.
    if model_type not in _MODEL_ENV_MAP:
        valid_types = ", ".join(f'"{k}"' for k in _MODEL_ENV_MAP.keys())
        raise ValueError(
            f"Invalid model_type '{model_type}'. Must be one of: {valid_types}"
        )

    # Resolve model name from environment.
    model_name = _get_required_env(_MODEL_ENV_MAP[model_type])

    # Resolve common configuration from environment.
    api_key = _get_required_env("ANTHROPIC_AUTH_TOKEN")
    base_url = _get_required_env("ANTHROPIC_BASE_URL")

    # Instantiate ChatAnthropic with retry support.
    client = ChatAnthropic(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
        max_tokens=4096,
        temperature=0,
        max_retries=3,
    )

    # Cache and return.
    _client_cache[model_type] = client
    return client


def count_tokens(messages: list[AnyMessage], model: str = "") -> int:
    """估算消息列表的 token 数。用于成本监控和上下文管理。

    Uses a simple heuristic:
    - For text with significant Chinese content: ~1.5 characters per token.
    - Otherwise: ~4 characters per token.
    Falls back gracefully if exact counting is unavailable.

    Args:
        messages: List of LangChain message objects.
        model: Optional model name (ignored for now, reserved for future use).

    Returns:
        Estimated total token count (non-negative).
    """
    total_chars = 0
    total_tokens = 0

    for msg in messages:
        content = getattr(msg, "content", "")
        if not isinstance(content, str):
            continue

        text_len = len(content)
        if text_len == 0:
            continue

        # Detect if text contains significant Chinese characters.
        chinese_chars = sum(1 for ch in content if "一" <= ch <= "鿿")
        if chinese_chars > text_len * 0.3:
            # Predominantly Chinese text: ~1.5 chars per token.
            tokens = max(1, int(text_len / 1.5))
        else:
            # Mostly non-Chinese text: ~4 chars per token.
            tokens = max(1, text_len // 4)

        total_tokens += tokens

    return total_tokens
