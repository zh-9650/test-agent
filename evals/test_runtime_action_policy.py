"""Tests for runtime_action_policy — hook-level and chain-level.

Refactored (2026-07-09): tests now cover individual hooks in isolation
and verify that removing a hook from the chain disables that policy.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.runtime_action_policy import (
    ActionPolicyDecision,
    _POLICY_HOOKS,
    _require_action_mapping,
    _require_known_tool,
    _require_args_mapping,
    _validate_navigation,
    _validate_selector,
    _require_input_text,
    enforce_runtime_action_policy,
)

TARGET = "http://localhost:3001/"
CURRENT = "http://localhost:3001/dashboard"


# ── Individual hook tests ────────────────────────────────────────────────────


def test_hook_require_action_mapping_rejects_none() -> None:
    decision = _require_action_mapping(None, TARGET, CURRENT)
    assert decision is not None
    assert not decision.allowed
    assert decision.error_code == "policy.action_not_mapping"


def test_hook_require_action_mapping_passes_dict() -> None:
    decision = _require_action_mapping({"tool": "click"}, TARGET, CURRENT)
    assert decision is None  # passes


def test_hook_require_known_tool_rejects_empty() -> None:
    decision = _require_known_tool({"tool": ""}, TARGET, CURRENT)
    assert decision is not None
    assert not decision.allowed


def test_hook_require_known_tool_rejects_unknown() -> None:
    decision = _require_known_tool({"tool": "delete_everything"}, TARGET, CURRENT)
    assert decision is not None
    assert not decision.allowed
    assert decision.error_code == "policy.unsupported_tool"


def test_hook_require_known_tool_passes_click() -> None:
    decision = _require_known_tool({"tool": "click"}, TARGET, CURRENT)
    assert decision is None


def test_hook_require_args_mapping_rejects_non_mapping() -> None:
    decision = _require_args_mapping({"tool": "click", "args": "not_a_dict"}, TARGET, CURRENT)
    assert decision is not None
    assert not decision.allowed


def test_hook_require_args_mapping_passes_dict() -> None:
    decision = _require_args_mapping({"tool": "click", "args": {"selector": "#1"}}, TARGET, CURRENT)
    assert decision is None


def test_hook_validate_navigation_rejects_empty_url() -> None:
    decision = _validate_navigation(
        {"tool": "navigate", "args": {"url": ""}}, TARGET, CURRENT,
    )
    assert decision is not None
    assert not decision.allowed
    assert decision.error_code == "policy.missing_navigation_url"


def test_hook_validate_navigation_rejects_cross_origin() -> None:
    decision = _validate_navigation(
        {"tool": "navigate", "args": {"url": "https://evil.com/"}}, TARGET, CURRENT,
    )
    assert decision is not None
    assert not decision.allowed
    assert decision.error_code == "policy.cross_origin_navigation_blocked"


def test_hook_validate_navigation_rejects_file_protocol() -> None:
    decision = _validate_navigation(
        {"tool": "navigate", "args": {"url": "file:///etc/passwd"}}, TARGET, CURRENT,
    )
    assert decision is not None
    assert not decision.allowed
    assert decision.error_code == "policy.forbidden_navigation_target"


def test_hook_validate_navigation_passes_same_origin() -> None:
    decision = _validate_navigation(
        {"tool": "navigate", "args": {"url": "/settings"}}, TARGET, CURRENT,
    )
    assert decision is None


def test_hook_validate_navigation_skips_non_navigate() -> None:
    decision = _validate_navigation({"tool": "click"}, TARGET, CURRENT)
    assert decision is None  # not a navigate action


def test_hook_validate_selector_rejects_empty() -> None:
    for tool in ("click", "input_text", "select_option"):
        decision = _validate_selector(
            {"tool": tool, "args": {"selector": ""}}, TARGET, CURRENT,
        )
        assert decision is not None, f"{tool} should reject empty selector"
        assert decision.error_code == "policy.missing_selector"


def test_hook_validate_selector_rejects_generic_container() -> None:
    for bad in ("body", "html", "document"):
        decision = _validate_selector(
            {"tool": "click", "args": {"selector": bad}}, TARGET, CURRENT,
        )
        assert decision is not None, f"should reject selector '{bad}'"
        assert decision.error_code == "policy.generic_container_selector_blocked"


def test_hook_validate_selector_passes_valid() -> None:
    decision = _validate_selector(
        {"tool": "click", "args": {"selector": "#login-button"}}, TARGET, CURRENT,
    )
    assert decision is None


def test_hook_validate_selector_skips_non_selector_tools() -> None:
    decision = _validate_selector({"tool": "navigate"}, TARGET, CURRENT)
    assert decision is None


def test_hook_require_input_text_rejects_missing_text() -> None:
    decision = _require_input_text(
        {"tool": "input_text", "args": {"selector": "#5"}}, TARGET, CURRENT,
    )
    assert decision is not None
    assert not decision.allowed
    assert decision.error_code == "policy.missing_input_text"


def test_hook_require_input_text_passes_with_text() -> None:
    decision = _require_input_text(
        {"tool": "input_text", "args": {"selector": "#5", "text": "hello"}}, TARGET, CURRENT,
    )
    assert decision is None


def test_hook_require_input_text_passes_with_value_alias() -> None:
    decision = _require_input_text(
        {"tool": "input_text", "args": {"selector": "#5", "value": "admin"}}, TARGET, CURRENT,
    )
    assert decision is None


def test_hook_require_input_text_skips_non_input() -> None:
    decision = _require_input_text({"tool": "click"}, TARGET, CURRENT)
    assert decision is None


# ── Hook chain tests (end-to-end via enforce_runtime_action_policy) ──────────


def test_chain_rejects_none_action() -> None:
    decision = enforce_runtime_action_policy(None, target_url=TARGET, current_url=CURRENT)
    assert not decision.allowed


def test_chain_rejects_unknown_tool() -> None:
    decision = enforce_runtime_action_policy(
        {"tool": "rm -rf /"}, target_url=TARGET, current_url=CURRENT,
    )
    assert not decision.allowed


def test_chain_rejects_cross_origin() -> None:
    decision = enforce_runtime_action_policy(
        {"tool": "navigate", "args": {"url": "https://evil.com/"}},
        target_url=TARGET,
        current_url=CURRENT,
    )
    assert not decision.allowed
    assert decision.error_code == "policy.cross_origin_navigation_blocked"


def test_chain_normalizes_input_text_value_to_text() -> None:
    decision = enforce_runtime_action_policy(
        {"tool": "input_text", "args": {"selector": "#5", "value": "admin"}},
        target_url=TARGET,
        current_url=CURRENT,
    )
    assert decision.allowed
    assert decision.normalized_action is not None
    assert decision.normalized_action["args"]["text"] == "admin"


def test_chain_normalizes_scroll_direction_invalid() -> None:
    decision = enforce_runtime_action_policy(
        {"tool": "scroll", "args": {"direction": "left"}},
        target_url=TARGET,
        current_url=CURRENT,
    )
    assert decision.allowed
    assert decision.normalized_action["args"]["direction"] == "down"


def test_chain_normalizes_wait_ms_clamp() -> None:
    decision = enforce_runtime_action_policy(
        {"tool": "wait", "args": {"ms": 99999}},
        target_url=TARGET,
        current_url=CURRENT,
    )
    assert decision.allowed
    assert decision.normalized_action["args"]["ms"] == 5000


def test_chain_normalizes_navigation_url() -> None:
    decision = enforce_runtime_action_policy(
        {"tool": "navigate", "args": {"url": "/settings"}},
        target_url=TARGET,
        current_url=CURRENT,
    )
    assert decision.allowed
    assert decision.normalized_action["args"]["url"] == "http://localhost:3001/settings"


# ── Legacy regression tests (kept from original) ─────────────────────────────


def test_input_text_accepts_value_alias() -> None:
    decision = enforce_runtime_action_policy(
        {"tool": "input_text", "args": {"selector": "#5", "value": "admin"}},
        target_url=TARGET,
        current_url=CURRENT,
    )

    assert decision.allowed
    assert decision.normalized_action is not None
    assert decision.normalized_action["args"]["text"] == "admin"


def test_input_text_still_requires_text_or_value() -> None:
    decision = enforce_runtime_action_policy(
        {"tool": "input_text", "args": {"selector": "#5"}},
        target_url=TARGET,
        current_url=CURRENT,
    )

    assert not decision.allowed
    assert decision.error_code == "policy.missing_input_text"


# ── Hook-chain composability tests ───────────────────────────────────────────


def test_disabling_cross_origin_hook_allows_cross_origin() -> None:
    """Verify that removing _validate_navigation from the chain disables the policy.

    This is the key advantage of hook architecture: you can disable a single
    policy by removing it from _POLICY_HOOKS, without touching any hook internals.
    """
    hooks_without_navigation = tuple(
        h for h in _POLICY_HOOKS if h is not _validate_navigation
    )

    action = {"tool": "navigate", "args": {"url": "https://evil.com/"}}
    for hook in hooks_without_navigation:
        rejection = hook(action, TARGET, CURRENT)
        assert rejection is None, f"hook {hook.__name__} rejected unexpectedly"

    # All hooks pass → action would be allowed without the navigation policy.
    # (This confirms the cross-origin check lives ONLY in _validate_navigation.)


def test_disabling_selector_hook_allows_generic_selector() -> None:
    """Verify that removing _validate_selector allows generic selectors."""
    hooks_without_selector = tuple(
        h for h in _POLICY_HOOKS if h is not _validate_selector
    )

    action = {"tool": "click", "args": {"selector": "body"}}
    for hook in hooks_without_selector:
        rejection = hook(action, TARGET, CURRENT)
        assert rejection is None, f"hook {hook.__name__} rejected unexpectedly"


if __name__ == "__main__":
    import traceback

    tests = [
        # Individual hooks
        test_hook_require_action_mapping_rejects_none,
        test_hook_require_action_mapping_passes_dict,
        test_hook_require_known_tool_rejects_empty,
        test_hook_require_known_tool_rejects_unknown,
        test_hook_require_known_tool_passes_click,
        test_hook_require_args_mapping_rejects_non_mapping,
        test_hook_require_args_mapping_passes_dict,
        test_hook_validate_navigation_rejects_empty_url,
        test_hook_validate_navigation_rejects_cross_origin,
        test_hook_validate_navigation_rejects_file_protocol,
        test_hook_validate_navigation_passes_same_origin,
        test_hook_validate_navigation_skips_non_navigate,
        test_hook_validate_selector_rejects_empty,
        test_hook_validate_selector_rejects_generic_container,
        test_hook_validate_selector_passes_valid,
        test_hook_validate_selector_skips_non_selector_tools,
        test_hook_require_input_text_rejects_missing_text,
        test_hook_require_input_text_passes_with_text,
        test_hook_require_input_text_passes_with_value_alias,
        test_hook_require_input_text_skips_non_input,
        # Chain
        test_chain_rejects_none_action,
        test_chain_rejects_unknown_tool,
        test_chain_rejects_cross_origin,
        test_chain_normalizes_input_text_value_to_text,
        test_chain_normalizes_scroll_direction_invalid,
        test_chain_normalizes_wait_ms_clamp,
        test_chain_normalizes_navigation_url,
        # Legacy
        test_input_text_accepts_value_alias,
        test_input_text_still_requires_text_or_value,
        # Composability
        test_disabling_cross_origin_hook_allows_cross_origin,
        test_disabling_selector_hook_allows_generic_selector,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print(f"  PASS  {test.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL  {test.__name__}")
            traceback.print_exc()

    print(f"\n{passed} passed, {failed} failed out of {len(tests)} tests")
    if failed:
        sys.exit(1)
