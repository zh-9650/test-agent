"""Deterministic runtime-side action guardrails.

Refactored (2026-07-09): policy checks extracted into independent hook functions,
registered in a composable chain. Normalizations stay separate from rejections.

Architecture:
  _POLICY_HOOKS  →  ordered tuple of hooks. Each returns None (pass) or rejection.
  _normalize_*   →  pure data fixes, never reject.

To disable a policy, remove it from _POLICY_HOOKS. No other code changes needed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

from core.runtime_tool_contract import (
    RUNTIME_ACTION_TOOLS,
    RuntimePermissionLevel,
    permission_level_for_tool,
)


# ── Data types ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ActionPolicyDecision:
    allowed: bool
    reason: str = ""
    error_code: str = ""
    permission_level: RuntimePermissionLevel = "L1"
    normalized_action: dict[str, Any] | None = None


# ── Constants ────────────────────────────────────────────────────────────────

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

# Hook signature: receives (action, target_url, current_url),
# returns ActionPolicyDecision if the action should be blocked, or None to pass.
PolicyHook = Callable[
    [Mapping[str, Any], str, str],
    ActionPolicyDecision | None,
]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _reject(
    code: str,
    *,
    permission_level: RuntimePermissionLevel,
) -> ActionPolicyDecision:
    return ActionPolicyDecision(
        False,
        reason=code,
        error_code=f"policy.{code}",
        permission_level=permission_level,
    )


def _is_same_origin(base_url: str, candidate_url: str) -> bool:
    base = urlparse(base_url)
    candidate = urlparse(candidate_url)
    return (
        base.scheme == candidate.scheme
        and base.netloc == candidate.netloc
    )


# ── Policy Hooks ─────────────────────────────────────────────────────────────
#
# Each hook receives the raw action dict (not yet validated as Mapping!),
# target_url, and current_url.
#
# Order in _POLICY_HOOKS matters: earlier hooks can assume later hooks'
# checks haven't run yet. Keep structural validators first, then
# tool-specific validators.


def _require_action_mapping(
    action: Mapping[str, Any],
    _target_url: str,
    _current_url: str,
) -> ActionPolicyDecision | None:
    """Block if action is not a dict-like Mapping."""
    if not isinstance(action, Mapping):
        return _reject("action_not_mapping", permission_level="L3")
    return None


def _require_known_tool(
    action: Mapping[str, Any],
    _target_url: str,
    _current_url: str,
) -> ActionPolicyDecision | None:
    """Block if tool name is missing or not in the allowed tool set."""
    tool = str(action.get("tool", "")).strip()
    if not tool:
        return _reject("missing_tool", permission_level="L3")
    if tool not in RUNTIME_ACTION_TOOLS:
        return _reject(
            "unsupported_tool",
            permission_level=permission_level_for_tool(tool),
        )
    return None


def _require_args_mapping(
    action: Mapping[str, Any],
    _target_url: str,
    _current_url: str,
) -> ActionPolicyDecision | None:
    """Block if args exists but is not a dict-like Mapping."""
    raw_args = action.get("args", {})
    if raw_args is not None and not isinstance(raw_args, Mapping):
        return _reject("args_not_mapping", permission_level="L3")
    return None


def _validate_navigation(
    action: Mapping[str, Any],
    target_url: str,
    current_url: str,
) -> ActionPolicyDecision | None:
    """navigate tool: require URL, forbid dangerous schemes, enforce same-origin."""
    tool = str(action.get("tool", "")).strip()
    if tool != "navigate":
        return None

    args = action.get("args", {}) or {}
    raw_url = str(args.get("url", "")).strip()
    permission_level = permission_level_for_tool(tool)

    if not raw_url:
        return _reject("missing_navigation_url", permission_level=permission_level)

    lowered = raw_url.lower()
    if lowered.startswith(_FORBIDDEN_NAVIGATION_PREFIXES):
        return _reject(
            "forbidden_navigation_target",
            permission_level=permission_level,
        )

    normalized_url = urljoin(current_url or target_url, raw_url)
    if not _is_same_origin(target_url, normalized_url):
        return _reject(
            "cross_origin_navigation_blocked",
            permission_level=permission_level,
        )

    return None


def _validate_selector(
    action: Mapping[str, Any],
    _target_url: str,
    _current_url: str,
) -> ActionPolicyDecision | None:
    """click / input_text / select_option: require selector, forbid generic/chrome targets."""
    tool = str(action.get("tool", "")).strip()
    if tool not in {"click", "input_text", "select_option"}:
        return None

    args = action.get("args", {}) or {}
    selector = str(args.get("selector", "")).strip()
    permission_level = permission_level_for_tool(tool)

    if not selector:
        return _reject("missing_selector", permission_level=permission_level)

    selector_lower = selector.lower()
    if selector_lower in _GENERIC_CONTAINER_SELECTORS:
        return _reject(
            "generic_container_selector_blocked",
            permission_level=permission_level,
        )
    if any(snippet in selector_lower for snippet in _FORBIDDEN_SELECTOR_SNIPPETS):
        return _reject(
            "browser_chrome_selector_blocked",
            permission_level=permission_level,
        )

    return None


def _require_input_text(
    action: Mapping[str, Any],
    _target_url: str,
    _current_url: str,
) -> ActionPolicyDecision | None:
    """input_text tool: text (or value alias) must be present."""
    tool = str(action.get("tool", "")).strip()
    if tool != "input_text":
        return None

    args = action.get("args", {}) or {}
    # value alias is accepted; normalization happens later
    if "text" not in args and "value" not in args:
        return _reject(
            "missing_input_text",
            permission_level=permission_level_for_tool(tool),
        )

    return None


# ── Policy Hook Chain ────────────────────────────────────────────────────────
#
# To disable a policy temporarily (e.g. for debugging cross-origin navigation),
# comment it out from this tuple. No other code changes required.

_POLICY_HOOKS: tuple[PolicyHook, ...] = (
    _require_action_mapping,
    _require_known_tool,
    _require_args_mapping,
    _validate_navigation,
    _validate_selector,
    _require_input_text,
)


# ── Normalizers (data fixes only, never reject) ──────────────────────────────


def _normalize_navigation_url(
    args: dict[str, Any],
    target_url: str,
    current_url: str,
) -> None:
    """Resolve relative navigation URL to absolute."""
    if "url" not in args:
        return
    raw_url = str(args.get("url", "")).strip()
    if raw_url:
        args["url"] = urljoin(current_url or target_url, raw_url)


def _normalize_input_text_value_alias(args: dict[str, Any]) -> None:
    """input_text: treat 'value' as alias for 'text'."""
    if "text" not in args and "value" in args:
        args["text"] = args["value"]
    if "text" in args:
        args["text"] = str(args.get("text", ""))


def _normalize_scroll_direction(args: dict[str, Any]) -> None:
    """scroll: default direction to 'down'."""
    if "direction" not in args:
        return
    direction = str(args.get("direction", "down")).lower()
    if direction not in {"down", "up"}:
        args["direction"] = "down"


def _normalize_wait_ms(args: dict[str, Any]) -> None:
    """wait: clamp ms to [100, 5000]."""
    if "ms" not in args:
        return
    try:
        ms = int(args.get("ms", 1000))
    except (TypeError, ValueError):
        ms = 1000
    args["ms"] = min(max(ms, 100), 5000)


# ── Public API ───────────────────────────────────────────────────────────────


def enforce_runtime_action_policy(
    action: Mapping[str, Any] | None,
    *,
    target_url: str,
    current_url: str,
) -> ActionPolicyDecision:
    """Validate and normalize a browser action before execution.

    Architecture (s20 harness pattern):
      1. Run the policy hook chain — any hook can reject the action.
      2. If all hooks pass, normalize args in-place (never reject).
      3. Return the decision with normalized action.

    To disable a policy, remove its hook from _POLICY_HOOKS.
    To add a policy, write a new hook and append it.
    """
    # Guard: None action is a caller error, not a policy check.
    if action is None:
        return _reject("action_not_mapping", permission_level="L3")

    # Phase 1: Policy hook chain
    for hook in _POLICY_HOOKS:
        rejection = hook(action, target_url, current_url)
        if rejection is not None:
            return rejection

    # Phase 2: Normalize args (pure data fixes, never reject)
    tool = str(action.get("tool", "")).strip()
    raw_args = action.get("args", {})
    args = dict(raw_args or {})

    if tool == "navigate":
        _normalize_navigation_url(args, target_url, current_url)
    if tool == "input_text":
        _normalize_input_text_value_alias(args)
    if tool == "scroll":
        _normalize_scroll_direction(args)
    if tool == "wait":
        _normalize_wait_ms(args)

    normalized = {"tool": tool, "args": args}
    permission_level = permission_level_for_tool(tool)

    return ActionPolicyDecision(
        True,
        permission_level=permission_level,
        normalized_action=normalized,
    )
