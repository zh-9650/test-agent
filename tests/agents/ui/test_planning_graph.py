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
         patch("agents.ui.planning_graph.tools", []), \
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
    """Mock tool call execution in explore_execute_node.

    注意: navigate 受 FireWall 约束 — target_url 在 _explored_urls 中 (或 == base_url)
    才会被放行。本测试用 base_url 自身, 保证 FireWall 放行 + 工具被调用。
    """
    from agents.ui.planning_graph import explore_execute_node

    ai_msg = AIMessage(
        content="",
        tool_calls=[{"name": "navigate", "args": {"url": "http://example.com/login"}, "id": "call_explore_1"}],
    )
    state = make_planning_state(
        messages=[ai_msg],
        task_config={
            "target_url": "http://example.com/login",
            "_explored_urls": [],
        },
    )

    # tools_by_name 值的结构: BaseTool (有 ainvoke) 或 call-able
    # 现有代码用 tool_fn.ainvoke(tool_args), 所以 mock 需要 MagicMock + AsyncMock on ainvoke
    mock_tool_fn = MagicMock()
    mock_tool_fn.ainvoke = AsyncMock(return_value="已导航到 http://example.com/login")

    with patch("agents.ui.planning_graph.tools_by_name", {"navigate": mock_tool_fn}):
        result = await explore_execute_node(state)

        mock_tool_fn.ainvoke.assert_called_once_with({"url": "http://example.com/login"})


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


# ---------------------------------------------------------------------------
# V1.6.2 planning_graph explore 加固测试 (2026-06-02)
# 验证 get_exploration_system_prompt 走 V1.6 5 段 XML + tool_call 契约,
# explore_decide 注入 SystemModel, explore_execute 永不崩。
# ---------------------------------------------------------------------------


def test_v162_exploration_prompt_v16_xml_structure():
    """V1.6.2: exploration system prompt 必须有 5 段 XML (role/context/task/rules/examples/output_contract)。"""
    from agents.ui.prompts import get_exploration_system_prompt

    prompt = get_exploration_system_prompt(
        accounts=[{"role": "员工", "username": "test_c", "password": "123456"}],
        task_config={"prd": "采购系统PRD", "changelog": "新增采购审批流"},
        scenarios=[{"priority": "high", "name": "提交采购申请", "entry_hint": "采购管理 → 新建"}],
    )

    # 5 段 XML 必须存在
    for tag in ("<role>", "<context>", "<task>", "<rules>", "<examples>", "<output_contract>"):
        assert tag in prompt, f"V1.6.2 prompt missing {tag}"
        assert f"</{tag}>" in prompt or f"</{tag[1:]}" in prompt, f"V1.6.2 prompt missing closing {tag}"


def test_v162_exploration_prompt_tool_call_contract():
    """V1.6.2: output_contract 必须明确 tool_call 必填 OR 显式停止。"""
    from agents.ui.prompts import get_exploration_system_prompt

    prompt = get_exploration_system_prompt()

    # 必须出现 "tool_call" 关键词
    assert "tool_call" in prompt, "V1.6.2 prompt missing tool_call keyword"
    # 必须出现禁止纯文本的规则
    assert "纯文本" in prompt or "禁止" in prompt, "V1.6.2 prompt missing 禁止纯文本 rule"
    # 必须有 good/bad example
    assert "<example" in prompt, "V1.6.2 prompt missing few-shot examples"


def test_v162_exploration_prompt_navigate_firewall_documented():
    """V1.6.2: 探索 prompt 必须明确 navigate 工具的 FireWall 白名单。"""
    from agents.ui.prompts import get_exploration_system_prompt

    prompt = get_exploration_system_prompt()

    # navigate 限制
    assert "navigate" in prompt, "V1.6.2 prompt missing navigate rule"
    # FireWall 关键词
    assert "FireWall" in prompt or "防火墙" in prompt, "V1.6.2 prompt missing FireWall mention"


def test_v162_exploration_prompt_accounts_injection():
    """V1.6.2: 账号注入到 prompt (供登录页面自动登录使用)。"""
    from agents.ui.prompts import get_exploration_system_prompt

    accounts = [{"role": "员工", "username": "test_c", "password": "123456"}]
    prompt = get_exploration_system_prompt(accounts=accounts)

    assert "test_c" in prompt
    assert "123456" in prompt
    assert "员工" in prompt


def test_v162_exploration_prompt_scenarios_injection():
    """V1.6.2: scenarios 注入 (Goal-Driven 提示)。"""
    from agents.ui.prompts import get_exploration_system_prompt

    scenarios = [
        {"priority": "high", "name": "提交采购申请", "entry_hint": "采购管理"},
        {"priority": "low", "name": "查看个人资料", "entry_hint": "右上角头像"},
    ]
    prompt = get_exploration_system_prompt(scenarios=scenarios)

    assert "提交采购申请" in prompt
    assert "查看个人资料" in prompt
    assert "采购管理" in prompt


def test_v162_exploration_prompt_safety_valves_in_context():
    """V1.6.2: context 段必须包含 Safety Valve 数值 (MAX_EXPLORE_PAGES / MAX_EXPLORE_MINUTES)。"""
    from agents.ui.prompts import get_exploration_system_prompt

    with patch.dict(os.environ, {"MAX_EXPLORE_PAGES": "20", "MAX_EXPLORE_MINUTES": "5"}):
        prompt = get_exploration_system_prompt()

    assert "20" in prompt, "V1.6.2 prompt should include MAX_EXPLORE_PAGES=20"
    assert "5" in prompt, "V1.6.2 prompt should include MAX_EXPLORE_MINUTES=5"


@pytest.mark.asyncio
async def test_v162_explore_decide_injects_system_model():
    """V1.6.2: explore_decide 必须把 SystemModel (modules/entities/flows) 注入到 human_msg。

    这是 V1.6.2 关键加固 — 让 LLM 看到理论业务地图, 避免漏探索核心模块。
    """
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
        task_config={
            "target_url": "http://example.com",
            "_explored_urls": ["http://example.com/login"],
            "_system_model": {
                "system_name": "采购系统",
                "modules": ["采购管理", "审批中心", "系统设置"],
                "entities": ["采购申请", "审批单"],
                "flows": [
                    {"name": "采购审批流", "nodes": ["草稿", "待审批"], "transitions": []},
                ],
            },
        },
    )

    with patch("agents.ui.planning_graph.get_llm_client", return_value=mock_llm):
        result = await explore_decide_node(state)

    # 验证 LLM 收到调用
    assert "messages" in result
    # 验证 LLM 收到的消息里有 SystemModel 上下文
    ainvoke_args = mock_llm_with_tools.ainvoke.call_args[0][0]
    # 最后一条 human_msg 应该含 SystemModel 信息
    last_human = None
    for m in ainvoke_args:
        if isinstance(m, HumanMessage):
            last_human = m.content
    assert last_human is not None
    assert "采购系统" in last_human, "explore_decide should inject system_name"
    assert "采购管理" in last_human, "explore_decide should inject modules"
    assert "审批中心" in last_human, "explore_decide should inject modules"
    assert "采购申请" in last_human, "explore_decide should inject entities"
    assert "采购审批流" in last_human, "explore_decide should inject flow names"


@pytest.mark.asyncio
async def test_v162_explore_decide_no_system_model_graceful():
    """V1.6.2: 如果没有 SystemModel, explore_decide 仍能跑 (不注入 system_model_ctx)。"""
    from agents.ui.planning_graph import explore_decide_node

    mock_llm = MagicMock()
    mock_llm_with_tools = MagicMock()
    mock_llm_with_tools.ainvoke = AsyncMock(return_value=AIMessage(content="", tool_calls=[]))
    mock_llm.bind_tools = MagicMock(return_value=mock_llm_with_tools)

    state = make_planning_state(
        task_config={
            "target_url": "http://example.com",
            "_explored_urls": [],
        },
    )

    with patch("agents.ui.planning_graph.get_llm_client", return_value=mock_llm):
        result = await explore_decide_node(state)

    # 不崩
    assert "messages" in result
    ainvoke_args = mock_llm_with_tools.ainvoke.call_args[0][0]
    last_human = None
    for m in ainvoke_args:
        if isinstance(m, HumanMessage):
            last_human = m.content
    assert last_human is not None
    # 不应注入 system_model_ctx (因为没有 _system_model)
    assert "理论业务地图" not in last_human, "no SystemModel → no system_model_ctx"


@pytest.mark.asyncio
async def test_v162_explore_decide_uses_v16_xml_prompt():
    """V1.6.2: explore_decide 实际 LLM 调用时, system_prompt 必须是 V1.6 5 段 XML。"""
    from agents.ui.planning_graph import explore_decide_node

    mock_llm = MagicMock()
    mock_llm_with_tools = MagicMock()
    mock_llm_with_tools.ainvoke = AsyncMock(return_value=AIMessage(content="", tool_calls=[]))
    mock_llm.bind_tools = MagicMock(return_value=mock_llm_with_tools)

    state = make_planning_state(task_config={"target_url": "http://example.com"})

    with patch("agents.ui.planning_graph.get_llm_client", return_value=mock_llm):
        await explore_decide_node(state)

    ainvoke_args = mock_llm_with_tools.ainvoke.call_args[0][0]
    system_msg = next((m for m in ainvoke_args if isinstance(m, SystemMessage)), None)
    assert system_msg is not None
    # V1.6 5 段 XML 必须都有
    for tag in ("<role>", "<context>", "<task>", "<rules>", "<output_contract>"):
        assert tag in system_msg.content, f"V1.6.2 system prompt missing {tag}"


@pytest.mark.asyncio
async def test_v162_explore_execute_returns_tool_message_on_tool_failure():
    """V1.6.2: explore_execute 工具失败时返回 ToolMessage (含错误字符串), 不抛异常。

    inter-node 契约: 上游 (decide) 输出 tool_call → 下游 (observe) 必看到 ToolMessage。
    工具失败不能让整个规划子图崩。
    """
    from agents.ui.planning_graph import explore_execute_node

    ai_msg = AIMessage(
        content="",
        tool_calls=[{"name": "click", "args": {"target": "#99"}, "id": "call_explore_1"}],
    )
    state = make_planning_state(messages=[ai_msg])

    # 模拟工具抛出异常 — 必须挂在 ainvoke 上, 不是 mock_tool_fn 上
    # (因为代码调用 tool_fn.ainvoke(args), 不是 tool_fn(args))
    mock_tool_fn = MagicMock()
    mock_tool_fn.ainvoke = AsyncMock(side_effect=Exception("element not found"))

    with patch("agents.ui.planning_graph.tools_by_name", {"click": mock_tool_fn}):
        result = await explore_execute_node(state)

    # 必须返回 ToolMessage (不抛异常)
    assert "messages" in result
    assert len(result["messages"]) == 1
    tool_msg = result["messages"][0]
    assert tool_msg.tool_call_id == "call_explore_1"
    assert "执行失败" in tool_msg.content or "not found" in tool_msg.content


@pytest.mark.asyncio
async def test_v162_explore_execute_navigate_firewall_blocks_external_url():
    """V1.6.2: navigate 工具的 FireWall 保留, 跨域 URL 必须被拦截。"""
    from agents.ui.planning_graph import explore_execute_node

    ai_msg = AIMessage(
        content="",
        tool_calls=[{"name": "navigate", "args": {"url": "http://evil.com/admin"}, "id": "call_nav_1"}],
    )
    state = make_planning_state(
        messages=[ai_msg],
        task_config={
            "target_url": "http://example.com",
            "_explored_urls": ["http://example.com/login"],
            "prd": "",
        },
    )

    # 工具不应该被调用 (FireWall 应拦截)
    mock_tool_fn = MagicMock()
    mock_tool_fn.ainvoke = AsyncMock(return_value="should not be called")

    with patch("agents.ui.planning_graph.tools_by_name", {"navigate": mock_tool_fn}):
        result = await explore_execute_node(state)

    # FireWall 应返回拒绝消息, 工具未被调用
    mock_tool_fn.ainvoke.assert_not_called()
    assert "messages" in result
    assert "Firewall" in result["messages"][0].content or "拦截" in result["messages"][0].content


@pytest.mark.asyncio
async def test_v162_explore_execute_navigate_allows_base_url():
    """V1.6.2: navigate 跳转到 base_url 应该被放行。"""
    from agents.ui.planning_graph import explore_execute_node

    ai_msg = AIMessage(
        content="",
        tool_calls=[{"name": "navigate", "args": {"url": "http://example.com"}, "id": "call_nav_2"}],
    )
    state = make_planning_state(
        messages=[ai_msg],
        task_config={
            "target_url": "http://example.com",
            "_explored_urls": [],
        },
    )

    mock_tool_fn = MagicMock()
    mock_tool_fn.ainvoke = AsyncMock(return_value="navigated")

    with patch("agents.ui.planning_graph.tools_by_name", {"navigate": mock_tool_fn}):
        result = await explore_execute_node(state)

    # 工具被调用
    mock_tool_fn.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_v162_should_continue_exploring_handles_no_tool_call_as_stop():
    """V1.6.2: should_continue_exploring 见到无 tool_call 的 AIMessage 视为"探索完成"。

    这是 inter-node 契约的关键一环: LLM 决定停止 = 不调工具 = 走到 generate_plan。
    """
    from agents.ui.planning_graph import should_continue_exploring

    ai_msg = AIMessage(content="已探索完毕, 我认为收集到足够信息了。")  # 无 tool_call
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
    assert result == "generate"