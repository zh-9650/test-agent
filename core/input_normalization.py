"""Helpers for normalizing rich task-config inputs into plain text."""

from __future__ import annotations

from typing import Any, Mapping


_TEXT_VALUE_KEYS = ("value", "text", "content", "markdown", "body")
_TEXT_CONFIG_FIELDS = {
    "prd",
    "api_doc",
    "swagger",
    "tech_doc",
    "prototype_url",
    "changelog",
    "focus_areas",
}


def normalize_text_input(value: Any) -> str:
    """Coerce rich document values into a plain string when possible."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        for key in _TEXT_VALUE_KEYS:
            if key in value:
                return normalize_text_input(value.get(key))
        if len(value) == 1:
            return normalize_text_input(next(iter(value.values())))
        return str(value)
    if isinstance(value, (list, tuple, set)):
        parts = [normalize_text_input(item).strip() for item in value]
        return "\n".join(part for part in parts if part)
    return str(value)


def normalize_task_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize text-bearing task-config fields while preserving structure."""
    normalized = dict(config or {})

    for field in _TEXT_CONFIG_FIELDS:
        if field in normalized:
            normalized[field] = normalize_text_input(normalized.get(field))

    if "rules" in normalized:
        rules = normalized.get("rules")
        if isinstance(rules, (list, tuple, set)):
            normalized_rules = [normalize_text_input(item).strip() for item in rules]
            normalized["rules"] = [item for item in normalized_rules if item]
        else:
            normalized["rules"] = normalize_text_input(rules)

    return normalized
