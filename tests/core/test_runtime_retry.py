"""2026-06-04: Tests for case-level retry policy (同行反馈).

测试场景:
- T1: 始终 fail → 重试 3 次 → human_review_required, retry_count=2, failure_context 有 2 条
- T2: 第 1 次 fail, 第 2 次 pass → passed, retry_count=1, failure_context 有 1 条
- T3: 首次 pass → passed, retry_count=0, failure_context=[]
- T4: failure_context 注入 → 重试时 SystemMessage 包含前次 assertion.reasoning
- T5: MAX_TEST_CASE_RETRIES=0 → 单次尝试, 不重试
"""
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.interfaces import (
    AssertionResult,
    ChangeReport,
    StepResult,
    TestCase,
    TestResult,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_test_case() -> TestCase:
    return TestCase(
        id="TC-R001",
        title="Retry test case",
        description="",
        preconditions=[],
        steps=["step1: click button", "step2: verify result"],
        expected="页面显示成功",
    )


def _make_pass_step() -> StepResult:
    return StepResult(
        step_index=0,
        action_type="click",
        action_target="#btn",
        action_args={},
        result="clicked",
        screenshot_path="",
        change_report=ChangeReport(url_changed=False),
        assertion=AssertionResult(status="pass", reasoning="页面变化符合预期"),
    )


def _make_fail_step(reason: str = "页面无变化") -> StepResult:
    return StepResult(
        step_index=0,
        action_type="click",
        action_target="#btn",
        action_args={},
        result="clicked",
        screenshot_path="",
        change_report=ChangeReport(url_changed=False),
        assertion=AssertionResult(status="fail", reasoning=reason),
    )


def _make_mock_graph(result_state: dict, call_log: list | None = None):
    """返回一个 mock execution graph, ainvoke 返回 result_state."""
    graph = MagicMock()

    async def fake_ainvoke(state):
        if call_log is not None:
            call_log.append(dict(state))
        return result_state

    graph.ainvoke = AsyncMock(side_effect=fake_ainvoke)
    graph.astream = AsyncMock(side_effect=lambda s: _async_gen_from_state(result_state))
    return graph


async def _async_gen_from_state(state: dict):
    """把 state dict 包成 astream 的 async generator."""
    yield {"observe": {**state, "_last_node_name": "observe", "_last_node_duration_ms": 100, "_last_token_count": 0}}
    yield {"record": {**state, "_last_node_name": "record", "_last_node_duration_ms": 50, "_last_token_count": 0}}


def _make_mock_page():
    """返回一个 mock Playwright page, 支持 accessibility.snapshot / screenshot / url."""
    page = AsyncMock()
    page.url = "https://app.com/page"
    page.accessibility.snapshot = AsyncMock(return_value={"role": "document", "name": "Test"})
    page.screenshot = AsyncMock(return_value=b"\x89PNG")
    page.evaluate = AsyncMock(return_value=None)
    page.goto = AsyncMock(return_value=None)
    return page


def _make_runtime_instance():
    """构造一个最小的 Runtime 实例, 绕过 __init__ (避免实际启动浏览器/DB)."""
    from core.runtime import Runtime
    rt = object.__new__(Runtime)
    rt.task_id = "test-retry-task"
    rt.target_url = "https://app.com/login"
    rt.task_config = {}
    rt._case_summaries = []
    rt._stream_results = []
    rt.context = MagicMock()
    rt.context.clear_cookies = AsyncMock()
    rt.page = _make_mock_page()
    rt.coverage_tracker = None
    rt._reset_browser_state = AsyncMock()
    return rt


# ── Tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_always_fail_goes_to_human_review():
    """T1: 始终 fail → 重试 3 次 → human_review_required."""
    os.environ["MAX_TEST_CASE_RETRIES"] = "2"
    os.environ["MAX_CONSECUTIVE_FAILURES"] = "3"
    os.environ["MAX_STEPS_PER_CASE"] = "15"

    fail_state = {
        "_collected_steps": [_make_fail_step("按钮不可点击")],
        "consecutive_failures": 1,
        "current_step": 1,
    }
    call_log = []

    rt = _make_runtime_instance()

    with patch("core.runtime.build_execution_graph", return_value=_make_mock_graph(fail_state, call_log)), \
         patch("core.runtime.log_test_result", new_callable=AsyncMock), \
         patch("core.runtime.log_step", new_callable=AsyncMock), \
         patch("core.runtime.generate_case_summary", new_callable=AsyncMock, return_value={"case_id": "TC-R001", "summary": ""}), \
         patch("core.runtime.execute_setup", new_callable=AsyncMock):

        result = await rt._execute_test_case(
            index=0,
            test_case=_make_test_case(),
            test_plan=[_make_test_case()],
            setups={},
        )

    assert result.status == "human_review_required"
    assert result.retry_count == 2  # 2 次重试 (共 3 次尝试)
    assert len(result.failure_context) == 2  # 前 2 次失败各记一条
    # failure_context 包含断言信息
    assert result.failure_context[0]["assertion_status"] == "fail"
    assert "按钮不可点击" in result.failure_context[0]["assertion_reasoning"]
    # ainvoke 被调了 3 次 (首次 + 2 重试)
    assert len(call_log) == 3


@pytest.mark.asyncio
async def test_fail_then_pass():
    """T2: 第 1 次 fail, 第 2 次 pass → passed."""
    os.environ["MAX_TEST_CASE_RETRIES"] = "2"
    os.environ["MAX_CONSECUTIVE_FAILURES"] = "3"
    os.environ["MAX_STEPS_PER_CASE"] = "15"

    fail_state = {
        "_collected_steps": [_make_fail_step("元素未找到")],
        "consecutive_failures": 1,
        "current_step": 1,
    }
    pass_state = {
        "_collected_steps": [_make_pass_step()],
        "consecutive_failures": 0,
        "current_step": 2,
    }

    call_count = 0

    async def adaptive_ainvoke(state):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return fail_state
        return pass_state

    graph = MagicMock()
    graph.ainvoke = AsyncMock(side_effect=adaptive_ainvoke)

    rt = _make_runtime_instance()

    with patch("core.runtime.build_execution_graph", return_value=graph), \
         patch("core.runtime.log_test_result", new_callable=AsyncMock), \
         patch("core.runtime.log_step", new_callable=AsyncMock), \
         patch("core.runtime.generate_case_summary", new_callable=AsyncMock, return_value={"case_id": "TC-R001", "summary": ""}), \
         patch("core.runtime.execute_setup", new_callable=AsyncMock):

        result = await rt._execute_test_case(
            index=0,
            test_case=_make_test_case(),
            test_plan=[_make_test_case()],
            setups={},
        )

    assert result.status == "passed"
    assert result.retry_count == 1  # 1 次重试
    assert len(result.failure_context) == 1  # 第 1 次失败有记录
    assert call_count == 2  # 共调了 2 次


@pytest.mark.asyncio
async def test_first_attempt_pass():
    """T3: 首次 pass → 不重试."""
    os.environ["MAX_TEST_CASE_RETRIES"] = "2"
    os.environ["MAX_CONSECUTIVE_FAILURES"] = "3"
    os.environ["MAX_STEPS_PER_CASE"] = "15"

    pass_state = {
        "_collected_steps": [_make_pass_step()],
        "consecutive_failures": 0,
        "current_step": 2,
    }
    call_log = []

    rt = _make_runtime_instance()

    with patch("core.runtime.build_execution_graph", return_value=_make_mock_graph(pass_state, call_log)), \
         patch("core.runtime.log_test_result", new_callable=AsyncMock), \
         patch("core.runtime.log_step", new_callable=AsyncMock), \
         patch("core.runtime.generate_case_summary", new_callable=AsyncMock, return_value={"case_id": "TC-R001", "summary": ""}), \
         patch("core.runtime.execute_setup", new_callable=AsyncMock):

        result = await rt._execute_test_case(
            index=0,
            test_case=_make_test_case(),
            test_plan=[_make_test_case()],
            setups={},
        )

    assert result.status == "passed"
    assert result.retry_count == 0
    assert result.failure_context == []
    assert len(call_log) == 1  # 只调了 1 次


@pytest.mark.asyncio
async def test_failure_context_injected_in_retry():
    """T4: 重试时 SystemMessage 包含前次 assertion.reasoning."""
    os.environ["MAX_TEST_CASE_RETRIES"] = "2"
    os.environ["MAX_CONSECUTIVE_FAILURES"] = "3"
    os.environ["MAX_STEPS_PER_CASE"] = "15"

    fail_state = {
        "_collected_steps": [_make_fail_step("按钮 #submit 不可交互")],
        "consecutive_failures": 1,
        "current_step": 1,
    }
    pass_state = {
        "_collected_steps": [_make_pass_step()],
        "consecutive_failures": 0,
        "current_step": 2,
    }

    captured_states = []
    call_count = 0

    async def capture_ainvoke(state):
        nonlocal call_count
        call_count += 1
        captured_states.append(state)
        if call_count == 1:
            return fail_state
        return pass_state

    graph = MagicMock()
    graph.ainvoke = AsyncMock(side_effect=capture_ainvoke)

    rt = _make_runtime_instance()

    with patch("core.runtime.build_execution_graph", return_value=graph), \
         patch("core.runtime.log_test_result", new_callable=AsyncMock), \
         patch("core.runtime.log_step", new_callable=AsyncMock), \
         patch("core.runtime.generate_case_summary", new_callable=AsyncMock, return_value={"case_id": "TC-R001", "summary": ""}), \
         patch("core.runtime.execute_setup", new_callable=AsyncMock):

        result = await rt._execute_test_case(
            index=0,
            test_case=_make_test_case(),
            test_plan=[_make_test_case()],
            setups={},
        )

    assert result.status == "passed"
    assert len(captured_states) == 2
    # 第 2 次 attempt 的 messages[0] 应包含前次失败信息
    retry_state = captured_states[1]
    msg_content = retry_state["messages"][0].content
    assert "上一次尝试" in msg_content
    assert "按钮 #submit 不可交互" in msg_content
    assert "a11y" in msg_content.lower() or "页面结构" in msg_content


@pytest.mark.asyncio
async def test_no_retry_when_max_retries_zero():
    """T5: MAX_TEST_CASE_RETRIES=0 → 单次尝试, 不重试."""
    os.environ["MAX_TEST_CASE_RETRIES"] = "0"
    os.environ["MAX_CONSECUTIVE_FAILURES"] = "3"
    os.environ["MAX_STEPS_PER_CASE"] = "15"

    fail_state = {
        "_collected_steps": [_make_fail_step("fail")],
        "consecutive_failures": 1,
        "current_step": 1,
    }
    call_log = []

    rt = _make_runtime_instance()

    with patch("core.runtime.build_execution_graph", return_value=_make_mock_graph(fail_state, call_log)), \
         patch("core.runtime.log_test_result", new_callable=AsyncMock), \
         patch("core.runtime.log_step", new_callable=AsyncMock), \
         patch("core.runtime.generate_case_summary", new_callable=AsyncMock, return_value={"case_id": "TC-R001", "summary": ""}), \
         patch("core.runtime.execute_setup", new_callable=AsyncMock):

        result = await rt._execute_test_case(
            index=0,
            test_case=_make_test_case(),
            test_plan=[_make_test_case()],
            setups={},
        )

    # 不重试 → 仍然 failed (不是 human_review_required, 因为没达到 max_retries+1 次)
    assert result.status == "failed"
    assert result.retry_count == 0
    assert result.failure_context == []
    assert len(call_log) == 1


@pytest.mark.asyncio
async def test_capture_failure_context_has_a11y_tree():
    """T6: _capture_failure_context 包含 a11y tree 和 screenshot."""
    rt = _make_runtime_instance()

    steps = [_make_fail_step("元素被遮挡")]
    ctx = await rt._capture_failure_context(rt.page, steps, attempt=1)

    assert ctx["attempt"] == 1
    assert ctx["failed_step_index"] == 0
    assert ctx["failed_action"] == "click"
    assert ctx["assertion_status"] == "fail"
    assert "元素被遮挡" in ctx["assertion_reasoning"]
    assert "screenshot_path" in ctx
    assert "a11y_tree" in ctx
    assert ctx["url_after"] == "https://app.com/page"
