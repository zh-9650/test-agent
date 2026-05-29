"""api/app.py — FastAPI application with REST endpoints.

Defines the main FastAPI app instance, includes routers, and configures middleware.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

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
    StepResponse,
    TaskListResponse,
    TaskResponse,
    AgentMemoryItem,
    MemoryListResponse
)
from api.websocket import manager as websocket_manager, stream_runtime_updates, websocket_endpoint
from database.connection import async_session, init_database
from database.models import Report, Task, TaskStep, AgentMemory
from core.execution_logger import _task_id_map
from api.utils import router as utils_router

app = FastAPI(title="AI Native Testing Platform", version="1.0")

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

# Static files for screenshots — mounted at /static/screenshots
SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent / "data" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static/screenshots", StaticFiles(directory=str(SCREENSHOTS_DIR)), name="screenshots")


@app.on_event("startup")
async def startup() -> None:
    """Initialize the database on application startup."""
    await init_database()


# POST /api/tasks — Create task
@app.post("/api/tasks", response_model=TaskResponse, status_code=201)
async def create_task(request: CreateTaskRequest) -> Task:
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
        _task_id_map[str(task.id)] = task.id

        # Start the test in background (can be disabled in tests)
        if _background_tasks_enabled:
            background_task = asyncio.create_task(_run_test_session(task.id, task.target_url, task.config))
            _running_tasks[task.id] = background_task
            background_task.add_done_callback(lambda _task, task_id=task.id: _running_tasks.pop(task_id, None))

        return task


# GET /api/tasks — List tasks
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
        return TaskListResponse(tasks=tasks, total=total)  # type: ignore[arg-type]


# GET /api/tasks/{task_id} — Task details
@app.get("/api/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int) -> Task:
    """Get details for a single task by ID."""
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task


# GET /api/tasks/{task_id}/steps — Task steps
@app.get("/api/tasks/{task_id}/steps", response_model=StepListResponse)
async def get_task_steps(
    task_id: int,
    test_case_id: str = Query("", description="Filter by test case ID"),
) -> StepListResponse:
    """Return steps for a given task, optionally filtered by test_case_id."""
    async with async_session() as session:
        query = select(TaskStep).where(TaskStep.task_id == task_id)
        if test_case_id:
            query = query.where(TaskStep.test_case_id == test_case_id)
        query = query.order_by(TaskStep.step_index)

        result = await session.execute(query)
        steps = result.scalars().all()

        total_result = await session.execute(
            select(func.count(TaskStep.id)).where(TaskStep.task_id == task_id)
        )
        total = total_result.scalar() or 0

        return StepListResponse(steps=steps, total=total)  # type: ignore[arg-type]


# GET /api/tasks/{task_id}/report — Get report
@app.get("/api/tasks/{task_id}/report")
async def get_report(task_id: int, download: bool = Query(False)) -> Any:
    """Return the latest report for a task. Optionally download as file."""
    async with async_session() as session:
        result = await session.execute(
            select(Report)
            .where(Report.task_id == task_id)
            .order_by(Report.created_at.desc())
            .limit(1)
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


# POST /api/tasks/{task_id}/stop — Stop task
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

        task.status = "cancelled"
        await session.commit()
        background_task = _running_tasks.pop(task_id, None)
        if background_task and not background_task.done():
            background_task.cancel()
        return MessageResponse(message="Task stopped", task_id=str(task_id))


# DELETE /api/tasks/{task_id} — Delete task
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

# Flag to disable background tasks in tests
_background_tasks_enabled: bool = True


from core.memory_utils import retrieve_memories, reflect_on_task

async def _run_test_session(task_db_id: int, target_url: str, config: dict | None) -> None:
    """Run the test session in the background using Runtime.

    Executes the full test pipeline (plan → execute → report) via Runtime.run_stream()
    and streams updates over WebSocket. Detects errors yielded by the runtime and
    sets the task status accordingly.
    """
    # Update status to running
    _task_id_map[str(task_db_id)] = task_db_id
    async with async_session() as session:
        task = await session.get(Task, task_db_id)
        if task:
            task.status = "running"
            task.started_at = datetime.now(timezone.utc)
            await session.commit()

    has_error = False
    try:
        from core.runtime import Runtime
        memory_context = await retrieve_memories(target_url)
        runtime = Runtime(task_config={"task_id": str(task_db_id), "target_url": target_url, "memory_context": memory_context, **(config or {})})

        async for update in runtime.run_stream():
            # Detect error messages yielded by the runtime
            if isinstance(update, dict) and isinstance(update.get("data"), dict):
                if "error" in update["data"]:
                    has_error = True
            await websocket_manager.send_message(str(task_db_id), update)
    except asyncio.CancelledError:
        has_error = False
        raise
    except Exception as e:
        import traceback
        print(f"[_run_test_session] Caught exception in background task: {e}")
        traceback.print_exc()
        has_error = True
    finally:
        # ALWAYS update final status, even if unexpected exception
        final_status = "failed" if has_error else "completed"
        async with async_session() as session:
            task = await session.get(Task, task_db_id)
            if task:
                if task.status != "cancelled":
                    task.status = final_status
                task.completed_at = datetime.now(timezone.utc)
                await session.commit()
                
        # Trigger reflection post-task
        await reflect_on_task(task_db_id)
