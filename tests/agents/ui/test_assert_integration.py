"""Day 6: tests for ActionResult integration into assert_node.

验证:
- Layer 0.6 status-based fast fail (failure/timeout/not_found)
- long_term_memory 注入到 reasoning
- candidates / extracted_content 注入到 prompt (Layer 2)
- 既有 extracted_content 又有 error 的优先级
"""
import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def make_state(action_result=None, tool_calls=None, **overrides):
    """构造一个最小的 assert_node state"""
    from langchain_core.messages import SystemMessage
    state = {
        "messages": [SystemMessage(content="test")],
        "task_id": "day6-test",
        "test_plan": [],
        "current_index": 0,
        "current_step": 1,
        "_last_action_result": action_result,
        "_last_tool_calls": tool_calls or [],
        "state_before": {},
        "state_after": {"url": "https://x.com", "title": "X"},
        "consecutive_failures": 0,
    }
    state.update(overrides)
    return state


@pytest.mark.asyncio
async def test_status_failure_fast_fail():
    from core.interfaces import ActionResult
    from agents.ui.execution_graph import assert_node

    ar = ActionResult(
        action="click", target="#1", success=False, status="failure",
        error="element not interactable",
        long_term_memory="尝试 #2 或 use evaluate_js",
    )
    state = make_state(action_result=ar)

    result = await assert_node(state)
    assert result["_last_assertion"].status == "fail"
    # 走 error 路径, error 优先, long_term_memory 注入到 reasoning
    assert "element not interactable" in result["_last_assertion"].reasoning
    assert "💡 后续建议" in result["_last_assertion"].reasoning


@pytest.mark.asyncio
async def test_status_failure_no_error():
    """status=failure 但 error 为空 — 走 status-based 路径"""
    from core.interfaces import ActionResult
    from agents.ui.execution_graph import assert_node

    ar = ActionResult(
        action="click", target="#1", success=False, status="failure",
        error="",
        long_term_memory="无 error 仅有 status",
    )
    state = make_state(action_result=ar)

    result = await assert_node(state)
    assert result["_last_assertion"].status == "fail"
    assert "status=failure" in result["_last_assertion"].reasoning
    assert "💡 后续建议" in result["_last_assertion"].reasoning


@pytest.mark.asyncio
async def test_status_timeout_fast_fail():
    from core.interfaces import ActionResult
    from agents.ui.execution_graph import assert_node

    ar = ActionResult(
        action="input_text", target="#username", success=False, status="timeout",
        error="timed out waiting for element",
    )
    state = make_state(action_result=ar)

    result = await assert_node(state)
    assert result["_last_assertion"].status == "fail"
    assert "timed out" in result["_last_assertion"].reasoning


@pytest.mark.asyncio
async def test_status_not_found_fast_fail():
    from core.interfaces import ActionResult
    from agents.ui.execution_graph import assert_node

    ar = ActionResult(
        action="click", target="#missing", success=False, status="not_found",
        error="no element matches selector",
    )
    state = make_state(action_result=ar)

    result = await assert_node(state)
    assert result["_last_assertion"].status == "fail"
    assert "no element matches selector" in result["_last_assertion"].reasoning


@pytest.mark.asyncio
async def test_error_without_status_still_fails():
    """当 ActionResult 仅有 error (无 status=failure) 时, 仍走 fail 路径"""
    from core.interfaces import ActionResult
    from agents.ui.execution_graph import assert_node

    # 模拟 status="failure" + error=message 场景 (error-based 优先路径)
    ar = ActionResult(
        action="click", target="#x", success=False, status="failure",
        error="some old-style error message",
    )
    state = make_state(action_result=ar)

    result = await assert_node(state)
    assert result["_last_assertion"].status == "fail"
    assert "some old-style error" in result["_last_assertion"].reasoning


@pytest.mark.asyncio
async def test_mark_task_failed_passes_through():
    """mark_task_failed 仍然走 marker 路径, 不被 Layer 0.6 抢走"""
    from core.interfaces import ActionResult
    from agents.ui.execution_graph import assert_node

    # mark_task_failed 工具的 action_result 来自 _make_action_result,
    # 默认 success=False, error=reasoning
    ar = ActionResult(
        action="mark_task_failed", target=None, success=False, error="用户明确失败",
    )
    state = make_state(
        action_result=ar,
        tool_calls=[{"name": "mark_task_failed", "args": {"reasoning": "用户明确失败"}}],
    )

    result = await assert_node(state)
    assert result["_last_assertion"].status == "fail"
    assert "用户明确失败" in result["_last_assertion"].reasoning


@pytest.mark.asyncio
async def test_status_success_does_not_fast_fail():
    """status=success + 无 marker → 不被 Layer 0.6 拦截, 走 Layer 1/2 路径"""
    from core.interfaces import ActionResult
    from agents.ui.execution_graph import assert_node

    ar = ActionResult(
        action="click", target="#ok", success=True, status="success",
        extracted_content="已点击提交按钮",
    )
    # current_step 设为非 final, 中间步骤, 走 inconclusive 路径
    state = make_state(action_result=ar)
    state["current_step"] = 1
    state["test_plan"] = []  # 空 test_plan, current_test_case=None

    # Mock LLM 调用避免真实网络
    fake_assertion = MagicMock()
    fake_assertion.status = "inconclusive"
    fake_assertion.reasoning = "mocked: success action, no real LLM call"
    fake_assertion.confidence = 0.5
    fake_assertion.evidence = ""

    with patch("agents.ui.execution_graph.safe_structured_invoke",
               new=AsyncMock(return_value=(fake_assertion, 0))):
        result = await assert_node(state)
    # 应当走 Layer 1/2 路径 (inconclusive), 而不是 Layer 0.6 fail
    assert "动作状态" not in result["_last_assertion"].reasoning
    assert "动作执行报错" not in result["_last_assertion"].reasoning


@pytest.mark.asyncio
async def test_long_term_memory_injected_into_reasoning():
    from core.interfaces import ActionResult
    from agents.ui.execution_graph import assert_node

    ar = ActionResult(
        action="click", target="#btn", success=False, status="failure",
        error="not interactable",
        long_term_memory="尝试用 evaluate_js 直接 .click()",
    )
    state = make_state(action_result=ar)

    result = await assert_node(state)
    assert "evaluate_js" in result["_last_assertion"].reasoning


@pytest.mark.asyncio
async def test_status_failure_passes_through_fast_assert():
    """Phase 2.0D: status-based failure 走 _fast_assert 路径, 返回 fail assertion.
    consecutive_failures 由 record_node 维护, 不在 assert_node 职责范围内.
    """
    from core.interfaces import ActionResult
    from agents.ui.execution_graph import assert_node

    ar = ActionResult(
        action="click", target="#1", success=False, status="failure",
        error="err",
    )
    state = make_state(action_result=ar, consecutive_failures=2)

    result = await assert_node(state)
    # _fast_assert 路径不更新 consecutive_failures (由 record_node 负责)
    assert result["_last_assertion"].status == "fail"
    assert "err" in result["_last_assertion"].reasoning
