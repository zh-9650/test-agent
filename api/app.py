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

class Layer2TestRequest(BaseModel):
    prd: str = ""
    api_doc: str = ""
    changelog: str = ""
    prototype: str = ""
    architecture: str = ""
    rules: str = ""

@app.post("/api/test/layer2")
async def test_layer2_endpoint(req: Layer2TestRequest):
    """Test the new L2 analysis pipeline with SSE streaming.

    使用新的 RequirementFact → RequirementAssertion → TestCondition
    → CoverageItem → CandidateTestCase → TestAssetPackage 管道。
    """
    if not any([req.prd, req.api_doc, req.changelog, req.prototype, req.architecture, req.rules]):
        raise HTTPException(status_code=400, detail="至少提供一个文档")

    req.prd = req.prd[:15000]
    req.api_doc = req.api_doc[:15000]
    req.changelog = req.changelog[:5000]
    req.prototype = req.prototype[:5000]
    req.architecture = req.architecture[:5000]
    req.rules = req.rules[:5000]

    async def generate():
        try:
            from core.skills.l2_pipeline import run_l2_pipeline

            yield json.dumps({"progress": "[N1] 正在提取原子化需求事实 (RequirementFact)..."}, ensure_ascii=False) + "\n"
            yield json.dumps({"progress": "[N1.5] 正在推导需求断言 (RequirementAssertion)..."}, ensure_ascii=False) + "\n"
            yield json.dumps({"progress": "[N2] 正在分析测试条件 (TestCondition)..."}, ensure_ascii=False) + "\n"
            yield json.dumps({"progress": "[N2.5] 正在选择设计技术 (TestDesignTechnique)..."}, ensure_ascii=False) + "\n"
            yield json.dumps({"progress": "[N3] 正在分析覆盖项 (CoverageItem)..."}, ensure_ascii=False) + "\n"
            yield json.dumps({"progress": "[N3.5] 正在生成候选用例 (CandidateTestCase)..."}, ensure_ascii=False) + "\n"
            yield json.dumps({"progress": "[N4] 正在构建追溯矩阵 (TraceabilityMatrix)..."}, ensure_ascii=False) + "\n"
            yield json.dumps({"progress": "[N4.5] 正在组装最终交付物 (TestAssetPackage)..."}, ensure_ascii=False) + "\n"

            package = await run_l2_pipeline(
                prd_content=req.prd,
                api_doc_content=req.api_doc,
                changelog_content=req.changelog,
                prototype_notes=req.prototype,
                architecture_notes=req.architecture,
                rules=req.rules,
            )

            final_result = {
                "progress": "done",
                "package": package.model_dump(),
                "summary": {
                    "fact_count": len(package.facts),
                    "assertion_count": len(package.assertions),
                    "condition_count": len(package.test_conditions),
                    "technique_count": len(package.test_design_techniques),
                    "coverage_count": len(package.coverage_items),
                    "candidate_count": len(package.candidate_cases),
                    "conflict_count": len(package.conflicts),
                    "manual_review_count": len(package.manual_review_items),
                },
            }
            yield json.dumps(final_result, ensure_ascii=False) + "\n"
        except Exception as e:
            import traceback
            yield json.dumps({"progress": "error", "error": str(e), "traceback": traceback.format_exc()}, ensure_ascii=False) + "\n"

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

            print("  [DEBUG SESSION] Starting retrieve_memories...", flush=True)
            memory_context = await retrieve_memories(target_url)
            print("  [DEBUG SESSION] Starting parse_and_fetch_links...", flush=True)
            enriched_config = await parse_and_fetch_links(config or {})
            print("  [DEBUG SESSION] parse_and_fetch_links done.", flush=True)

            # =========================================================================
            # L2 Phase 1 (探索前): 提取事实 → 推导断言 → review gate → 生成探索目标
            # =========================================================================
            print("  [DEBUG SESSION] Starting L2 Phase 1 (pre-exploration)...", flush=True)
            from core.skills.l2_pipeline import generate_exploration_goals, run_l2_pipeline
            from core.execution_logger import log_analysis_package

            # rules: 前端传字符串，直接用；如果是 list 则 join
            raw_rules = enriched_config.get("rules", "")
            rules_str = "\n".join(raw_rules) if isinstance(raw_rules, list) else str(raw_rules or "")

            goals, review_items, l2_facts, l2_assertions = await generate_exploration_goals(
                prd_content=enriched_config.get("prd", ""),
                api_doc_content=enriched_config.get("api_doc", "") or enriched_config.get("swagger", ""),
                changelog_content=enriched_config.get("changelog", ""),
                prototype_notes=enriched_config.get("prototype_url", ""),
                architecture_notes=enriched_config.get("tech_doc", ""),
                rules=rules_str,
            )

            if goals:
                enriched_config["_goals"] = [g.model_dump() for g in goals]
            if review_items:
                enriched_config["_l2_manual_review_items"] = review_items

            # 保存 Phase 1 结果供 Phase 2 复用，避免重复 LLM 调用
            enriched_config["_l2_precomputed_facts"] = [f.model_dump() for f in l2_facts]
            enriched_config["_l2_precomputed_assertions"] = [a.model_dump() for a in l2_assertions]
            enriched_config["_l2_precomputed_goals"] = [g.model_dump() for g in goals]

            print(f"  [DEBUG SESSION] L2 Phase 1 done: "
                  f"{len(l2_facts)} facts, {len(l2_assertions)} assertions, "
                  f"{len(goals)} goals, {len(review_items)} review items", flush=True)

            if review_items:
                print(f"  [L2 REVIEW GATE] {len(review_items)} 条高风险断言需要人工确认:", flush=True)
                for item in review_items[:5]:
                    print(f"    - {item[:120]}", flush=True)

            from core.diag_logger import get_diag_auto
            get_diag_auto().dump("99_task_config_evolution",
                snapshot_at="after_l2_phase1",
                config_keys=list(enriched_config.keys()),
                l2_facts=len(l2_facts),
                l2_assertions=len(l2_assertions),
                l2_goals=len(goals),
                l2_review_gate=len(review_items),
            )

            async with async_session() as session:
                task = await session.get(Task, task_db_id)
                if task:
                    task.config = enriched_config
                    await session.commit()

            # =========================================================================
            # Runtime: 探索 + 执行 (goals 已注入，planning_graph 会消费)
            # =========================================================================
            print("  [DEBUG SESSION] Initializing Runtime...", flush=True)
            runtime = Runtime(task_config={"task_id": str(task_db_id), "target_url": target_url, "memory_context": memory_context, **enriched_config})
            print("  [DEBUG SESSION] Runtime initialized. Running stream...", flush=True)

            async for update in runtime.run_stream():
                if isinstance(update, dict) and isinstance(update.get("data"), dict):
                    if "error" in update["data"]:
                        has_error = True
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

            # =========================================================================
            # L2 Phase 2 (探索后): 用真实 UI 证据跑完整分析管道
            # =========================================================================
            print("  [DEBUG SESSION] Starting L2 Phase 2 (post-exploration)...", flush=True)

            # 从 runtime.task_config 读取探索证据（planning_graph 写入的）
            system_map_evid = None
            exploration_history = runtime.task_config.get("_exploration_history")
            if exploration_history:
                from core.interfaces import PageMap, ActionMap, FormMap, NavigationMap, SystemMapEvid
                page_maps = []
                action_maps = []
                for page in exploration_history[-20:]:
                    url = page.get("url", "")
                    title = page.get("title", "")
                    elements = page.get("interactive_elements", [])
                    actions = [
                        f"{el.get('role', 'elem')}: {el.get('name', '') or el.get('text', '')}"
                        for el in elements[:15]
                    ]
                    page_maps.append(PageMap(
                        name=title or url or "未知页面",
                        url_pattern=url,
                        title=title,
                        elements=[e.get("name", "") or e.get("text", "") or "" for e in elements[:20]],
                        discovered_actions=actions,
                    ))
                    for el in elements:
                        action_text = el.get("name", "") or el.get("text", "") or ""
                        if action_text:
                            action_maps.append(ActionMap(
                                action_name=action_text,
                                target_page=title or url or "",
                            ))

                system_map_evid = SystemMapEvid(
                    pages=page_maps,
                    actions=action_maps,
                    forms=[],
                    navigations=[],
                )

            # 复用 Phase 1 预计算结果（使用 legacy adapter 兼容旧数据）
            from core.interfaces import RequirementFact, RequirementAssertion
            from core.skills.l2_pipeline import adapt_legacy_goals
            precomputed_facts = [RequirementFact.model_validate(f) for f in enriched_config.get("_l2_precomputed_facts", [])]
            precomputed_assertions = [RequirementAssertion.model_validate(a) for a in enriched_config.get("_l2_precomputed_assertions", [])]
            precomputed_goals = adapt_legacy_goals(enriched_config.get("_l2_precomputed_goals", []))
            precomputed_review_items = enriched_config.get("_l2_manual_review_items", [])

            package = await run_l2_pipeline(
                prd_content=enriched_config.get("prd", ""),
                api_doc_content=enriched_config.get("api_doc", "") or enriched_config.get("swagger", ""),
                changelog_content=enriched_config.get("changelog", ""),
                prototype_notes=enriched_config.get("prototype_url", ""),
                architecture_notes=enriched_config.get("tech_doc", ""),
                rules=rules_str,
                system_map=system_map_evid,
                precomputed_facts=precomputed_facts or None,
                precomputed_assertions=precomputed_assertions or None,
                precomputed_goals=precomputed_goals or None,
                precomputed_review_items=precomputed_review_items or None,
            )

            package_dict = package.model_dump()
            enriched_config["_test_asset_package"] = package_dict
            await log_analysis_package(str(runtime.task_config.get("task_id", task_db_id)), package_dict)

            print(f"  [DEBUG SESSION] L2 Phase 2 done: "
                  f"{len(package.facts)} facts, {len(package.assertions)} assertions, "
                  f"{len(package.candidate_cases)} candidate cases, "
                  f"{len(package.manual_review_items)} manual review items", flush=True)

            get_diag_auto().dump("99_task_config_evolution",
                snapshot_at="after_l2_phase2",
                config_keys=list(enriched_config.keys()),
                has_package="_test_asset_package" in enriched_config,
                l2_facts=len(package.facts),
                l2_assertions=len(package.assertions),
                l2_candidates=len(package.candidate_cases),
                l2_review_gate=len(package.manual_review_items),
                has_system_map=system_map_evid is not None,
            )

            async with async_session() as session:
                task = await session.get(Task, task_db_id)
                if task:
                    task.config = enriched_config
                    await session.commit()
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
