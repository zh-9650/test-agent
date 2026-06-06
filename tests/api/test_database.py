"""
tests/api/test_database.py — Database model and connection tests.

TDD tests for SQLAlchemy models, auto-init, CRUD, and relationships.
Uses a separate test database (smart_test_test) created and dropped per session.

All async tests are wrapped in a single event loop to avoid asyncpg
session/connection lifecycle issues with pytest-asyncio.
"""

import asyncio
import os
from datetime import datetime

import pytest
from sqlalchemy import text

# Ensure DATABASE_URL points to test DB before importing app code
os.environ["DATABASE_URL"] = "postgresql://postgres:123456@localhost:5432/smart_test_test"

from database.models import Base, Task, TaskStep, Report

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
# Helper
# ---------------------------------------------------------------------------

async def _get_session():
    """Yield an async session wrapped in an async context manager."""
    from database.connection import async_session
    async with async_session() as session:
        return session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_task_model_instantiation():
    """Test that Task model can be instantiated with valid data."""
    task = Task(
        task_name="Login Test",
        target_url="http://example.com/login",
        status="pending",
        config={"rules": ["rule1"], "credentials": {"user": "admin"}},
        total_tests=0,
        passed_tests=0,
        failed_tests=0,
    )
    assert task.task_name == "Login Test"
    assert task.target_url == "http://example.com/login"
    assert task.status == "pending"
    assert task.config == {"rules": ["rule1"], "credentials": {"user": "admin"}}
    assert task.total_tests == 0


def test_create_all_creates_tables():
    """Test that create_all() creates all 3 tables: task, task_step, report."""
    from database.connection import create_async_engine_instance

    async def _test():
        engine = create_async_engine_instance(os.environ["DATABASE_URL"])
        async with engine.connect() as conn:
            result = await conn.execute(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            ))
            tables = {row[0] for row in result.fetchall()}
        await engine.dispose()
        assert "task" in tables
        assert "task_step" in tables
        assert "report" in tables

    asyncio.get_event_loop().run_until_complete(_test())


def test_task_step_phase1_columns_exist():
    """Startup schema compatibility keeps additive TaskStep columns available."""
    from database.connection import create_async_engine_instance

    async def _test():
        engine = create_async_engine_instance(os.environ["DATABASE_URL"])
        async with engine.connect() as conn:
            result = await conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'task_step'"
            ))
            columns = {row[0] for row in result.fetchall()}
        await engine.dispose()
        assert {"test_case_status", "retry_count", "failure_context"} <= columns

    asyncio.get_event_loop().run_until_complete(_test())


def test_crud_create_task():
    """Test creating a task and reading it back."""
    from database.connection import async_session

    async def _test():
        async with async_session() as db_session:
            task = Task(
                task_name="CRUD Test",
                target_url="http://example.com",
                status="running",
                config={"key": "value"},
                total_tests=5,
                passed_tests=2,
                failed_tests=1,
            )
            db_session.add(task)
            await db_session.commit()
            await db_session.refresh(task)

            assert task.id is not None
            assert task.created_at is not None

            result = await db_session.get(Task, task.id)
            assert result is not None
            assert result.task_name == "CRUD Test"
            assert result.status == "running"
            assert result.config == {"key": "value"}

    asyncio.get_event_loop().run_until_complete(_test())


def test_crud_add_steps_and_query_by_task_id():
    """Test adding task steps and querying steps by task_id."""
    from database.connection import async_session

    async def _test():
        async with async_session() as db_session:
            task = Task(
                task_name="Step Test",
                target_url="http://example.com",
                status="running",
            )
            db_session.add(task)
            await db_session.commit()
            await db_session.refresh(task)

            step1 = TaskStep(
                task_id=task.id,
                test_case_id="TC-001",
                step_index=0,
                action_type="click",
                action_target="#login-button",
                action_args={"wait_for": "navigation"},
                result="Clicked login button",
                assertion_result={"status": "pass", "reasoning": "Login succeeded"},
            )
            step2 = TaskStep(
                task_id=task.id,
                test_case_id="TC-001",
                step_index=1,
                action_type="input_text",
                action_target="#username",
                action_args={"text": "admin"},
                result="Entered username",
            )
            db_session.add_all([step1, step2])
            await db_session.commit()

            result = await db_session.execute(
                text("SELECT * FROM task_step WHERE task_id = :tid"),
                {"tid": task.id},
            )
            rows = result.fetchall()
            assert len(rows) == 2

    asyncio.get_event_loop().run_until_complete(_test())


def test_foreign_key_relationships():
    """Test that foreign key relationships (task.steps, task.reports) work."""
    from database.connection import async_session

    async def _test():
        async with async_session() as db_session:
            task = Task(
                task_name="Relationship Test",
                target_url="http://example.com",
                status="completed",
            )
            db_session.add(task)
            await db_session.commit()
            await db_session.refresh(task)

            step = TaskStep(
                task_id=task.id,
                test_case_id="TC-002",
                step_index=0,
                action_type="navigate",
                action_target="http://example.com/dashboard",
            )
            report = Report(
                task_id=task.id,
                report_path="/reports/test_report.html",
                summary="All tests passed successfully.",
            )
            db_session.add_all([step, report])
            await db_session.commit()

            await db_session.refresh(task, attribute_names=["steps", "reports"])

            assert len(task.steps) == 1
            assert task.steps[0].action_type == "navigate"
            assert len(task.reports) == 1
            assert task.reports[0].summary == "All tests passed successfully."

    asyncio.get_event_loop().run_until_complete(_test())


def test_task_plan_jsonb():
    """Test that test_plan JSONB column stores and retrieves data correctly."""
    from database.connection import async_session

    async def _test():
        async with async_session() as db_session:
            plan = [
                {"id": "TC-001", "title": "Login", "steps": ["open page", "enter credentials"]},
                {"id": "TC-002", "title": "Logout", "steps": ["click logout", "confirm"]},
            ]
            task = Task(
                task_name="Plan Test",
                target_url="http://example.com",
                status="pending",
                test_plan=plan,
            )
            db_session.add(task)
            await db_session.commit()
            await db_session.refresh(task)

            fetched = await db_session.get(Task, task.id)
            assert fetched.test_plan == plan

    asyncio.get_event_loop().run_until_complete(_test())


def test_timestamps_are_timezone_aware():
    """Test that created_at and other timestamps are timezone-aware."""
    from database.connection import async_session

    async def _test():
        async with async_session() as db_session:
            task = Task(task_name="Timestamp Test", target_url="http://example.com")
            db_session.add(task)
            await db_session.commit()
            await db_session.refresh(task)

            assert task.created_at is not None
            assert task.created_at.tzinfo is not None

    asyncio.get_event_loop().run_until_complete(_test())
