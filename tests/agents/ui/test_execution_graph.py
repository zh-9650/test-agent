"""Tests for agents/ui/execution_graph.py (TDD)

Tests the LangGraph execution subgraph with mocked external dependencies.
No real LLM or browser calls in unit tests.
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from core.interfaces import (
    AssertionResult,
    ChangeReport,
    Setup,
    TestCase,
    TestState,
)


# ---------------------------------------------------------------------------
# Helpers to build sample state
# ---------------------------------------------------------------------------

SAMPLE_TEST_CASE = TestCase(
    id="TC-001",
    title="登录成功测试",
    description="验证用户可以正常登录系统",
    preconditions=["login_as_test"],
    steps=["打开登录页面", "输入用户名", "输入密码", "点击登录按钮"],
    expected="成功登录并跳转到主页",
    priority="high",
    category="functional",
)

SAMPLE_SETUP = Setup(id="login_as_test", description="以测试用户登录系统")


def make_sample_state(**overrides) -> dict:
    """Build a minimal TestState-compatible dict for testing."""
    defaults = {
        "messages": [],
        "test_plan": [SAMPLE_TEST_CASE],
        "setups": {"login_as_test": SAMPLE_SETUP},
        "current_index": 0,
        "current_step": 0,
        "results": [],
        "consecutive_failures": 0,
        "page_info": {
            "url": "http://example.com/login",
            "title": "登录页面",
            "interactive_elements": [
                {"id": "#1", "type": "input", "label": "用户名", "placeholder": "请输入用户名"},
                {"id": "#2", "type": "input", "label": "密码", "placeholder": "请输入密码"},
                {"id": "#3", "type": "button", "text": "登录"},
            ],
            "error_messages": [],
        },
        "screenshot": "",
        "state_before": {},
        "state_after": {},
        "task_id": "task-001",
        "task_config": {},
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# test_build_execution_graph
# ---------------------------------------------------------------------------


def test_build_execution_graph():
    """Graph compiles without errors and has expected nodes."""
    from agents.ui.execution_graph import build_execution_graph

    graph = build_execution_graph()
    # Compiled graph should have the expected node names
    node_names = set(graph.nodes.keys())
    # LangGraph compiled graph nodes include __start__ and __end__
    assert "observe" in node_names
    assert "decide" in node_names
    assert "execute" in node_names
    assert "assert" in node_names
    assert "record" in node_names


# ---------------------------------------------------------------------------
# test_should_continue_with_tool_call
# ---------------------------------------------------------------------------


def test_should_continue_with_tool_call():
    """Returns 'execute' when last message has tool_calls."""
    from agents.ui.execution_graph import should_continue

    ai_msg = AIMessage(
        content="",
        tool_calls=[{"name": "click", "args": {"target": "#3"}, "id": "call_1"}],
    )
    state = make_sample_state(messages=[ai_msg])
    result = should_continue(state)
    assert result == "execute"


# ---------------------------------------------------------------------------
# test_should_continue_without_tool_call
# ---------------------------------------------------------------------------


def test_should_continue_without_tool_call():
    """Returns 'record_complete' when no tool_calls."""
    from agents.ui.execution_graph import should_continue

    ai_msg = AIMessage(content="测试完成，所有步骤已验证。")
    state = make_sample_state(messages=[ai_msg])
    result = should_continue(state)
    assert result == "record_complete"


# ---------------------------------------------------------------------------
# test_should_stop_at_max_steps
# ---------------------------------------------------------------------------


def test_should_stop_at_max_steps():
    """Returns 'end' when current_step >= MAX_STEPS_PER_CASE."""
    from agents.ui.execution_graph import should_continue_or_stop

    # Override env var for test
    with patch.dict(os.environ, {"MAX_STEPS_PER_CASE": "5"}):
        # current_step = 5, max = 5, should stop
        ai_msg = AIMessage(
            content="",
            tool_calls=[{"name": "click", "args": {"target": "#3"}, "id": "call_1"}],
        )
        state = make_sample_state(current_step=5, consecutive_failures=0, messages=[ai_msg])
        result = should_continue_or_stop(state)
        assert result == "end"


# ---------------------------------------------------------------------------
# test_should_stop_at_max_failures
# ---------------------------------------------------------------------------


def test_should_stop_at_max_failures():
    """Returns 'end' when consecutive_failures >= MAX_CONSECUTIVE_FAILURES."""
    from agents.ui.execution_graph import should_continue_or_stop

    with patch.dict(os.environ, {"MAX_CONSECUTIVE_FAILURES": "3"}):
        ai_msg = AIMessage(
            content="",
            tool_calls=[{"name": "click", "args": {"target": "#3"}, "id": "call_1"}],
        )
        state = make_sample_state(current_step=1, consecutive_failures=3, messages=[ai_msg])
        result = should_continue_or_stop(state)
        assert result == "end"


# ---------------------------------------------------------------------------
# test_should_continue_or_stop_normal
# ---------------------------------------------------------------------------


def test_should_continue_or_stop_normal():
    """Returns 'observe' when within limits and has tool_calls."""
    from agents.ui.execution_graph import should_continue_or_stop

    with patch.dict(os.environ, {"MAX_STEPS_PER_CASE": "15", "MAX_CONSECUTIVE_FAILURES": "3"}):
        ai_msg = AIMessage(
            content="",
            tool_calls=[{"name": "click", "args": {"target": "#3"}, "id": "call_1"}],
        )
        state = make_sample_state(current_step=2, consecutive_failures=0, messages=[ai_msg])
        result = should_continue_or_stop(state)
        assert result == "observe"


# ---------------------------------------------------------------------------
# test_should_continue_or_stop_no_tool_call
# ---------------------------------------------------------------------------


def test_should_continue_or_stop_no_tool_call():
    """Returns 'end' when decide had no tool_call (test case complete)."""
    from agents.ui.execution_graph import should_continue_or_stop

    ai_msg = AIMessage(content="测试完成。")
    state = make_sample_state(current_step=4, consecutive_failures=0, messages=[ai_msg])
    result = should_continue_or_stop(state)
    assert result == "end"


# ---------------------------------------------------------------------------
# test_observe_node_mock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_observe_node_mock():
    """Mock page_semantic + screenshot, verify state update."""
    from agents.ui.execution_graph import observe_node

    mock_page_info = {
        "url": "http://example.com/login",
        "title": "登录页面",
        "interactive_elements": [
            {"id": "#1", "type": "input", "label": "用户名"},
            {"id": "#2", "type": "button", "text": "登录"},
        ],
        "error_messages": [],
    }
    mock_screenshot = "base64_encoded_screenshot_data"

    state = make_sample_state()

    # V2.0 A2 (2026-06-02): observe_node 现在用 take_screenshot_compressed, 改 patch 它
    with patch("agents.ui.execution_graph.extract_page_semantics", new_callable=AsyncMock) as mock_semantic, \
         patch("agents.ui.execution_graph.take_screenshot_compressed", new_callable=AsyncMock) as mock_ss, \
         patch("agents.ui.execution_graph.get_current_page") as mock_get_page, \
         patch("agents.ui.execution_graph.update_element_map") as mock_update_map:

        mock_semantic.return_value = mock_page_info
        mock_ss.return_value = mock_screenshot
        mock_get_page.return_value = MagicMock()

        result = await observe_node(state)

        mock_semantic.assert_called_once()
        mock_ss.assert_called_once()
        mock_update_map.assert_called_once_with(mock_page_info["interactive_elements"])

        assert result["page_info"] == mock_page_info
        assert result["screenshot"] == mock_screenshot
        assert result["state_before"]["url"] == "http://example.com/login"
        assert "state_after" in result


# ---------------------------------------------------------------------------
# test_decide_node_mock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decide_node_mock():
    """Mock LLM, verify it receives tools and returns AIMessage with tool_calls."""
    from agents.ui.execution_graph import decide_node

    # Create a mock LLM that returns an AIMessage with tool_call
    mock_llm = MagicMock()
    mock_llm_with_tools = MagicMock()

    response = AIMessage(
        content="",
        tool_calls=[{"name": "click", "args": {"target": "#3"}, "id": "call_1"}],
    )
    mock_llm_with_tools.ainvoke = AsyncMock(return_value=response)
    mock_llm.bind_tools = MagicMock(return_value=mock_llm_with_tools)

    state = make_sample_state(
        messages=[
            SystemMessage(content="系统提示"),
            HumanMessage(content="请执行步骤"),
        ]
    )

    # V2.0 A (2026-06-02): pre-existing test bug — 源码用 `tools` 不是 `ui_tools`,
    # 且 retrieve_memories 会被真调, 要 mock 掉
    with patch("agents.ui.execution_graph.get_llm_client", return_value=mock_llm), \
         patch("agents.ui.execution_graph.get_execution_system_prompt", return_value="执行系统提示"), \
         patch("agents.ui.execution_graph.get_step_prompt", return_value="当前步骤: 输入用户名"), \
         patch("agents.ui.execution_graph.tools", return_value=[]), \
         patch("agents.ui.execution_graph._format_page_info", return_value="URL: http://example.com/login\n交互元素:\n  #1: input - 用户名"), \
         patch("core.memory_utils.retrieve_memories", new=AsyncMock(return_value="")), \
         patch("agents.ui.tools.set_current_task"):

        result = await decide_node(state)

        # Result should contain messages (the LLM response)
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert result["messages"][0].tool_calls[0]["name"] == "click"


# ---------------------------------------------------------------------------
# test_execute_node_mock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_node_mock():
    """Mock tool call, verify execution and state_after update."""
    from agents.ui.execution_graph import execute_node

    ai_msg = AIMessage(
        content="",
        tool_calls=[{"name": "click", "args": {"target": "#3"}, "id": "call_1"}],
    )
    state = make_sample_state(messages=[ai_msg], current_step=0)

    mock_tool_fn = AsyncMock()
    mock_tool_fn.ainvoke = AsyncMock(return_value="已点击 #3")
    mock_state_after = {
        "url": "http://example.com/home",
        "title": "主页",
        "interactive_elements": [],
    }

    with patch("agents.ui.execution_graph.tools_by_name", {"click": mock_tool_fn}), \
         patch("agents.ui.execution_graph.get_current_page") as mock_get_page, \
         patch("agents.ui.execution_graph.extract_page_semantics", new_callable=AsyncMock) as mock_semantic:

        mock_get_page.return_value = MagicMock()
        mock_semantic.return_value = mock_state_after

        result = await execute_node(state)

        mock_tool_fn.ainvoke.assert_called_once_with({"target": "#3"})
        assert result["state_after"] == mock_state_after
        assert result["current_step"] == 1
        assert result["_last_tool_result"] == "已点击 #3"


# ---------------------------------------------------------------------------
# test_execute_node_error_handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_node_error_handling():
    """Tool execution failure should not crash, should set state_after from page."""
    from agents.ui.execution_graph import execute_node

    ai_msg = AIMessage(
        content="",
        tool_calls=[{"name": "click", "args": {"target": "#999"}, "id": "call_1"}],
    )
    state = make_sample_state(messages=[ai_msg], current_step=0)

    mock_tool_fn = AsyncMock()
    mock_tool_fn.ainvoke = AsyncMock(side_effect=Exception("元素不存在"))
    mock_state_after = {
        "url": "http://example.com/login",
        "title": "登录页面",
        "interactive_elements": [],
    }

    with patch("agents.ui.execution_graph.tools_by_name", {"click": mock_tool_fn}), \
         patch("agents.ui.execution_graph.get_current_page") as mock_get_page, \
         patch("agents.ui.execution_graph.extract_page_semantics", new_callable=AsyncMock) as mock_semantic:

        mock_get_page.return_value = MagicMock()
        mock_semantic.return_value = mock_state_after

        result = await execute_node(state)

        # Should still return state_after and increment step
        assert result["state_after"] == mock_state_after
        assert result["current_step"] == 1
        assert result["_last_tool_result"] == "执行失败: 元素不存在"


# ---------------------------------------------------------------------------
# test_assert_node_mock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assert_node_mock():
    """Mock change_detector + LLM, verify assertion result."""
    from agents.ui.execution_graph import assert_node

    ai_msg = AIMessage(
        content="点击登录按钮",
        tool_calls=[{"name": "click", "args": {"target": "#3"}, "id": "call_1"}],
    )
    tool_msg = ToolMessage(content="已点击 #3", tool_call_id="call_1")

    state = make_sample_state(
        messages=[ai_msg, tool_msg],
        state_before={"url": "http://example.com/login", "interactive_elements": [{"id": "#3", "type": "button", "text": "登录"}]},
        state_after={"url": "http://example.com/home", "interactive_elements": [{"id": "#4", "type": "link", "text": "仪表盘"}]},
        consecutive_failures=0,
    )

    mock_change_report = ChangeReport(
        url_changed=True,
        url_before="http://example.com/login",
        url_after="http://example.com/home",
        new_elements=["#4 link: 仪表盘"],
        gone_elements=["#3 button: 登录"],
    )

    # V2.0 B2 (2026-06-02): assert_node 改走 safe_structured_invoke + pydantic AssertionResult.
    # Mock 直接返回 AssertionResult 对象, 跳过 LLM 调用.
    from core.interfaces import AssertionResult as _AR
    mock_assertion = _AR(status="pass", reasoning="URL跳转成功, 验证通过。")

    with patch("agents.ui.execution_graph.detect_changes", return_value=mock_change_report), \
         patch("agents.ui.execution_graph.get_assertion_prompt", return_value="请判断操作结果是否符合预期。"), \
         patch("agents.ui.execution_graph.safe_structured_invoke", new=AsyncMock(return_value=mock_assertion)):

        result = await assert_node(state)

        assert "_last_change_report" in result
        assert "_last_assertion" in result
        assert result["_last_assertion"].status == "pass"
        assert "通过" in result["_last_assertion"].reasoning or "PASS" in result["_last_assertion"].reasoning


# ---------------------------------------------------------------------------
# test_assert_node_fail_result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assert_node_fail_result():
    """LLM returns FAIL, verify assertion result is 'fail'."""
    from agents.ui.execution_graph import assert_node

    ai_msg = AIMessage(
        content="点击登录按钮",
        tool_calls=[{"name": "click", "args": {"target": "#3"}, "id": "call_1"}],
    )
    tool_msg = ToolMessage(content="已点击 #3", tool_call_id="call_1")

    state = make_sample_state(
        messages=[ai_msg, tool_msg],
        state_before={"url": "http://example.com/login", "interactive_elements": []},
        state_after={"url": "http://example.com/login", "interactive_elements": [], "error_messages": ["用户名或密码错误"]},
        consecutive_failures=0,
    )

    mock_change_report = ChangeReport(
        url_changed=False,
        error_messages_visible=["用户名或密码错误"],
    )

    llm_assert_response = AIMessage(content="FAIL: 登录失败，页面显示错误提示。")

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=llm_assert_response)

    with patch("agents.ui.execution_graph.detect_changes", return_value=mock_change_report), \
         patch("agents.ui.execution_graph.get_llm_client", return_value=mock_llm), \
         patch("agents.ui.execution_graph.get_assertion_prompt", return_value="请判断操作结果是否符合预期。"):

        result = await assert_node(state)

        assert result["_last_assertion"].status == "fail"


# ---------------------------------------------------------------------------
# test_assert_node_inconclusive_result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assert_node_inconclusive_result():
    """LLM returns inconclusive, verify assertion result."""
    from agents.ui.execution_graph import assert_node

    ai_msg = AIMessage(
        content="点击登录",
        tool_calls=[{"name": "click", "args": {"target": "#3"}, "id": "call_1"}],
    )
    tool_msg = ToolMessage(content="已点击 #3", tool_call_id="call_1")

    state = make_sample_state(
        messages=[ai_msg, tool_msg],
        state_before={},
        state_after={},
        consecutive_failures=0,
    )

    mock_change_report = ChangeReport(url_changed=False)

    llm_assert_response = AIMessage(content="INCONCLUSIVE: 无法确定结果，页面还在加载中。")

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=llm_assert_response)

    with patch("agents.ui.execution_graph.detect_changes", return_value=mock_change_report), \
         patch("agents.ui.execution_graph.get_llm_client", return_value=mock_llm), \
         patch("agents.ui.execution_graph.get_assertion_prompt", return_value="请判断操作结果是否符合预期。"):

        result = await assert_node(state)

        assert result["_last_assertion"].status == "inconclusive"


# ---------------------------------------------------------------------------
# test_record_node_mock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_node_builds_step_result():
    """Record node should build StepResult when reached via assert (has tool_call)."""
    from agents.ui.execution_graph import record_node
    from core.interfaces import StepResult

    ai_msg = AIMessage(
        content="点击登录按钮以验证登录功能",
        tool_calls=[{"name": "click", "args": {"target": "#3"}, "id": "call_1"}],
    )
    tool_msg = ToolMessage(content="已点击 #3", tool_call_id="call_1")

    change_report = ChangeReport(url_changed=True, url_before="http://example.com/login", url_after="http://example.com/home")
    assertion = AssertionResult(status="pass", reasoning="验证通过")

    state = make_sample_state(
        messages=[ai_msg, tool_msg],
        current_step=1,  # execute already incremented
        _last_tool_result="已点击 #3",
        _last_change_report=change_report,
        _last_assertion=assertion,
        screenshot="base64data",
    )

    result = await record_node(state)

    assert "_collected_steps" in result
    assert len(result["_collected_steps"]) == 1
    step = result["_collected_steps"][0]
    assert isinstance(step, StepResult)
    assert step.step_index == 0  # current_step - 1
    assert step.action_type == "click"
    assert step.action_target == "#3"
    assert step.action_args == {"target": "#3"}
    assert step.result == "已点击 #3"
    assert step.screenshot_path == "base64data"
    assert step.change_report == change_report
    assert step.assertion == assertion
    assert step.thought == "点击登录按钮以验证登录功能"


# ---------------------------------------------------------------------------
# test_record_node_no_step_result_on_completion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_node_no_step_result_on_completion():
    """Record node should NOT build StepResult when test case naturally completes (no tool_call)."""
    from agents.ui.execution_graph import record_node

    # Test case complete: AIMessage with no tool_calls
    ai_msg = AIMessage(content="测试完成，所有步骤已验证。")

    state = make_sample_state(
        messages=[ai_msg],
        current_step=4,
        _last_tool_result="",
        _last_change_report=ChangeReport(),
        _last_assertion=AssertionResult(status="pass", reasoning="通过"),
    )

    result = await record_node(state)

    assert "_collected_steps" not in result or len(result.get("_collected_steps", [])) == 0


# ---------------------------------------------------------------------------
# test_record_node_short_messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_node_short_messages_with_step_result():
    """Record node should build StepResult even with short messages (no trimming needed)."""
    from agents.ui.execution_graph import record_node
    from core.interfaces import StepResult

    ai_msg = AIMessage(
        content="输入用户名",
        tool_calls=[{"name": "input_text", "args": {"target": "#1", "text": "test_c"}, "id": "call_2"}],
    )

    state = make_sample_state(
        messages=[SystemMessage(content="系统提示"), ai_msg],
        current_step=1,
        _last_tool_result="已在 #1 输入 test_c",
        _last_change_report=ChangeReport(url_changed=False),
        _last_assertion=AssertionResult(status="inconclusive", reasoning="无法判断"),
    )

    result = await record_node(state)

    # Should have StepResult but no RemoveMessage (messages too short for trimming)
    assert "_collected_steps" in result
    assert len(result["_collected_steps"]) == 1
    assert result["_collected_steps"][0].action_type == "input_text"
    # No message trimming since < 10 messages
    assert "messages" not in result