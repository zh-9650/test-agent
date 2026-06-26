"""core/llm_client.py — Unified LLM client wrapper using Anthropic SDK.

Provides `get_llm_client()` for obtaining a configured `ChatAnthropic` instance
and `count_tokens()` for estimating token usage.

Supports multi-model switching via environment variables, includes retry logic,
and caches client instances by model_type.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
import re
import ast
from typing import TYPE_CHECKING, Any, TypeVar, get_args, get_origin

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AnyMessage
from pydantic import BaseModel

if TYPE_CHECKING:
    pass

T = TypeVar("T", bound=BaseModel)

# Cache for LLM client instances, keyed by model_type.
_client_cache: dict[str, ChatAnthropic] = {}

# Tier 2 (2026-06-06): raw content 缓存 (供 diag 日志落盘)
# 单变量 (非 per-call) — 假定 L1 串行调用. 入口清空, raw fallback 后设.
_last_raw_content: str = ""
_DIAG_RAW_MAX_BYTES = 4096


def get_last_raw() -> str:
    """返回最近一次 safe_structured_invoke 走 raw fallback 的内容 (前 4KB).

    用法: dump 时 raw_content=get_last_raw()
    注意: 异步并发场景下可能被覆盖, 但 L1 流水线串行调用安全.
    """
    return _last_raw_content

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

    # Instantiate ChatAnthropic with bounded, configurable request behavior.
    # Real target: PRD + Swagger + Changelog easily produces 10K+ token structured JSON.
    # 65536 covers current 5 skills + headroom for richer inputs (multi-PDF, full Swagger).
    client = ChatAnthropic(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
        max_tokens=65536,
        temperature=0,
        max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
        timeout=float(os.getenv("LLM_REQUEST_TIMEOUT_SECONDS", "180")),
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


def _loads_json_compat(blob: str) -> Any:
    """Parse strictly first, then tolerate provider-emitted control characters."""
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return json.loads(blob, strict=False)


def _recover_truncated_json(blob: str) -> Any | None:
    """Recover from truncated JSON (LLM output too long, JSON cut off mid-stream).

    Strategy:
    - If blob is a truncated array [..., {incomplete], find last complete object
    - If blob is a truncated object, try closing open brackets
    - Returns parsed data or None if recovery fails
    """
    blob = blob.strip()

    # Case 1: Truncated array — find last complete object
    if blob.startswith("["):
        # Walk backwards to find the last complete "}" before truncation
        last_close = blob.rfind("}")
        if last_close > 0:
            # Find the matching "[" for this "}"
            depth = 0
            for i in range(last_close, -1, -1):
                if blob[i] == "}":
                    depth += 1
                elif blob[i] == "{":
                    depth -= 1
                if depth == 0:
                    # Found start of this object — take everything up to and including it
                    candidate = blob[:last_close + 1]
                    # Close the outer array
                    if not candidate.endswith("]"):
                        candidate += "]"
                    try:
                        return _loads_json_compat(candidate)
                    except Exception:
                        pass
            # Fallback: just try closing the array
            candidate = blob[:last_close + 1] + "]"
            try:
                return _loads_json_compat(candidate)
            except Exception:
                pass

    # Case 2: Truncated object — try closing open braces/brackets
    open_braces = blob.count("{") - blob.count("}")
    open_brackets = blob.count("[") - blob.count("]")
    if open_braces > 0 or open_brackets > 0:
        candidate = blob + "]" * open_brackets + "}" * open_braces
        try:
            return _loads_json_compat(candidate)
        except Exception:
            pass

    return None


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


def _parse_jsonish_once(value: str) -> Any | None:
    """Best-effort parse for provider-emitted JSON-ish strings."""
    stripped = value.strip()
    if not stripped:
        return None

    candidates: list[str] = [stripped]

    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "\"'":
        inner = stripped[1:-1].strip()
        if inner:
            candidates.append(inner)

    blob = _extract_json_blob(stripped)
    if blob and blob != stripped:
        candidates.append(blob)

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            return _loads_json_compat(candidate)
        except (json.JSONDecodeError, ValueError):
            fixed = re.sub(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})', r'\\\\', candidate)
            try:
                return _loads_json_compat(fixed)
            except (json.JSONDecodeError, ValueError):
                recovered = _recover_truncated_json(candidate)
                if recovered is not None:
                    return recovered
                try:
                    return ast.literal_eval(candidate)
                except (SyntaxError, ValueError):
                    continue
    return None


def _parse_jsonish_string(value: str, *, max_depth: int = 3) -> Any | None:
    """Parse JSON-like strings, recursively unwrapping double-encoded payloads."""
    current = value
    for _ in range(max_depth):
        parsed = _parse_jsonish_once(current)
        if isinstance(parsed, str):
            next_value = parsed.strip()
            if (
                not next_value
                or next_value == current.strip()
                or next_value[0] not in "[{\"'"
            ):
                return parsed
            current = next_value
            continue
        return parsed
    return None


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

    e.g. {"RequirementFact": {...}} or {"TestAssetPackage": {...}}. We peel one layer.
    """
    if len(blob) == 1:
        only = next(iter(blob.values()))
        if isinstance(only, dict):
            return only
    return blob


def _annotation_supports_origin(annotation: Any, expected_origin: type) -> bool:
    origin = get_origin(annotation)
    if origin is expected_origin:
        return True
    return any(
        _annotation_supports_origin(arg, expected_origin)
        for arg in get_args(annotation)
    )


def _single_container_field_name(schema: type[T], expected_origin: type) -> str | None:
    matches = [
        field_name
        for field_name, field_info in schema.model_fields.items()
        if _annotation_supports_origin(field_info.annotation, expected_origin)
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _decode_nested_jsonish(value: Any) -> Any:
    if isinstance(value, str):
        parsed = _parse_jsonish_string(value)
        if parsed is None:
            return value
        if parsed == value:
            return value
        return _decode_nested_jsonish(parsed)
    if isinstance(value, Mapping):
        return {
            key: _decode_nested_jsonish(item)
            for key, item in dict(value).items()
        }
    if isinstance(value, list):
        return [_decode_nested_jsonish(item) for item in value]
    return value


def _decode_json_container_fields(payload: dict[str, Any], schema: type[T]) -> dict[str, Any]:
    """Decode provider-encoded JSON strings for fields declared as list or dict."""
    decoded = dict(payload)
    for field_name, field_info in schema.model_fields.items():
        value = decoded.get(field_name)
        if not isinstance(value, str):
            continue
        accepts_list = _annotation_supports_origin(field_info.annotation, list)
        accepts_dict = _annotation_supports_origin(field_info.annotation, dict)
        if not accepts_list and not accepts_dict:
            continue
        parsed = _parse_jsonish_string(value)
        if parsed is None:
            if accepts_list:
                salvaged_items = _salvage_list_items_from_text(
                    value,
                    field_name=field_name,
                )
                if salvaged_items:
                    decoded[field_name] = salvaged_items
            continue
        if accepts_list and isinstance(parsed, list):
            decoded[field_name] = parsed
        elif accepts_dict and isinstance(parsed, dict):
            decoded[field_name] = parsed
    return decoded


def _extract_balanced_region(
    text: str,
    start_index: int,
    *,
    open_char: str,
    close_char: str,
) -> str | None:
    depth = 0
    in_string = False
    quote_char = ""
    escaped = False

    for index in range(start_index, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote_char:
                in_string = False
            continue

        if char in "\"'":
            in_string = True
            quote_char = char
            continue
        if char == open_char:
            depth += 1
            continue
        if char == close_char and depth > 0:
            depth -= 1
            if depth == 0:
                return text[start_index:index + 1]

    if depth > 0:
        return text[start_index:]
    return None


def _extract_named_array_blob(text: str, field_name: str) -> str | None:
    match = re.search(
        rf'["\']?{re.escape(field_name)}["\']?\s*:',
        text,
    )
    if match is None:
        return None
    array_start = text.find("[", match.end())
    if array_start < 0:
        return None
    return _extract_balanced_region(
        text,
        array_start,
        open_char="[",
        close_char="]",
    )


def _extract_top_level_object_blobs(text: str) -> list[str]:
    objects: list[str] = []
    depth = 0
    start_index: int | None = None
    in_string = False
    quote_char = ""
    escaped = False

    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote_char:
                in_string = False
            continue

        if char in "\"'":
            in_string = True
            quote_char = char
            continue
        if char == "{":
            if depth == 0:
                start_index = index
            depth += 1
            continue
        if char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start_index is not None:
                objects.append(text[start_index:index + 1])
                start_index = None

    return objects


def _salvage_list_items_from_text(
    text: str,
    *,
    field_name: str,
) -> list[Any]:
    candidates: list[str] = []
    named_array = _extract_named_array_blob(text, field_name)
    if named_array:
        candidates.append(named_array)

    stripped = text.strip()
    if stripped.startswith("["):
        candidates.append(stripped)

    candidates.append(text)

    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)

        parsed_items: list[Any] = []
        for blob in _extract_top_level_object_blobs(normalized):
            parsed = _parse_jsonish_once(blob)
            if isinstance(parsed, Mapping):
                parsed_items.append(_decode_nested_jsonish(dict(parsed)))

        if parsed_items:
            return parsed_items

    return []


def _salvage_single_list_field_from_text(
    text: str,
    schema: type[T],
) -> dict[str, Any] | None:
    field_name = _single_container_field_name(schema, list)
    if not field_name:
        return None
    items = _salvage_list_items_from_text(text, field_name=field_name)
    if not items:
        return None
    return {field_name: items}


def _coerce_text_like_value(value: Any) -> str:
    """Normalize provider-emitted non-string text fields into plain text."""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return json.dumps(dict(value), ensure_ascii=False)
    if isinstance(value, (list, tuple, set)):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return " / ".join(parts)
    return str(value)


def _normalize_string_list(values: Any) -> list[str]:
    if isinstance(values, str):
        raw_items = [values]
    elif isinstance(values, (list, tuple, set)):
        raw_items = list(values)
    else:
        raw_items = []

    normalized: list[str] = []
    for item in raw_items:
        if item is None:
            continue
        text = item.strip() if isinstance(item, str) else _coerce_text_like_value(item).strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _looks_read_only_case_text(text: str) -> bool:
    lowered = text.lower()
    return any(
        keyword in lowered
        for keyword in (
            "只读",
            "仅展示",
            "只展示",
            "不可在线编辑",
            "不可编辑",
            "不能编辑",
            "禁止编辑",
            "read-only",
            "readonly",
        )
    )


def _normalize_read_only_case_text(text: str) -> str:
    replacement = (
        "不包含业务编辑输入、保存、提交、修改、新增、删除等写入入口；"
        "导航、筛选、视图切换或角色切换控件不视为违规"
    )
    replacements = (
        "不包含任何输入框、下拉框、可点击编辑按钮或操作按钮",
        "无任何输入框、下拉框、可点击编辑按钮或操作按钮",
        "不包含任何输入框、下拉框或操作按钮",
        "无任何输入框、下拉框或操作按钮",
        "不包含任何可编辑的输入框或操作按钮",
        "无任何可编辑的输入框或操作按钮",
    )
    normalized = text
    for pattern in replacements:
        normalized = normalized.replace(pattern, replacement)
    return normalized


def _normalize_dashboard_formula_case_text(text: str) -> str:
    replacements = {
        "“明星人才”卡片": "“明星/核心人才”卡片",
        "‘明星人才’卡片": "‘明星/核心人才’卡片",
        '"明星人才"卡片': '"明星/核心人才"卡片',
        "'明星人才'卡片": "'明星/核心人才'卡片",
        "明星人才卡片": "明星/核心人才卡片",
        "“核心人才”卡片": "“明星/核心人才”卡片",
        "‘核心人才’卡片": "‘明星/核心人才’卡片",
        '"核心人才"卡片': '"明星/核心人才"卡片',
        "'核心人才'卡片": "'明星/核心人才'卡片",
        "核心人才卡片": "明星/核心人才卡片",
    }
    normalized = text
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    normalized = normalized.replace("明星/明星/核心人才", "明星/核心人才")
    return normalized


def _normalize_case_generation_text(
    value: Any,
    *,
    read_only_context: bool = False,
) -> str:
    text = _coerce_text_like_value(value).strip()
    if not text:
        return text
    text = text.replace("关注人才", "关注")
    text = _normalize_dashboard_formula_case_text(text)
    if read_only_context:
        text = _normalize_read_only_case_text(text)
    return text


def _normalize_case_generation_case(case: dict[str, Any]) -> None:
    roles = _normalize_string_list(case.get("required_roles"))
    unique_role = roles[0] if len(roles) == 1 else ""
    combined_text = "\n".join(
        str(case.get(field_name) or "")
        for field_name in (
            "title",
            "goal",
            "description",
            "expected_result",
            "execution_hint",
        )
    )
    for precondition in case.get("preconditions") or []:
        if isinstance(precondition, dict):
            combined_text += "\n" + str(precondition.get("description") or "")
    read_only_context = _looks_read_only_case_text(combined_text)

    for field_name in (
        "title",
        "goal",
        "description",
        "expected_result",
        "execution_hint",
    ):
        field_value = case.get(field_name)
        if field_value is None:
            continue
        case[field_name] = _normalize_case_generation_text(
            field_value,
            read_only_context=read_only_context,
        )

    for datum in case.get("input_data") or []:
        if not isinstance(datum, dict):
            continue
        for field_name in (
            "name",
            "value",
            "placeholder",
            "source",
            "generation_strategy",
            "boundary_category",
        ):
            field_value = datum.get(field_name)
            if field_value is not None and not isinstance(field_value, str):
                datum[field_name] = _coerce_text_like_value(field_value)

    preconditions = case.get("preconditions")
    if not isinstance(preconditions, list):
        case["required_roles"] = roles
        return

    for precondition in preconditions:
        if not isinstance(precondition, dict):
            continue
        description = precondition.get("description")
        if description is not None:
            precondition["description"] = _normalize_case_generation_text(
                description,
                read_only_context=read_only_context,
            )
        if precondition.get("type") != "account_role":
            continue

        role = precondition.get("required_role")
        normalized_role = ""
        if role is not None:
            normalized_role = _coerce_text_like_value(role).strip()

        if normalized_role:
            precondition["required_role"] = normalized_role
            if normalized_role not in roles:
                roles.append(normalized_role)
            continue

        if unique_role:
            precondition["required_role"] = unique_role
            continue

        precondition["type"] = "environment"
        precondition["required_role"] = None
        precondition["satisfiable_by_agent"] = False
        precondition["failure_policy"] = "human_review_required"

    case["required_roles"] = roles


def _coerce_to_pydantic(payload: Any, schema: type[T]) -> T:
    """Coerce dict/str/list payloads into the target pydantic model."""
    if isinstance(payload, schema):
        return payload
    if isinstance(payload, str):
        parsed = _parse_jsonish_string(payload)
        if parsed is None:
            salvaged = _salvage_single_list_field_from_text(payload, schema)
            if salvaged is None:
                raise ValueError("no JSON blob found in string payload")
            payload = salvaged
        else:
            payload = parsed
    if isinstance(payload, list):
        payload = _decode_nested_jsonish(payload)
        candidates: list[Any] = []
        container_field = _single_container_field_name(schema, list)
        if container_field:
            candidates.append({container_field: payload})
        candidates.extend(({"use_cases": payload}, payload))
        for candidate in candidates:
            try:
                return schema.model_validate(candidate)
            except Exception:
                continue
        raise ValueError("could not coerce list payload")
    if isinstance(payload, Mapping):
        payload = _decode_nested_jsonish(dict(payload))
        payload = _unwrap_envelope(payload)
        payload = _decode_json_container_fields(payload, schema)
        if schema.__name__ == "TechniqueResult":
            techniques = payload.get("techniques")
            if isinstance(techniques, list):
                for index, technique in enumerate(techniques, start=1):
                    if not isinstance(technique, dict):
                        continue
                    condition_id = str(technique.get("condition_id") or "")
                    technique.setdefault(
                        "id",
                        f"TECH-{condition_id or index:03}" if not condition_id else f"TECH-{condition_id}",
                    )
        if schema.__name__ == "CaseGenerationResult":
            cases = payload.get("cases")
            if isinstance(cases, list):
                for case in cases:
                    if not isinstance(case, dict):
                        continue
                    _normalize_case_generation_case(case)
        if schema.__name__ == "ConditionResult":
            conditions = payload.get("conditions")
            if isinstance(conditions, list):
                for condition in conditions:
                    if not isinstance(condition, dict):
                        continue
                    if condition.get("condition_type") == "e2e":
                        condition["condition_type"] = "functional"
                        condition.setdefault("branch_type", "e2e")
        if schema.__name__ == "CoverageResult":
            items = payload.get("items")
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    if item.get("coverage_dimension") == "e2e":
                        item["coverage_dimension"] = "normal"
                        item.setdefault("branch_type", "e2e")
        # Robust mapping for typical LLM model field aliases in AssertionResult
        if schema.__name__ == "AssertionResult":
            if "reason" in payload and "reasoning" not in payload:
                payload["reasoning"] = payload["reason"]
            if "verdict" in payload and "status" not in payload:
                payload["status"] = payload["verdict"]
        return schema.model_validate(payload)
    raise ValueError(f"unsupported payload type: {type(payload).__name__}")


def sanitize_messages_for_structured_output(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Sanitize message history to avoid 'Unknown tool type' errors from strict LLM APIs.

    Converts AIMessage with tool_calls and ToolMessage into plain text messages.
    """
    from langchain_core.messages import AIMessage, ToolMessage, HumanMessage

    sanitized = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            # Convert tool calls to plain text description in content
            tool_calls_desc = []
            for tc in msg.tool_calls:
                tool_calls_desc.append(f"[调用工具: {tc['name']}, 参数: {tc['args']}]")
            text_content = msg.content or ""
            if isinstance(text_content, list):
                parts = []
                for item in text_content:
                    if isinstance(item, dict):
                        if item.get("type") == "text" and isinstance(item.get("text"), str):
                            parts.append(item["text"])
                        elif "text" in item and isinstance(item["text"], str):
                            parts.append(item["text"])
                    elif isinstance(item, str):
                        parts.append(item)
                text_content = "\n".join(parts)
            else:
                text_content = str(text_content)

            if text_content:
                text_content = f"{text_content}\n" + "\n".join(tool_calls_desc)
            else:
                text_content = "\n".join(tool_calls_desc)

            # Create a new AIMessage without tool_calls
            sanitized.append(AIMessage(content=text_content, id=msg.id))
        elif isinstance(msg, ToolMessage):
            # Convert ToolMessage to a HumanMessage
            text_content = f"[工具 {msg.name} 执行结果]: {msg.content}"
            sanitized.append(HumanMessage(content=text_content, id=msg.id))
        else:
            sanitized.append(msg)
    return sanitized


async def safe_structured_invoke(
    prompt: str | list[AnyMessage],
    schema: type[T],
    model_type: str = "default",
) -> T | None:
    """Invoke the LLM and robustly return a parsed pydantic model.

    Tries the native structured-output wrapper first; on None/exception, falls back
    to a raw LLM call + manual JSON extraction. Returns None only if both paths
    fail or produce an empty result.

    Tier 2 (2026-06-06): 暴露 raw content 缓存 — 调 get_last_raw() 拿最近一次
    raw fallback 的文本 (前 4KB). 供 diag 日志落盘.
    """
    from langchain_core.messages import HumanMessage

    global _last_raw_content
    _last_raw_content = ""  # 入口清空, 避免上一调用残留

    llm = get_llm_client(model_type)

    if isinstance(prompt, str):
        messages = [HumanMessage(content=prompt)]
    else:
        messages = sanitize_messages_for_structured_output(prompt)

    try:
        # include_raw=True → 拿原始 LLM 响应 + parsed result, 用于 diag 落盘
        wrapper = llm.with_structured_output(schema, include_raw=True)
        raw_result = await wrapper.ainvoke(messages)
        # raw_result: {"raw": BaseMessage, "parsed": T | None, "parsing_error": Exception | None}
        parsed = raw_result.get("parsed") if isinstance(raw_result, dict) else None
        raw_msg = raw_result.get("raw") if isinstance(raw_result, dict) else None
        if raw_msg is not None:
            try:
                # 优先取 tool_calls args (LLM 实际生成的结构化数据, 比 text block 完整)
                tool_calls = getattr(raw_msg, "tool_calls", None) or []
                if tool_calls and isinstance(tool_calls, list) and tool_calls[0]:
                    args = tool_calls[0].get("args") if isinstance(tool_calls[0], dict) else getattr(tool_calls[0], "args", None)
                    if args:
                        import json as _json
                        _last_raw_content = _json.dumps(args, ensure_ascii=False, default=str)[:_DIAG_RAW_MAX_BYTES]
                    else:
                        _last_raw_content = _unwrap_content(raw_msg.content)[:_DIAG_RAW_MAX_BYTES]
                else:
                    _last_raw_content = _unwrap_content(raw_msg.content)[:_DIAG_RAW_MAX_BYTES]
            except Exception:
                pass
        if parsed is not None:
            return _coerce_to_pydantic(parsed, schema)
        if raw_msg is not None:
            tool_calls = getattr(raw_msg, "tool_calls", None) or []
            if tool_calls:
                first_call = tool_calls[0]
                native_args = (
                    first_call.get("args")
                    if isinstance(first_call, dict)
                    else getattr(first_call, "args", None)
                )
                if native_args is not None:
                    try:
                        return _coerce_to_pydantic(native_args, schema)
                    except Exception as e:
                        print(
                            f"[LLM] native tool args recovery failed for "
                            f"{schema.__name__}: {e}"
                        )
            native_text = _unwrap_content(raw_msg.content)
            if native_text:
                try:
                    return _coerce_to_pydantic(native_text, schema)
                except Exception as e:
                    print(
                        f"[LLM] native text recovery failed for "
                        f"{schema.__name__}: {e}"
                    )
        print(f"[LLM] structured_output returned None for {schema.__name__}, falling back to raw parse")
    except Exception as e:
        print(f"[LLM] structured_output errored for {schema.__name__}: {e}; falling back to raw parse")

    try:
        raw = await llm.ainvoke(messages)
        text = _unwrap_content(raw.content)
        _last_raw_content = text[:_DIAG_RAW_MAX_BYTES]  # 缓存供 diag 落盘
        blob = _extract_json_blob(text)
        if not blob:
            print(f"[LLM] raw fallback: no JSON found in response for {schema.__name__}")
            return None

        try:
            payload = _loads_json_compat(blob)
        except json.JSONDecodeError as je:
            print(f"[LLM] json.loads failed: {je}. Attempting auto-recovery...", flush=True)
            # Try to fix illegal backslashes (e.g. C:\Users -> C:\\Users)
            fixed_blob = re.sub(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})', r'\\\\', blob)
            try:
                payload = _loads_json_compat(fixed_blob)
                print("[LLM] auto-recovery succeeded after fixing illegal backslashes", flush=True)
            except Exception:
                # Try truncation recovery — LLM output may be cut off mid-JSON
                print(f"[LLM] backslash recovery failed, trying truncation recovery...", flush=True)
                recovered = _recover_truncated_json(blob)
                if recovered is not None:
                    payload = recovered
                    print(f"[LLM] truncation recovery succeeded (partial data)", flush=True)
                else:
                    salvaged = _salvage_single_list_field_from_text(blob, schema)
                    if salvaged is not None:
                        payload = salvaged
                        print(
                            f"[LLM] list-field salvage succeeded for {schema.__name__}",
                            flush=True,
                        )
                    else:
                        print(
                            f"[LLM] auto-recovery failed for {schema.__name__} "
                            f"(payload length={len(blob)})",
                            flush=True,
                        )
                        raise je

        return _coerce_to_pydantic(payload, schema)
    except Exception as e:
        print(f"[LLM] raw fallback also failed for {schema.__name__}: {e}")
        return None
