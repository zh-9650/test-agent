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
from core.execution_logger import log_step, log_test_result
from agents.ui.planning_graph import build_planning_graph
from agents.ui.execution_graph import build_execution_graph
from agents.ui.setup_manager import execute_setup
from agents.ui.tools import set_current_page


def _now_iso() -> str:
    """Return current time as ISO format string."""
    return datetime.now(timezone.utc).isoformat()


class Runtime:
    """Orchestrates a complete test session.

    Lifecycle:
    1. __init__: Configure from env/task_config
    2. run(): Execute full session (plan -> execute each case -> report)
    3. Provides async generator for streaming updates (for WebSocket)
    """

    def __init__(self, task_config: dict[str, Any]):
        self.task_id = task_config.get("task_id", str(uuid.uuid4()))
        self.task_config = task_config
        self.target_url = task_config["target_url"]
        self.browser = None
        self.context = None
        self.page = None
        self._playwright = None
        self._checkpointer = None

    async def run(self) -> list[TestResult]:
        """Execute the full test session.

        Returns:
            List of TestResult for all test cases.
        """
        results: list[TestResult] = []
        try:
            # 1. Launch browser
            await self._launch_browser()

            # 2. Run planning subgraph
            test_plan, setups = await self._run_planning()

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
        try:
            await self._launch_browser()

            # Run planning with streaming exploration progress
            planning_graph = build_planning_graph()
            planning_state = self._build_initial_state()

            test_plan: list[TestCase] = []
            setups: dict[str, Setup] = {}

            async for node_name, state_update in planning_graph.astream(planning_state):
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
                elif node_name == "explore_observe":
                    page_info = state_update.get("page_info", {})
                    yield {
                        "type": "page_update",
                        "test_case_id": "",
                        "step_index": 0,
                        "data": {
                            "phase": "exploration",
                            "url": page_info.get("url", ""),
                        },
                        "timestamp": _now_iso(),
                    }
                elif node_name == "generate_plan":
                    test_plan = state_update.get("test_plan", [])
                    setups = state_update.get("setups", {})

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
        """Launch Playwright browser with trace and video recording."""
        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.launch(headless=True)

        # Create data directory for this task
        data_dir = os.path.join("data", "sessions", self.task_id)
        os.makedirs(data_dir, exist_ok=True)

        self.context = await self.browser.new_context(
            record_video_dir=os.path.join(data_dir, "videos"),
            viewport={"width": 1280, "height": 720},
        )

        # Enable tracing
        await self.context.tracing.start(
            screenshots=True,
            snapshots=True,
            sources=True,
        )

        self.page = await self.context.new_page()
        set_current_page(self.page)

        # Navigate to target URL
        await self.page.goto(self.target_url, wait_until="networkidle", timeout=30000)

    async def _close_browser(self):
        """Save trace and close browser."""
        try:
            if self.context:
                trace_path = os.path.join("data", "sessions", self.task_id, "trace.zip")
                await self.context.tracing.stop(path=trace_path)
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass  # best effort cleanup

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
        execution_state["messages"] = [
            SystemMessage(
                content=f"开始执行测试用例: {test_case.id} - {test_case.title}"
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
        else:
            status = "passed"

        return TestResult(
            test_case_id=test_case.id,
            status=status,
            steps=steps,
            summary=f"{'通过' if status == 'passed' else '失败'}: {test_case.title}",
            duration_seconds=duration,
            setup_results=[],
        )

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
        execution_state["messages"] = [
            SystemMessage(
                content=f"开始执行测试用例: {test_case.id} - {test_case.title}"
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
            async for node_name, state_update in execution_graph.astream(execution_state):
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
                        tool_calls = (
                            last_msg.tool_calls
                            if hasattr(last_msg, "tool_calls") and last_msg.tool_calls
                            else []
                        )
                        yield {
                            "type": "ai_thinking",
                            "test_case_id": test_case.id,
                            "step_index": final_state.get("current_step", 0),
                            "data": {
                                "thought": content,
                                "tool_calls": [
                                    {"name": tc["name"], "args": tc["args"]}
                                    for tc in tool_calls
                                ],
                            },
                            "timestamp": _now_iso(),
                        }

                elif node_name == "execute":
                    # Get tool call info from the last AI message in accumulated state
                    tc_messages = final_state.get("messages", [])
                    last_ai = None
                    for msg in reversed(tc_messages):
                        if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
                            last_ai = msg
                            break

                    tool_name = ""
                    tool_args: dict[str, Any] = {}
                    if last_ai and last_ai.tool_calls:
                        tool_name = last_ai.tool_calls[0]["name"]
                        tool_args = last_ai.tool_calls[0]["args"]

                    yield {
                        "type": "action_result",
                        "test_case_id": test_case.id,
                        "step_index": state_update.get("current_step", 0),
                        "data": {
                            "tool_name": tool_name,
                            "tool_args": tool_args,
                            "result": state_update.get("_last_tool_result", ""),
                        },
                        "timestamp": _now_iso(),
                    }

                elif node_name == "assert":
                    yield {
                        "type": "assertion_result",
                        "test_case_id": test_case.id,
                        "step_index": final_state.get("current_step", 0),
                        "data": {
                            "change_report": state_update.get("_last_change_report"),
                            "assertion": state_update.get("_last_assertion"),
                        },
                        "timestamp": _now_iso(),
                    }

                elif node_name == "record":
                    new_steps = state_update.get("_collected_steps", [])
                    if new_steps:
                        collected_steps.extend(new_steps)
                        for step in new_steps:
                            await log_step(self.task_id, test_case.id, step)

        except Exception:
            # Browser crash — try to recover
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
        else:
            status = "passed"

        result = TestResult(
            test_case_id=test_case.id,
            status=status,
            steps=collected_steps,
            summary=f"{'通过' if status == 'passed' else '失败'}: {test_case.title}",
            duration_seconds=duration,
            setup_results=[],
        )

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