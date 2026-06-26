"""Authoritative persistence for execution runs and terminal case results."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select

from core.interfaces import CaseResult
from database.connection import async_session
from database.models import CaseResultRecord, ExecutionRunRecord, Task, TaskStep

TERMINAL_STATUSES = (
    "passed",
    "failed",
    "skipped",
    "incomplete",
    "human_review_required",
)
_UNSET = object()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(value: str | datetime | None) -> datetime:
    if isinstance(value, datetime):
        return value
    if value:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return utc_now()


def aggregate_statuses(statuses: list[str], planned: int) -> dict[str, int]:
    summary = {
        "planned": planned,
        "terminal": len(statuses),
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "incomplete": 0,
        "human_review_required": 0,
    }
    for status in statuses:
        if status in TERMINAL_STATUSES:
            summary[status] += 1
    return summary


async def create_execution_run(
    task_id: int,
    candidate_case_ids: list[str],
    *,
    resumed_from_run_id: str | None = None,
) -> ExecutionRunRecord:
    run = ExecutionRunRecord(
        run_id=f"run-{uuid.uuid4().hex}",
        task_id=task_id,
        status="running",
        candidate_case_ids=list(candidate_case_ids),
        resumed_from_run_id=resumed_from_run_id,
        summary=aggregate_statuses([], len(candidate_case_ids)),
        started_at=utc_now(),
    )
    async with async_session() as session:
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run


async def upsert_case_result(result: CaseResult) -> CaseResultRecord:
    """Store one result and refresh its run summary in the same transaction."""
    async with async_session() as session:
        query = select(CaseResultRecord).where(
            CaseResultRecord.run_id == result.run_id,
            CaseResultRecord.candidate_case_id == result.candidate_case_id,
        )
        row = (await session.execute(query)).scalar_one_or_none()
        values = {
            "terminal_status": result.terminal_status,
            "attempt_count": result.attempt_count,
            "summary": result.summary,
            "evidence_refs": list(result.evidence_refs),
            "failure_reason": result.failure_reason,
            "started_at": parse_timestamp(result.started_at),
            "completed_at": parse_timestamp(result.completed_at),
        }
        if row is None:
            row = CaseResultRecord(
                run_id=result.run_id,
                candidate_case_id=result.candidate_case_id,
                **values,
            )
            session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        await session.flush()
        run = await session.get(ExecutionRunRecord, result.run_id)
        if run is None:
            raise ValueError(f"Execution run not found: {result.run_id}")
        status_query = select(CaseResultRecord.terminal_status).where(
            CaseResultRecord.run_id == result.run_id
        )
        statuses = list((await session.execute(status_query)).scalars().all())
        run.summary = aggregate_statuses(
            statuses,
            len(run.candidate_case_ids or []),
        )
        await session.commit()
        await session.refresh(row)
        return row


async def append_task_step(
    *,
    task_id: int,
    run_id: str,
    candidate_case_id: str,
    attempt_no: int,
    step_index: int,
    action: dict,
    result: str,
) -> TaskStep:
    """Idempotently persist one attempt-scoped execution record."""
    tool_name = str(action.get("tool", "unknown"))
    args = action.get("args", {})
    async with async_session() as session:
        query = select(TaskStep).where(
            TaskStep.run_id == run_id,
            TaskStep.test_case_id == candidate_case_id,
            TaskStep.attempt_no == attempt_no,
            TaskStep.step_index == step_index,
        )
        row = (await session.execute(query)).scalar_one_or_none()
        values = {
            "task_id": task_id,
            "action_type": tool_name,
            "action_target": str(
                args.get("selector")
                or args.get("url")
                or args.get("reason")
                or ""
            ),
            "action_args": args,
            "result": result,
            "screenshot_path": "",
        }
        if row is None:
            row = TaskStep(
                run_id=run_id,
                test_case_id=candidate_case_id,
                attempt_no=attempt_no,
                step_index=step_index,
                **values,
            )
            session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        await session.commit()
        await session.refresh(row)
        return row


async def list_case_results(run_id: str) -> list[CaseResultRecord]:
    async with async_session() as session:
        query = (
            select(CaseResultRecord)
            .where(CaseResultRecord.run_id == run_id)
            .order_by(CaseResultRecord.id)
        )
        return list((await session.execute(query)).scalars().all())


async def list_execution_runs(task_id: int) -> list[ExecutionRunRecord]:
    async with async_session() as session:
        query = (
            select(ExecutionRunRecord)
            .where(ExecutionRunRecord.task_id == task_id)
            .order_by(ExecutionRunRecord.started_at.desc())
        )
        return list((await session.execute(query)).scalars().all())


async def get_execution_run(run_id: str) -> ExecutionRunRecord | None:
    async with async_session() as session:
        return await session.get(ExecutionRunRecord, run_id)


async def refresh_run_summary(run_id: str) -> dict[str, int]:
    async with async_session() as session:
        run = await session.get(ExecutionRunRecord, run_id)
        if run is None:
            raise ValueError(f"Execution run not found: {run_id}")
        query = select(CaseResultRecord.terminal_status).where(
            CaseResultRecord.run_id == run_id
        )
        statuses = list((await session.execute(query)).scalars().all())
        run.summary = aggregate_statuses(statuses, len(run.candidate_case_ids or []))
        await session.commit()
        return dict(run.summary)


async def finalize_execution_run(run_id: str, status: str) -> dict[str, int]:
    summary = await refresh_run_summary(run_id)
    async with async_session() as session:
        run = await session.get(ExecutionRunRecord, run_id)
        if run is None:
            raise ValueError(f"Execution run not found: {run_id}")
        if summary["terminal"] != summary["planned"]:
            raise ValueError(
                f"Cannot finalize run {run_id}: "
                f"{summary['terminal']} terminal results for {summary['planned']} cases"
            )
        run.status = status
        run.completed_at = utc_now()
        run.summary = summary
        await session.commit()
    return summary


async def latest_execution_run(task_id: int) -> ExecutionRunRecord | None:
    async with async_session() as session:
        query = (
            select(ExecutionRunRecord)
            .where(ExecutionRunRecord.task_id == task_id)
            .order_by(ExecutionRunRecord.started_at.desc())
            .limit(1)
        )
        return (await session.execute(query)).scalar_one_or_none()


async def fill_cancelled_results(run_id: str) -> dict[str, int]:
    """Complete a cancelled run without losing its accounting invariant."""
    run = await get_execution_run(run_id)
    if run is None:
        raise ValueError(f"Execution run not found: {run_id}")
    existing = {
        row.candidate_case_id
        for row in await list_case_results(run_id)
    }
    missing = [
        case_id for case_id in run.candidate_case_ids
        if case_id not in existing
    ]
    now = utc_now().isoformat()
    for index, case_id in enumerate(missing):
        await upsert_case_result(CaseResult(
            run_id=run_id,
            candidate_case_id=case_id,
            terminal_status="incomplete" if index == 0 else "skipped",
            attempt_count=0,
            started_at=now,
            completed_at=now,
            summary="任务已取消",
            failure_reason="cancelled",
        ))
    return await finalize_execution_run(run_id, "cancelled")


async def fill_failed_results(run_id: str, reason: str) -> dict[str, int]:
    """Close the denominator after an execution-level crash."""
    run = await get_execution_run(run_id)
    if run is None:
        raise ValueError(f"Execution run not found: {run_id}")
    existing = {
        row.candidate_case_id
        for row in await list_case_results(run_id)
    }
    missing = [
        case_id for case_id in run.candidate_case_ids
        if case_id not in existing
    ]
    now = utc_now().isoformat()
    for index, case_id in enumerate(missing):
        await upsert_case_result(CaseResult(
            run_id=run_id,
            candidate_case_id=case_id,
            terminal_status="incomplete" if index == 0 else "skipped",
            attempt_count=0,
            started_at=now,
            completed_at=now,
            summary="执行因系统异常中止",
            failure_reason=reason if index == 0 else "execution_aborted",
        ))
    return await finalize_execution_run(run_id, "failed")


async def update_task_lifecycle(
    task_id: int,
    *,
    status: str | None = None,
    phase: str | None = None,
    report_status: str | None = None,
    failure_reason: str | None | object = _UNSET,
    completed: bool = False,
) -> None:
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        if status is not None:
            task.status = status
        task.phase = phase
        if report_status is not None:
            task.report_status = report_status
        if failure_reason is not _UNSET:
            task.failure_reason = failure_reason
        if completed:
            task.completed_at = utc_now()
        await session.commit()


async def run_count(task_id: int) -> int:
    async with async_session() as session:
        query = select(func.count(ExecutionRunRecord.run_id)).where(
            ExecutionRunRecord.task_id == task_id
        )
        return int((await session.execute(query)).scalar_one())
