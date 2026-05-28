"""Tests for core/execution_logger.py and core/report_builder.py (TDD)

Covers logging to database and report generation.
Uses the same test database setup pattern as tests/api/test_database.py.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

# Ensure DATABASE_URL points to test DB before importing app code
os.environ["DATABASE_URL"] = "postgresql://postgres:123456@localhost:5432/smart_test_test"

from database.models import Base, Task, TaskStep
from core.interfaces import TestCase, TestResult, StepResult, AssertionResult, ChangeReport

# ---------------------------------------------------------------------------
# Session-scoped setup / teardown
# ---------------------------------------------------------------------------

def setup_module():
    """Create test database and tables before running any tests."""
    from sqlalchemy import create_engine
    from urllib.parse import urlparse
    from database.connection import create_async_engine_instance

    db_url = os.environ["DATABASE_URL"]
    parsed = urlparse(db_url)
    db_name = parsed.path.lstrip("/")
    admin_url = f"{parsed.scheme}://{parsed.username}:{parsed.password}@{parsed.hostname}:{parsed.port or 5432}/postgres"

    # Create test database if not exists
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        result = conn.execute(
            text(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'")
        )
        if not result.scalar():
            conn.execute(text(f"CREATE DATABASE {db_name}"))
    admin_engine.dispose()

    # Create tables using async engine
    async def _create_tables():
        engine = create_async_engine_instance(db_url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()
    asyncio.get_event_loop().run_until_complete(_create_tables())


def teardown_module():
    """Drop the test database after all tests finish."""
    from sqlalchemy import create_engine
    from urllib.parse import urlparse

    db_url = os.environ["DATABASE_URL"]
    parsed = urlparse(db_url)
    db_name = parsed.path.lstrip("/")
    admin_url = f"{parsed.scheme}://{parsed.username}:{parsed.password}@{parsed.hostname}:{parsed.port or 5432}/postgres"

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(
            text(f"""
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = '{db_name}' AND pid <> pg_backend_pid()
            """)
        )
        conn.execute(text(f"DROP DATABASE IF EXISTS {db_name}"))
    admin_engine.dispose()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_task_id_map():
    """Reset the internal task_id map before each test."""
    from core import execution_logger
    execution_logger._task_id_map.clear()
    yield


@pytest.fixture(autouse=True)
def _cleanup_reports():
    """Clean up report directories after each test."""
    yield
    # Cleanup report directories
    reports_dir = Path("data/reports")
    if reports_dir.exists():
        shutil.rmtree(reports_dir)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_TEST_CASE = TestCase(
    id="TC-001",
    title="Login Test",
    description="Verify user can login",
    preconditions=[],
    steps=["Open login page", "Enter credentials", "Click login"],
    expected="User is logged in",
    priority="high",
    category="functional",
)

SAMPLE_STEP = StepResult(
    step_index=0,
    action_type="click",
    action_target="#login-button",
    action_args={"wait_for": "navigation"},
    result="Clicked login button",
    screenshot_path="data/screenshots/test.png",
    change_report=ChangeReport(
        url_changed=True,
        url_before="http://example.com/login",
        url_after="http://example.com/dashboard",
    ),
    assertion=AssertionResult(status="pass", reasoning="Login succeeded"),
    thought="I should click the login button",
)

SAMPLE_TEST_RESULT_PASSED = TestResult(
    test_case_id="TC-001",
    status="passed",
    steps=[SAMPLE_STEP],
    summary="Login test passed",
    duration_seconds=5.0,
)

SAMPLE_TEST_RESULT_FAILED = TestResult(
    test_case_id="TC-002",
    status="failed",
    steps=[],
    summary="Login test failed",
    duration_seconds=3.0,
)


# ---------------------------------------------------------------------------
# Test: log_task_created
# ---------------------------------------------------------------------------

def test_log_task_created():
    """log_task_created creates a Task record in the database."""
    from core.execution_logger import log_task_created
    from database.connection import async_session

    async def _test():
        await log_task_created(
            task_id="task-abc-123",
            task_name="Login Suite",
            target_url="http://example.com/login",
            config={"browser": "chromium", "headless": True},
        )

        async with async_session() as session:
            result = await session.execute(
                text("SELECT task_name, target_url, status FROM task WHERE task_name = 'Login Suite'")
            )
            row = result.fetchone()
            assert row is not None
            assert row.task_name == "Login Suite"
            assert row.target_url == "http://example.com/login"
            assert row.status == "pending"

    asyncio.get_event_loop().run_until_complete(_test())


# ---------------------------------------------------------------------------
# Test: log_test_plan
# ---------------------------------------------------------------------------

def test_log_test_plan():
    """log_test_plan updates the task's test_plan and total_tests."""
    from core.execution_logger import log_task_created, log_test_plan
    from database.connection import async_session

    async def _test():
        await log_task_created(
            task_id="task-plan-001",
            task_name="Plan Test",
            target_url="http://example.com",
            config={},
        )

        test_plan = [SAMPLE_TEST_CASE]
        await log_test_plan(task_id="task-plan-001", test_plan=test_plan)

        async with async_session() as session:
            result = await session.execute(
                text("SELECT test_plan, total_tests FROM task WHERE task_name = 'Plan Test'")
            )
            row = result.fetchone()
            assert row is not None
            assert row.total_tests == 1
            assert len(row.test_plan) == 1
            assert row.test_plan[0]["id"] == "TC-001"

    asyncio.get_event_loop().run_until_complete(_test())


# ---------------------------------------------------------------------------
# Test: log_step
# ---------------------------------------------------------------------------

def test_log_step():
    """log_step creates a TaskStep record in the database."""
    from core.execution_logger import log_task_created, log_step
    from database.connection import async_session

    async def _test():
        await log_task_created(
            task_id="task-step-001",
            task_name="Step Test",
            target_url="http://example.com",
            config={},
        )

        await log_step(
            task_id="task-step-001",
            test_case_id="TC-001",
            step=SAMPLE_STEP,
        )

        async with async_session() as session:
            result = await session.execute(
                text("SELECT * FROM task_step WHERE test_case_id = 'TC-001'")
            )
            rows = result.fetchall()
            assert len(rows) == 1
            assert rows[0].action_type == "click"
            assert rows[0].action_target == "#login-button"
            assert rows[0].result == "Clicked login button"

    asyncio.get_event_loop().run_until_complete(_test())


# ---------------------------------------------------------------------------
# Test: log_test_result_updates_counts
# ---------------------------------------------------------------------------

def test_log_test_result_updates_counts():
    """log_test_result updates passed_tests or failed_tests counts."""
    from core.execution_logger import log_task_created, log_test_result
    from database.connection import async_session

    async def _test():
        await log_task_created(
            task_id="task-result-001",
            task_name="Result Test",
            target_url="http://example.com",
            config={},
        )

        # Log a passed result
        await log_test_result(task_id="task-result-001", result=SAMPLE_TEST_RESULT_PASSED)

        async with async_session() as session:
            result = await session.execute(
                text("SELECT passed_tests, failed_tests FROM task WHERE task_name = 'Result Test'")
            )
            row = result.fetchone()
            assert row is not None
            assert row.passed_tests == 1
            assert row.failed_tests == 0

        # Log a failed result
        await log_test_result(task_id="task-result-001", result=SAMPLE_TEST_RESULT_FAILED)

        async with async_session() as session:
            result = await session.execute(
                text("SELECT passed_tests, failed_tests FROM task WHERE task_name = 'Result Test'")
            )
            row = result.fetchone()
            assert row is not None
            assert row.passed_tests == 1
            assert row.failed_tests == 1

    asyncio.get_event_loop().run_until_complete(_test())


# ---------------------------------------------------------------------------
# Test: get_task_steps
# ---------------------------------------------------------------------------

def test_get_task_steps():
    """get_task_steps returns all steps for a task."""
    from core.execution_logger import log_task_created, log_step, get_task_steps

    async def _test():
        await log_task_created(
            task_id="task-get-steps-001",
            task_name="Get Steps Test",
            target_url="http://example.com",
            config={},
        )

        step1 = StepResult(step_index=0, action_type="navigate", action_target="http://example.com")
        step2 = StepResult(step_index=1, action_type="click", action_target="#btn")

        await log_step(task_id="task-get-steps-001", test_case_id="TC-A", step=step1)
        await log_step(task_id="task-get-steps-001", test_case_id="TC-B", step=step2)

        steps = await get_task_steps(task_id="task-get-steps-001")
        assert len(steps) == 2
        assert steps[0]["action_type"] == "navigate"
        assert steps[1]["action_type"] == "click"

    asyncio.get_event_loop().run_until_complete(_test())


# ---------------------------------------------------------------------------
# Test: get_task_steps_filtered
# ---------------------------------------------------------------------------

def test_get_task_steps_filtered():
    """get_task_steps filtered by test_case_id returns only matching steps."""
    from core.execution_logger import log_task_created, log_step, get_task_steps

    async def _test():
        await log_task_created(
            task_id="task-filter-001",
            task_name="Filter Test",
            target_url="http://example.com",
            config={},
        )

        step1 = StepResult(step_index=0, action_type="navigate", action_target="http://example.com")
        step2 = StepResult(step_index=0, action_type="click", action_target="#btn")

        await log_step(task_id="task-filter-001", test_case_id="TC-A", step=step1)
        await log_step(task_id="task-filter-001", test_case_id="TC-B", step=step2)

        steps = await get_task_steps(task_id="task-filter-001", test_case_id="TC-A")
        assert len(steps) == 1
        assert steps[0]["action_type"] == "navigate"
        assert steps[0]["test_case_id"] == "TC-A"

    asyncio.get_event_loop().run_until_complete(_test())


# ---------------------------------------------------------------------------
# Test: report_builder_add_result
# ---------------------------------------------------------------------------

def test_report_builder_add_result():
    """ReportBuilder.add_result accumulates results."""
    from core.report_builder import ReportBuilder

    builder = ReportBuilder(task_id="task-report-001")
    builder.add_result(SAMPLE_TEST_RESULT_PASSED)
    builder.add_result(SAMPLE_TEST_RESULT_FAILED)

    assert len(builder.results) == 2
    assert builder.results[0].test_case_id == "TC-001"
    assert builder.results[1].test_case_id == "TC-002"


# ---------------------------------------------------------------------------
# Test: report_builder_build_html
# ---------------------------------------------------------------------------

def test_report_builder_build_html():
    """ReportBuilder.build_html generates HTML with expected sections."""
    from core.report_builder import ReportBuilder

    builder = ReportBuilder(task_id="task-report-002")
    builder.add_result(SAMPLE_TEST_RESULT_PASSED)
    builder.add_result(SAMPLE_TEST_RESULT_FAILED)

    html = builder.build_html()
    assert "task-report-002" in html
    assert "TC-001" in html
    assert "TC-002" in html
    assert "passed" in html.lower()
    assert "failed" in html.lower()
    assert "Login test passed" in html
    assert "Login test failed" in html
    # Should contain summary stats
    assert "Total" in html
    assert "Passed" in html
    assert "Failed" in html


# ---------------------------------------------------------------------------
# Test: report_builder_save
# ---------------------------------------------------------------------------

def test_report_builder_save():
    """ReportBuilder.save writes HTML file to correct path."""
    from core.report_builder import ReportBuilder

    builder = ReportBuilder(task_id="task-report-003")
    builder.add_result(SAMPLE_TEST_RESULT_PASSED)

    path = builder.save("data/reports/task-report-003/report.html")
    assert os.path.exists("data/reports/task-report-003/report.html")
    assert path == "data/reports/task-report-003/report.html"

    with open("data/reports/task-report-003/report.html", "r", encoding="utf-8") as f:
        content = f.read()
        assert "task-report-003" in content


# ---------------------------------------------------------------------------
# Test: report_builder_generate_summary
# ---------------------------------------------------------------------------

def test_report_builder_generate_summary():
    """ReportBuilder.generate_summary returns a summary string (mocked LLM)."""
    from core.report_builder import ReportBuilder

    builder = ReportBuilder(task_id="task-report-004")

    async def _test():
        with patch("core.report_builder.get_llm_client") as mock_get_llm:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(return_value=AsyncMock(content="测试总结：所有用例执行完毕。"))
            mock_get_llm.return_value = mock_llm

            summary = await builder.generate_summary([SAMPLE_TEST_RESULT_PASSED])

        assert isinstance(summary, str)
        assert "测试总结" in summary

    asyncio.get_event_loop().run_until_complete(_test())
