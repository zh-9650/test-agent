from __future__ import annotations

"""Deterministic runtime-side action guardrails."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

from core.runtime_tool_contract import RUNTIME_ACTION_TOOLS


@dataclass(frozen=True)
class ActionPolicyDecision:
    allowed: bool
    reason: str = ""
    normalized_action: dict[str, Any] | None = None


_FORBIDDEN_NAVIGATION_PREFIXES = (
    "view-source:",
    "devtools:",
    "chrome:",
    "edge:",
    "file:",
)
_FORBIDDEN_SELECTOR_SNIPPETS = (
    "next.js dev tools",
    "dev tools",
)
_GENERIC_CONTAINER_SELECTORS = {"body", "html", "document"}


def enforce_runtime_action_policy(
    action: Mapping[str, Any] | None,
    *,
    target_url: str,
    current_url: str,
) -> ActionPolicyDecision:
    if not isinstance(action, Mapping):
        return ActionPolicyDecision(False, "action_not_mapping")

    tool = str(action.get("tool", "")).strip()
    raw_args = action.get("args", {})
    if not tool:
        return ActionPolicyDecision(False, "missing_tool")
    if tool not in RUNTIME_ACTION_TOOLS:
        return ActionPolicyDecision(False, "unsupported_tool")
    if raw_args is not None and not isinstance(raw_args, Mapping):
        return ActionPolicyDecision(False, "args_not_mapping")

    args = dict(raw_args or {})
    normalized = {"tool": tool, "args": args}

    if tool == "navigate":
        raw_url = str(args.get("url", "")).strip()
        if not raw_url:
            return ActionPolicyDecision(False, "missing_navigation_url")
        lowered = raw_url.lower()
        if lowered.startswith(_FORBIDDEN_NAVIGATION_PREFIXES):
            return ActionPolicyDecision(False, "forbidden_navigation_target")
        normalized_url = urljoin(current_url or target_url, raw_url)
        if not _is_same_origin(target_url, normalized_url):
            return ActionPolicyDecision(False, "cross_origin_navigation_blocked")
        args["url"] = normalized_url

    if tool in {"click", "input_text", "select_option"}:
        selector = str(args.get("selector", "")).strip()
        if not selector:
            return ActionPolicyDecision(False, "missing_selector")
        selector_lower = selector.lower()
        if selector_lower in _GENERIC_CONTAINER_SELECTORS:
            return ActionPolicyDecision(False, "generic_container_selector_blocked")
        if any(snippet in selector_lower for snippet in _FORBIDDEN_SELECTOR_SNIPPETS):
            return ActionPolicyDecision(False, "browser_chrome_selector_blocked")

    if tool == "input_text":
        if "text" not in args:
            return ActionPolicyDecision(False, "missing_input_text")
        args["text"] = str(args.get("text", ""))

    if tool == "scroll":
        direction = str(args.get("direction", "down")).lower()
        if direction not in {"down", "up"}:
            direction = "down"
        args["direction"] = direction

    if tool == "wait":
        try:
            ms = int(args.get("ms", 1000))
        except (TypeError, ValueError):
            ms = 1000
        args["ms"] = min(max(ms, 100), 5000)

    return ActionPolicyDecision(True, normalized_action=normalized)


def _is_same_origin(base_url: str, candidate_url: str) -> bool:
    base = urlparse(base_url)
    candidate = urlparse(candidate_url)
    return (
        base.scheme == candidate.scheme
        and base.netloc == candidate.netloc
    )
