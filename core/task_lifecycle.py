"""Application service for the authoritative task lifecycle."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from core.document_parser import parse_and_fetch_links
from core.execution_store import (
    create_human_review_request,
    create_execution_run,
    fill_cancelled_results,
    fill_failed_results,
    finalize_execution_run,
    record_task_checkpoint,
    set_task_resume_policy,
    update_task_lifecycle,
)
from core.input_normalization import combine_text_inputs
from core.interfaces import CandidateTestCase, TestAssetPackage
from core.run_report import build_run_report, save_run_report
from core.runtime_session import RuntimeSession
from core.skills.asset_packager import build_source_registry
from core.skills.case_adapter import adapt_executable_cases
from core.skills.l2_pipeline import generate_exploration_goals, run_l2_pipeline
from database.connection import async_session
from database.models import CaseResultRecord, ExecutionRunRecord, Report, Task, TaskStep
from database.models import HumanReviewRequestRecord


LifecycleEventSink = Callable[[str, str, dict[str, Any]], Awaitable[None]]


class TaskLifecycleService:
    """Own the long-running task lifecycle outside the FastAPI route module."""

    def __init__(self) -> None:
        self.execution_lock = asyncio.Lock()

    @staticmethod
    def _combine_rule_text(*values: Any) -> str:
        return combine_text_inputs(*values)

    async def run_test_session(
        self,
        task_db_id: int,
        target_url: str,
        config: dict | None,
        *,
        event_sink: LifecycleEventSink | None = None,
        resumed_from_run_id: str | None = None,
        resume_case_ids: list[str] | None = None,
    ) -> None:
        run_id = ""
        final_event_sent = False

        async def emit(event_type: str, data: dict[str, Any]) -> None:
            nonlocal final_event_sent
            if event_type in (
                "session_completed",
                "session_failed",
                "session_cancelled",
                "session_paused_for_review",
            ):
                if final_event_sent:
                    return
                final_event_sent = True
            if event_sink is not None:
                await event_sink(event_type, run_id, data)

        async def start_phase(phase: str) -> None:
            await update_task_lifecycle(
                task_db_id,
                status="running",
                phase=phase,
            )
            await record_task_checkpoint(
                task_db_id,
                phase=phase,
                status="started",
                run_id=run_id or None,
            )
            await emit("phase_started", {"phase": phase})

        async def complete_phase(phase: str, **data: Any) -> None:
            await record_task_checkpoint(
                task_db_id,
                phase=phase,
                status="completed",
                run_id=run_id or None,
                payload=data,
            )
            await emit("phase_completed", {"phase": phase, **data})

        async def run_phase_operation(
            phase: str,
            operation: Awaitable[Any],
            *,
            minimum_timeout: float = 0,
        ) -> Any:
            env_name = f"{phase.upper()}_PHASE_TIMEOUT_SECONDS"
            default_timeouts = {
                "analyzing": "900",
                "designing": "900",
                "executing": "1800",
            }
            default_timeout = default_timeouts.get(phase, "300")
            timeout_seconds = max(
                float(os.getenv(env_name, default_timeout)),
                minimum_timeout,
            )
            try:
                return await asyncio.wait_for(operation, timeout=timeout_seconds)
            except asyncio.TimeoutError as exc:
                raise RuntimeError(
                    f"{phase}_phase_timeout: {timeout_seconds:g}s"
                ) from exc

        async with self.execution_lock:
            async with async_session() as session:
                task = await session.get(Task, task_db_id)
                if task is None:
                    return
                task.status = "running"
                task.started_at = task.started_at or datetime.now(timezone.utc)
                task.completed_at = None
                task.failure_reason = None
                await session.commit()

            try:
                enriched_config = await parse_and_fetch_links(config or {})
                memory_context_disabled = self._memory_context_disabled(
                    enriched_config
                )
                if memory_context_disabled:
                    memory_context_text, memory_context_refs = "", []
                else:
                    memory_context_text, memory_context_refs = (
                        await self._recall_memory_context(target_url)
                    )
                if memory_context_text:
                    enriched_config["memory_context_text"] = memory_context_text
                    enriched_config["memory_context_refs"] = memory_context_refs
                package: TestAssetPackage | None = None
                candidates: list[CandidateTestCase]

                if resumed_from_run_id:
                    async with async_session() as session:
                        task = await session.get(Task, task_db_id)
                        package_dict = task.analysis_package if task else None
                    if not package_dict:
                        raise RuntimeError("resume_missing_analysis_package")
                    package = TestAssetPackage.model_validate(package_dict)
                    self._attach_memory_runtime_hints(
                        package,
                        memory_context_text,
                        memory_context_refs,
                    )
                    allowed = set(resume_case_ids or [])
                    candidates = [
                        case
                        for case in package.candidate_cases
                        if case.id in allowed
                    ]
                    if not candidates:
                        raise RuntimeError("resume_has_no_eligible_cases")

                    run = await create_execution_run(
                        task_db_id,
                        [case.id for case in candidates],
                        resumed_from_run_id=resumed_from_run_id,
                    )
                    run_id = run.run_id
                    await start_phase("executing")
                    async with RuntimeSession(
                        {
                            "task_id": str(task_db_id),
                            "target_url": target_url,
                            **enriched_config,
                        },
                        event_sink=emit,
                    ) as runtime:
                        await run_phase_operation(
                            "executing",
                            runtime.execute(
                                run_id,
                                adapt_executable_cases(candidates),
                            ),
                        )
                    await complete_phase("executing")
                else:
                    await start_phase("analyzing")
                    raw_rules = enriched_config.get("rules", "")
                    rules = self._combine_rule_text(
                        raw_rules,
                        enriched_config.get("case_generation_requirements", ""),
                    )
                    prototype_notes = self._combine_prototype_notes(enriched_config)
                    goals, review_items, facts, assertions = await run_phase_operation(
                        "analyzing",
                        generate_exploration_goals(
                            prd_content=enriched_config.get("prd", ""),
                            api_doc_content=(
                                enriched_config.get("api_doc", "")
                                or enriched_config.get("swagger", "")
                            ),
                            changelog_content=enriched_config.get("changelog", ""),
                            prototype_notes=prototype_notes,
                            architecture_notes=enriched_config.get("tech_doc", ""),
                            rules=rules,
                            focus_areas=enriched_config.get("focus_areas", ""),
                            target_url=target_url,
                        ),
                    )
                    if not goals:
                        raise RuntimeError("analysis_produced_no_exploration_goals")
                    source_registry = build_source_registry(
                        facts,
                        {
                            "prd": enriched_config.get("prd", ""),
                            "swagger": (
                                enriched_config.get("api_doc", "")
                                or enriched_config.get("swagger", "")
                            ),
                            "changelog": enriched_config.get("changelog", ""),
                            "prototype": prototype_notes,
                            "architecture": enriched_config.get("tech_doc", ""),
                            "rule": rules,
                        },
                    )
                    package = TestAssetPackage(
                        facts=facts,
                        assertions=assertions,
                        source_registry=source_registry,
                        exploration_goals=goals,
                        manual_review_items=review_items,
                    )
                    self._attach_memory_runtime_hints(
                        package,
                        memory_context_text,
                        memory_context_refs,
                    )
                    await self._persist_analysis_package(task_db_id, package)
                    await self._open_manual_review_requests(
                        task_db_id,
                        None,
                        "analyzing",
                        package.manual_review_items,
                    )
                    await complete_phase(
                        "analyzing",
                        facts=len(facts),
                        assertions=len(assertions),
                        goals=len(goals),
                    )

                    if self._is_pre_execution_mode(enriched_config):
                        skip_payload = {
                            "reason": "pre_execution_mode",
                            "target_url": target_url,
                        }
                        await record_task_checkpoint(
                            task_db_id,
                            phase="exploring",
                            status="skipped",
                            run_id=None,
                            payload=skip_payload,
                        )
                        await emit(
                            "phase_completed",
                            {
                                "phase": "exploring",
                                "status": "skipped",
                                **skip_payload,
                            },
                        )

                        await start_phase("designing")
                        package = await run_phase_operation(
                            "designing",
                            run_l2_pipeline(
                                prd_content=enriched_config.get("prd", ""),
                                api_doc_content=(
                                    enriched_config.get("api_doc", "")
                                    or enriched_config.get("swagger", "")
                                ),
                                changelog_content=enriched_config.get("changelog", ""),
                                prototype_notes=prototype_notes,
                                architecture_notes=enriched_config.get(
                                    "tech_doc", ""
                                ),
                                rules=rules,
                                focus_areas=enriched_config.get("focus_areas", ""),
                                target_url=target_url,
                                system_map=None,
                                precomputed_facts=facts,
                                precomputed_assertions=assertions,
                                precomputed_goals=goals,
                                precomputed_review_items=review_items,
                                source_registry=source_registry,
                                memory_context_text=memory_context_text,
                                disable_memory_context=memory_context_disabled,
                            ),
                        )
                        package.runtime_hints["execution_mode"] = "pre_execution"
                        package.runtime_hints["live_exploration"] = {
                            "status": "skipped",
                            **skip_payload,
                        }
                        package.runtime_hints["execution_skipped"] = True
                        self._attach_memory_runtime_hints(
                            package,
                            memory_context_text,
                            memory_context_refs,
                        )
                        await self._persist_analysis_package(task_db_id, package)
                        await self._open_manual_review_requests(
                            task_db_id,
                            None,
                            "designing",
                            package.manual_review_items,
                        )
                        self._raise_for_quality_gate(
                            package,
                            "test_asset_quality_gate_failed",
                        )

                        candidates = package.candidate_cases
                        if not candidates:
                            raise RuntimeError("design_produced_no_candidate_cases")

                        from core.skills.execution_selector import select_execution_cases
                        from core.skills.quality_gates import run_quality_gates

                        profile = str(
                            enriched_config.get("execution_profile", "balanced")
                        )
                        target_value = enriched_config.get("execution_target")
                        target_count = (
                            int(target_value)
                            if target_value is not None
                            else None
                        )
                        selection = select_execution_cases(
                            package,
                            profile,
                            target_count,
                        )
                        package.runtime_hints["execution_selection"] = (
                            selection.model_dump(mode="json")
                        )
                        package.quality_gate_report = run_quality_gates(package)
                        self._raise_for_quality_gate(
                            package,
                            "execution_selection_quality_gate_failed",
                        )
                        await self._persist_analysis_package(task_db_id, package)
                        await complete_phase(
                            "designing",
                            asset_cases=len(package.candidate_cases),
                            selected_cases=selection.selected_count,
                            deferred_cases=selection.deferred_count,
                            exploration_skipped=True,
                        )
                        await record_task_checkpoint(
                            task_db_id,
                            phase="executing",
                            status="skipped",
                            run_id=None,
                            payload=skip_payload,
                        )
                        await emit(
                            "phase_completed",
                            {
                                "phase": "executing",
                                "status": "skipped",
                                **skip_payload,
                            },
                        )
                        summary = {
                            "mode": "pre_execution",
                            "asset_cases": len(package.candidate_cases),
                            "selected_cases": selection.selected_count,
                            "deferred_cases": selection.deferred_count,
                            "execution_skipped": True,
                        }
                        await record_task_checkpoint(
                            task_db_id,
                            phase="pre_execution",
                            status="completed",
                            run_id=None,
                            payload=summary,
                        )
                        await set_task_resume_policy(
                            task_db_id,
                            {
                                "mode": "start_online_execution_after_environment_ready",
                                "requires_target_available": True,
                                "selected_case_ids": selection.selected_case_ids,
                                "deferred_case_ids": selection.deferred_case_ids,
                            },
                        )
                        await update_task_lifecycle(
                            task_db_id,
                            status="completed",
                            phase=None,
                            report_status="skipped",
                            completed=True,
                        )
                        await emit("session_completed", {"summary": summary})
                        return

                    async with RuntimeSession(
                        {
                            "task_id": str(task_db_id),
                            "target_url": target_url,
                            **enriched_config,
                        },
                        event_sink=emit,
                    ) as runtime:
                        await start_phase("exploring")
                        exploration = await run_phase_operation(
                            "exploring",
                            runtime.explore(goals),
                        )
                        exploration_summary = {
                            "total": len(exploration.goal_results),
                            "found": sum(
                                1
                                for result in exploration.goal_results
                                if result.status == "found"
                            ),
                            "not_found": sum(
                                1
                                for result in exploration.goal_results
                                if result.status == "not_found"
                            ),
                            "blocked": sum(
                                1
                                for result in exploration.goal_results
                                if result.status == "blocked"
                            ),
                            "insufficient": sum(
                                1
                                for result in exploration.goal_results
                                if result.status == "insufficient"
                            ),
                            "pages": len(exploration.system_map.pages),
                            "actions": len(exploration.system_map.actions),
                            "forms": len(exploration.system_map.forms),
                            "navigations": len(exploration.system_map.navigations),
                            "evidence_ref_count": sum(
                                len(result.evidence_refs)
                                for result in exploration.goal_results
                            ),
                        }
                        exploration_evidence = {
                            "goal_results": [
                                result.model_dump(mode="json")
                                for result in exploration.goal_results
                            ],
                            "summary": exploration_summary,
                        }
                        package.system_map = exploration.system_map
                        package.exploration_evidence = exploration_evidence
                        await self._persist_analysis_package(task_db_id, package)

                        found = exploration_summary["found"]
                        has_page_evidence = bool(exploration.system_map.pages)
                        if not exploration.goal_results or (
                            found == 0 and not has_page_evidence
                        ):
                            if not self._can_continue_after_degraded_exploration(
                                package,
                                exploration_summary,
                            ):
                                raise RuntimeError("exploration_failed")
                            degraded_payload = {
                                "status": "degraded",
                                "reason": "live_exploration_no_page_evidence",
                                **exploration_summary,
                            }
                            package.runtime_hints["live_exploration"] = (
                                degraded_payload
                            )
                            await self._persist_analysis_package(task_db_id, package)
                            await record_task_checkpoint(
                                task_db_id,
                                phase="exploring",
                                status="degraded",
                                run_id=None,
                                payload=degraded_payload,
                            )
                            await emit(
                                "phase_completed",
                                {"phase": "exploring", **degraded_payload},
                            )
                        else:
                            await complete_phase(
                                "exploring",
                                found=found,
                                total=len(exploration.goal_results),
                                pages=len(exploration.system_map.pages),
                                actions=len(exploration.system_map.actions),
                                forms=len(exploration.system_map.forms),
                                navigations=len(exploration.system_map.navigations),
                            )

                        await start_phase("designing")
                        package = await run_phase_operation(
                            "designing",
                            run_l2_pipeline(
                                prd_content=enriched_config.get("prd", ""),
                                api_doc_content=(
                                    enriched_config.get("api_doc", "")
                                    or enriched_config.get("swagger", "")
                                ),
                                changelog_content=enriched_config.get("changelog", ""),
                                prototype_notes=prototype_notes,
                                architecture_notes=enriched_config.get(
                                    "tech_doc", ""
                                ),
                                rules=rules,
                                focus_areas=enriched_config.get("focus_areas", ""),
                                target_url=target_url,
                                system_map=exploration.system_map,
                                precomputed_facts=facts,
                                precomputed_assertions=assertions,
                                precomputed_goals=goals,
                                precomputed_review_items=review_items,
                                source_registry=source_registry,
                                memory_context_text=memory_context_text,
                                disable_memory_context=memory_context_disabled,
                            ),
                        )
                        package.system_map = exploration.system_map
                        package.exploration_evidence = exploration_evidence
                        self._attach_memory_runtime_hints(
                            package,
                            memory_context_text,
                            memory_context_refs,
                        )
                        await self._persist_analysis_package(task_db_id, package)
                        await self._open_manual_review_requests(
                            task_db_id,
                            None,
                            "designing",
                            package.manual_review_items,
                        )
                        self._raise_for_quality_gate(
                            package,
                            "test_asset_quality_gate_failed",
                        )

                        candidates = package.candidate_cases
                        if not candidates:
                            raise RuntimeError("design_produced_no_candidate_cases")

                        from core.skills.execution_selector import select_execution_cases
                        from core.skills.quality_gates import run_quality_gates

                        profile = str(
                            enriched_config.get("execution_profile", "balanced")
                        )
                        target_value = enriched_config.get("execution_target")
                        target_count = (
                            int(target_value)
                            if target_value is not None
                            else None
                        )
                        selection = select_execution_cases(
                            package,
                            profile,
                            target_count,
                        )
                        package.runtime_hints["execution_selection"] = (
                            selection.model_dump(mode="json")
                        )
                        selected_ids = set(selection.selected_case_ids)
                        candidates = [
                            case
                            for case in package.candidate_cases
                            if case.id in selected_ids
                        ]
                        package.quality_gate_report = run_quality_gates(package)
                        self._raise_for_quality_gate(
                            package,
                            "execution_selection_quality_gate_failed",
                        )
                        await self._persist_analysis_package(task_db_id, package)
                        await complete_phase(
                            "designing",
                            asset_cases=len(package.candidate_cases),
                            selected_cases=len(candidates),
                            deferred_cases=selection.deferred_count,
                        )

                        run = await create_execution_run(
                            task_db_id,
                            [case.id for case in candidates],
                        )
                        run_id = run.run_id
                        await start_phase("executing")
                        await run_phase_operation(
                            "executing",
                            runtime.execute(
                                run_id,
                                adapt_executable_cases(candidates),
                            ),
                            minimum_timeout=(
                                len(candidates)
                                * float(os.getenv("MAX_CASE_ATTEMPT_SECONDS", "120"))
                                if profile == "full"
                                else 0
                            ),
                        )
                        await complete_phase("executing")

                pending_review = False
                summary = await finalize_execution_run(run_id, "completed")
                if summary.get("human_review_required", 0) > 0:
                    pending_review = True
                await start_phase("reporting")
                await self._write_report(task_db_id, run_id, package)
                await complete_phase("reporting")
                if pending_review:
                    await set_task_resume_policy(
                        task_db_id,
                        {
                            "mode": "rerun_non_passed_cases_after_review",
                            "resumed_from_run_id": run_id,
                            "requires_resolved_human_reviews": True,
                            "summary": summary,
                        },
                    )
                    await update_task_lifecycle(
                        task_db_id,
                        status="paused_for_review",
                        phase="review",
                        completed=False,
                    )
                    await record_task_checkpoint(
                        task_db_id,
                        phase="review",
                        status="paused_for_review",
                        run_id=run_id,
                        payload={"summary": summary},
                    )
                    await emit("session_paused_for_review", {"summary": summary})
                else:
                    await set_task_resume_policy(task_db_id, {})
                    await update_task_lifecycle(
                        task_db_id,
                        status="completed",
                        phase=None,
                        completed=True,
                    )
                    await emit("session_completed", {"summary": summary})
            except asyncio.CancelledError:
                if run_id:
                    await fill_cancelled_results(run_id)
                await record_task_checkpoint(
                    task_db_id,
                    phase="cancelled",
                    status="cancelled",
                    run_id=run_id or None,
                )
                await update_task_lifecycle(
                    task_db_id,
                    status="cancelled",
                    phase=None,
                    failure_reason="cancelled",
                    completed=True,
                )
                await emit("session_cancelled", {})
                raise
            except Exception as exc:
                if run_id:
                    await fill_failed_results(run_id, str(exc))
                await record_task_checkpoint(
                    task_db_id,
                    phase="failed",
                    status="failed",
                    run_id=run_id or None,
                    payload={"error": str(exc)},
                )
                await update_task_lifecycle(
                    task_db_id,
                    status="failed",
                    phase=None,
                    failure_reason=str(exc),
                    completed=True,
                )
                await emit("session_failed", {"error": str(exc)})

    @staticmethod
    def _is_pre_execution_mode(config: dict[str, Any]) -> bool:
        return (
            str(config.get("execution_mode", "online")).strip().lower()
            == "pre_execution"
        )

    @staticmethod
    def _combine_prototype_notes(config: dict[str, Any]) -> str:
        parts = []
        for key, label in (
            ("prototype_url", "Prototype URL"),
            ("prototype_source", "Prototype Source"),
        ):
            value = str(config.get(key) or "").strip()
            if value:
                parts.append(f"## {label}\n{value}")
        return "\n\n".join(parts)

    @staticmethod
    def _memory_context_disabled(config: dict[str, Any]) -> bool:
        value = config.get("disable_memory_context")
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _can_continue_after_degraded_exploration(
        package: TestAssetPackage,
        exploration_summary: dict[str, Any],
    ) -> bool:
        """Allow static asset design to continue when live exploration is empty.

        The browser execution phase can still produce authoritative evidence if
        L1/L2 already produced requirements, assertions, and exploration goals.
        A package with no goals/results remains a hard analysis failure.
        """

        if int(exploration_summary.get("total") or 0) <= 0:
            return False
        if int(exploration_summary.get("found") or 0) > 0:
            return True
        if int(exploration_summary.get("pages") or 0) > 0:
            return True
        return bool(
            package.facts
            and package.assertions
            and package.exploration_goals
        )

    @staticmethod
    async def _recall_memory_context(
        target_url: str,
    ) -> tuple[str, list[dict[str, str]]]:
        try:
            from core.memory_context import (
                format_memory_context_for_prompt,
                recall_memory_context,
            )

            contexts = await recall_memory_context(target_url)
            refs = [
                {
                    "scope_type": context.scope_type,
                    "scope_value": context.scope_value,
                    "memory_key": context.memory_key,
                    "source_domain": context.source_domain,
                    "provenance": context.provenance,
                }
                for context in contexts
            ]
            return format_memory_context_for_prompt(contexts), refs
        except Exception as exc:
            print(f"[TaskLifecycle] Memory context recall skipped: {exc}")
            return "", []

    @staticmethod
    def _attach_memory_runtime_hints(
        package: TestAssetPackage,
        memory_context_text: str,
        memory_context_refs: list[dict[str, str]],
    ) -> None:
        if not memory_context_text:
            return
        package.runtime_hints["memory_context_hint_present"] = True
        package.runtime_hints["memory_context_policy"] = (
            "hint_only_not_requirement_fact_source"
        )
        package.runtime_hints["memory_context_refs"] = memory_context_refs

    @staticmethod
    async def _open_manual_review_requests(
        task_id: int,
        run_id: str | None,
        phase: str,
        review_items: list[str],
    ) -> None:
        for item in review_items:
            await create_human_review_request(
                task_id=task_id,
                run_id=run_id,
                candidate_case_id="",
                phase=phase,
                reason=item,
                evidence_refs=[],
                blocked_tool=None,
            )

    @staticmethod
    def _raise_for_quality_gate(
        package: TestAssetPackage,
        prefix: str,
    ) -> None:
        if package.quality_gate_report and not package.quality_gate_report.passed:
            errors = [
                finding.code
                for finding in package.quality_gate_report.findings
                if finding.severity == "error"
            ]
            raise RuntimeError(f"{prefix}: {','.join(errors)}")

    @staticmethod
    async def _persist_analysis_package(
        task_id: int,
        package: TestAssetPackage,
    ) -> None:
        async with async_session() as session:
            task = await session.get(Task, task_id)
            if task:
                task.analysis_package = package.model_dump(mode="json")
                await session.commit()

    @staticmethod
    async def _write_report(
        task_id: int,
        run_id: str,
        package: TestAssetPackage | None,
    ) -> None:
        try:
            async with async_session() as session:
                run_record = await session.get(ExecutionRunRecord, run_id)
                result_rows = list(
                    (
                        await session.execute(
                            select(CaseResultRecord)
                            .where(CaseResultRecord.run_id == run_id)
                            .order_by(CaseResultRecord.id)
                        )
                    )
                    .scalars()
                    .all()
                )
                step_rows = list(
                    (
                        await session.execute(
                            select(TaskStep)
                            .where(TaskStep.run_id == run_id)
                            .order_by(
                                TaskStep.test_case_id,
                                TaskStep.attempt_no,
                                TaskStep.step_index,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                review_rows = list(
                    (
                        await session.execute(
                            select(HumanReviewRequestRecord)
                            .where(HumanReviewRequestRecord.task_id == task_id)
                            .order_by(
                                HumanReviewRequestRecord.requested_at.desc(),
                                HumanReviewRequestRecord.id.desc(),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                html = build_run_report(
                    run_record,
                    result_rows,
                    step_rows,
                    package,
                    review_rows,
                )
                report_path = save_run_report(run_id, html)
                session.add(
                    Report(
                        task_id=task_id,
                        run_id=run_id,
                        status="completed",
                        report_path=report_path,
                        summary="",
                    )
                )
                await session.commit()
            await update_task_lifecycle(
                task_id,
                report_status="completed",
                phase=None,
            )
        except Exception as report_error:
            await update_task_lifecycle(
                task_id,
                report_status="failed",
                phase=None,
                failure_reason=f"report_error: {report_error}",
            )
