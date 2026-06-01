"""core/runtime.py — Runtime orchestrator for the AI Native Testing Platform.

Combines planning and execution subgraphs, manages browser lifecycle,
iterates through test cases, and handles checkpointing.

Lifecycle:
1. __init__: Configure from env/task_config
2. run(): Execute full session (plan -> execute each case -> report)
3. run_stream(): Same as run() but yields WebSocket-compatible updates
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from langchain_core.messages import AIMessage, SystemMessage
from playwright.async_api import async_playwright

from core.interfaces import AssertionResult, ChangeReport, Setup, StepResult, TestCase, TestResult
from core.execution_logger import _task_id_map, log_step, log_test_result
from agents.ui.planning_graph import build_planning_graph
from agents.ui.execution_graph import build_execution_graph
from agents.ui.setup_manager import execute_setup
from agents.ui.tools import cleanup_task_context, set_current_page, set_current_task
from core.report_builder import ReportBuilder
from core.skills.session_summary import generate_case_summary
from core.skills.coverage_tracker import CoverageTracker
from database.connection import async_session
from database.models import Report, Task


def _now_iso() -> str:
    """Return current time as ISO format string."""
    return datetime.now(timezone.utc).isoformat()


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

            report_path = ""
            if self._stream_results:
                report_path = await self._save_report(self._stream_results)

            final_report = {
                "task_id": self.task_id,
                "status": "completed",
                "test_plan": [{**tc.model_dump(), "status": getattr(tc, "status", "pending")} for tc in test_plan],
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
            await self._close_browser()

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
        print("DEBUG: Creating BrowserSession")
        self.browser_session = BrowserSession(headless=True, browser_profile=profile)
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
        # Attach the browser_session to the page object so page_semantic.py can use it
        self.page._browser_session = self.browser_session
        set_current_task(self.task_id)
        set_current_page(self.page, task_id=self.task_id)

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
            "task_id": self.task_id,
            "task_config": self.task_config,
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
                system_model=self.task_config.get("_system_model")
            )
            self.task_config["_scenarios"] = scenarios

        planning_graph = build_planning_graph()
        result = await planning_graph.ainvoke(self._build_initial_state())
        return result.get("test_plan", []), result.get("setups", {})

    async def _execute_test_case(
        self,
        index: int,
        test_case: TestCase,
        test_plan: list[TestCase],
        setups: dict[str, Setup],
    ) -> TestResult:
        """Execute a single test case."""
        start_time = time.time()

        # Reset browser state to prevent cross-test contamination
        try:
            if getattr(self, "context", None):
                await self.context.clear_cookies()
            if getattr(self, "page", None):
                try:
                    await self.page.evaluate("localStorage.clear(); sessionStorage.clear();")
                    await self.page.goto("about:blank")
                except Exception:
                    pass
                await self.page.goto(self.target_url, wait_until="load", timeout=30000)
        except Exception as e:
            print(f"[Runtime] Failed to reset browser state: {e}")

        # Execute setups if needed
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

        # Build execution state
        execution_state = self._build_initial_state()
        previous_context = ""
        if self._case_summaries:
            summaries_text = "\n".join(
                f"- {s['case_id']}: {s.get('summary', '')}" for s in self._case_summaries
            )
            previous_context = f"\n\n前面已完成的测试用例摘要:\n{summaries_text}"
        execution_state["messages"] = [
            SystemMessage(
                content=f"开始执行测试用例: {test_case.id} - {test_case.title}{previous_context}"
            ),
        ]
        execution_state["test_plan"] = test_plan
        execution_state["setups"] = setups
        execution_state["current_index"] = index

        # Run execution subgraph
        execution_graph = build_execution_graph()

        try:
            result_state = await execution_graph.ainvoke(execution_state)
        except Exception:
            # Browser crash — try to recover
            result_state = await self._handle_browser_crash(test_case, execution_state)

        duration = time.time() - start_time

        # Determine overall status
        steps = result_state.get("_collected_steps", [])
        max_failures = int(os.getenv("MAX_CONSECUTIVE_FAILURES", "3"))
        max_steps = int(os.getenv("MAX_STEPS_PER_CASE", "15"))

        if result_state.get("consecutive_failures", 0) >= max_failures:
            status = "failed"
        elif result_state.get("current_step", 0) >= max_steps:
            status = "incomplete"
        elif any(
            s.assertion and s.assertion.status == "fail" for s in steps if hasattr(s, "assertion")
        ):
            status = "failed"
        elif any(
            s.assertion and s.assertion.status == "pass" for s in steps if hasattr(s, "assertion")
        ):
            status = "passed"
        else:
            status = "incomplete"

        test_result = TestResult(
            test_case_id=test_case.id,
            status=status,
            steps=steps,
            summary=f"{'通过' if status == 'passed' else '失败'}: {test_case.title}",
            duration_seconds=duration,
            setup_results=[],
        )

        # Generate session summary for cross-case context
        try:
            urls = set()
            for s in steps:
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
                status=status,
                steps=steps,
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
        """Execute a test case, yielding per-step streaming updates via astream().

        Emits WebSocket events for each node in the execution graph:
        - observe  → page_update (url, title)
        - decide   → ai_thinking (thought, tool_calls)
        - execute  → action_result (tool_name, tool_args, result)
        - assert   → assertion_result (change_report, assertion)
        - record   → (internal, no event)
        Finally emits test_case_complete.
        """
        start_time = time.time()

        # Reset browser state to prevent cross-test contamination
        try:
            if getattr(self, "context", None):
                await self.context.clear_cookies()
            if getattr(self, "page", None):
                try:
                    await self.page.evaluate("localStorage.clear(); sessionStorage.clear();")
                    await self.page.goto("about:blank")
                except Exception:
                    pass
                await self.page.goto(self.target_url, wait_until="load", timeout=30000)
        except Exception as e:
            print(f"[Runtime] Failed to reset browser state: {e}")

        # Execute setups if needed
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

        # Build execution state
        execution_state = self._build_initial_state()
        previous_context = ""
        if self._case_summaries:
            summaries_text = "\n".join(
                f"- {s['case_id']}: {s.get('summary', '')}" for s in self._case_summaries
            )
            previous_context = f"\n\n前面已完成的测试用例摘要:\n{summaries_text}"
        execution_state["messages"] = [
            SystemMessage(
                content=f"开始执行测试用例: {test_case.id} - {test_case.title}{previous_context}"
            ),
        ]
        execution_state["test_plan"] = test_plan
        execution_state["setups"] = setups
        execution_state["current_index"] = index

        # Run execution subgraph with streaming
        execution_graph = build_execution_graph()
        collected_steps: list[StepResult] = []
        final_state = dict(execution_state)

        try:
            async for stream_update in execution_graph.astream(execution_state):
                print(f"[DEBUG_STREAM] {stream_update.keys() if isinstance(stream_update, dict) else type(stream_update)}")
                for node_name, state_update in _stream_items(stream_update):
                    # Accumulate state from each node
                    final_state.update(state_update)

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
            # Browser crash — try to recover
            import traceback
            traceback.print_exc()
            print(f"[DEBUG] _execute_test_case_stream crashed with: {e}")
            final_state = await self._handle_browser_crash(test_case, execution_state)
            collected_steps = final_state.get("_collected_steps", [])

        duration = time.time() - start_time

        # Determine overall status
        max_failures = int(os.getenv("MAX_CONSECUTIVE_FAILURES", "3"))
        max_steps = int(os.getenv("MAX_STEPS_PER_CASE", "15"))

        if final_state.get("consecutive_failures", 0) >= max_failures:
            status = "failed"
        elif final_state.get("current_step", 0) >= max_steps:
            status = "incomplete"
        elif any(
            s.assertion and s.assertion.status == "fail"
            for s in collected_steps
            if hasattr(s, "assertion")
        ):
            status = "failed"
        elif any(
            s.assertion and s.assertion.status == "pass"
            for s in collected_steps
            if hasattr(s, "assertion")
        ):
            status = "passed"
        else:
            status = "incomplete"

        result = TestResult(
            test_case_id=test_case.id,
            status=status,
            steps=collected_steps,
            summary=f"{'通过' if status == 'passed' else '失败'}: {test_case.title}",
            duration_seconds=duration,
            setup_results=[],
        )
        self._stream_results.append(result)

        # Generate session summary for cross-case context
        try:
            urls = set()
            for s in collected_steps:
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
                status=status,
                steps=collected_steps,
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

        l1_coverage = self.task_config.get("_coverage_report")
        if l1_coverage:
            builder.set_layer1_coverage(l1_coverage)

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
                    task.failed_tests = sum(1 for r in results if r.status == "failed")
                session.add(Report(task_id=db_task_id, report_path=saved_path, summary=summary))
                await session.commit()
        except Exception:
            # Report file is still useful even when DB persistence is unavailable.
            return saved_path

        return saved_path
