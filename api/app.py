"""api/app.py — FastAPI application with REST endpoints.

Defines the main FastAPI app instance, includes routers, and configures middleware.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from typing import Any

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
import json
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
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
from api.websocket import manager as websocket_manager, websocket_endpoint
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


# GET /api/tasks/{task_id}/diag — List diag log files for a task
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


# GET /api/tasks/{task_id}/diag/{stage} — Get a single diag log file
@app.get("/api/tasks/{task_id}/diag/{stage}")
async def get_diag_file(task_id: int, stage: str) -> dict:
    """Return a single diag stage JSON. stage is filename without .json extension."""
    import json
    from pathlib import Path

    # 安全: stage 不允许路径分隔符
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

class ResumeRequest(BaseModel):
    message: str

@app.post("/api/tasks/{task_id}/resume", response_model=MessageResponse)
async def resume_task(task_id: int, req: ResumeRequest) -> MessageResponse:
    from agents.ui.tools import _hitl_events, _hitl_responses
    task_id_str = str(task_id)
    if task_id_str not in _hitl_events:
        raise HTTPException(status_code=400, detail="Task is not waiting for human intervention")

    _hitl_responses[task_id_str] = req.message
    _hitl_events[task_id_str].set()
    return MessageResponse(message="Task resumed")

class Layer1TestRequest(BaseModel):
    prd: str = ""
    api_doc: str = ""
    changelog: str = ""

@app.post("/api/test/layer1")
async def test_layer1_endpoint(req: Layer1TestRequest):
    """Test the Layer 1 extraction pipeline with SSE streaming"""
    if not any([req.prd, req.api_doc, req.changelog]):
        raise HTTPException(status_code=400, detail="至少提供一个文档")

    # 截断保护
    req.prd = req.prd[:15000]
    req.api_doc = req.api_doc[:15000]
    req.changelog = req.changelog[:5000]

    async def generate():
        try:
            from core.skills.knowledge_extractor import extract_knowledge
            from core.skills.use_case_modeler import generate_use_case_model
            from core.skills.use_case_coverage import check_use_case_coverage
            from core.skills.system_modeler import generate_system_model
            from core.skills.goal_extractor import extract_goals

            yield json.dumps({"progress": "[Node 1] 正在提取无损事实库 (KnowledgeBase)..."}, ensure_ascii=False) + "\n"
            knowledge = await extract_knowledge(req.prd, req.api_doc, req.changelog)

            yield json.dumps({"progress": "[Node 1.5] 正在构建角色用例脚手架 (UseCaseModel)..."}, ensure_ascii=False) + "\n"
            use_case_model = await generate_use_case_model(knowledge)

            yield json.dumps({"progress": "[Node 1.7] 正在进行覆盖率自检 (Coverage Check)..."}, ensure_ascii=False) + "\n"
            use_case_model, coverage_report = await check_use_case_coverage(knowledge, use_case_model)

            yield json.dumps({"progress": "[Node 2] 正在构建状态机流转网络 (SystemModel)..."}, ensure_ascii=False) + "\n"
            system_model = await generate_system_model(knowledge, use_case_model)

            yield json.dumps({"progress": "[Node 3] 正在派生探索目标 (Goals)..."}, ensure_ascii=False) + "\n"
            goals = await extract_goals(use_case_model.model_dump())

            final_result = {
                "progress": "done",
                "knowledge_base": knowledge.model_dump(),
                "use_case_model": use_case_model.model_dump(),
                "coverage_report": coverage_report.model_dump(),
                "system_model": system_model.model_dump(),
                "goals": [g.model_dump() for g in goals]
            }
            yield json.dumps(final_result, ensure_ascii=False) + "\n"
        except Exception as e:
            yield json.dumps({"progress": "error", "error": str(e)}, ensure_ascii=False) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )

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
_task_execution_lock = asyncio.Lock()

# Flag to disable background tasks in tests
_background_tasks_enabled: bool = True


from core.memory_utils import retrieve_memories, reflect_on_task

async def _run_test_session(task_db_id: int, target_url: str, config: dict | None) -> None:
    """Run the test session in the background using Runtime.

    Executes the full test pipeline (plan → execute → report) via Runtime.run_stream()
    and streams updates over WebSocket. Detects errors yielded by the runtime and
    sets the task status accordingly.
    """
    # Wait for the global lock to prevent browser concurrency collision
    async with _task_execution_lock:
        # Update status to running only after acquiring the lock
        _task_id_map[str(task_db_id)] = task_db_id
        async with async_session() as session:
            task = await session.get(Task, task_db_id)
            if task:
                task.status = "running"
                task.started_at = datetime.now(timezone.utc)
                await session.commit()

        # Diag: 启动 + 入口 dump + 注入 task context
        from core.diag_logger import get_diag, set_current_task
        task_id_str = str(task_db_id)
        set_current_task(task_id_str)
        diag = get_diag(task_id_str)
        diag.start()
        diag.dump("00_entry", target_url=target_url, task_name=f"Test {target_url}",
                  config_keys=list((config or {}).keys()),
                  has_prd=bool((config or {}).get("prd")),
                  has_swagger=bool((config or {}).get("api_doc") or (config or {}).get("swagger")),
                  has_changelog=bool((config or {}).get("changelog")),
                  has_focus=bool((config or {}).get("focus_areas")),
                  accounts_count=len((config or {}).get("accounts", [])),
                  rules_count=len((config or {}).get("rules", [])))

        has_error = False
        try:
            from core.runtime import Runtime
            from agents.ui.tools import _hitl_callbacks
            from core.document_parser import parse_and_fetch_links

            async def hitl_callback(reason: str):
                await websocket_manager.send_message(str(task_db_id), {
                    "type": "hitl_requested",
                    "test_case_id": "",
                    "step_index": 0,
                    "data": {"reason": reason},
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })

            _hitl_callbacks[str(task_db_id)] = hitl_callback

            from core.skills.system_modeler import generate_system_model
            from core.skills.knowledge_extractor import extract_knowledge
            from core.skills.use_case_modeler import generate_use_case_model
            from core.skills.use_case_coverage import check_use_case_coverage

            from core.interfaces import KnowledgeBase
            from core.skills.use_case_modeler import UseCaseModel
            from core.skills.use_case_coverage import CoverageReport
            from core.skills.system_modeler import SystemModel

            print("  [DEBUG SESSION] Starting retrieve_memories...", flush=True)
            memory_context = await retrieve_memories(target_url)
            print("  [DEBUG SESSION] Starting parse_and_fetch_links...", flush=True)
            enriched_config = await parse_and_fetch_links(config or {})
            print("  [DEBUG SESSION] parse_and_fetch_links done.", flush=True)

            # Node 1: Knowledge Extraction
            if "_knowledge_base" in enriched_config and enriched_config["_knowledge_base"]:
                print("  [DEBUG SESSION] Found _knowledge_base cache in config. Using cached version.", flush=True)
                knowledge = KnowledgeBase.model_validate(enriched_config["_knowledge_base"])
            else:
                print("  [DEBUG SESSION] Starting extract_knowledge...", flush=True)
                knowledge = await extract_knowledge(
                    prd_content=enriched_config.get("prd", ""),
                    api_doc_content=enriched_config.get("api_doc", "") or enriched_config.get("swagger", ""),
                    changelog_content=enriched_config.get("changelog", "")
                )
                enriched_config["_knowledge_base"] = knowledge.model_dump()
                print("  [DEBUG SESSION] extract_knowledge done.", flush=True)

            # Node 1.5 + 1.7: Use Case Modeling & Coverage
            if "_use_case_model" in enriched_config and enriched_config["_use_case_model"] and "_coverage_report" in enriched_config and enriched_config["_coverage_report"]:
                print("  [DEBUG SESSION] Found _use_case_model & _coverage_report cache in config. Using cached version.", flush=True)
                use_case_model = UseCaseModel.model_validate(enriched_config["_use_case_model"])
                coverage_report = CoverageReport.model_validate(enriched_config["_coverage_report"])
            else:
                print("  [DEBUG SESSION] Starting generate_use_case_model...", flush=True)
                use_case_model = await generate_use_case_model(knowledge)
                print("  [DEBUG SESSION] Starting check_use_case_coverage...", flush=True)
                use_case_model, coverage_report = await check_use_case_coverage(knowledge, use_case_model)
                enriched_config["_use_case_model"] = use_case_model.model_dump()
                enriched_config["_coverage_report"] = coverage_report.model_dump()
                print("  [DEBUG SESSION] Use Case modeling & Coverage done.", flush=True)

            # Node 2: System Modeling (State Machine)
            if "_system_model" in enriched_config and enriched_config["_system_model"]:
                print("  [DEBUG SESSION] Found _system_model cache in config. Using cached version.", flush=True)
                system_model = SystemModel.model_validate(enriched_config["_system_model"])
            else:
                print("  [DEBUG SESSION] Starting generate_system_model...", flush=True)
                system_model = await generate_system_model(knowledge, use_case_model)
                enriched_config["_system_model"] = system_model.model_dump()
                print("  [DEBUG SESSION] generate_system_model done.", flush=True)

            # Diag: task_config 演化快照 (L1 5 节点之后, 落 enriched_config 状态)
            from core.diag_logger import get_diag_auto
            get_diag_auto().dump("99_task_config_evolution", snapshot_at="after_l1_n2",
                                 config_keys=list(enriched_config.keys()),
                                 has_kb="_knowledge_base" in enriched_config,
                                 has_ucm="_use_case_model" in enriched_config,
                                 has_cov="_coverage_report" in enriched_config,
                                 has_sm="_system_model" in enriched_config,
                                 l1_outputs_summary={
                                     "kb_rules": len(knowledge.business_rules),
                                     "ucm_cases": len(use_case_model.use_cases),
                                     "cov_covered": len(coverage_report.covered_rules),
                                     "sm_flows": len(system_model.flows),
                                 })

            async with async_session() as session:
                task = await session.get(Task, task_db_id)
                if task:
                    task.config = enriched_config
                    await session.commit()

            print("  [DEBUG SESSION] Initializing Runtime...", flush=True)
            runtime = Runtime(task_config={"task_id": str(task_db_id), "target_url": target_url, "memory_context": memory_context, **enriched_config})
            print("  [DEBUG SESSION] Runtime initialized. Running stream...", flush=True)

            async for update in runtime.run_stream():
                # Detect error messages yielded by the runtime
                if isinstance(update, dict) and isinstance(update.get("data"), dict):
                    if "error" in update["data"]:
                        has_error = True
                    # Check if final session complete event indicates aborted/pending cases (issue 3)
                    if update.get("type") == "session_complete" and update["data"].get("phase") == "final":
                        report_data = update["data"].get("report_data", {})
                        test_cases = report_data.get("test_plan", [])
                        executed_cases = [
                            tc for tc in test_cases
                            if tc.get("status") in ("passed", "failed", "skipped", "incomplete", "human_review_required")
                        ]
                        if len(executed_cases) < len(test_cases):
                            has_error = True
                await websocket_manager.send_message(str(task_db_id), update)
        except asyncio.CancelledError:
            has_error = False
            raise
        except Exception as e:
            import logging
            logging.exception(f"[_run_test_session] Caught exception in background task: {e}")
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

            # Cleanup HITL callbacks
            from agents.ui.tools import _hitl_callbacks, _hitl_events, _hitl_responses
            _hitl_callbacks.pop(str(task_db_id), None)
            _hitl_events.pop(str(task_db_id), None)
            _hitl_responses.pop(str(task_db_id), None)

            # Diag: await finalize (关键 — 进程退出 / 异常时也必须等所有 pending 写完)
            from core.diag_logger import get_diag
            diag_final = get_diag(str(task_db_id))
            await diag_final.finalize()
