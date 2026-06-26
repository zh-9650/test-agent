import asyncio
import os
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine, func, select, text

os.environ["DATABASE_URL"] = (
    "postgresql://postgres:123456@localhost:5432/smart_test_test"
)

from core.execution_store import (
    append_task_step,
    create_execution_run,
    fill_cancelled_results,
    fill_failed_results,
    list_case_results,
    upsert_case_result,
)
from core.interfaces import CaseResult
from database.connection import (
    async_session,
    create_async_engine_instance,
)
from database.models import (
    AgentMemory,
    Base,
    CaseResultRecord,
    ExecutionRunRecord,
    Task,
    TaskStep,
)


def _admin_urls() -> tuple[str, str]:
    parsed = urlparse(os.environ["DATABASE_URL"])
    name = parsed.path.lstrip("/")
    admin = (
        f"{parsed.scheme}://{parsed.username}:{parsed.password}"
        f"@{parsed.hostname}:{parsed.port or 5432}/postgres"
    )
    return admin, name


def setup_module():
    admin_url, db_name = _admin_urls()
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        exists = connection.execute(
            text("SELECT 1 FROM pg_database WHERE datname=:name"),
            {"name": db_name},
        ).scalar()
        if not exists:
            connection.execute(text(f'CREATE DATABASE "{db_name}"'))
    engine.dispose()

    async def prepare():
        async_engine = create_async_engine_instance(os.environ["DATABASE_URL"])
        async with async_engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
        await async_engine.dispose()

    asyncio.run(prepare())


def teardown_module():
    admin_url, db_name = _admin_urls()
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        connection.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=:name AND pid <> pg_backend_pid()"
            ),
            {"name": db_name},
        )
        connection.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
    engine.dispose()


async def _task(name: str = "contract") -> Task:
    async with async_session() as session:
        task = Task(
            task_name=name,
            target_url="https://example.com",
            status="running",
            phase="executing",
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return task


def _result(run_id: str, case_id: str, status: str, attempts: int):
    return CaseResult(
        run_id=run_id,
        candidate_case_id=case_id,
        terminal_status=status,
        attempt_count=attempts,
        started_at="2026-06-11T00:00:00+00:00",
        completed_at="2026-06-11T00:00:01+00:00",
        summary=status,
    )


@pytest.mark.asyncio
async def test_authoritative_tables_and_columns_exist():
    engine = create_async_engine_instance(os.environ["DATABASE_URL"])
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public'"
            )
        )
        tables = {row[0] for row in rows}
    await engine.dispose()
    assert {
        "task",
        "execution_run",
        "case_result",
        "task_step",
        "report",
        "agent_memory",
    } <= tables
    assert not hasattr(Task, "test_plan")
    assert not hasattr(Task, "total_tests")


@pytest.mark.asyncio
async def test_duplicate_case_result_updates_without_duplicate_count():
    task = await _task("idempotent")
    run = await create_execution_run(task.id, ["CASE-1"])
    await upsert_case_result(_result(run.run_id, "CASE-1", "failed", 1))
    await upsert_case_result(_result(run.run_id, "CASE-1", "passed", 2))

    async with async_session() as session:
        count = await session.scalar(
            select(func.count(CaseResultRecord.id)).where(
                CaseResultRecord.run_id == run.run_id
            )
        )
    rows = await list_case_results(run.run_id)
    assert count == 1
    assert rows[0].terminal_status == "passed"
    assert rows[0].attempt_count == 2
    async with async_session() as session:
        refreshed_run = await session.get(ExecutionRunRecord, run.run_id)
        assert refreshed_run.summary == {
            "planned": 1,
            "terminal": 1,
            "passed": 1,
            "failed": 0,
            "skipped": 0,
            "incomplete": 0,
            "human_review_required": 0,
        }


@pytest.mark.asyncio
async def test_three_attempts_keep_three_step_histories():
    task = await _task("attempts")
    run = await create_execution_run(task.id, ["CASE-1"])
    for attempt in (1, 2, 3):
        await append_task_step(
            task_id=task.id,
            run_id=run.run_id,
            candidate_case_id="CASE-1",
            attempt_no=attempt,
            step_index=0,
            action={"tool": "click", "args": {"selector": "#submit"}},
            result=f"attempt-{attempt}",
        )
    await upsert_case_result(_result(run.run_id, "CASE-1", "passed", 3))

    async with async_session() as session:
        attempts = list(
            (
                await session.execute(
                    select(TaskStep.attempt_no)
                    .where(TaskStep.run_id == run.run_id)
                    .order_by(TaskStep.attempt_no)
                )
            ).scalars()
        )
    assert attempts == [1, 2, 3]
    assert len(await list_case_results(run.run_id)) == 1


@pytest.mark.asyncio
async def test_duplicate_step_identity_updates_without_duplicate_history():
    task = await _task("step-idempotent")
    run = await create_execution_run(task.id, ["CASE-1"])
    common = {
        "task_id": task.id,
        "run_id": run.run_id,
        "candidate_case_id": "CASE-1",
        "attempt_no": 1,
        "step_index": 0,
    }
    await append_task_step(
        **common,
        action={"tool": "click", "args": {"selector": "#submit"}},
        result="first",
    )
    await append_task_step(
        **common,
        action={"tool": "click", "args": {"selector": "#submit"}},
        result="updated",
    )

    async with async_session() as session:
        rows = list(
            (
                await session.execute(
                    select(TaskStep).where(TaskStep.run_id == run.run_id)
                )
            ).scalars()
        )
    assert len(rows) == 1
    assert rows[0].result == "updated"


@pytest.mark.asyncio
async def test_cancel_marks_active_incomplete_and_unstarted_skipped():
    task = await _task("cancel")
    run = await create_execution_run(task.id, ["DONE", "ACTIVE", "WAITING"])
    await upsert_case_result(_result(run.run_id, "DONE", "passed", 1))
    summary = await fill_cancelled_results(run.run_id)
    rows = {
        row.candidate_case_id: row.terminal_status
        for row in await list_case_results(run.run_id)
    }
    assert rows == {
        "DONE": "passed",
        "ACTIVE": "incomplete",
        "WAITING": "skipped",
    }
    assert summary["terminal"] == summary["planned"] == 3


@pytest.mark.asyncio
async def test_execution_crash_fills_missing_results():
    task = await _task("crash")
    run = await create_execution_run(task.id, ["DONE", "ACTIVE", "WAITING"])
    await upsert_case_result(_result(run.run_id, "DONE", "passed", 1))
    summary = await fill_failed_results(run.run_id, "browser crashed")
    rows = {
        row.candidate_case_id: row.terminal_status
        for row in await list_case_results(run.run_id)
    }
    assert rows["ACTIVE"] == "incomplete"
    assert rows["WAITING"] == "skipped"
    assert summary["terminal"] == 3


@pytest.mark.asyncio
async def test_resume_run_keeps_source_and_only_selected_cases():
    task = await _task("resume")
    first = await create_execution_run(task.id, ["PASS", "FAIL"])
    resumed = await create_execution_run(
        task.id,
        ["FAIL"],
        resumed_from_run_id=first.run_id,
    )
    async with async_session() as session:
        row = await session.get(ExecutionRunRecord, resumed.run_id)
        assert row.resumed_from_run_id == first.run_id
        assert row.candidate_case_ids == ["FAIL"]


@pytest.mark.asyncio
async def test_runtime_reset_preserves_agent_memory():
    async with async_session() as session:
        session.add(
            AgentMemory(
                scope_type="global",
                scope_value="*",
                memory_key="key",
                memory_value="value",
            )
        )
        await session.commit()
    from database.connection import reset_runtime_database

    await reset_runtime_database(
        "smart_test_test",
        os.environ["DATABASE_URL"],
    )
    async with async_session() as session:
        assert await session.scalar(select(func.count(AgentMemory.id))) == 1
        assert await session.scalar(select(func.count(Task.id))) == 0
