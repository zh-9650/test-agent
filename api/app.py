"""api/app.py 閳?FastAPI application with REST endpoints.

Defines the main FastAPI app instance, includes routers, and configures middleware.
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas import (
    CreateTaskRequest,
    MessageResponse,
    StepListResponse,
    TaskListResponse,
    TaskResponse,
    ExecutionRunResponse,
    ExecutionRunListResponse,
    CaseResultListResponse,
    AgentMemoryItem,
    MemoryListResponse
)
from api.websocket import (
    create_ws_message,
    manager as websocket_manager,
    set_stop_handler,
    websocket_endpoint,
)
from core.task_lifecycle import TaskLifecycleService
from database.connection import async_session, init_database
from database.models import (
    AgentMemory,
    CaseResultRecord,
    ExecutionRunRecord,
    Report,
    Task,
    TaskStep,
)
from api.utils import router as utils_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Initialize persistent storage without destructive startup behavior."""
    await init_database()
    yield


app = FastAPI(
    title="AI Native Testing Platform",
    version="1.0",
    lifespan=lifespan,
)

app.include_router(utils_router)

# Register WebSocket route
app.add_api_websocket_route("/ws/tasks/{task_id}", websocket_endpoint)

# CORS for frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files for screenshots 閳?mounted at /static/screenshots
SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent / "data" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static/screenshots", StaticFiles(directory=str(SCREENSHOTS_DIR)), name="screenshots")


async def _latest_run_in_session(
    session: AsyncSession,
    task_id: int,
) -> ExecutionRunRecord | None:
    query = (
        select(ExecutionRunRecord)
        .where(ExecutionRunRecord.task_id == task_id)
        .order_by(ExecutionRunRecord.started_at.desc())
        .limit(1)
    )
    return (await session.execute(query)).scalar_one_or_none()


def _serialize_task(
    task: Task,
    latest_run: ExecutionRunRecord | None,
) -> dict[str, Any]:
    return {
        "id": task.id,
        "task_name": task.task_name,
        "target_url": task.target_url,
        "status": task.status,
        "phase": task.phase,
        "report_status": task.report_status,
        "failure_reason": task.failure_reason,
        "config": task.config,
        "analysis_package": task.analysis_package,
        "latest_run": (
            {
                "run_id": latest_run.run_id,
                "status": latest_run.status,
                "summary": latest_run.summary,
                "started_at": latest_run.started_at.isoformat(),
                "completed_at": (
                    latest_run.completed_at.isoformat()
                    if latest_run.completed_at else None
                ),
            }
            if latest_run else None
        ),
        "started_at": task.started_at,
        "completed_at": task.completed_at,
        "created_at": task.created_at,
    }


# POST /api/tasks 閳?Create task
@app.post("/api/tasks", response_model=TaskResponse, status_code=201)
async def create_task(request: CreateTaskRequest) -> dict[str, Any]:
    """Create a new test task and start it in the background."""
    async with async_session() as session:
        task = Task(
            task_name=request.task_name or f"Test {request.target_url}",
            target_url=request.target_url,
            status="pending",
            config=request.config,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        _start_task_session(task.id, task.target_url, task.config)

        return _serialize_task(task, None)


# GET /api/tasks 閳?List tasks
@app.get("/api/tasks", response_model=TaskListResponse)
async def list_tasks(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> TaskListResponse:
    """Return a paginated list of tasks ordered by creation time (descending)."""
    async with async_session() as session:
        total_result = await session.execute(select(func.count(Task.id)))
        total = total_result.scalar() or 0

        result = await session.execute(
            select(Task).order_by(Task.created_at.desc()).offset(skip).limit(limit)
        )
        tasks = result.scalars().all()
        serialized = []
        for task in tasks:
            latest = await _latest_run_in_session(session, task.id)
            serialized.append(_serialize_task(task, latest))
        return TaskListResponse(tasks=serialized, total=total)  # type: ignore[arg-type]


# GET /api/tasks/{task_id} 閳?Task details
@app.get("/api/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int) -> dict[str, Any]:
    """Get details for a single task by ID."""
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        latest = await _latest_run_in_session(session, task.id)
        return _serialize_task(task, latest)


# GET /api/tasks/{task_id}/steps 閳?Task steps
@app.get("/api/tasks/{task_id}/steps", response_model=StepListResponse)
async def get_task_steps(
    task_id: int,
    run_id: str = Query(..., description="Execution run ID"),
    test_case_id: str = Query("", description="Filter by test case ID"),
    attempt_no: int | None = Query(None, ge=1),
) -> StepListResponse:
    """Return steps for a given task, optionally filtered by test_case_id."""
    async with async_session() as session:
        query = select(TaskStep).where(
            TaskStep.task_id == task_id,
            TaskStep.run_id == run_id,
        )
        if test_case_id:
            query = query.where(TaskStep.test_case_id == test_case_id)
        if attempt_no is not None:
            query = query.where(TaskStep.attempt_no == attempt_no)
        query = query.order_by(
            TaskStep.test_case_id,
            TaskStep.attempt_no,
            TaskStep.step_index,
        )

        result = await session.execute(query)
        steps = result.scalars().all()

        return StepListResponse(steps=steps, total=len(steps))  # type: ignore[arg-type]


@app.get("/api/tasks/{task_id}/runs", response_model=ExecutionRunListResponse)
async def list_task_runs(task_id: int) -> ExecutionRunListResponse:
    async with async_session() as session:
        if await session.get(Task, task_id) is None:
            raise HTTPException(status_code=404, detail="Task not found")
        query = (
            select(ExecutionRunRecord)
            .where(ExecutionRunRecord.task_id == task_id)
            .order_by(ExecutionRunRecord.started_at.desc())
        )
        runs = list((await session.execute(query)).scalars().all())
        return ExecutionRunListResponse(runs=runs, total=len(runs))


@app.get("/api/tasks/{task_id}/runs/{run_id}", response_model=ExecutionRunResponse)
async def get_task_run(task_id: int, run_id: str) -> ExecutionRunRecord:
    async with async_session() as session:
        run = await session.get(ExecutionRunRecord, run_id)
        if run is None or run.task_id != task_id:
            raise HTTPException(status_code=404, detail="Execution run not found")
        return run


@app.get("/api/tasks/{task_id}/runs/{run_id}/results", response_model=CaseResultListResponse)
async def get_run_results(task_id: int, run_id: str) -> CaseResultListResponse:
    async with async_session() as session:
        run = await session.get(ExecutionRunRecord, run_id)
        if run is None or run.task_id != task_id:
            raise HTTPException(status_code=404, detail="Execution run not found")
        query = (
            select(CaseResultRecord)
            .where(CaseResultRecord.run_id == run_id)
            .order_by(CaseResultRecord.id)
        )
        results = list((await session.execute(query)).scalars().all())
        return CaseResultListResponse(results=results, total=len(results))


# GET /api/tasks/{task_id}/diag 閳?List diag log files for a task
@app.get("/api/tasks/{task_id}/diag")
async def get_diag_list(task_id: int) -> dict:
    """Return diag log index for a task. Files are loaded lazily via /diag/{stage}."""
    import json
    from pathlib import Path

    diag_dir = Path("data") / "diag" / str(task_id)
    if not diag_dir.is_dir():
        return {"task_id": task_id, "exists": False, "stages": [], "index": None}

    index_path = diag_dir / "index.json"
    index_data = None
    if index_path.is_file():
        try:
            index_data = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception as e:
            index_data = {"_error": f"index.json unreadable: {e}"}

    files = []
    for p in sorted(diag_dir.glob("*.json")):
        if p.name == "index.json":
            continue
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            files.append({
                "stage": p.stem,
                "size": p.stat().st_size,
                "status": "unreadable",
                "error": str(e),
            })
            continue
        files.append({
            "stage": p.stem,
            "size": p.stat().st_size,
            "started_at": st.get("started_at"),
            "node": st.get("node"),
            "status": st.get("status"),
        })

    return {
        "task_id": task_id,
        "exists": True,
        "stages": files,
        "index": index_data,
    }


# GET /api/tasks/{task_id}/diag/{stage} 閳?Get a single diag log file
@app.get("/api/tasks/{task_id}/diag/{stage}")
async def get_diag_file(task_id: int, stage: str) -> dict:
    """Return a single diag stage JSON. stage is filename without .json extension."""
    import json
    from pathlib import Path

    # 鐎瑰鍙? stage 娑撳秴鍘戠拋姝岀熅瀵板嫬鍨庨梾鏃傤儊
    if "/" in stage or "\\" in stage or ".." in stage:
        raise HTTPException(status_code=400, detail="invalid stage name")

    diag_dir = Path("data") / "diag" / str(task_id)
    f = diag_dir / f"{stage}.json"
    if not f.is_file():
        raise HTTPException(status_code=404, detail=f"diag stage '{stage}' not found for task {task_id}")

    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"diag file '{stage}' unreadable: {e}")


# GET /api/tasks/{task_id}/report 閳?Get report
@app.get("/api/tasks/{task_id}/report")
async def get_report(
    task_id: int,
    download: bool = Query(False),
    run_id: str | None = Query(None),
) -> Any:
    """Return the latest report for a task. Optionally download as file."""
    async with async_session() as session:
        query = select(Report).where(Report.task_id == task_id)
        if run_id:
            query = query.where(Report.run_id == run_id)
        result = await session.execute(
            query.order_by(Report.created_at.desc()).limit(1)
        )
        report = result.scalar_one_or_none()
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")

        if download:
            return FileResponse(
                report.report_path,
                media_type="text/html",
                filename=f"report-{task_id}.html",
            )
        else:
            with open(report.report_path, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())


# POST /api/tasks/{task_id}/stop 閳?Stop task
@app.post("/api/tasks/{task_id}/stop", response_model=MessageResponse)
async def stop_task(task_id: int) -> MessageResponse:
    """Stop a running task by updating its status to cancelled."""
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.status != "running":
            raise HTTPException(
                status_code=400,
                detail=f"Task is not running (status: {task.status})",
            )

        background_task = _running_tasks.pop(task_id, None)
        if background_task and not background_task.done():
            background_task.cancel()
            try:
                await background_task
            except asyncio.CancelledError:
                pass
        from core.execution_store import fill_cancelled_results, latest_execution_run
        latest = await latest_execution_run(task_id)
        if latest is not None and latest.status == "running":
            await fill_cancelled_results(latest.run_id)
        task.status = "cancelled"
        task.phase = None
        task.failure_reason = "cancelled"
        task.completed_at = datetime.now(timezone.utc)
        await session.commit()
        return MessageResponse(message="Task stopped", task_id=str(task_id))


async def _handle_ws_stop(task_id: int) -> None:
    await stop_task(task_id)


set_stop_handler(_handle_ws_stop)


# DELETE /api/tasks/{task_id} 閳?Delete task
@app.delete("/api/tasks/{task_id}", response_model=MessageResponse)
async def delete_task(task_id: int) -> MessageResponse:
    """Delete a task. Cannot delete a running task."""
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.status == "running":
            raise HTTPException(status_code=400, detail="Cannot delete running task")

        await session.delete(task)
        await session.commit()
        return MessageResponse(message="Task deleted", task_id=str(task_id))

@app.post("/api/tasks/{task_id}/resume", response_model=MessageResponse)
async def resume_task(task_id: int) -> MessageResponse:
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.status == "running":
            raise HTTPException(status_code=400, detail="Task is already running")
        latest = await _latest_run_in_session(session, task_id)
        if latest is None:
            raise HTTPException(status_code=400, detail="Task has no execution run")
        query = select(CaseResultRecord).where(
            CaseResultRecord.run_id == latest.run_id,
            CaseResultRecord.terminal_status != "passed",
        )
        retry_ids = [
            row.candidate_case_id
            for row in (await session.execute(query)).scalars().all()
        ]
        if not retry_ids:
            raise HTTPException(status_code=400, detail="No non-passed cases to resume")
        task.status = "pending"
        task.phase = None
        task.failure_reason = None
        task.completed_at = None
        await session.commit()

    _start_task_session(
        task_id,
        task.target_url,
        task.config,
        resumed_from_run_id=latest.run_id,
        resume_case_ids=retry_ids,
    )
    return MessageResponse(message="Task resumed", task_id=str(task_id))

# --- Memory Endpoints ---

# GET /api/memory
@app.get("/api/memory", response_model=MemoryListResponse)
async def list_memories(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    scope_type: str | None = None
) -> MemoryListResponse:
    async with async_session() as session:
        query = select(AgentMemory)
        if scope_type:
            query = query.where(AgentMemory.scope_type == scope_type)

        total_result = await session.execute(select(func.count(AgentMemory.id)))
        total = total_result.scalar() or 0

        result = await session.execute(query.order_by(AgentMemory.created_at.desc()).offset(skip).limit(limit))
        memories = result.scalars().all()
        return MemoryListResponse(memories=memories, total=total)  # type: ignore

# POST /api/memory
@app.post("/api/memory", response_model=AgentMemoryItem, status_code=201)
async def create_memory(item: AgentMemoryItem) -> AgentMemory:
    async with async_session() as session:
        mem = AgentMemory(
            scope_type=item.scope_type,
            scope_value=item.scope_value,
            memory_key=item.memory_key,
            memory_value=item.memory_value
        )
        session.add(mem)
        await session.commit()
        await session.refresh(mem)
        return mem

# PUT /api/memory/{id}
@app.put("/api/memory/{memory_id}", response_model=AgentMemoryItem)
async def update_memory(memory_id: int, item: AgentMemoryItem) -> AgentMemory:
    async with async_session() as session:
        mem = await session.get(AgentMemory, memory_id)
        if not mem:
            raise HTTPException(status_code=404, detail="Memory not found")
        mem.scope_type = item.scope_type
        mem.scope_value = item.scope_value
        mem.memory_key = item.memory_key
        mem.memory_value = item.memory_value
        await session.commit()
        await session.refresh(mem)
        return mem

# DELETE /api/memory/{id}
@app.delete("/api/memory/{memory_id}", response_model=MessageResponse)
async def delete_memory(memory_id: int) -> MessageResponse:
    async with async_session() as session:
        mem = await session.get(AgentMemory, memory_id)
        if not mem:
            raise HTTPException(status_code=404, detail="Memory not found")
        await session.delete(mem)
        await session.commit()
        return MessageResponse(message="Memory deleted")


# --- Background task runner ---
_running_tasks: dict[int, asyncio.Task] = {}
_task_lifecycle_service = TaskLifecycleService()



def _make_lifecycle_event_sink(
    task_db_id: int,
) -> Any:
    async def send_ws_event(
        event_type: str,
        current_run_id: str,
        data: dict[str, Any],
    ) -> None:
        payload = dict(data)
        await websocket_manager.send_message(
            str(task_db_id),
            create_ws_message(
                event_type,
                task_id=task_db_id,
                run_id=current_run_id,
                phase=payload.pop("phase", None),
                candidate_case_id=payload.pop("candidate_case_id", ""),
                attempt_no=payload.pop("attempt_no", None),
                step_index=payload.pop("step_index", None),
                data=payload,
            ),
        )

    return send_ws_event


def _start_task_session(
    task_id: int,
    target_url: str,
    config: dict | None,
    *,
    resumed_from_run_id: str | None = None,
    resume_case_ids: list[str] | None = None,
) -> None:
    background_task = asyncio.create_task(
        _task_lifecycle_service.run_test_session(
            task_id,
            target_url,
            config,
            event_sink=_make_lifecycle_event_sink(task_id),
            resumed_from_run_id=resumed_from_run_id,
            resume_case_ids=resume_case_ids,
        )
    )
    _running_tasks[task_id] = background_task
    background_task.add_done_callback(
        lambda _task, current_id=task_id: _running_tasks.pop(current_id, None)
    )

