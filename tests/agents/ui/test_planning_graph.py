"""Tests for agents/ui/planning_graph.py (TDD)

Tests the LangGraph planning subgraph with mocked external dependencies.
No real LLM or browser calls in unit tests.
"""

import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from core.interfaces import Setup, TestCase, TestState


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


def make_planning_state(**overrides) -> dict:
    """Build a minimal TestState-compatible dict for planning tests."""
    defaults = {
        "messages": [],
        "test_plan": [],
        "setups": {},
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
                {"id": "#4", "type": "link", "text": "注册", "href": "/register"},
            ],
            "error_messages": [],
        },
        "screenshot": "",
        "state_before": {},
        "state_after": {},
        "task_id": "task-plan-001",
        "task_config": {
            "target_url": "http://example.com/login",
            "accounts": [{"role": "admin", "username": "test_c"}],
            "_explored_urls": [],
            "_explore_start_time": time.time(),
        },
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# test_build_planning_graph
# ---------------------------------------------------------------------------


def test_build_planning_graph():
    """Graph compiles without errors and has expected nodes."""
    from agents.ui.planning_graph import build_planning_graph

    graph = build_planning_graph()
    node_names = set(graph.nodes.keys())
    assert "explore_observe" in node_names
    assert "explore_decide" in node_names
    assert "explore_execute" in node_names
    assert "generate_plan" in node_names


# ---------------------------------------------------------------------------
# test_should_continue_exploring_under_limits
# ---------------------------------------------------------------------------


def test_should_continue_exploring_under_limits():
    """Returns 'explore' when under both page and time limits and LLM has tool_calls."""
    from agents.ui.planning_graph import should_continue_exploring

    ai_msg = AIMessage(
        content="",
        tool_calls=[{"name": "click", "args": {"target": "#4"}, "id": "call_1"}],
    )
    state = make_planning_state(
        messages=[ai_msg],
        task_config={
            "target_url": "http://example.com",
            "_explored_urls": ["http://example.com/login", "http://example.com/home"],
            "_explore_start_time": time.time(),
        },
    )
    with patch.dict(os.environ, {"MAX_EXPLORE_PAGES": "20", "MAX_EXPLORE_MINUTES": "5"}):
        result = should_continue_exploring(state)
    assert result == "explore"


# ---------------------------------------------------------------------------
# test_should_stop_at_max_pages
# ---------------------------------------------------------------------------


def test_should_stop_at_max_pages():
    """Returns 'generate' when explored >= MAX_EXPLORE_PAGES."""
    from agents.ui.planning_graph import should_continue_exploring

    ai_msg = AIMessage(
        content="",
        tool_calls=[{"name": "navigate", "args": {"url": "http://example.com/settings"}, "id": "call_1"}],
    )
    # 20 URLs explored, max is 20
    urls = [f"http://example.com/page{i}" for i in range(20)]
    state = make_planning_state(
        messages=[ai_msg],
        task_config={
            "target_url": "http://example.com",
            "_explored_urls": urls,
            "_explore_start_time": time.time(),
        },
    )
    with patch.dict(os.environ, {"MAX_EXPLORE_PAGES": "20", "MAX_EXPLORE_MINUTES": "5"}):
        result = should_continue_exploring(state)
    assert result == "generate"


# ---------------------------------------------------------------------------
# test_should_stop_at_max_time
# ---------------------------------------------------------------------------


def test_should_stop_at_max_time():
    """Returns 'generate' when elapsed >= MAX_EXPLORE_MINUTES."""
    from agents.ui.planning_graph import should_continue_exploring

    ai_msg = AIMessage(
        content="",
        tool_calls=[{"name": "click", "args": {"target": "#1"}, "id": "call_1"}],
    )
    # Start time was 5 minutes ago
    start_time = time.time() - (5 * 60 + 1)
    state = make_planning_state(
        messages=[ai_msg],
        task_config={
            "target_url": "http://example.com",
            "_explored_urls": ["http://example.com/login"],
            "_explore_start_time": start_time,
        },
    )
    with patch.dict(os.environ, {"MAX_EXPLORE_PAGES": "20", "MAX_EXPLORE_MINUTES": "5"}):
        result = should_continue_exploring(state)
    assert result == "generate"


# ---------------------------------------------------------------------------
# test_should_stop_no_tool_call
# ---------------------------------------------------------------------------


def test_should_stop_no_tool_call():
    """Returns 'generate' when LLM has no tool_calls (exploration complete)."""
    from agents.ui.planning_graph import should_continue_exploring

    ai_msg = AIMessage(content="探索完成，已收集足够信息。")
    state = make_planning_state(
        messages=[ai_msg],
        task_config={
            "target_url": "http://example.com",
            "_explored_urls": ["http://example.com/login"],
            "_explore_start_time": time.time(),
        },
    )
    with patch.dict(os.environ, {"MAX_EXPLORE_PAGES": "20", "MAX_EXPLORE_MINUTES": "5"}):
        result = should_continue_exploring(state)
    assert result == "generate"


# ---------------------------------------------------------------------------
# test_generate_plan_node_mock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_plan_node_mock():
    """Mock LLM response with create_test_plan tool call -> produces test_plan and setups."""
    from agents.ui.planning_graph import generate_plan_node

    # Mock LLM response with a create_test_plan tool call
    plan_tool_call = {
        "name": "create_test_plan",
        "args": {
            "test_cases": [
                {
                    "id": "TC-001",
                    "title": "登录成功测试",
                    "description": "验证用户可以正常登录",
                    "preconditions": ["login_as_admin"],
                    "steps": ["打开登录页面", "输入用户名", "输入密码", "点击登录"],
                    "expected": "成功登录并跳转到主页",
                    "priority": "high",
                    "category": "functional",
                },
                {
                    "id": "TC-002",
                    "title": "注册页面验证",
                    "description": "验证注册页面可以正常访问",
                    "preconditions": [],
                    "steps": ["点击注册链接", "验证注册页面加载"],
                    "expected": "注册页面正常显示",
                    "priority": "medium",
                    "category": "functional",
                },
            ],
            "setups": [
                {
                    "id": "login_as_admin",
                    "description": "以管理员账号登录系统",
                },
            ],
        },
        "id": "call_plan_1",
    }

    response = AIMessage(content="", tool_calls=[plan_tool_call])

    mock_llm = MagicMock()
    mock_llm_with_tool = MagicMock()
    mock_llm_with_tool.ainvoke = AsyncMock(return_value=response)
    mock_llm.bind_tools = MagicMock(return_value=mock_llm_with_tool)

    state = make_planning_state(
        task_config={
            "target_url": "http://example.com/login",
            "accounts": [{"role": "admin", "username": "test_c"}],
            "_explored_urls": ["http://example.com/login", "http://example.com/home"],
            "_explore_start_time": time.time(),
        },
    )

    with patch("agents.ui.planning_graph.get_llm_client", return_value=mock_llm), \
         patch("agents.ui.planning_graph.get_plan_generation_prompt", return_value="请生成测试计划"):
        result = await generate_plan_node(state)

    # Verify test_plan and setups are produced
    assert "test_plan" in result
    assert len(result["test_plan"]) == 2
    assert result["test_plan"][0].id == "TC-001"
    assert result["test_plan"][0].title == "登录成功测试"
    assert result["test_plan"][1].id == "TC-002"

    assert "setups" in result
    assert "login_as_admin" in result["setups"]
    assert result["setups"]["login_as_admin"].id == "login_as_admin"
    assert result["setups"]["login_as_admin"].description == "以管理员账号登录系统"


# ---------------------------------------------------------------------------
# test_explore_observe_node_mock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_explore_observe_node_mock():
    """Mock page_semantic + screenshot, verify explored_urls tracking."""
    from agents.ui.planning_graph import explore_observe_node

    mock_page_info = {
        "url": "http://example.com/home",
        "title": "主页",
        "interactive_elements": [
            {"id": "#1", "type": "link", "text": "仪表盘"},
            {"id": "#2", "type": "link", "text": "设置"},
        ],
        "error_messages": [],
    }
    mock_screenshot = "base64_explore_screenshot"

    # State with one already-explored URL
    state = make_planning_state(
        task_config={
            "target_url": "http://example.com",
            "_explored_urls": ["http://example.com/login"],
            "_explore_start_time": time.time(),
        },
    )

    with patch("agents.ui.planning_graph.extract_page_semantics", new_callable=AsyncMock) as mock_semantic, \
         patch("agents.ui.planning_graph.take_screenshot", new_callable=AsyncMock) as mock_ss, \
         patch("agents.ui.planning_graph.get_current_page") as mock_get_page, \
         patch("agents.ui.planning_graph.update_element_map") as mock_update_map:

        mock_semantic.return_value = mock_page_info
        mock_ss.return_value = mock_screenshot
        mock_get_page.return_value = MagicMock()

        result = await explore_observe_node(state)

        mock_semantic.assert_called_once()
        mock_ss.assert_called_once()
        mock_update_map.assert_called_once_with(mock_page_info["interactive_elements"])

        assert result["page_info"] == mock_page_info
        assert result["screenshot"] == mock_screenshot

        # Verify explored_urls tracking — new URL should be added
        updated_config = result["task_config"]
        assert "http://example.com/login" in updated_config["_explored_urls"]
        assert "http://example.com/home" in updated_config["_explored_urls"]
        assert len(updated_config["_explored_urls"]) == 2


# ---------------------------------------------------------------------------
# test_explore_decide_node_mock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_explore_decide_node_mock():
    """Mock LLM, verify it receives tools and returns AIMessage."""
    from agents.ui.planning_graph import explore_decide_node

    mock_llm = MagicMock()
    mock_llm_with_tools = MagicMock()

    response = AIMessage(
        content="",
        tool_calls=[{"name": "click", "args": {"target": "#4"}, "id": "call_explore_1"}],
    )
    mock_llm_with_tools.ainvoke = AsyncMock(return_value=response)
    mock_llm.bind_tools = MagicMock(return_value=mock_llm_with_tools)

    state = make_planning_state(
        messages=[],
        task_config={
            "target_url": "http://example.com",
            "_explored_urls": ["http://example.com/login"],
            "_explore_start_time": time.time(),
        },
    )

    with patch("agents.ui.planning_graph.get_llm_client", return_value=mock_llm), \
         patch("agents.ui.planning_graph.get_exploration_system_prompt", return_value="你是测试探索者"), \
         patch("agents.ui.planning_graph.ui_tools", []), \
         patch("agents.ui.planning_graph._format_page_info", return_value="URL: http://example.com/login\n交互元素:\n  #4: link - 注册"):
        result = await explore_decide_node(state)

    assert "messages" in result
    assert len(result["messages"]) == 1
    assert result["messages"][0].tool_calls[0]["name"] == "click"


# ---------------------------------------------------------------------------
# test_explore_execute_node_mock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_explore_execute_node_mock():
    """Mock tool call execution in explore_execute_node."""
    from agents.ui.planning_graph import explore_execute_node

    ai_msg = AIMessage(
        content="",
        tool_calls=[{"name": "navigate", "args": {"url": "http://example.com/home"}, "id": "call_explore_1"}],
    )
    state = make_planning_state(messages=[ai_msg])

    mock_tool_fn = AsyncMock(return_value="已导航到 http://example.com/home")

    with patch("agents.ui.planning_graph.tools_by_name", {"navigate": mock_tool_fn}):
        result = await explore_execute_node(state)

        mock_tool_fn.ainvoke.assert_called_once_with({"url": "http://example.com/home"})


# ---------------------------------------------------------------------------
# test_setup_manager_creates_test_case
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_manager_creates_test_case():
    """Verify Setup is converted to TestCase for execution via setup_manager."""
    from agents.ui.setup_manager import execute_setup

    setup = Setup(id="login_as_admin", description="以管理员账号登录系统")

    state = make_planning_state(
        task_config={
            "target_url": "http://example.com/login",
            "_explored_urls": ["http://example.com/login"],
        },
    )

    # Mock the execution graph
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={"test_plan": [], "results": [], "messages": []})

    with patch("agents.ui.setup_manager.build_execution_graph", return_value=mock_graph):
        result = await execute_setup(setup, state)

        # Verify the graph was invoked with a setup-derived test case
        call_args = mock_graph.ainvoke.call_args[0][0]
        assert len(call_args["test_plan"]) == 1
        setup_case = call_args["test_plan"][0]
        assert setup_case.id == "SETUP-login_as_admin"
        assert setup_case.title == "Setup: 以管理员账号登录系统"
        assert setup_case.description == "以管理员账号登录系统"
        assert setup_case.steps == ["以管理员账号登录系统"]
        assert setup_case.expected == "Setup completed successfully"