"""Tests for core/runtime.py (TDD)

Tests the Runtime orchestrator with mocked external dependencies.
No real LLM or browser calls in unit tests.
"""

import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.interfaces import AssertionResult, ChangeReport, Setup, StepResult, TestCase, TestResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_TEST_CASE_1 = TestCase(
    id="TC-001",
    title="登录成功测试",
    description="验证用户可以正常登录系统",
    preconditions=["login_as_test"],
    steps=["打开登录页面", "输入用户名", "输入密码", "点击登录按钮"],
    expected="成功登录并跳转到主页",
    priority="high",
    category="functional",
)

SAMPLE_TEST_CASE_2 = TestCase(
    id="TC-002",
    title="导航栏测试",
    description="验证导航栏可以正常使用",
    preconditions=["login_as_test"],
    steps=["点击导航栏菜单", "验证页面跳转"],
    expected="页面正常跳转",
    priority="medium",
    category="functional",
)

SAMPLE_SETUP = Setup(id="login_as_test", description="以测试用户登录系统")

BASIC_TASK_CONFIG = {
    "task_id": "task-rt-001",
    "target_url": "http://example.com/login",
    "accounts": [{"role": "test", "username": "test_c", "password": "123456"}],
}


# ---------------------------------------------------------------------------
# test_runtime_init
# ---------------------------------------------------------------------------


def test_runtime_init():
    """Runtime initializes with task_config, sets attributes correctly."""
    from core.runtime import Runtime

    rt = Runtime(BASIC_TASK_CONFIG)

    assert rt.task_id == "task-rt-001"
    assert rt.target_url == "http://example.com/login"
    assert rt.task_config == BASIC_TASK_CONFIG
    assert rt.browser is None
    assert rt.context is None
    assert rt.page is None
    assert rt._playwright is None
    assert rt._checkpointer is None


def test_runtime_init_generates_uuid_if_missing():
    """Runtime generates a UUID task_id if not provided in task_config."""
    from core.runtime import Runtime

    config = {"target_url": "http://example.com/login"}
    rt = Runtime(config)

    assert rt.task_id  # not empty
    assert len(rt.task_id) > 0


# ---------------------------------------------------------------------------
# test_empty_test_plan
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_test_plan():
    """Planning returns empty test_plan -> run returns empty results."""
    from core.runtime import Runtime

    rt = Runtime(BASIC_TASK_CONFIG)

    # Mock _launch_browser and _close_browser to avoid real browser
    rt._launch_browser = AsyncMock()
    rt._close_browser = AsyncMock()

    # Mock planning graph to return empty test_plan
    mock_planning_graph = MagicMock()
    mock_planning_graph.ainvoke = AsyncMock(return_value={
        "test_plan": [],
        "setups": {},
        "messages": [],
    })

    with patch("core.runtime.build_planning_graph", return_value=mock_planning_graph):
        results = await rt.run()

    assert results == []
    rt._launch_browser.assert_called_once()
    rt._close_browser.assert_called_once()


# ---------------------------------------------------------------------------
# test_run_full_session_mock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_full_session_mock():
    """Mock both graphs -> runs full session, returns results for all test cases."""
    from core.runtime import Runtime

    rt = Runtime(BASIC_TASK_CONFIG)

    rt._launch_browser = AsyncMock()
    rt._close_browser = AsyncMock()

    # Mock planning graph
    mock_planning_graph = MagicMock()
    mock_planning_graph.ainvoke = AsyncMock(return_value={
        "test_plan": [SAMPLE_TEST_CASE_1, SAMPLE_TEST_CASE_2],
        "setups": {"login_as_test": SAMPLE_SETUP},
        "messages": [],
    })

    # Mock execution graph
    mock_execution_graph = MagicMock()
    mock_execution_graph.ainvoke = AsyncMock(return_value={
        "messages": [],
        "test_plan": [SAMPLE_TEST_CASE_1, SAMPLE_TEST_CASE_2],
        "setups": {"login_as_test": SAMPLE_SETUP},
        "current_index": 0,
        "current_step": 5,
        "results": [],
        "consecutive_failures": 0,
        "page_info": {},
        "screenshot": "",
        "state_before": {},
        "state_after": {},
        "task_id": "task-rt-001",
        "task_config": BASIC_TASK_CONFIG,
    })

    # Mock execute_setup (the setup_manager)
    mock_setup_result_state = {
        "messages": [],
        "test_plan": [],
        "setups": {},
        "current_index": 0,
        "current_step": 0,
        "results": [],
        "consecutive_failures": 0,
        "page_info": {},
        "screenshot": "",
        "state_before": {},
        "state_after": {},
        "task_id": "task-rt-001",
        "task_config": BASIC_TASK_CONFIG,
    }

    with patch("core.runtime.build_planning_graph", return_value=mock_planning_graph), \
         patch("core.runtime.build_execution_graph", return_value=mock_execution_graph), \
         patch("core.runtime.execute_setup", new_callable=AsyncMock, return_value=mock_setup_result_state), \
         patch("core.runtime.set_current_page") as mock_set_page:

        results = await rt.run()

    assert len(results) == 2
    assert results[0].test_case_id == "TC-001"
    assert results[1].test_case_id == "TC-002"
    # Both should be "passed" since consecutive_failures = 0 and no failing assertions
    assert results[0].status == "passed"
    assert results[1].status == "passed"
    rt._launch_browser.assert_called_once()
    rt._close_browser.assert_called_once()


# ---------------------------------------------------------------------------
# test_execute_test_case_mock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_test_case_mock():
    """Mock execution graph -> returns TestResult for a single test case."""
    from core.runtime import Runtime

    rt = Runtime(BASIC_TASK_CONFIG)
    rt._launch_browser = AsyncMock()
    rt.page = MagicMock()  # pretend browser is already launched

    # Mock execution graph to return a state with some steps
    mock_execution_graph = MagicMock()
    mock_execution_graph.ainvoke = AsyncMock(return_value={
        "messages": [],
        "test_plan": [SAMPLE_TEST_CASE_1],
        "setups": {"login_as_test": SAMPLE_SETUP},
        "current_index": 0,
        "current_step": 4,
        "results": [],
        "consecutive_failures": 0,
        "page_info": {},
        "screenshot": "",
        "state_before": {},
        "state_after": {},
        "task_id": "task-rt-001",
        "task_config": BASIC_TASK_CONFIG,
        "_collected_steps": [],
    })

    with patch("core.runtime.build_execution_graph", return_value=mock_execution_graph), \
         patch("core.runtime.execute_setup", new_callable=AsyncMock) as mock_setup, \
         patch.dict(os.environ, {"MAX_CONSECUTIVE_FAILURES": "3", "MAX_STEPS_PER_CASE": "15"}):

        result = await rt._execute_test_case(
            index=0,
            test_case=SAMPLE_TEST_CASE_1,
            test_plan=[SAMPLE_TEST_CASE_1],
            setups={"login_as_test": SAMPLE_SETUP},
        )

    assert isinstance(result, TestResult)
    assert result.test_case_id == "TC-001"
    assert result.status == "passed"
    assert result.duration_seconds > 0


# ---------------------------------------------------------------------------
# test_execute_test_case_failed_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_test_case_failed_status():
    """When consecutive_failures >= threshold, result status is 'failed'."""
    from core.runtime import Runtime

    rt = Runtime(BASIC_TASK_CONFIG)
    rt.page = MagicMock()

    mock_execution_graph = MagicMock()
    mock_execution_graph.ainvoke = AsyncMock(return_value={
        "messages": [],
        "test_plan": [SAMPLE_TEST_CASE_1],
        "setups": {},
        "current_index": 0,
        "current_step": 5,
        "results": [],
        "consecutive_failures": 3,  # >= threshold
        "page_info": {},
        "screenshot": "",
        "state_before": {},
        "state_after": {},
        "task_id": "task-rt-001",
        "task_config": BASIC_TASK_CONFIG,
        "_collected_steps": [],
    })

    with patch("core.runtime.build_execution_graph", return_value=mock_execution_graph), \
         patch("core.runtime.execute_setup", new_callable=AsyncMock), \
         patch.dict(os.environ, {"MAX_CONSECUTIVE_FAILURES": "3", "MAX_STEPS_PER_CASE": "15"}):

        result = await rt._execute_test_case(
            index=0,
            test_case=SAMPLE_TEST_CASE_1,
            test_plan=[SAMPLE_TEST_CASE_1],
            setups={},
        )

    assert result.status == "failed"


# ---------------------------------------------------------------------------
# test_execute_test_case_incomplete_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_test_case_incomplete_status():
    """When current_step >= MAX_STEPS_PER_CASE, result status is 'incomplete'."""
    from core.runtime import Runtime

    rt = Runtime(BASIC_TASK_CONFIG)
    rt.page = MagicMock()

    mock_execution_graph = MagicMock()
    mock_execution_graph.ainvoke = AsyncMock(return_value={
        "messages": [],
        "test_plan": [SAMPLE_TEST_CASE_1],
        "setups": {},
        "current_index": 0,
        "current_step": 15,  # >= max steps
        "results": [],
        "consecutive_failures": 0,
        "page_info": {},
        "screenshot": "",
        "state_before": {},
        "state_after": {},
        "task_id": "task-rt-001",
        "task_config": BASIC_TASK_CONFIG,
        "_collected_steps": [],
    })

    with patch("core.runtime.build_execution_graph", return_value=mock_execution_graph), \
         patch("core.runtime.execute_setup", new_callable=AsyncMock), \
         patch.dict(os.environ, {"MAX_CONSECUTIVE_FAILURES": "3", "MAX_STEPS_PER_CASE": "15"}):

        result = await rt._execute_test_case(
            index=0,
            test_case=SAMPLE_TEST_CASE_1,
            test_plan=[SAMPLE_TEST_CASE_1],
            setups={},
        )

    assert result.status == "incomplete"


# ---------------------------------------------------------------------------
# test_execute_test_case_failing_assertion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_test_case_failing_assertion():
    """When a step has a failing assertion, result status is 'failed'."""
    from core.runtime import Runtime

    rt = Runtime(BASIC_TASK_CONFIG)
    rt.page = MagicMock()

    failing_step = StepResult(
        step_index=2,
        action_type="click",
        action_target="#3",
        result="点击失败",
        assertion=AssertionResult(status="fail", reasoning="按钮不存在"),
    )

    mock_execution_graph = MagicMock()
    mock_execution_graph.ainvoke = AsyncMock(return_value={
        "messages": [],
        "test_plan": [SAMPLE_TEST_CASE_1],
        "setups": {},
        "current_index": 0,
        "current_step": 5,
        "results": [],
        "consecutive_failures": 0,
        "page_info": {},
        "screenshot": "",
        "state_before": {},
        "state_after": {},
        "task_id": "task-rt-001",
        "task_config": BASIC_TASK_CONFIG,
        "_collected_steps": [failing_step],
    })

    with patch("core.runtime.build_execution_graph", return_value=mock_execution_graph), \
         patch("core.runtime.execute_setup", new_callable=AsyncMock), \
         patch.dict(os.environ, {"MAX_CONSECUTIVE_FAILURES": "3", "MAX_STEPS_PER_CASE": "15"}):

        result = await rt._execute_test_case(
            index=0,
            test_case=SAMPLE_TEST_CASE_1,
            test_plan=[SAMPLE_TEST_CASE_1],
            setups={},
        )

    assert result.status == "failed"


# ---------------------------------------------------------------------------
# test_browser_crash_recovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_browser_crash_recovery():
    """Mock browser crash -> recovers, continues with remaining test cases."""
    from core.runtime import Runtime

    rt = Runtime(BASIC_TASK_CONFIG)
    rt._launch_browser = AsyncMock()
    rt._close_browser = AsyncMock()

    # Mock planning graph
    mock_planning_graph = MagicMock()
    mock_planning_graph.ainvoke = AsyncMock(return_value={
        "test_plan": [SAMPLE_TEST_CASE_1, SAMPLE_TEST_CASE_2],
        "setups": {"login_as_test": SAMPLE_SETUP},
        "messages": [],
    })

    # First execution call crashes, second succeeds
    crash_exc = RuntimeError("Browser crashed")
    mock_execution_graph = MagicMock()

    # First invocation crashes (for TC-001)
    # Second invocation succeeds (for TC-002)
    success_result = {
        "messages": [],
        "test_plan": [SAMPLE_TEST_CASE_2],
        "setups": {"login_as_test": SAMPLE_SETUP},
        "current_index": 1,
        "current_step": 3,
        "results": [],
        "consecutive_failures": 0,
        "page_info": {},
        "screenshot": "",
        "state_before": {},
        "state_after": {},
        "task_id": "task-rt-001",
        "task_config": BASIC_TASK_CONFIG,
        "_collected_steps": [],
    }

    # TC-001 execution raises, TC-002 succeeds
    mock_execution_graph.ainvoke = AsyncMock(side_effect=[crash_exc, success_result])

    with patch("core.runtime.build_planning_graph", return_value=mock_planning_graph), \
         patch("core.runtime.build_execution_graph", return_value=mock_execution_graph), \
         patch("core.runtime.execute_setup", new_callable=AsyncMock), \
         patch.dict(os.environ, {"MAX_CONSECUTIVE_FAILURES": "3", "MAX_STEPS_PER_CASE": "15"}):

        results = await rt.run()

    # TC-001 should be 'failed' (crash recovery), TC-002 should be 'passed'
    assert len(results) == 2
    assert results[0].status == "failed"
    assert results[0].test_case_id == "TC-001"
    assert results[1].status == "passed"
    assert results[1].test_case_id == "TC-002"


# ---------------------------------------------------------------------------
# test_browser_lifecycle_mock
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_browser_lifecycle_mock():
    """_launch_browser and _close_browser are called in run()."""
    from core.runtime import Runtime

    rt = Runtime(BASIC_TASK_CONFIG)

    # Mock everything so browser isn't actually launched
    mock_planning_graph = MagicMock()
    mock_planning_graph.ainvoke = AsyncMock(return_value={
        "test_plan": [],
        "setups": {},
        "messages": [],
    })

    mock_pw = MagicMock()
    mock_browser = MagicMock()
    mock_context = MagicMock()
    mock_page = MagicMock()

    mock_pw.start = AsyncMock(return_value=mock_pw)
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.tracing.start = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_context.tracing.stop = AsyncMock()
    mock_context.close = AsyncMock()
    mock_browser.close = AsyncMock()
    mock_pw.stop = AsyncMock()

    with patch("core.runtime.async_playwright", return_value=mock_pw), \
         patch("core.runtime.build_planning_graph", return_value=mock_planning_graph), \
         patch("core.runtime.set_current_page") as mock_set_page:

        results = await rt.run()

    # Verify browser was launched and closed
    mock_pw.start.assert_called_once()
    mock_pw.chromium.launch.assert_called_once()
    mock_browser.new_context.assert_called_once()
    mock_context.new_page.assert_called_once()
    mock_page.goto.assert_called_once_with("http://example.com/login", wait_until="networkidle", timeout=30000)
    mock_context.tracing.start.assert_called_once()
    mock_context.tracing.stop.assert_called_once()
    mock_context.close.assert_called_once()
    mock_browser.close.assert_called_once()
    mock_pw.stop.assert_called_once()
    mock_set_page.assert_called_once_with(mock_page)


# ---------------------------------------------------------------------------
# test_run_stream_yields_updates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_stream_yields_updates():
    """run_stream yields WebSocket-compatible dicts."""
    from core.runtime import Runtime

    rt = Runtime(BASIC_TASK_CONFIG)
    rt._launch_browser = AsyncMock()
    rt._close_browser = AsyncMock()

    # Mock planning graph
    mock_planning_graph = MagicMock()
    mock_planning_graph.ainvoke = AsyncMock(return_value={
        "test_plan": [SAMPLE_TEST_CASE_1],
        "setups": {"login_as_test": SAMPLE_SETUP},
        "messages": [],
    })

    # Mock _execute_test_case_stream to yield a test_case_complete update
    async def mock_execute_stream(index, test_case, test_plan, setups):
        yield {
            "type": "test_case_complete",
            "test_case_id": test_case.id,
            "step_index": 0,
            "data": {"status": "passed", "summary": "通过: 登录成功测试", "duration": 5.0},
            "timestamp": "2026-05-28T00:00:00+00:00",
        }

    with patch("core.runtime.build_planning_graph", return_value=mock_planning_graph), \
         patch.object(rt, "_execute_test_case_stream", side_effect=mock_execute_stream):

        updates = []
        async for update in rt.run_stream():
            updates.append(update)

    # Should have: planning_complete + test_case_complete for TC-001
    assert len(updates) >= 2

    # Check planning_complete message
    planning_update = updates[0]
    assert planning_update["type"] == "session_complete"
    assert planning_update["data"]["phase"] == "planning_complete"
    assert planning_update["data"]["total_tests"] == 1

    # Check test_case_complete message
    tc_update = updates[1]
    assert tc_update["type"] == "test_case_complete"
    assert tc_update["test_case_id"] == "TC-001"
    assert tc_update["data"]["status"] == "passed"


# ---------------------------------------------------------------------------
# test_run_stream_error_handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_stream_error_handling():
    """run_stream yields error update when planning fails."""
    from core.runtime import Runtime

    rt = Runtime(BASIC_TASK_CONFIG)
    rt._launch_browser = AsyncMock()
    rt._close_browser = AsyncMock()

    # Mock planning graph to raise exception
    mock_planning_graph = MagicMock()
    mock_planning_graph.ainvoke = AsyncMock(side_effect=RuntimeError("Planning failed"))

    with patch("core.runtime.build_planning_graph", return_value=mock_planning_graph):
        updates = []
        async for update in rt.run_stream():
            updates.append(update)

    # Should yield an error session_complete
    assert len(updates) == 1
    assert updates[0]["type"] == "session_complete"
    assert "error" in updates[0]["data"]
    assert "Planning failed" in updates[0]["data"]["error"]


# ---------------------------------------------------------------------------
# test_handle_browser_crash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_browser_crash():
    """_handle_browser_crash closes old browser, launches new one, returns error state."""
    from core.runtime import Runtime

    rt = Runtime(BASIC_TASK_CONFIG)

    state = {
        "messages": [],
        "test_plan": [SAMPLE_TEST_CASE_1],
        "current_index": 0,
        "current_step": 3,
        "consecutive_failures": 0,
    }

    # Mock _close_browser and _launch_browser
    rt._close_browser = AsyncMock()
    rt._launch_browser = AsyncMock()

    with patch.dict(os.environ, {"MAX_CONSECUTIVE_FAILURES": "3"}):
        result_state = await rt._handle_browser_crash(SAMPLE_TEST_CASE_1, state)

    rt._close_browser.assert_called_once()
    rt._launch_browser.assert_called_once()
    assert result_state["consecutive_failures"] == 3  # hit the threshold
    assert result_state["_collected_steps"] == []


# ---------------------------------------------------------------------------
# test_now_iso
# ---------------------------------------------------------------------------


def test_now_iso():
    """_now_iso returns a valid ISO format string."""
    from core.runtime import _now_iso

    result = _now_iso()
    assert isinstance(result, str)
    assert len(result) > 0
    # Should contain a date pattern like 2026-05-28
    assert "2026" in result or "2025" in result


# ---------------------------------------------------------------------------
# test_run_preserves_partial_results_on_error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_preserves_partial_results_on_error():
    """When execution fails mid-session, partial results are still returned."""
    from core.runtime import Runtime

    rt = Runtime(BASIC_TASK_CONFIG)
    rt._launch_browser = AsyncMock()
    rt._close_browser = AsyncMock()

    # Mock planning graph to return 2 test cases
    mock_planning_graph = MagicMock()
    mock_planning_graph.ainvoke = AsyncMock(return_value={
        "test_plan": [SAMPLE_TEST_CASE_1, SAMPLE_TEST_CASE_2],
        "setups": {},
        "messages": [],
    })

    # TC-001 succeeds, TC-002 crashes
    crash_exc = RuntimeError("Unexpected crash during TC-002")

    success_result_state = {
        "messages": [],
        "test_plan": [SAMPLE_TEST_CASE_1, SAMPLE_TEST_CASE_2],
        "setups": {},
        "current_index": 0,
        "current_step": 4,
        "results": [],
        "consecutive_failures": 0,
        "page_info": {},
        "screenshot": "",
        "state_before": {},
        "state_after": {},
        "task_id": "task-rt-001",
        "task_config": BASIC_TASK_CONFIG,
        "_collected_steps": [],
    }

    mock_execution_graph = MagicMock()
    # First invocation succeeds, second raises (will be caught by crash handler)
    mock_execution_graph.ainvoke = AsyncMock(side_effect=[success_result_state, crash_exc])

    with patch("core.runtime.build_planning_graph", return_value=mock_planning_graph), \
         patch("core.runtime.build_execution_graph", return_value=mock_execution_graph), \
         patch("core.runtime.execute_setup", new_callable=AsyncMock), \
         patch.dict(os.environ, {"MAX_CONSECUTIVE_FAILURES": "3", "MAX_STEPS_PER_CASE": "15"}):

        results = await rt.run()

    # TC-001 should be passed, TC-002 should be failed (crash recovery)
    assert len(results) == 2
    assert results[0].test_case_id == "TC-001"
    assert results[0].status == "passed"
    assert results[1].test_case_id == "TC-002"
    assert results[1].status == "failed"


# ---------------------------------------------------------------------------
# test_execute_test_case_with_setup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_test_case_with_setup():
    """When test case has preconditions, setups are executed before the test case."""
    from core.runtime import Runtime

    rt = Runtime(BASIC_TASK_CONFIG)
    rt.page = MagicMock()

    mock_execution_graph = MagicMock()
    mock_execution_graph.ainvoke = AsyncMock(return_value={
        "messages": [],
        "test_plan": [SAMPLE_TEST_CASE_1],
        "setups": {"login_as_test": SAMPLE_SETUP},
        "current_index": 0,
        "current_step": 4,
        "results": [],
        "consecutive_failures": 0,
        "page_info": {},
        "screenshot": "",
        "state_before": {},
        "state_after": {},
        "task_id": "task-rt-001",
        "task_config": BASIC_TASK_CONFIG,
        "_collected_steps": [],
    })

    mock_setup_return = {
        "messages": [],
        "test_plan": [],
        "setups": {},
        "current_index": 0,
        "current_step": 0,
        "results": [],
        "consecutive_failures": 0,
        "page_info": {},
        "screenshot": "",
        "state_before": {},
        "state_after": {},
        "task_id": "task-rt-001",
        "task_config": BASIC_TASK_CONFIG,
    }

    with patch("core.runtime.build_execution_graph", return_value=mock_execution_graph), \
         patch("core.runtime.execute_setup", new_callable=AsyncMock, return_value=mock_setup_return) as mock_setup, \
         patch.dict(os.environ, {"MAX_CONSECUTIVE_FAILURES": "3", "MAX_STEPS_PER_CASE": "15"}):

        result = await rt._execute_test_case(
            index=0,
            test_case=SAMPLE_TEST_CASE_1,
            test_plan=[SAMPLE_TEST_CASE_1],
            setups={"login_as_test": SAMPLE_SETUP},
        )

    # Setup should have been called for login_as_test precondition
    mock_setup.assert_called_once()
    assert result.test_case_id == "TC-001"


# ---------------------------------------------------------------------------
# test_data_directory_creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_data_directory_creation():
    """_launch_browser creates the data/sessions/<task_id> directory."""
    from core.runtime import Runtime

    rt = Runtime({"task_id": "dir-test-001", "target_url": "http://example.com/login"})

    mock_pw = MagicMock()
    mock_browser = MagicMock()
    mock_context = MagicMock()
    mock_page = MagicMock()

    mock_pw_instance = MagicMock()
    mock_pw_instance.start = AsyncMock(return_value=mock_pw_instance)
    mock_pw_instance.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.tracing.start = AsyncMock()
    mock_page.goto = AsyncMock()

    with patch("core.runtime.async_playwright", return_value=mock_pw_instance), \
         patch("core.runtime.set_current_page"), \
         patch("os.makedirs") as mock_makedirs:

        await rt._launch_browser()

    expected_dir = os.path.join("data", "sessions", "dir-test-001")
    mock_makedirs.assert_called_once_with(expected_dir, exist_ok=True)