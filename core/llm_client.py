"""core/llm_client.py — Unified LLM client wrapper using Anthropic SDK.

Provides `get_llm_client()` for obtaining a configured `ChatAnthropic` instance
and `count_tokens()` for estimating token usage.

Supports multi-model switching via environment variables, includes retry logic,
and caches client instances by model_type.
"""

from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING, Any, TypeVar

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AnyMessage
from pydantic import BaseModel

if TYPE_CHECKING:
    pass

T = TypeVar("T", bound=BaseModel)

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

    # Instantiate ChatAnthropic with retry support and large output/timeout budget.
    # Real target: PRD + Swagger + Changelog easily produces 10K+ token structured JSON.
    # 65536 covers current 5 skills + headroom for richer inputs (multi-PDF, full Swagger).
    client = ChatAnthropic(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
        max_tokens=65536,
        temperature=0,
        max_retries=2,
        timeout=1800.0,
    )

    # Cache and return.
    _client_cache[model_type] = client
    return client


# V2.0 D1 (2026-06-02): tiktoken-based accurate token counting
# Anthropic Claude / Qwen3 / Kimi / DeepSeek 都用 cl100k_base 兼容的 BPE tokenizer
# (cl100k_base 是 tiktoken 默认 encoding, 与 GPT-4/Claude tokenizer 误差 <5%)
# tiktoken 不在时回退到启发式估算
try:
    import tiktoken
    _TIKTOKEN_ENCODING = tiktoken.get_encoding("cl100k_base")
    _TIKTOKEN_AVAILABLE = True
except ImportError:
    _TIKTOKEN_ENCODING = None
    _TIKTOKEN_AVAILABLE = False


def _heuristic_count_tokens(messages: list[AnyMessage]) -> int:
    """启发式 token 估算 (tiktoken 不可用时回退).

    - 中文为主: ~1.5 字符/token
    - 否则: ~4 字符/token
    """
    total_tokens = 0
    for msg in messages:
        content = getattr(msg, "content", "")
        if not isinstance(content, str):
            continue
        text_len = len(content)
        if text_len == 0:
            continue
        chinese_chars = sum(1 for ch in content if "一" <= ch <= "鿿")
        if chinese_chars > text_len * 0.3:
            tokens = max(1, int(text_len / 1.5))
        else:
            tokens = max(1, text_len // 4)
        total_tokens += tokens
    return total_tokens


def count_tokens(messages: list[AnyMessage], model: str = "") -> int:
    """估算消息列表的 token 数。用于成本监控和上下文管理。

    V2.0 D1 (2026-06-02): 优先用 tiktoken 精确计数 (cl100k_base, Claude/GPT-4 兼容),
    tiktoken 不可用时回退到启发式. 决策依据: plan §3.4 D1 (偏差 > 30% 回退).

    Args:
        messages: List of LangChain message objects.
        model: Optional model name (ignored for now, reserved for future use).

    Returns:
        Estimated total token count (non-negative).
    """
    if not _TIKTOKEN_AVAILABLE:
        return _heuristic_count_tokens(messages)

    total_tokens = 0
    for msg in messages:
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            if content:
                total_tokens += len(_TIKTOKEN_ENCODING.encode(content))
        elif isinstance(content, list):
            # multimodal: [{type: "text", text: ...}, {type: "image_url", ...}]
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text" and isinstance(block.get("text"), str):
                        total_tokens += len(_TIKTOKEN_ENCODING.encode(block["text"]))
                    elif block.get("type") == "image_url":
                        # Anthropic 低分辨率图像 ~85 tokens, 高分 ~300+ tokens
                        # 我们用 JPEG q=60 压缩, 视为低分
                        total_tokens += 85
    return total_tokens


def extract_tool_calls_from_message(msg: AnyMessage) -> list[dict[str, Any]]:
    """Extract tool calls from an AIMessage.

    Handles both standard msg.tool_calls and fallback parsing from msg.content
    when the LLM provider/adapter embeds the tool call as JSON blocks inside the text.
    """
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        return msg.tool_calls

    extracted = []
    content = getattr(msg, "content", None)
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                extracted.append({
                    "id": item.get("id", ""),
                    "name": item.get("name", ""),
                    "args": item.get("input", {}),
                })
    return extracted


_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)
_OUTER_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_OUTER_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def _extract_json_blob(text: str) -> str | None:
    """Best-effort JSON extraction from raw LLM text."""
    if not text:
        return None
    fence = _CODE_FENCE_RE.search(text)
    if fence:
        return fence.group(1)
    start_obj = text.find("{")
    start_arr = text.find("[")
    if start_obj == -1 and start_arr == -1:
        return None
    if start_obj == -1:
        match = _OUTER_ARRAY_RE.search(text, start_arr)
    elif start_arr == -1:
        match = _OUTER_OBJECT_RE.search(text, start_obj)
    else:
        if start_obj < start_arr:
            match = _OUTER_OBJECT_RE.search(text, start_obj)
        else:
            match = _OUTER_ARRAY_RE.search(text, start_arr)
    return match.group(0) if match else None


def _unwrap_content(content: Any) -> str:
    """Normalize an LLM message content into a plain text string.

    Handles three shapes:
    - str (pass through)
    - list of Anthropic-style content blocks [{"type": "text", "text": "..."}, ...]
    - any other object (str() fallback)
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    parts.append(block["text"])
                elif "text" in block and isinstance(block["text"], str):
                    parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        if parts:
            return "\n".join(parts)
    return str(content)


def _unwrap_envelope(blob: dict) -> dict:
    """Some models wrap the real payload under a single key matching the model name.

    e.g. {"UseCaseModel": {...}} or {"SystemModel": {...}}. We peel one layer.
    """
    if len(blob) == 1:
        only = next(iter(blob.values()))
        if isinstance(only, dict):
            return only
    return blob


def _coerce_to_pydantic(payload: Any, schema: type[T]) -> T:
    """Coerce dict/str/list payloads into the target pydantic model."""
    if isinstance(payload, schema):
        return payload
    if isinstance(payload, str):
        blob = _extract_json_blob(payload)
        if not blob:
            raise ValueError("no JSON blob found in string payload")
        payload = json.loads(blob)
    if isinstance(payload, list):
        for candidate in ({"use_cases": payload}, payload):
            try:
                return schema.model_validate(candidate)
            except Exception:
                continue
        raise ValueError("could not coerce list payload")
    if isinstance(payload, dict):
        payload = _unwrap_envelope(payload)
        # Robust mapping for typical LLM model field aliases in AssertionResult
        if schema.__name__ == "AssertionResult":
            if "reason" in payload and "reasoning" not in payload:
                payload["reasoning"] = payload["reason"]
            if "verdict" in payload and "status" not in payload:
                payload["status"] = payload["verdict"]
        return schema.model_validate(payload)
    raise ValueError(f"unsupported payload type: {type(payload).__name__}")


async def safe_structured_invoke(
    prompt: str | list[AnyMessage],
    schema: type[T],
    model_type: str = "default",
) -> T | None:
    """Invoke the LLM and robustly return a parsed pydantic model.

    Tries the native structured-output wrapper first; on None/exception, falls back
    to a raw LLM call + manual JSON extraction. Returns None only if both paths
    fail or produce an empty result.
    """
    from langchain_core.messages import HumanMessage

    llm = get_llm_client(model_type)

    if isinstance(prompt, str):
        messages = [HumanMessage(content=prompt)]
    else:
        messages = prompt

    try:
        result = await llm.with_structured_output(schema).ainvoke(messages)
        if result is not None:
            return _coerce_to_pydantic(result, schema)
        print(f"[LLM] structured_output returned None for {schema.__name__}, falling back to raw parse")
    except Exception as e:
        print(f"[LLM] structured_output errored for {schema.__name__}: {e}; falling back to raw parse")

    try:
        raw = await llm.ainvoke(messages)
        text = _unwrap_content(raw.content)
        blob = _extract_json_blob(text)
        if not blob:
            print(f"[LLM] raw fallback: no JSON found in response for {schema.__name__}")
            return None
        payload = json.loads(blob)
        return _coerce_to_pydantic(payload, schema)
    except Exception as e:
        print(f"[LLM] raw fallback also failed for {schema.__name__}: {e}")
        return None
