"""Production lifecycle wrapper for goal-driven exploration and execution."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from core.execution_store import upsert_case_result
from core.interfaces import (
    CaseResult,
    ExplorationGoal,
    ExplorationResult,
    RuntimeExecutableCase,
)
from core.runtime import Runtime

EventSink = Callable[[str, dict[str, Any]], Awaitable[None]]


class RuntimeSession:
    """Own browser resources for exploration, design, and execution."""

    def __init__(
        self,
        task_config: dict[str, Any],
        *,
        event_sink: EventSink | None = None,
    ) -> None:
        self.runtime = Runtime(task_config)
        self.event_sink = event_sink
        self.runtime.bind_event_sink(self.emit)

    async def __aenter__(self) -> "RuntimeSession":
        await self.runtime.launch_browser()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.runtime.close_browser()

    async def emit(self, event_type: str, **data: Any) -> None:
        if self.event_sink is not None:
            await self.event_sink(event_type, data)

    async def explore(self, goals: list[ExplorationGoal]) -> ExplorationResult:
        return await self.runtime.explore(goals)

    async def execute(
        self,
        run_id: str,
        cases: list[RuntimeExecutableCase],
    ) -> list[CaseResult]:
        results: list[CaseResult] = []
        max_retries = int(os.getenv("MAX_TEST_CASE_RETRIES", "2"))
        attempt_timeout = float(os.getenv("MAX_CASE_ATTEMPT_SECONDS", "120"))
        for case in cases:
            await self.emit("case_started", candidate_case_id=case.id)
            final: CaseResult | None = None
            for attempt_no in range(1, max_retries + 2):
                await self.emit(
                    "case_attempt_started",
                    candidate_case_id=case.id,
                    attempt_no=attempt_no,
                )
                try:
                    result = await asyncio.wait_for(
                        self.runtime.execute_attempt(run_id, case, attempt_no),
                        timeout=attempt_timeout,
                    )
                except asyncio.TimeoutError:
                    now = datetime.now(timezone.utc).isoformat()
                    self.runtime.remember_case_feedback(
                        case.id,
                        f"case_attempt_timeout: {attempt_timeout:g}s",
                    )
                    await self.runtime.record_attempt_step(
                        case.id,
                        {
                            "tool": "attempt_timeout",
                            "args": {"timeout_seconds": attempt_timeout},
                        },
                        f"用例尝试超过 {attempt_timeout:g}s",
                    )
                    result = CaseResult(
                        run_id=run_id,
                        candidate_case_id=case.id,
                        terminal_status="incomplete",
                        attempt_count=attempt_no,
                        started_at=now,
                        completed_at=now,
                        summary=f"执行超时: {case.objective}",
                        failure_reason=(
                            f"case_attempt_timeout: {attempt_timeout:g}s"
                        ),
                    )
                except Exception as exc:
                    now = datetime.now(timezone.utc).isoformat()
                    self.runtime.remember_case_feedback(
                        case.id,
                        f"execution_error: {exc}",
                    )
                    await self.runtime.record_attempt_step(
                        case.id,
                        {
                            "tool": "execution_error",
                            "args": {"error": str(exc)},
                        },
                        f"执行异常: {exc}",
                    )
                    result = CaseResult(
                        run_id=run_id,
                        candidate_case_id=case.id,
                        terminal_status="incomplete",
                        attempt_count=attempt_no,
                        started_at=now,
                        completed_at=now,
                        summary=f"执行异常: {case.objective}",
                        failure_reason=f"execution_error: {exc}",
                    )
                precondition_terminal = result.attempt_count == 0
                result.run_id = run_id
                if not precondition_terminal:
                    result.attempt_count = attempt_no
                final = result
                if precondition_terminal:
                    break
                if result.terminal_status not in ("failed", "incomplete"):
                    break
                if attempt_no <= max_retries:
                    await self.runtime.reset_browser_state()

            assert final is not None
            if (
                final.terminal_status == "incomplete"
                and final.attempt_count > max_retries
            ):
                final.terminal_status = "human_review_required"
                final.failure_reason = final.failure_reason or "retry_exhausted"
            await upsert_case_result(final)
            results.append(final)
            self.runtime.clear_case_feedback(case.id)
            await self.emit(
                "case_completed",
                candidate_case_id=case.id,
                status=final.terminal_status,
                attempt_count=final.attempt_count,
            )
        return results
