"""core/runtime.py — Runtime orchestrator for the AI Native Testing Platform.

Combines planning and execution subgraphs, manages browser lifecycle,
iterates through test cases, and handles checkpointing.

Lifecycle:
1. __init__: Configure from env/task_config
2. run(): Execute full session (plan -> execute each case -> report)
3. run_stream(): Same as run() but yields WebSocket-compatible updates
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from langchain_core.messages import AIMessage, SystemMessage
from playwright.async_api import async_playwright

from core.interfaces import (
    AssertionResult, ChangeReport, Setup, StepResult, TestCase, TestResult,
    ExplorationGoal, GoalResult, RuntimeExecutableCase, TerminalAssertion,
    CaseResult, ExplorationResult, SystemMapEvid,
)
from core.execution_logger import _task_id_map, log_step, log_test_result, clear_test_case_steps
from agents.ui.planning_graph import build_planning_graph
from agents.ui.execution_graph import build_execution_graph
from agents.ui.setup_manager import execute_setup
from agents.ui.tools import cleanup_task_context, set_cdp_session, set_current_page, set_current_task
from core.report_builder import ReportBuilder
from core.skills.session_summary import generate_case_summary
from core.skills.coverage_tracker import CoverageTracker
from core.diag_logger import get_diag, get_current_task
from database.connection import async_session
from database.models import Report, Task


# Tier 2 (2026-06-05): astream 监听 → 落 06-13 stage
# 节点名 → (stage 标识, mode) 映射
_PLANNING_NODE_STAGE: dict[str, tuple[str, str]] = {
    "extract_goals": ("06_l2_planning_extract_goals", "overwrite"),
    "explore_observe": ("07_l2_planning_explore_step", "append"),
    "explore_decide": ("07_l2_planning_explore_step", "append"),
    "explore_execute": ("07_l2_planning_explore_step", "append"),
    "generate_system_map": ("08_l2_planning_generate_system_map", "overwrite"),
    "extract_scenarios": ("09_l2_planning_extract_scenarios", "overwrite"),
    "generate_plan": ("10_l2_planning_generate_plan", "overwrite"),
}
_EXEC_NODE_STAGE: dict[str, tuple[str, str]] = {
    "observe": ("11_l3_execution_step", "append"),
    "decide": ("11_l3_execution_step", "append"),
    "execute": ("11_l3_execution_step", "append"),
    "assert": ("12_l3_execution_assert", "append"),
    "record": ("13_l3_execution_record", "append"),
}


def _dump_node(node_name: str, state_update: dict[str, Any], stage_map: dict[str, tuple[str, str]]) -> None:
    """Tier 2 helper: 按 stage_map 把 node 输出 dump 到 diag. 不抛错."""
    if node_name not in stage_map:
        return
    stage, mode = stage_map[node_name]
    try:
        diag = get_diag(get_current_task())
        # 精简 fields: 保留 _last_node_* 观测字段 + 关键 state (去掉 messages / screenshot base64)
        slim = {
            "node": node_name,
            "duration_ms": state_update.get("_last_node_duration_ms", "N/A"),
            "token_count": state_update.get("_last_token_count", "N/A"),
        }
        # 保留非巨型字段
        for k in ("current_step", "case_id", "test_case_id", "action_name", "action_result", "assertion"):
            if k in state_update:
                v = state_update[k]
                if isinstance(v, str) and len(v) > 1000:
                    slim[k] = v[:1000] + "..."
                else:
                    slim[k] = v
        # page_info 走 slim_page_info
        if "page_info" in state_update:
            from core.diag_logger import slim_page_info
            slim["page_info"] = slim_page_info(state_update["page_info"])
        diag.dump(stage, mode=mode, **slim)
    except Exception as e:
        sys.stderr.write(f"[Diag] dump_node {node_name}→{stage} failed: {e}\n")


def _now_iso() -> str:
    """Return current time as ISO format string."""
    return datetime.now(timezone.utc).isoformat()


def _should_emit_early_warning(state: dict[str, Any], max_failures: int) -> bool:
    """V2.0 D4 (2026-06-02): 判断当前 state 是否应该推 early_warning 告警.

    设计:
    - 阈值: consecutive_failures >= 2 (留 1 次缓冲给上游, 避免"刚 fail 一次就狂叫")
    - 限频: 1 次/case (用 _early_warning_sent 标志)
    - 边界: cf >= max_failures 时直接触发安全阀, 不发 early-warning (避免重复告警)

    Args:
        state: 当前累积 state
        max_failures: MAX_CONSECUTIVE_FAILURES env

    Returns:
        True if early_warning 应发, False otherwise
    """
    cf = state.get("consecutive_failures", 0)
    threshold = 2
    return (
        cf >= threshold
        and cf < max_failures
        and not state.get("_early_warning_sent", False)
    )


def _stream_items(update: Any) -> list[tuple[str, dict[str, Any]]]:
    """Normalize LangGraph astream updates to (node_name, state_update) pairs."""
    if isinstance(update, tuple) and len(update) == 2 and isinstance(update[0], str):
        node_name, state_update = update
        return [(node_name, state_update or {})]
    if isinstance(update, dict):
        return [
            (node_name, state_update or {})
            for node_name, state_update in update.items()
            if isinstance(node_name, str)
        ]
    return []


class Runtime:
    """Orchestrates a complete test session.

    Lifecycle:
    1. __init__: Configure from env/task_config
    2. run(): Execute full session (plan -> execute each case -> report)
    3. Provides async generator for streaming updates (for WebSocket)
    """

    def __init__(self, task_config: dict[str, Any]):
        self.task_id = str(task_config.get("task_id", uuid.uuid4()))
        self.task_config = task_config
        self.target_url = task_config["target_url"]
        self.browser = None
        self.context = None
        self.page = None
        self._playwright = None
        self._checkpointer = None
        self._stream_results: list[TestResult] = []
        self._case_summaries: list[dict] = []
        self.coverage_tracker = None

    async def run(self) -> list[TestResult]:
        """Execute the full test session.

        Returns:
            List of TestResult for all test cases.
        """
        results: list[TestResult] = []
        set_current_task(self.task_id)
        get_diag(self.task_id).start()
        try:
            # 1. Launch browser
            await self._launch_browser()

            # 2. Run planning subgraph
            test_plan, setups = await self._run_planning()

            # Initialize coverage tracker after planning has collected _explored_urls
            explored_urls = self.task_config.get("_explored_urls", [])
            scenarios = self.task_config.get("_scenarios", [])
            self.coverage_tracker = CoverageTracker(explored_urls, scenarios)

            if self.task_id in _task_id_map:
                from core.execution_logger import log_test_plan
                await log_test_plan(self.task_id, test_plan)

            if not test_plan:
                return results

            # 3. Execute each test case
            for index, test_case in enumerate(test_plan):
                result = await self._execute_test_case(
                    index=index,
                    test_case=test_case,
                    test_plan=test_plan,
                    setups=setups,
                )
                results.append(result)

            if results:
                await self._save_report(results)

        except Exception as e:
            # Log error but don't crash — return partial results
            import traceback
            traceback.print_exc()
        finally:
            await self._close_browser()
            # Diag: 兜底 finalize (api/app.py:_run_test_session 的 finally 也会调, 但 Runtime 单独用时必须自兜底)
            await get_diag(self.task_id).finalize()

        return results

    async def run_stream(self) -> AsyncGenerator[dict[str, Any], None]:
        """Execute the full test session, yielding updates for WebSocket streaming.

        Yields dicts matching the WebSocket message types:
        - ai_thinking (planning exploration)
        - session_complete (with phase: planning_complete or final)
        - page_update / ai_thinking / action_result / assertion_result (per step)
        - test_case_complete
        """
        set_current_task(self.task_id)
        get_diag(self.task_id).start()
        report_saved = False
        try:
            await self._launch_browser()
            self._stream_results = []

            # V1.2: Scenario Extractor is now part of the planning_graph, executed AFTER exploration
            # so it has access to the actual System Map.


            # Run planning with streaming exploration progress
            planning_graph = build_planning_graph()
            planning_state = self._build_initial_state()

            test_plan: list[TestCase] = []
            setups: dict[str, Setup] = {}

            async for stream_update in planning_graph.astream(planning_state):
                for node_name, state_update in _stream_items(stream_update):
                    _dump_node(node_name, state_update, _PLANNING_NODE_STAGE)
                    if node_name == "explore_decide":
                        messages = state_update.get("messages", [])
                        if messages:
                            last_msg = messages[-1]
                            content = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
                            yield {
                                "type": "ai_thinking",
                                "test_case_id": "",
                                "step_index": 0,
                                "data": {"phase": "exploration", "thought": content},
                                "timestamp": _now_iso(),
                            }
                    elif node_name == "explore_execute":
                        messages = state_update.get("messages", [])
                        tool_name = "未知"
                        result_text = "操作已执行，但无返回结果"
                        if messages:
                            msg = messages[-1]
                            tool_name = getattr(msg, "name", "") or getattr(msg, "tool_name", "") or "未知"
                            
                            content = getattr(msg, "content", "")
                            if content:
                                result_text = content if isinstance(content, str) else str(content)
                                
                        yield {
                            "type": "action_result",
                            "test_case_id": "",
                            "step_index": 0,
                            "data": {
                                "phase": "exploration",
                                "tool_name": tool_name,
                                "result": result_text,
                            },
                            "timestamp": _now_iso(),
                        }
                    elif node_name == "explore_observe":
                        page_info = state_update.get("page_info", {})
                        screenshot = state_update.get("screenshot", "")
                        yield {
                            "type": "page_update",
                            "test_case_id": "",
                            "step_index": 0,
                            "data": {
                                "phase": "exploration",
                                "url": page_info.get("url", ""),
                                "screenshot": screenshot,
                            },
                            "timestamp": _now_iso(),
                        }
                    elif node_name == "generate_plan":
                        test_plan = state_update.get("test_plan", [])
                        setups = state_update.get("setups", {})
                        
                        # Initialize coverage tracker
                        cfg = state_update.get("task_config", {})
                        explored_urls = cfg.get("_explored_urls", [])
                        scenarios = cfg.get("_scenarios", [])
                        self.coverage_tracker = CoverageTracker(explored_urls, scenarios)

                        # Sync exploration evidence back to self.task_config
                        # so callers (api/app.py) can access it after run_stream()
                        for key in ("_exploration_history", "_system_map", "_scenarios", "_explored_urls"):
                            if key in cfg:
                                self.task_config[key] = cfg[key]
                        
                        if self.task_id in _task_id_map:
                            from core.execution_logger import log_test_plan
                            await log_test_plan(self.task_id, test_plan)

            yield {
                "type": "session_complete",
                "test_case_id": "",
                "step_index": 0,
                "data": {
                    "phase": "planning_complete",
                    "total_tests": len(test_plan),
                },
                "timestamp": _now_iso(),
            }

            for index, test_case in enumerate(test_plan):
                async for update in self._execute_test_case_stream(
                    index=index,
                    test_case=test_case,
                    test_plan=test_plan,
                    setups=setups,
                ):
                    yield update

            report_path = await self._save_report(self._stream_results)
            report_saved = True
            result_statuses = {
                result.test_case_id: result.status
                for result in self._stream_results
            }
            final_plan = [
                {
                    **test_case.model_dump(),
                    "status": result_statuses.get(test_case.id, "incomplete"),
                }
                for test_case in test_plan
            ]
            final_report = {
                "task_id": self.task_id,
                "status": (
                    "completed"
                    if len(self._stream_results) == len(test_plan)
                    else "failed"
                ),
                "test_plan": final_plan,
                "report_path": report_path,
            }
            yield {
                "type": "session_complete",
                "test_case_id": "",
                "step_index": 0,
                "data": {
                    "phase": "final",
                    "total_tests": len(test_plan),
                    "report_data": final_report,
                },
                "timestamp": _now_iso(),
            }

        except Exception as e:
            yield {
                "type": "session_complete",
                "test_case_id": "",
                "step_index": 0,
                "data": {"error": str(e)},
                "timestamp": _now_iso(),
            }
        finally:
            # Error/partial-run fallback. Successful runs save before final completion.
            if not report_saved:
                try:
                    await self._save_report(self._stream_results)
                except Exception as _report_err:
                    print(f"[Runtime] finally _save_report failed: {_report_err}", flush=True)
            await self._close_browser()
            # Diag: 兜底 finalize
            await get_diag(self.task_id).finalize()

    async def _launch_browser(self):
        """Launch Playwright browser with trace and video recording.
        Now uses BrowserSession to provide DomService accessibility tree.
        """
        from browser_use import BrowserSession, BrowserProfile

        # Create data directory for this task
        data_dir = os.path.join("data", "sessions", self.task_id)
        os.makedirs(data_dir, exist_ok=True)

        profile = BrowserProfile(
            record_video_dir=os.path.join(data_dir, "videos"),
        )
        # V2.0 D+ 调试支持: BROWSER_HEADED=true 启动有头浏览器便于人工观察
        # 默认 headless=true (CI 友好); dev/scratch 脚本可设 BROWSER_HEADED=1
        _headed_env = os.getenv("BROWSER_HEADED", "false").lower() in ("true", "1", "yes")
        print(f"DEBUG: Creating BrowserSession headless={not _headed_env}")
        self.browser_session = BrowserSession(headless=not _headed_env, browser_profile=profile)
        print("DEBUG: Starting BrowserSession")
        await self.browser_session.start()

        print("DEBUG: Starting Playwright")
        self._playwright = await async_playwright().start()
        print("DEBUG: Connecting to CDP")
        self.browser = await self._playwright.chromium.connect_over_cdp(self.browser_session.cdp_url)

        self.context = self.browser.contexts[0]

        # Enable tracing
        print("DEBUG: Starting tracing")
        await self.context.tracing.start(
            screenshots=True,
            snapshots=True,
            sources=True,
        )

        print("DEBUG: Getting page")
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        from core.page_semantic import track_page_requests
        track_page_requests(self.page)
        self.context.on("page", lambda p: track_page_requests(p))
        # Attach the browser_session to the page object so page_semantic.py can use it
        self.page._browser_session = self.browser_session
        set_current_task(self.task_id)
        set_current_page(self.page, task_id=self.task_id)

        # Phase 2.0C: Create CDP session and register with tools
        print("DEBUG: Creating CDP session...")
        try:
            cdp_session = await self.page.context.new_cdp_session(self.page)
            set_cdp_session(cdp_session, task_id=self.task_id)
            self._cdp_session = cdp_session
            print("DEBUG: CDP session created.")
        except Exception as e:
            print(f"DEBUG: CDP session not available (non-Chromium browser?): {e}")
            self._cdp_session = None

        print("DEBUG: Navigating to target URL...")
        # Navigate to target URL
        await self.page.goto(self.target_url, wait_until="load", timeout=30000)
        print("DEBUG: Navigation complete.")

    async def _close_browser(self):
        """Save trace and close browser."""
        try:
            if getattr(self, "context", None):
                trace_path = os.path.join("data", "sessions", self.task_id, "trace.zip")
                await self.context.tracing.stop(path=trace_path)
                await self.context.close()
        except Exception:
            pass
        try:
            if getattr(self, "browser_session", None):
                await self.browser_session.close()
        except Exception:
            pass
        try:
            if getattr(self, "browser", None):
                await self.browser.close()
            if getattr(self, "_playwright", None):
                await self._playwright.stop()
        except Exception:
            pass
        cleanup_task_context(self.task_id)

    def _build_initial_state(self) -> dict[str, Any]:
        """Build the initial state dict for a LangGraph subgraph invocation."""
        return {
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
            "_collected_steps": [],
            "_last_tool_result": "",
            "_last_change_report": None,
            "_last_assertion": None,
            # V2.0 D 可观测性 (2026-06-02)
            "_last_token_count": 0,
            "_last_node_name": "",
            "_last_node_duration_ms": 0,
            "_early_warning_sent": False,
            "_step_token_log": [],
            "task_id": self.task_id,
            "task_config": self.task_config,
            "_locator_stats": {"total": 0, "failed": 0},
        }

    async def _run_planning(self) -> tuple[list[TestCase], dict[str, Setup]]:
        """Run the planning subgraph to generate test plan and setups."""
        # Extract business scenarios from PRD (if provided)
        task_prd = self.task_config.get("prd", "")
        task_changelog = self.task_config.get("changelog", "")
        task_focus = self.task_config.get("focus_areas", "")
        if task_prd or task_changelog:
            scenarios = await extract_scenarios(
                task_prd, 
                task_changelog, 
                task_focus,
                system_map=self.task_config.get("_system_map", {})
            )
            self.task_config["_scenarios"] = scenarios

        planning_graph = build_planning_graph()
        result = await planning_graph.ainvoke(self._build_initial_state())

        # Sync exploration evidence back to self.task_config
        result_tc = result.get("task_config", {})
        for key in ("_exploration_history", "_system_map", "_scenarios", "_explored_urls"):
            if key in result_tc:
                self.task_config[key] = result_tc[key]

        return result.get("test_plan", []), result.get("setups", {})

    # ========================================================================
    # 2026-06-04 retry policy (同行反馈): 用例级重试 + 失败 context 注入
    # ========================================================================

    async def _reset_browser_state(self) -> None:
        """B1.5: 浏览器状态完全重置 — 防止测试用例间/重试间状态污染.

        重置内容:
        - 清 cookies (context.clear_cookies)
        - 清 localStorage + sessionStorage
        - 跳转 about:blank 等待 domcontentloaded
        - 重新导航到 target_url 等 networkidle
        - 等待 DOM 稳定 (_wait_for_stable)
        - 验证 URL 匹配, 不匹配再重试一次

        复用自 _execute_test_case / _execute_test_case_stream 的内联代码 (2026-06-04 抽取).
        """
        is_closed = False
        try:
            if not getattr(self, "page", None) or self.page.is_closed():
                is_closed = True
        except Exception:
            is_closed = True

        if is_closed:
            print("[Runtime] [ResetState] 浏览器页面已关闭/损坏，正在重新启动浏览器...", flush=True)
            try:
                await self._close_browser()
            except Exception:
                pass
            await self._launch_browser()
            return

        print("[Runtime] [ResetState] Starting browser-state reset...", flush=True)
        try:
            if getattr(self, "context", None):
                print("[Runtime] [ResetState] Clearing cookies...", flush=True)
                await self.context.clear_cookies()
            if getattr(self, "page", None):
                try:
                    print("[Runtime] [ResetState] Clearing localStorage & sessionStorage...", flush=True)
                    await self.page.evaluate("localStorage.clear(); sessionStorage.clear();")
                    print("[Runtime] [ResetState] Navigating to about:blank...", flush=True)
                    await self.page.goto("about:blank", wait_until="domcontentloaded", timeout=15000)
                except Exception as e:
                    print(f"[Runtime] [ResetState] (Non-fatal) Clear/blank failed: {e}", flush=True)
                print("[Runtime] [ResetState] Navigating to target URL...", flush=True)
                await self.page.goto(self.target_url, wait_until="networkidle", timeout=30000)
                from agents.ui.tools import _wait_for_stable
                try:
                    print("[Runtime] [ResetState] Waiting for DOM stability...", flush=True)
                    await _wait_for_stable(self.page, timeout=3000, poll_interval=300)
                except Exception:
                    pass
                current_url = self.page.url
                if not current_url.startswith(self.target_url.rstrip("/")):
                    print("[Runtime] [ResetState] URL mismatch after reset, retrying navigation...", flush=True)
                    await self.page.goto(self.target_url, wait_until="load", timeout=30000)
            print("[Runtime] [ResetState] Browser state reset completed.", flush=True)
        except Exception as e:
            print(f"[Runtime] [ResetState] 增强状态重置失败: {e}，将强制重新启动浏览器以恢复连接...", flush=True)
            try:
                await self._close_browser()
            except Exception:
                pass
            try:
                await self._launch_browser()
            except Exception as launch_err:
                print(f"[Runtime] [ResetState] 强制重新启动浏览器失败: {launch_err}", flush=True)

    async def _capture_failure_context(
        self,
        page: Any | None,
        collected_steps: list[StepResult],
        attempt: int,
    ) -> dict[str, Any]:
        """捕获上一次失败尝试的 context, 注入下一次重试的 prompt.

        包含字段:
        - attempt: 1-indexed 失败尝试编号 (给人类读)
        - failed_step_index / failed_action / failed_action_target / failed_action_args
        - assertion_status / assertion_reasoning (为什么 fail)
        - screenshot_path: 失败时的截图 (落地到 data/screenshots/{task_id}/)
        - url_after: 失败时的 URL
        - a11y_tree: page.accessibility.snapshot() 序列化, 截断到 10KB (保护 L2_TOKEN_BUDGET)

        如果 page 为 None 或 captured 失败, 仍返回基础 dict (without screenshot/a11y).
        """
        # 找最后一个失败步骤
        last_step: StepResult | None = None
        for s in reversed(collected_steps):
            if s.assertion and s.assertion.status == "fail":
                last_step = s
                break
        if last_step is None and collected_steps:
            last_step = collected_steps[-1]

        if last_step is None:
            return {
                "attempt": attempt,
                "no_step": True,
                "reason": "no steps collected before failure",
            }

        # 截屏
        screenshot_path = ""
        if page is not None:
            try:
                dir_path = f"data/screenshots/{self.task_id}"
                os.makedirs(dir_path, exist_ok=True)
                screenshot_path = f"{dir_path}/retry{attempt}_step{last_step.step_index}.png"
                await page.screenshot(path=screenshot_path, full_page=False, timeout=5000)
            except Exception as e:
                print(f"[Runtime] 重试 context 截图失败: {e}")
                screenshot_path = ""

        # a11y 树 (截断到 10KB)
        a11y_tree = ""
        if page is not None:
            try:
                snap = await page.accessibility.snapshot()
                a11y_tree = json.dumps(snap, ensure_ascii=False, default=str)
                if len(a11y_tree) > 10240:  # 10KB 硬截断, 留 20% L2 budget 缓冲
                    a11y_tree = a11y_tree[:10240] + "\n... (a11y tree truncated to 10KB)"
            except Exception as e:
                print(f"[Runtime] 重试 context a11y 树失败: {e}")
                a11y_tree = ""

        # URL
        url_after = ""
        if page is not None:
            try:
                url_after = page.url
            except Exception:
                url_after = ""

        assertion = last_step.assertion
        return {
            "attempt": attempt,
            "failed_step_index": last_step.step_index,
            "failed_action": last_step.action_type,
            "failed_action_target": str(last_step.action_target) if last_step.action_target else "",
            "failed_action_args": last_step.action_args or {},
            "assertion_status": assertion.status if assertion else "unknown",
            "assertion_reasoning": assertion.reasoning if assertion else "",
            "screenshot_path": screenshot_path,
            "url_after": url_after,
            "a11y_tree": a11y_tree,
        }

    def _format_failure_context_message(
        self,
        failure_context: dict[str, Any],
        test_case: TestCase,
    ) -> str:
        """把 failure_context 格式化成 SystemMessage 内容, 注入下一次重试.

        注入位置: messages[0] (前置, 跟现有 previous_context 风格一致).
        内容顺序: 失败摘要 → 步骤详情 → 断言 → 截图 → a11y 树 → 建议.
        """
        if failure_context.get("no_step"):
            return (
                f"开始执行测试用例: {test_case.id} - {test_case.title}\n\n"
                f"[上一次尝试 #{failure_context['attempt']} 失败] 原因: {failure_context.get('reason', '未知')}\n"
                f"请重试."
            )

        lines = [
            f"开始执行测试用例: {test_case.id} - {test_case.title}",
            "",
            f"[上一次尝试 #{failure_context['attempt']} 失败 — 请换策略重试]",
            f"- 失败步骤: step {failure_context['failed_step_index']} — "
            f"{failure_context['failed_action']}('{failure_context['failed_action_target']}')",
        ]
        if failure_context.get("failed_action_args"):
            lines.append(f"  args: {failure_context['failed_action_args']}")
        lines.append(
            f"- 断言结果: {failure_context['assertion_status']} — {failure_context['assertion_reasoning']}"
        )
        if failure_context.get("url_after"):
            lines.append(f"- 当前 URL: {failure_context['url_after']}")
        if failure_context.get("screenshot_path"):
            lines.append(f"- 失败截图: {failure_context['screenshot_path']}")
        if failure_context.get("a11y_tree"):
            lines.append(
                f"- 页面结构 (a11y tree, 截断到 10KB):\n{failure_context['a11y_tree']}"
            )
        lines.append(
            "\n请重试, 建议考虑: 换 selector / 加 wait / 先关闭弹窗 / 调整执行顺序"
        )
        return "\n".join(lines)

    def _build_execution_state(
        self,
        test_case: TestCase,
        test_plan: list[TestCase],
        setups: dict[str, Setup],
        index: int,
        failure_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """构造 execution_state, 注入 session_summary + (可选) failure_context SystemMessage.

        抽取自 _execute_test_case / _execute_test_case_stream 的内联代码 (2026-06-04).
        failure_context 不为 None 时, 把上一轮失败信息拼到 messages[0] 顶部, 跟现有
        previous_context 风格一致.
        """
        execution_state = self._build_initial_state()
        execution_state["test_plan"] = test_plan
        execution_state["setups"] = setups
        execution_state["current_index"] = index

        # V2.0 A3: 前序 case 摘要 (跨用例 context)
        previous_context = ""
        if self._case_summaries:
            summaries_text = "\n".join(
                f"- {s['case_id']}: {s.get('summary', '')}" for s in self._case_summaries
            )
            previous_context = f"\n\n前面已完成的测试用例摘要:\n{summaries_text}"
        execution_state["session_summary"] = (
            "\n".join(
                f"- {s['case_id']}: {s.get('summary', '')}" for s in self._case_summaries
            )
            if self._case_summaries
            else ""
        )

        # messages[0] — 起始 SystemMessage
        if failure_context is not None:
            content = self._format_failure_context_message(failure_context, test_case)
        else:
            content = f"开始执行测试用例: {test_case.id} - {test_case.title}{previous_context}"

        execution_state["messages"] = [SystemMessage(content=content)]
        return execution_state

    def _determine_status(
        self,
        final_state: dict[str, Any],
        collected_steps: list[StepResult],
    ) -> str:
        """判定用例最终状态. 跟原内联逻辑一致, 抽取成方法便于复用."""
        max_failures = int(os.getenv("MAX_CONSECUTIVE_FAILURES", "3"))
        max_steps = int(os.getenv("MAX_STEPS_PER_CASE", "15"))

        if final_state.get("consecutive_failures", 0) >= max_failures:
            return "failed"
        if final_state.get("current_step", 0) >= max_steps:
            return "incomplete"
        if any(s.assertion and s.assertion.status == "fail" for s in collected_steps if getattr(s, "assertion", None) is not None):
            return "failed"
        if any(s.assertion and s.assertion.status == "pass" for s in collected_steps if getattr(s, "assertion", None) is not None):
            return "passed"
        return "incomplete"

    async def _execute_test_case(
        self,
        index: int,
        test_case: TestCase,
        test_plan: list[TestCase],
        setups: dict[str, Setup],
    ) -> TestResult:
        """Execute a single test case, with case-level retry on failure (2026-06-04 同行反馈).

        重试策略 (env: MAX_TEST_CASE_RETRIES, 默认 2 → 总 3 次尝试):
        1. 第 1 次失败 → 抓 failure_context (screenshot + a11y tree + assertion)
        2. 重置 browser state
        3. 用 failure_context 注入 SystemMessage 顶部, 整个用例从头跑
        4. 第 2 次失败 → 同样流程, 但 capture 新的 failure_context
        5. 第 3 次仍 fail → status="human_review_required", 保留所有 failure_contexts

        兼容: 当 MAX_TEST_CASE_RETRIES=0 时, 退化为旧行为 (单次尝试).
        """
        start_time = time.time()
        max_retries = int(os.getenv("MAX_TEST_CASE_RETRIES", "2"))
        failure_contexts: list[dict[str, Any]] = []
        final_status = "incomplete"
        final_steps: list[StepResult] = []
        attempts_used = 0

        for attempt in range(max_retries + 1):
            attempts_used = attempt + 1

            # 重试或后续用例首尝时: 重置 browser state
            if attempt > 0 or index > 0:
                await self._reset_browser_state()

            # Execute setups (每次重试都重新跑, 假设 setup 可能被前次失败污染)
            setup_results: list[Any] = []
            for precondition_id in test_case.preconditions:
                if precondition_id in setups:
                    setup = setups[precondition_id]
                    base_state = self._build_initial_state()
                    base_state["test_plan"] = test_plan
                    base_state["setups"] = setups
                    base_state["current_index"] = index
                    setup_result = await execute_setup(setup, base_state)
                    setup_results.append(setup_result)

            # Build execution state — retry 时注入 failure_context
            failure_ctx = failure_contexts[-1] if failure_contexts else None
            execution_state = self._build_execution_state(
                test_case, test_plan, setups, index, failure_context=failure_ctx
            )

            # Run execution subgraph
            if self.task_id in _task_id_map:
                await clear_test_case_steps(self.task_id, test_case.id)
            execution_graph = build_execution_graph()
            try:
                result_state = await execution_graph.ainvoke(execution_state)
            except Exception:
                # Browser crash — try to recover
                result_state = await self._handle_browser_crash(test_case, execution_state)

            steps = result_state.get("_collected_steps", [])
            status = self._determine_status(result_state, steps)

            if status != "failed" or attempt >= max_retries:
                final_status = status
                final_steps = steps
                break

            # Failed 且还有重试机会: 抓 failure_context, 准备下一轮
            try:
                fc = await self._capture_failure_context(
                    getattr(self, "page", None), steps, attempt + 1
                )
            except Exception as e:
                print(f"[Runtime] 抓 failure_context 失败: {e}")
                fc = {"attempt": attempt + 1, "no_step": True, "reason": str(e)}
            failure_contexts.append(fc)
            final_steps = steps  # 保留最后一次失败的 steps, 用于报告
            print(
                f"[Runtime] 用例 {test_case.id} 第 {attempt + 1}/{max_retries + 1} 次失败, "
                f"准备重试 (断言: {fc.get('assertion_status', '?')})"
            )

        duration = time.time() - start_time

        # 3 次都失败 → human_review_required
        if final_status == "failed" and attempts_used >= max_retries + 1 and failure_contexts:
            final_status = "human_review_required"

        test_result = TestResult(
            test_case_id=test_case.id,
            status=final_status,
            steps=final_steps,
            summary=f"{'通过' if final_status == 'passed' else '失败' if final_status == 'failed' else '需人工'}: {test_case.title}",
            duration_seconds=duration,
            setup_results=[],
            retry_count=attempts_used - 1,  # 0=首次成功, 1-2=重试次数
            failure_context=failure_contexts,
        )

        # Generate session summary for cross-case context
        try:
            urls = set()
            for s in final_steps:
                if s.change_report:
                    if s.change_report.url_before: urls.add(s.change_report.url_before)
                    if s.change_report.url_after: urls.add(s.change_report.url_after)
            page_urls = list(urls)

            if getattr(self, "coverage_tracker", None):
                self.coverage_tracker.auto_match_scenario(test_case.title)
                for u in page_urls:
                    self.coverage_tracker.mark_url_covered(u)

            summary = await generate_case_summary(
                test_case_id=test_case.id,
                test_case_title=test_case.title,
                status=final_status,
                steps=final_steps,
                page_urls=page_urls,
            )
            self._case_summaries.append(summary)
        except Exception:
            pass

        return test_result

    async def _execute_test_case_stream(
        self,
        index: int,
        test_case: TestCase,
        test_plan: list[TestCase],
        setups: dict[str, Setup],
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Execute a test case with case-level retry on failure (2026-06-04 同行反馈).

        Emits WebSocket events for each node in the execution graph:
        - observe  → page_update (url, title)
        - decide   → ai_thinking (thought, tool_calls)
        - execute  → action_result (tool_name, tool_args, result)
        - assert   → assertion_result (change_report, assertion)
        - record   → (internal, no event)
        - test_case_retry → (before each retry, 1-indexed attempt info)
        Finally emits test_case_complete (once, after all attempts).

        重试策略 (env: MAX_TEST_CASE_RETRIES, 默认 2 → 总 3 次尝试):
        失败 → capture failure_context → 重置 browser → 注入 SystemMessage → 从头重跑.
        3 次都 fail → status="human_review_required".
        """
        start_time = time.time()
        max_retries = int(os.getenv("MAX_TEST_CASE_RETRIES", "2"))
        failure_contexts: list[dict[str, Any]] = []
        final_status = "incomplete"
        final_steps: list[StepResult] = []
        final_state: dict[str, Any] = {}
        attempts_used = 0

        for attempt in range(max_retries + 1):
            attempts_used = attempt + 1

            # ── 重试或后续用例首尝: yield 事件 + 重置浏览器 ──────────────────────────
            if attempt > 0 or index > 0:
                if attempt > 0:
                    last_fc = failure_contexts[-1]
                    yield {
                        "type": "test_case_retry",
                        "test_case_id": test_case.id,
                        "step_index": 0,
                        "data": {
                            "attempt": attempt + 1,  # 1-indexed for human
                            "max_retries": max_retries + 1,
                            "previous_status": last_fc.get("assertion_status", "unknown"),
                            "previous_reasoning": last_fc.get("assertion_reasoning", ""),
                            "screenshot_path": last_fc.get("screenshot_path", ""),
                        },
                        "timestamp": _now_iso(),
                    }
                await self._reset_browser_state()

            # ── Execute setups ───────────────────────────────────────────
            for precondition_id in test_case.preconditions:
                if precondition_id in setups:
                    setup = setups[precondition_id]
                    yield {
                        "type": "setup_progress",
                        "test_case_id": test_case.id,
                        "step_index": 0,
                        "data": {"status": "starting", "description": setup.description},
                        "timestamp": _now_iso(),
                    }
                    base_state = self._build_initial_state()
                    base_state["test_plan"] = test_plan
                    base_state["setups"] = setups
                    base_state["current_index"] = index
                    await execute_setup(setup, base_state)
                    yield {
                        "type": "setup_progress",
                        "test_case_id": test_case.id,
                        "step_index": 0,
                        "data": {"status": "completed", "description": setup.description},
                        "timestamp": _now_iso(),
                    }

            # ── Build execution state (retry 时注入 failure_context) ────
            failure_ctx = failure_contexts[-1] if failure_contexts else None
            execution_state = self._build_execution_state(
                test_case, test_plan, setups, index, failure_context=failure_ctx
            )

            # ── Run execution subgraph with streaming ────────────────────
            if self.task_id in _task_id_map:
                await clear_test_case_steps(self.task_id, test_case.id)
            execution_graph = build_execution_graph()
            collected_steps: list[StepResult] = []
            final_state = dict(execution_state)

            try:
                async for stream_update in execution_graph.astream(execution_state):
                    for node_name, state_update in _stream_items(stream_update):
                        _dump_node(node_name, state_update, _EXEC_NODE_STAGE)
                        print(f"[DEBUG RUNTIME] node_name={node_name}, keys={list(state_update.keys()) if isinstance(state_update, dict) else type(state_update)}", flush=True)
                        # Accumulate state from each node
                        final_state.update(state_update)

                        # V2.0 D2: 节点级 observability
                        if "_last_node_name" in state_update:
                            yield {
                                "type": "node_event",
                                "test_case_id": test_case.id,
                                "step_index": final_state.get("current_step", 0),
                                "data": {
                                    "node": state_update.get("_last_node_name", node_name),
                                    "duration_ms": state_update.get("_last_node_duration_ms", 0),
                                    "token_count": state_update.get("_last_token_count", 0),
                                },
                                "timestamp": _now_iso(),
                            }

                        # V2.0 D4: consecutive_failures >= 2 early-warning
                        max_failures_now = int(os.getenv("MAX_CONSECUTIVE_FAILURES", "3"))
                        if _should_emit_early_warning(final_state, max_failures_now):
                            cf = final_state.get("consecutive_failures", 0)
                            final_state["_early_warning_sent"] = True
                            yield {
                                "type": "early_warning",
                                "test_case_id": test_case.id,
                                "step_index": final_state.get("current_step", 0),
                                "data": {
                                    "consecutive_failures": cf,
                                    "threshold": 2,
                                    "max": max_failures_now,
                                    "message": f"⚠️ 连续失败 {cf} 次, 即将触发安全阀 (上限 {max_failures_now})",
                                },
                                "timestamp": _now_iso(),
                            }

                        if node_name == "observe":
                            page_info = state_update.get("page_info", {})
                            yield {
                                "type": "page_update",
                                "test_case_id": test_case.id,
                                "step_index": final_state.get("current_step", 0),
                                "data": {
                                    "url": page_info.get("url", ""),
                                    "title": page_info.get("title", ""),
                                    "screenshot": state_update.get("screenshot", ""),
                                },
                                "timestamp": _now_iso(),
                            }

                        elif node_name == "decide":
                            messages = state_update.get("messages", [])
                            if messages:
                                last_msg = messages[-1]
                                content = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
                                from core.llm_client import extract_tool_calls_from_message
                                tool_calls = extract_tool_calls_from_message(last_msg)
                                final_state["_last_tool_calls"] = tool_calls
                                yield {
                                    "type": "ai_thinking",
                                    "test_case_id": test_case.id,
                                    "step_index": final_state.get("current_step", 0),
                                    "data": {
                                        "thought": content,
                                        "tool_calls": [
                                            {"name": tc.get("name", ""), "args": tc.get("args", {})}
                                            for tc in tool_calls
                                        ],
                                    },
                                    "timestamp": _now_iso(),
                                }

                        elif node_name == "execute":
                            tool_calls = final_state.get("_last_tool_calls", [])
                            tool_name = tool_calls[0].get("name", "") if tool_calls else ""
                            tool_args = tool_calls[0].get("args", {}) if tool_calls else {}
                            result_text = state_update.get("_last_tool_result", "")

                            yield {
                                "type": "action_result",
                                "test_case_id": test_case.id,
                                "step_index": state_update.get("current_step", 0),
                                "data": {
                                    "tool_name": tool_name or "未知",
                                    "tool_args": tool_args,
                                    "result": result_text or "操作已执行，但无返回结果",
                                },
                                "timestamp": _now_iso(),
                            }

                        elif node_name == "assert":
                            yield {
                                "type": "assertion_result",
                                "test_case_id": test_case.id,
                                "step_index": final_state.get("current_step", 0),
                                "data": {
                                    "change_report": state_update.get("_last_change_report").model_dump() if state_update.get("_last_change_report") else None,
                                    "assertion": state_update.get("_last_assertion").model_dump() if state_update.get("_last_assertion") else None,
                                },
                                "timestamp": _now_iso(),
                            }

                        elif node_name == "record":
                            new_steps = state_update.get("_collected_steps", [])
                            if new_steps:
                                collected_steps.extend(new_steps)
                                for step in new_steps:
                                    await log_step(self.task_id, test_case.id, step)

            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"[DEBUG] _execute_test_case_stream attempt {attempt + 1} crashed: {e}")
                final_state = await self._handle_browser_crash(test_case, execution_state)
                collected_steps = final_state.get("_collected_steps", [])

            # ── 判定本次 attempt 状态 ──────────────────────────────────
            status = self._determine_status(final_state, collected_steps)

            # 成功或达到最大重试次数 → 结束循环
            if status != "failed" or attempt >= max_retries:
                final_status = status
                final_steps = collected_steps
                break

            # 失败且还有重试机会 → 抓 failure_context, 准备下一轮
            try:
                fc = await self._capture_failure_context(
                    getattr(self, "page", None), collected_steps, attempt + 1
                )
            except Exception as e:
                print(f"[Runtime] 抓 failure_context 失败: {e}")
                fc = {"attempt": attempt + 1, "no_step": True, "reason": str(e)}
            failure_contexts.append(fc)
            final_steps = collected_steps
            print(
                f"[Runtime] 用例 {test_case.id} 第 {attempt + 1}/{max_retries + 1} 次失败, "
                f"准备重试 (断言: {fc.get('assertion_status', '?')})"
            )

        # ── 循环结束, 构建最终 TestResult ──────────────────────────────
        if final_status == "failed" and attempts_used >= max_retries + 1 and failure_contexts:
            final_status = "human_review_required"

        duration = time.time() - start_time

        result = TestResult(
            test_case_id=test_case.id,
            status=final_status,
            steps=final_steps,
            summary=f"{'通过' if final_status == 'passed' else '失败' if final_status == 'failed' else '需人工'}: {test_case.title}",
            duration_seconds=duration,
            setup_results=[],
            retry_count=attempts_used - 1,
            failure_context=failure_contexts,
        )
        self._stream_results.append(result)

        # Generate session summary for cross-case context
        try:
            urls = set()
            for s in final_steps:
                if s.change_report:
                    if s.change_report.url_before: urls.add(s.change_report.url_before)
                    if s.change_report.url_after: urls.add(s.change_report.url_after)
            page_urls = list(urls)

            if getattr(self, "coverage_tracker", None):
                self.coverage_tracker.auto_match_scenario(test_case.title)
                for u in page_urls:
                    self.coverage_tracker.mark_url_covered(u)

            summary = await generate_case_summary(
                test_case_id=test_case.id,
                test_case_title=test_case.title,
                status=final_status,
                steps=final_steps,
                page_urls=page_urls,
            )
            self._case_summaries.append(summary)
        except Exception:
            pass

        await log_test_result(self.task_id, result)

        yield {
            "type": "test_case_complete",
            "test_case_id": test_case.id,
            "step_index": 0,
            "data": {
                "status": result.status,
                "summary": result.summary,
                "duration": result.duration_seconds,
                "retry_count": result.retry_count,
            },
            "timestamp": _now_iso(),
        }

    async def _handle_browser_crash(
        self, test_case: TestCase, state: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle browser crash: restart and return error state."""
        try:
            await self._close_browser()
            await self._launch_browser()
        except Exception:
            pass

        return {
            **state,
            "consecutive_failures": int(os.getenv("MAX_CONSECUTIVE_FAILURES", "3")),
            "_collected_steps": [],
        }

    async def _save_report(self, results: list[TestResult]) -> str:
        """Build the HTML report and persist a report row when a DB task exists."""
        builder = ReportBuilder(task_id=self.task_id)
        for result in results:
            builder.add_result(result)

        if getattr(self, "coverage_tracker", None):
            builder.set_coverage(self.coverage_tracker.get_coverage_report())

        # Generate AI summary
        ai_summary = ""
        try:
            ai_summary = await builder.generate_summary(results)
        except Exception as e:
            print(f"[ReportBuilder] AI summary generation failed: {e}")
            ai_summary = f"共 {len(results)} 个用例，{sum(1 for r in results if r.status == 'passed')} 个通过，{sum(1 for r in results if r.status == 'failed')} 个失败。"

        report_path = os.path.join("data", "reports", self.task_id, "report.html")
        saved_path = builder.save(report_path, ai_summary=ai_summary)

        db_task_id = _task_id_map.get(self.task_id)
        if db_task_id is None:
            try:
                db_task_id = int(self.task_id)
            except ValueError:
                return saved_path

        summary = f"共 {len(results)} 个用例，{sum(1 for r in results if r.status == 'passed')} 个通过。"
        try:
            async with async_session() as session:
                # Update task statistics
                task = await session.get(Task, db_task_id)
                if task:
                    task.total_tests = len(results)
                    task.passed_tests = sum(1 for r in results if r.status == "passed")
                    task.failed_tests = sum(1 for r in results if r.status in ("failed", "incomplete", "human_review_required"))
                session.add(Report(task_id=db_task_id, report_path=saved_path, summary=summary))
                await session.commit()
        except Exception:
            # Report file is still useful when DB persistence is unavailable.
            pass
        # Diag: 报告层 dump
        from core.diag_logger import get_diag
        get_diag(self.task_id).dump("15_report_summary", node="ReportBuilder",
                                    report_path=saved_path,
                                    total_tests=len(results),
                                    passed_tests=sum(1 for r in results if r.status == "passed"),
                                    failed_tests=sum(1 for r in results if r.status == "failed"),
                                    incomplete=sum(1 for r in results if r.status == "incomplete"),
                                    human_review_required=sum(1 for r in results if r.status == "human_review_required"),
                                    ai_summary_preview=ai_summary[:200] if ai_summary else "")
        return saved_path

    # ========================================================================
    # M2: Runtime explore/execute 拆分 — 目标驱动执行
    # ========================================================================

    async def explore(
        self, goals: list[ExplorationGoal]
    ) -> ExplorationResult:
        """目标驱动探索阶段。

        为每个 Goal 产出 GoalResult，收集 SystemMapEvid 作为唯一权威探索证据。

        Args:
            goals: 严格探索目标列表

        Returns:
            ExplorationResult 包含 system_map 和 goal_results
        """
        from core.interfaces import GoalResult, SystemMapEvid, PageMap

        goal_results: list[GoalResult] = []
        all_pages: list[PageMap] = []

        for goal in goals:
            try:
                result = await self._explore_single_goal(goal)
                goal_results.append(result)

                # 收集探索证据到 SystemMapEvid
                if result.status == "found":
                    page_info = getattr(self, "_last_page_info", {})
                    if page_info:
                        page_map = PageMap(
                            name=page_info.get("title", ""),
                            url_pattern=page_info.get("url", ""),
                            title=page_info.get("title", ""),
                            elements=page_info.get("elements", []),
                        )
                        all_pages.append(page_map)
            except Exception as e:
                goal_results.append(GoalResult(
                    goal_id=goal.id,
                    status="blocked",
                    stop_reason=f"探索异常: {str(e)}",
                    observed_at=_now_iso(),
                ))

        system_map = SystemMapEvid(pages=all_pages)

        return ExplorationResult(
            system_map=system_map,
            goal_results=goal_results,
        )

    async def _explore_single_goal(self, goal: ExplorationGoal) -> GoalResult:
        """探索单个目标，返回 GoalResult。"""
        max_steps = int(os.getenv("MAX_EXPLORE_STEPS_PER_GOAL", "10"))
        step_count = 0

        while step_count < max_steps:
            page_info = await self._observe_page()
            self._last_page_info = page_info

            if self._check_stop_condition(goal, page_info):
                return GoalResult(
                    goal_id=goal.id,
                    status="found",
                    evidence_refs=[page_info.get("url", "")],
                    stop_reason=f"满足停止条件: {goal.stop_condition}",
                    observed_at=_now_iso(),
                )

            action = await self._decide_explore_action(goal, page_info, step_count)
            if action is None:
                return GoalResult(
                    goal_id=goal.id,
                    status="insufficient",
                    stop_reason="无法决定下一步探索行动",
                    observed_at=_now_iso(),
                )

            await self._execute_explore_action(action)
            step_count += 1

        return GoalResult(
            goal_id=goal.id,
            status="insufficient",
            stop_reason=f"达到最大探索步数 {max_steps}，未找到充分证据",
            observed_at=_now_iso(),
        )

    async def _observe_page(self) -> dict[str, Any]:
        """观察当前页面状态。"""
        try:
            from core.page_semantic import extract_page_semantics
            return await extract_page_semantics(self.page)
        except Exception as e:
            return {"url": self.page.url if self.page else "", "error": str(e)}

    def _check_stop_condition(
        self, goal: ExplorationGoal, page_info: dict[str, Any]
    ) -> bool:
        """检查是否满足 Goal 的 stop_condition。"""
        page_text = str(page_info).lower()
        for evidence in goal.expected_evidence:
            if evidence.lower() in page_text:
                return True
        return False

    async def _decide_explore_action(
        self, goal: ExplorationGoal, page_info: dict[str, Any], step_count: int
    ) -> dict[str, Any] | None:
        """LLM 决定探索下一步行动。"""
        from langchain_core.messages import SystemMessage, HumanMessage

        prompt = f"""你是一个探索 agent，目标是找到支持以下断言的证据:

目标: {goal.goal}
预期证据: {', '.join(goal.expected_evidence)}
停止条件: {goal.stop_condition}

当前页面:
URL: {page_info.get('url', '')}
标题: {page_info.get('title', '')}

已完成 {step_count} 步探索。请决定下一步行动。
返回 JSON: {{"tool": "click|navigate|scroll|wait", "args": {{"selector": "..." or "url": "..." or "direction": "down"}}}}
如果已找到证据: {{"tool": "mark_task_complete", "args": {{"summary": "证据"}}}}
如果无法继续: {{"tool": "mark_task_failed", "args": {{"reason": "原因"}}}}
"""
        try:
            from core.llm_client import get_llm_client
            llm = get_llm_client("haiku")
            response = await llm.ainvoke([
                SystemMessage(content="你是探索 agent。"),
                HumanMessage(content=prompt),
            ])
            content = response.content if isinstance(response.content, str) else str(response.content)
            import json
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(content[start:end])
        except Exception as e:
            print(f"[Runtime] explore decide error: {e}")
        return None

    async def _execute_explore_action(self, action: dict[str, Any]) -> None:
        """执行探索行动。"""
        tool_name = action.get("tool", "")
        args = action.get("args", {})
        try:
            if tool_name == "click":
                selector = args.get("selector", "")
                if selector:
                    await self.page.click(selector)
            elif tool_name == "navigate":
                url = args.get("url", "")
                if url:
                    await self.page.goto(url, wait_until="load", timeout=30000)
            elif tool_name == "scroll":
                direction = args.get("direction", "down")
                delta = 500 if direction == "down" else -500
                await self.page.evaluate(f"window.scrollBy(0, {delta})")
            elif tool_name == "wait":
                await self.page.wait_for_timeout(args.get("ms", 1000))
        except Exception as e:
            print(f"[Runtime] explore action error: {e}")

    async def execute(
        self, executable_cases: list[RuntimeExecutableCase]
    ) -> list[CaseResult]:
        """目标驱动执行阶段。"""
        return [await self._execute_single_case(case) for case in executable_cases]

    async def _execute_single_case(self, case: RuntimeExecutableCase) -> CaseResult:
        """执行单个用例，产出 CaseResult。"""
        start_time = time.time()
        max_steps = int(os.getenv("MAX_STEPS_PER_CASE", "15"))

        precondition_result = await self._check_preconditions(case)
        if precondition_result is not None:
            return precondition_result

        steps_executed = 0
        evidence_collected: list[str] = []

        while steps_executed < max_steps:
            page_info = await self._observe_page()
            terminal = await self._evaluate_terminal_assertion(
                case, page_info, evidence_collected
            )

            if terminal is not None:
                return CaseResult(
                    run_id="",
                    candidate_case_id=case.id,
                    terminal_status="passed" if self._all_terminal_satisfied(terminal) else "failed",
                    attempt_count=1,
                    started_at=_now_iso(),
                    completed_at=_now_iso(),
                    summary=f"{'通过' if self._all_terminal_satisfied(terminal) else '失败'}: {case.objective}",
                    evidence_refs=evidence_collected,
                    failure_reason=None if self._all_terminal_satisfied(terminal) else
                        f"objective={terminal.objective_satisfied}, "
                        f"expected={terminal.expected_result_supported}, "
                        f"evidence={terminal.terminal_evidence_sufficient}",
                )

            action = await self._decide_execute_action(case, page_info, steps_executed)
            if action is None:
                break

            result = await self._execute_test_action(action)
            if result:
                evidence_collected.append(result)
            steps_executed += 1

        return CaseResult(
            run_id="",
            candidate_case_id=case.id,
            terminal_status="incomplete",
            attempt_count=1,
            started_at=_now_iso(),
            completed_at=_now_iso(),
            summary=f"未完成: {case.objective}",
            evidence_refs=evidence_collected,
            failure_reason=f"达到最大步数 {max_steps} 或无法继续",
        )

    async def _check_preconditions(self, case: RuntimeExecutableCase) -> CaseResult | None:
        """检查前置条件。"""
        for precond in case.preconditions:
            if not precond.satisfiable_by_agent:
                status_map = {
                    "skipped": "skipped",
                    "human_review_required": "human_review_required",
                    "failed": "failed",
                }
                terminal = status_map.get(precond.failure_policy, "incomplete")
                return CaseResult(
                    run_id="",
                    candidate_case_id=case.id,
                    terminal_status=terminal,
                    attempt_count=0,
                    started_at=_now_iso(),
                    completed_at=_now_iso(),
                    summary=f"前置条件: {precond.description}",
                    failure_reason=f"precondition_{precond.failure_policy}: {precond.description}",
                )

            if precond.type == "account_role" and not precond.required_role:
                return CaseResult(
                    run_id="",
                    candidate_case_id=case.id,
                    terminal_status="incomplete",
                    attempt_count=0,
                    started_at=_now_iso(),
                    completed_at=_now_iso(),
                    summary="账号角色未解析",
                    failure_reason="account_role_unresolved",
                )
        return None

    async def _evaluate_terminal_assertion(
        self,
        case: RuntimeExecutableCase,
        page_info: dict[str, Any],
        evidence_refs: list[str],
    ) -> TerminalAssertion | None:
        """评估终态判定三条件。"""
        from langchain_core.messages import SystemMessage, HumanMessage

        prompt = f"""评估当前页面是否达到终态。

目标: {case.objective}
预期结果: {case.expected}
URL: {page_info.get('url', '')}
标题: {page_info.get('title', '')}
已收集证据: {evidence_refs[-3:] if evidence_refs else '无'}

返回 JSON:
{{"objective_satisfied": bool, "expected_result_supported": bool, "terminal_evidence_sufficient": bool, "reasoning": "..."}}
如果还需观察: {{"need_more_observation": true}}
"""
        try:
            from core.llm_client import get_llm_client
            llm = get_llm_client("haiku")
            response = await llm.ainvoke([
                SystemMessage(content="你是测试执行 agent。"),
                HumanMessage(content=prompt),
            ])
            content = response.content if isinstance(response.content, str) else str(response.content)
            import json
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                result = json.loads(content[start:end])
                if result.get("need_more_observation"):
                    return None
                return TerminalAssertion(
                    objective_satisfied=result.get("objective_satisfied", False),
                    expected_result_supported=result.get("expected_result_supported", False),
                    terminal_evidence_sufficient=result.get("terminal_evidence_sufficient", False),
                    reasoning=result.get("reasoning", ""),
                )
        except Exception as e:
            print(f"[Runtime] terminal assertion error: {e}")
        return None

    def _all_terminal_satisfied(self, terminal: TerminalAssertion) -> bool:
        """判断终态三条件是否全部满足。"""
        return (terminal.objective_satisfied
                and terminal.expected_result_supported
                and terminal.terminal_evidence_sufficient)

    async def _decide_execute_action(
        self, case: RuntimeExecutableCase, page_info: dict[str, Any], step_count: int
    ) -> dict[str, Any] | None:
        """LLM 决定执行下一步行动。"""
        from langchain_core.messages import SystemMessage, HumanMessage

        prompt = f"""执行测试用例:
目标: {case.objective}
预期: {case.expected}
提示: {case.hints}
页面: {page_info.get('url', '')} - {page_info.get('title', '')}
已完成 {step_count} 步。

返回 JSON: {{"tool": "click|navigate|scroll|input_text|wait", "args": {{...}}}}
完成: {{"tool": "mark_task_complete", "args": {{"summary": "结果"}}}}
失败: {{"tool": "mark_task_failed", "args": {{"reason": "原因"}}}}
"""
        try:
            from core.llm_client import get_llm_client
            llm = get_llm_client("haiku")
            response = await llm.ainvoke([
                SystemMessage(content="你是测试执行 agent。"),
                HumanMessage(content=prompt),
            ])
            content = response.content if isinstance(response.content, str) else str(response.content)
            import json
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(content[start:end])
        except Exception as e:
            print(f"[Runtime] execute decide error: {e}")
        return None

    async def _execute_test_action(self, action: dict[str, Any]) -> str | None:
        """执行测试行动，返回证据引用。"""
        tool_name = action.get("tool", "")
        args = action.get("args", {})
        try:
            if tool_name == "click":
                sel = args.get("selector", "")
                if sel:
                    await self.page.click(sel)
                    return f"clicked: {sel}"
            elif tool_name == "navigate":
                url = args.get("url", "")
                if url:
                    await self.page.goto(url, wait_until="load", timeout=30000)
                    return f"navigated: {url}"
            elif tool_name == "scroll":
                d = args.get("direction", "down")
                delta = 500 if d == "down" else -500
                await self.page.evaluate(f"window.scrollBy(0, {delta})")
                return f"scrolled {d}"
            elif tool_name == "input_text":
                sel = args.get("selector", "")
                txt = args.get("text", "")
                if sel and txt:
                    await self.page.fill(sel, txt)
                    return f"input: {sel}"
            elif tool_name == "wait":
                await self.page.wait_for_timeout(args.get("ms", 1000))
                return f"waited {args.get('ms', 1000)}ms"
        except Exception as e:
            return f"error: {e}"
        return None
