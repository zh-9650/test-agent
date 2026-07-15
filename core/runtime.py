"""Goal-driven browser runtime.

The production lifecycle lives in ``RuntimeSession`` and the API orchestrator.
This module only owns browser resources, exploration, and one execution attempt.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlparse

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from pydantic import BaseModel, Field

from agents.ui.tools import (
    cleanup_task_context,
    set_cdp_session,
    set_current_page,
    set_current_task,
)
from core.interfaces import (
    ActionMap,
    CaseResult,
    ExplorationGoal,
    ExplorationResult,
    FormMap,
    GoalResult,
    NavigationMap,
    PageMap,
    RuntimeExecutableCase,
    SystemMapEvid,
    TerminalAssertion,
)
from core.runtime_action_policy import enforce_runtime_action_policy
from core.runtime_locator_metrics import RuntimeLocatorMetrics
from core.runtime_tool_contract import (
    EXECUTION_ACTION_TOOLS,
    EXPLORATION_ACTION_TOOLS,
    RUNTIME_ACTION_TOOLS,
    RuntimePhase,
    RuntimeToolResult,
    format_tool_example,
    format_tool_prompt_line,
    normalize_args_for_storage,
    permission_level_for_tool,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GoalEvidenceAssessment(BaseModel):
    evidence_sufficient: bool
    reasoning: str = ""


class TerminalAssessment(BaseModel):
    need_more_observation: bool = False
    objective_satisfied: bool = False
    expected_result_supported: bool = False
    terminal_evidence_sufficient: bool = False
    reasoning: str = ""


class BrowserAction(BaseModel):
    tool: Literal[*RUNTIME_ACTION_TOOLS]
    args: dict[str, Any] = Field(default_factory=dict)


_DASHBOARD_FORMULA_SPECS: tuple[dict[str, Any], ...] = (
    {
        "target": "明星/核心人才",
        "parts": ("明星人才", "核心人才"),
        "exclusions": {
            "明星人才": (),
            "核心人才": ("明星/核心人才",),
        },
    },
    {
        "target": "待关注人员",
        "parts": ("业绩不佳者", "关注"),
        "exclusions": {
            "业绩不佳者": (),
            "关注": ("待关注", "待关注人员", "关注人员"),
        },
    },
)


class Runtime:
    """Execute goal-driven exploration and a single candidate-case attempt."""

    def __init__(self, task_config: dict[str, Any]) -> None:
        self.task_id = str(task_config.get("task_id", uuid.uuid4()))
        self.task_config = task_config
        self.target_url = task_config["target_url"]
        self._memory_context_text = str(task_config.get("memory_context_text") or "")
        self.browser_session = None
        self.browser = None
        self.context = None
        self.page = None
        self._playwright = None
        self._cdp_session = None
        self._last_page_info: dict[str, Any] = {}
        self._active_run_id = ""
        self._active_attempt_no = 1
        self._active_step_index = 0
        self._current_evidence: list[str] = []
        self._case_feedback: dict[str, list[str]] = {}
        self._locator_metrics = RuntimeLocatorMetrics()
        self._explore_observation_count = 0
        self._explore_deadline = 0.0
        self._last_exploration_page_info: dict[str, Any] = {}
        self._pending_exploration_action: dict[str, str] | None = None
        self._event_sink: Callable[..., Awaitable[None]] | None = None

    def bind_event_sink(
        self,
        event_sink: Callable[..., Awaitable[None]] | None,
    ) -> None:
        self._event_sink = event_sink

    async def launch_browser(self) -> None:
        await self._launch_browser()

    async def close_browser(self) -> None:
        await self._close_browser()

    async def reset_browser_state(self) -> None:
        await self._reset_browser_state()

    async def execute_attempt(
        self,
        run_id: str,
        case: RuntimeExecutableCase,
        attempt_no: int,
    ) -> CaseResult:
        self._active_run_id = run_id
        self._active_attempt_no = attempt_no
        self._active_step_index = 0
        return await self._execute_single_case(case)

    async def record_attempt_step(
        self,
        candidate_case_id: str,
        action: dict[str, Any],
        result: str,
        *,
        status: str = "failed",
        error_code: str = "",
    ) -> None:
        tool = str(action.get("tool", "runtime"))
        tool_result = self._make_runtime_tool_result(
            action,
            phase="execution",
            status=status,
            error_code=error_code or f"runtime.{tool}",
            message=result,
            llm_feedback=f"error: {error_code or f'runtime.{tool}'}",
        )
        await self._record_step(candidate_case_id, action, result, tool_result)

    async def _launch_browser(self) -> None:
        from browser_use import BrowserProfile, BrowserSession

        data_dir = os.path.join("data", "sessions", self.task_id)
        os.makedirs(data_dir, exist_ok=True)
        headed = os.getenv("BROWSER_HEADED", "false").lower() in ("true", "1", "yes")
        record_video = os.getenv(
            "BROWSER_RECORD_VIDEO",
            "false",
        ).lower() in ("true", "1", "yes")
        profile = BrowserProfile(
            record_video_dir=(
                os.path.join(data_dir, "videos")
                if record_video
                else None
            )
        )
        self.browser_session = BrowserSession(
            headless=not headed,
            browser_profile=profile,
        )
        await self.browser_session.start()
        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.connect_over_cdp(
            self.browser_session.cdp_url
        )
        self.context = self.browser.contexts[0]
        await self.context.tracing.start(
            screenshots=True,
            snapshots=True,
            sources=True,
        )
        self.page = (
            self.context.pages[0]
            if self.context.pages
            else await self.context.new_page()
        )
        from core.page_semantic import track_page_requests

        track_page_requests(self.page)
        self.context.on("page", track_page_requests)
        self.page._browser_session = self.browser_session
        set_current_task(self.task_id)
        set_current_page(self.page, task_id=self.task_id)
        try:
            self._cdp_session = await self.page.context.new_cdp_session(self.page)
            set_cdp_session(self._cdp_session, task_id=self.task_id)
        except Exception:
            self._cdp_session = None
        await self.page.goto(self.target_url, wait_until="load", timeout=30000)

    async def _close_browser(self) -> None:
        async def stop_tracing():
            if self.context:
                trace_path = os.path.join(
                    "data", "sessions", self.task_id, "trace.zip"
                )
                try:
                    await asyncio.wait_for(self.context.tracing.stop(path=trace_path), timeout=2.0)
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(self.context.close(), timeout=2.0)
                except Exception:
                    pass

        async def close_session():
            if self.browser_session:
                try:
                    await asyncio.wait_for(self.browser_session.close(), timeout=2.0)
                except Exception:
                    pass

        async def close_playwright():
            if self.browser:
                try:
                    await asyncio.wait_for(self.browser.close(), timeout=2.0)
                except Exception:
                    pass
            if self._playwright:
                try:
                    await asyncio.wait_for(self._playwright.stop(), timeout=2.0)
                except Exception:
                    pass

        try:
            await stop_tracing()
        except Exception:
            pass
        try:
            await close_session()
        except Exception:
            pass
        try:
            await close_playwright()
        except Exception:
            pass
        cleanup_task_context(self.task_id)

    async def _reset_browser_state(self) -> None:
        try:
            page_closed = not self.page or self.page.is_closed()
        except Exception:
            page_closed = True
        if page_closed:
            await self._close_browser()
            await self._launch_browser()
            return

        try:
            if self.context:
                await self.context.clear_cookies()
                try:
                    await self.context.clear_permissions()
                except Exception:
                    pass
            await self._clear_current_page_storage()
            await self._clear_cdp_storage_for_url(self.target_url)
            await self.page.goto(
                "about:blank",
                wait_until="domcontentloaded",
                timeout=15000,
            )
            await self._clear_cdp_storage_for_url(self.target_url)
            await self.page.goto(
                self.target_url,
                wait_until="networkidle",
                timeout=30000,
            )
        except Exception:
            await self._close_browser()
            await self._launch_browser()

    async def _clear_current_page_storage(self) -> None:
        if self.page is None:
            return
        try:
            await self.page.evaluate(
                """
async () => {
  try { localStorage.clear(); } catch (error) {}
  try { sessionStorage.clear(); } catch (error) {}
  try {
    if ("caches" in window) {
      const keys = await caches.keys();
      await Promise.all(keys.map((key) => caches.delete(key)));
    }
  } catch (error) {}
  try {
    if ("indexedDB" in window && indexedDB.databases) {
      const databases = await indexedDB.databases();
      await Promise.all(
        databases
          .map((database) => database && database.name)
          .filter(Boolean)
          .map((name) => new Promise((resolve) => {
            const request = indexedDB.deleteDatabase(name);
            request.onsuccess = request.onerror = request.onblocked = resolve;
          }))
      );
    }
  } catch (error) {}
}
"""
            )
        except Exception:
            pass

    async def _clear_cdp_storage_for_url(self, url: str) -> None:
        if self._cdp_session is None:
            return
        origin = self._storage_origin_for_url(url)
        if not origin:
            return
        try:
            await self._cdp_session.send(
                "Storage.clearDataForOrigin",
                {"origin": origin, "storageTypes": "all"},
            )
        except Exception:
            pass

    @staticmethod
    def _storage_origin_for_url(url: str) -> str:
        parsed = urlparse(str(url or ""))
        if not parsed.scheme or not parsed.netloc:
            return ""
        return f"{parsed.scheme}://{parsed.netloc}"

    def remember_case_feedback(self, candidate_case_id: str, note: str) -> None:
        normalized = note.strip()
        if not normalized:
            return
        feedback = self._case_feedback.setdefault(candidate_case_id, [])
        if normalized in feedback:
            return
        feedback.append(normalized)
        max_items = 8
        if len(feedback) > max_items:
            del feedback[:-max_items]

    def clear_case_feedback(self, candidate_case_id: str) -> None:
        self._case_feedback.pop(candidate_case_id, None)

    async def explore(self, goals: list[ExplorationGoal]) -> ExplorationResult:
        self._explore_observation_count = 0
        self._last_exploration_page_info = {}
        self._pending_exploration_action = None
        self._explore_deadline = (
            time.monotonic()
            + float(os.getenv("MAX_EXPLORE_MINUTES", "5")) * 60
        )
        goal_results: list[GoalResult] = []
        system_map = SystemMapEvid()
        for goal in goals:
            if self._exploration_budget_exhausted():
                goal_results.append(GoalResult(
                    goal_id=goal.id,
                    status="insufficient",
                    stop_reason="达到全局探索页数或时长限制",
                    observed_at=_now_iso(),
                ))
                continue
            try:
                result = await self._explore_single_goal(goal, system_map)
            except Exception as exc:
                result = GoalResult(
                    goal_id=goal.id,
                    status="blocked",
                    stop_reason=f"探索异常: {exc}",
                    observed_at=_now_iso(),
                )
            goal_results.append(result)
        return ExplorationResult(
            system_map=system_map,
            goal_results=goal_results,
        )

    async def _explore_single_goal(
        self,
        goal: ExplorationGoal,
        system_map: SystemMapEvid,
    ) -> GoalResult:
        max_steps = int(os.getenv("MAX_EXPLORE_STEPS_PER_GOAL", "10"))
        for step_count in range(max_steps):
            if self._exploration_budget_exhausted():
                return GoalResult(
                    goal_id=goal.id,
                    status="insufficient",
                    stop_reason="达到全局探索页数或时长限制",
                    observed_at=_now_iso(),
                )
            page_info = await self._observe_page()
            self._explore_observation_count += 1
            self._last_page_info = page_info
            self._remember_exploration_observation(system_map, page_info)
            evidence_sufficient = self._check_stop_condition(goal, page_info)
            if not evidence_sufficient:
                evidence_sufficient = await self._evaluate_goal_evidence(
                    goal,
                    page_info,
                )
            if evidence_sufficient:
                return GoalResult(
                    goal_id=goal.id,
                    status="found",
                    evidence_refs=self._exploration_evidence_refs(page_info),
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
            if action.get("tool") == "mark_task_complete":
                return GoalResult(
                    goal_id=goal.id,
                    status="found",
                    evidence_refs=self._exploration_evidence_refs(page_info),
                    stop_reason=str(action.get("args", {}).get("summary", "")),
                    observed_at=_now_iso(),
                )
            if action.get("tool") == "mark_task_failed":
                return GoalResult(
                    goal_id=goal.id,
                    status="not_found",
                    stop_reason=str(action.get("args", {}).get("reason", "")),
                    observed_at=_now_iso(),
                )
            action_result = await self._execute_explore_action(action)
            if action_result.is_success() and action_result.feedback_text():
                self._pending_exploration_action = self._describe_explore_action(
                    action,
                    page_info,
                )
        return GoalResult(
            goal_id=goal.id,
            status="insufficient",
            stop_reason=f"达到最大探索步数 {max_steps}",
            observed_at=_now_iso(),
        )

    def _remember_exploration_observation(
        self,
        system_map: SystemMapEvid,
        page_info: dict[str, Any],
    ) -> None:
        page_map = self._build_page_map(page_info)
        if page_map is None:
            return
        previous_page = self._build_page_map(self._last_exploration_page_info)
        if (
            previous_page is not None
            and self._pending_exploration_action is not None
            and not self._is_same_page_map(previous_page, page_map)
        ):
            self._remember_exploration_navigation(
                system_map,
                previous_page,
                page_map,
                self._pending_exploration_action,
            )
        self._pending_exploration_action = None
        self._last_exploration_page_info = page_info
        self._remember_exploration_page(system_map, page_map)
        self._remember_exploration_actions(system_map, page_map, page_info)
        self._remember_exploration_forms(system_map, page_map, page_info)

    def _remember_exploration_page(
        self,
        system_map: SystemMapEvid,
        page_map: PageMap,
    ) -> None:
        for existing in system_map.pages:
            if self._is_same_page_map(existing, page_map):
                existing.name = existing.name or page_map.name
                existing.title = existing.title or page_map.title
                existing.url_pattern = existing.url_pattern or page_map.url_pattern
                existing.elements = self._dedupe_texts(
                    [*existing.elements, *page_map.elements],
                    limit=24,
                )
                existing.discovered_actions = self._dedupe_texts(
                    [
                        *existing.discovered_actions,
                        *page_map.discovered_actions,
                    ],
                    limit=24,
                )
                existing.evidence_refs = self._dedupe_texts(
                    [*existing.evidence_refs, *page_map.evidence_refs],
                    limit=24,
                )
                return
        system_map.pages.append(page_map)

    def _remember_exploration_actions(
        self,
        system_map: SystemMapEvid,
        page_map: PageMap,
        page_info: dict[str, Any],
    ) -> None:
        for element in page_info.get("interactive_elements", [])[:24]:
            action_name = str(
                element.get("label")
                or element.get("text")
                or element.get("placeholder")
                or ""
            ).strip()
            if not action_name:
                continue
            trigger = str(
                element.get("role")
                or element.get("type")
                or ""
            ).strip()
            href = str(element.get("href") or "").strip()
            preconditions: list[str] = []
            if element.get("disabled") or element.get("enabled") is False:
                preconditions.append("控件当前禁用")
            if element.get("readonly"):
                preconditions.append("控件只读")
            action_map = ActionMap(
                action_name=action_name,
                trigger=trigger,
                source_page=page_map.name or page_map.url_pattern,
                target_page=href,
                preconditions=preconditions,
                evidence_refs=self._dedupe_texts(
                    [
                        f"page_url: {page_map.url_pattern}",
                        f"semantic_element: {str(element.get('id') or '').strip()}",
                    ],
                    limit=4,
                ),
            )
            existing = next(
                (
                    item
                    for item in system_map.actions
                    if (
                        item.action_name.strip().lower(),
                        item.trigger.strip().lower(),
                        item.source_page.strip().lower(),
                    ) == (
                        action_map.action_name.strip().lower(),
                        action_map.trigger.strip().lower(),
                        action_map.source_page.strip().lower(),
                    )
                ),
                None,
            )
            if existing is None:
                system_map.actions.append(action_map)
            else:
                existing.target_page = (
                    existing.target_page or action_map.target_page
                )
                existing.preconditions = self._dedupe_texts(
                    [*existing.preconditions, *action_map.preconditions],
                    limit=8,
                )
                existing.evidence_refs = self._dedupe_texts(
                    [*existing.evidence_refs, *action_map.evidence_refs],
                    limit=8,
                )

        for shadow in page_info.get("shadow_dom", [])[:10]:
            host = str(shadow.get("host") or "shadow-host").strip()
            for control in shadow.get("controls", [])[:10]:
                action_name = str(
                    control.get("label")
                    or control.get("text")
                    or ""
                ).strip()
                if not action_name:
                    continue
                trigger = str(
                    control.get("role")
                    or control.get("type")
                    or control.get("tag")
                    or ""
                ).strip()
                action_map = ActionMap(
                    action_name=action_name,
                    trigger=f"shadow:{host}:{trigger}",
                    source_page=page_map.name or page_map.url_pattern,
                    evidence_refs=[
                        f"page_url: {page_map.url_pattern}",
                        f"shadow_host: {host}",
                    ],
                )
                if not any(
                    item.action_name.strip().lower()
                    == action_map.action_name.strip().lower()
                    and item.trigger.strip().lower()
                    == action_map.trigger.strip().lower()
                    and item.source_page.strip().lower()
                    == action_map.source_page.strip().lower()
                    for item in system_map.actions
                ):
                    system_map.actions.append(action_map)

    def _remember_exploration_forms(
        self,
        system_map: SystemMapEvid,
        page_map: PageMap,
        page_info: dict[str, Any],
    ) -> None:
        submit_actions = [
            str(
                element.get("label")
                or element.get("text")
                or ""
            ).strip()
            for element in page_info.get("interactive_elements", [])
            if (
                str(element.get("button_type") or "").lower() == "submit"
                and str(
                    element.get("label")
                    or element.get("text")
                    or ""
                ).strip()
            )
        ]
        for index, form in enumerate(page_info.get("forms", [])[:12], start=1):
            form_name = str(
                form.get("name")
                or form.get("id")
                or form.get("action")
                or f"form-{index}"
            ).strip()
            fields: list[str] = []
            for field in form.get("fields", [])[:20]:
                label = str(
                    field.get("label")
                    or field.get("name")
                    or field.get("id")
                    or field.get("placeholder")
                    or ""
                ).strip()
                field_type = str(
                    field.get("field_type")
                    or field.get("tag")
                    or ""
                ).strip()
                if label and field_type:
                    fields.append(f"{field_type}:{label}")
                elif label:
                    fields.append(label)
            form_map = FormMap(
                form_name=form_name,
                page=page_map.name or page_map.url_pattern,
                fields=self._dedupe_texts(fields, limit=20),
                submit_action=submit_actions[0] if submit_actions else "",
                evidence_refs=self._dedupe_texts(
                    [
                        f"page_url: {page_map.url_pattern}",
                        f"form: {form_name}",
                    ],
                    limit=4,
                ),
            )
            existing = next(
                (
                    item
                    for item in system_map.forms
                    if (
                        item.form_name.strip().lower(),
                        item.page.strip().lower(),
                    ) == (
                        form_map.form_name.strip().lower(),
                        form_map.page.strip().lower(),
                    )
                ),
                None,
            )
            if existing is None:
                system_map.forms.append(form_map)
            else:
                existing.fields = self._dedupe_texts(
                    [*existing.fields, *form_map.fields],
                    limit=20,
                )
                existing.submit_action = (
                    existing.submit_action or form_map.submit_action
                )
                existing.evidence_refs = self._dedupe_texts(
                    [*existing.evidence_refs, *form_map.evidence_refs],
                    limit=8,
                )

    def _remember_exploration_navigation(
        self,
        system_map: SystemMapEvid,
        source_page: PageMap,
        target_page: PageMap,
        action: dict[str, str],
    ) -> None:
        source = source_page.name or source_page.url_pattern
        target = target_page.name or target_page.url_pattern
        navigation = NavigationMap(
            source=source,
            target=target,
            via=action.get("tool", ""),
            action=action.get("label") or action.get("selector", ""),
            evidence_refs=self._dedupe_texts(
                [
                    f"source_url: {source_page.url_pattern}",
                    f"target_url: {target_page.url_pattern}",
                    f"action: {action.get('label') or action.get('selector', '')}",
                ],
                limit=6,
            ),
        )
        if not any(
            (
                item.source.strip().lower(),
                item.target.strip().lower(),
                item.action.strip().lower(),
            )
            == (
                navigation.source.strip().lower(),
                navigation.target.strip().lower(),
                navigation.action.strip().lower(),
            )
            for item in system_map.navigations
        ):
            system_map.navigations.append(navigation)

        action_label = navigation.action.strip().lower()
        if action_label:
            for action_map in system_map.actions:
                if (
                    action_map.action_name.strip().lower() == action_label
                    and action_map.source_page.strip().lower()
                    == source.strip().lower()
                ):
                    action_map.target_page = target_page.url_pattern or target

    def _describe_explore_action(
        self,
        action: dict[str, Any],
        page_info: dict[str, Any],
    ) -> dict[str, str]:
        args = action.get("args", {})
        selector = str(args.get("selector") or "").strip()
        label = ""
        if selector:
            normalized_selector = (
                self._semantic_element_id_from_selector(selector) or selector
            )
            for element in page_info.get("interactive_elements", []):
                if str(element.get("id") or "") != normalized_selector:
                    continue
                label = str(
                    element.get("label")
                    or element.get("text")
                    or element.get("placeholder")
                    or ""
                ).strip()
                break
        return {
            "tool": str(action.get("tool") or ""),
            "selector": selector,
            "label": label or selector,
        }

    def _build_page_map(self, page_info: dict[str, Any]) -> PageMap | None:
        if not self._has_page_surface_evidence(page_info):
            return None
        title = str(page_info.get("title") or "").strip()
        url = str(page_info.get("url") or "").strip()
        headings = [
            str(value).strip()
            for value in page_info.get("headings", [])
            if str(value or "").strip()
        ]
        name = headings[0] if headings else title or url
        return PageMap(
            name=name,
            url_pattern=self._canonical_page_url(url) or url,
            title=title,
            elements=self._summarize_page_elements(page_info),
            discovered_actions=self._summarize_page_actions(page_info),
            evidence_refs=self._exploration_evidence_refs(page_info),
        )

    @staticmethod
    def _is_same_page_map(left: PageMap, right: PageMap) -> bool:
        left_url = Runtime._canonical_page_url(left.url_pattern)
        right_url = Runtime._canonical_page_url(right.url_pattern)
        if left_url and right_url:
            return left_url == right_url
        return (left.title or "").strip().lower() == (
            right.title or ""
        ).strip().lower()

    @staticmethod
    def _canonical_page_url(value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        parsed = urlparse(raw)
        if not parsed.scheme and not parsed.netloc:
            path = raw.split("?", 1)[0].split("#", 1)[0]
            return Runtime._normalize_route_path(path).lower()
        path = Runtime._normalize_route_path(parsed.path)
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"

    @staticmethod
    def _normalize_route_path(path: str) -> str:
        raw_path = str(path or "").strip()
        if not raw_path or raw_path == "/":
            return "/"
        normalized_segments: list[str] = []
        for segment in raw_path.strip("/").split("/"):
            if re.fullmatch(r"\d+", segment):
                normalized_segments.append(":id")
            elif re.fullmatch(
                r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
                r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
                segment,
            ):
                normalized_segments.append(":id")
            elif re.fullmatch(r"[0-9a-fA-F]{16,}", segment):
                normalized_segments.append(":id")
            else:
                normalized_segments.append(segment)
        return "/" + "/".join(normalized_segments)

    @staticmethod
    def _dedupe_texts(values: list[str], *, limit: int) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for raw in values:
            value = str(raw or "").strip()
            if not value:
                continue
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(value)
            if len(ordered) >= limit:
                break
        return ordered

    def _summarize_page_elements(self, page_info: dict[str, Any]) -> list[str]:
        elements: list[str] = []
        elements.extend(
            str(value).strip()
            for value in page_info.get("headings", [])[:6]
            if str(value or "").strip()
        )
        elements.extend(
            str(value).strip()
            for value in page_info.get("visible_texts", [])[:12]
            if str(value or "").strip()
        )
        for form in page_info.get("forms", [])[:4]:
            form_name = str(form.get("name") or form.get("id") or "").strip()
            if form_name:
                elements.append(f"form:{form_name}")
        for table in page_info.get("tables", [])[:3]:
            caption = str(table.get("caption") or "").strip()
            headers = [
                str(value).strip()
                for value in table.get("headers", [])[:4]
                if str(value or "").strip()
            ]
            if caption:
                elements.append(f"table:{caption}")
            elif headers:
                elements.append(f"table:{', '.join(headers)}")
        for element in page_info.get("interactive_elements", [])[:10]:
            label = str(element.get("label") or element.get("text") or "").strip()
            if label:
                elements.append(label)
        for frame in page_info.get("frames", [])[:4]:
            frame_name = str(
                frame.get("title")
                or frame.get("name")
                or frame.get("url")
                or ""
            ).strip()
            if frame_name:
                elements.append(f"frame:{frame_name}")
        for shadow in page_info.get("shadow_dom", [])[:4]:
            host = str(shadow.get("host") or "").strip()
            text = str(shadow.get("text") or "").strip()
            if host and text:
                elements.append(f"shadow:{host}:{text[:80]}")
            elif host:
                elements.append(f"shadow:{host}")
        return self._dedupe_texts(elements, limit=24)

    def _summarize_page_actions(self, page_info: dict[str, Any]) -> list[str]:
        actions: list[str] = []
        for element in page_info.get("interactive_elements", [])[:12]:
            label = str(element.get("label") or element.get("text") or "").strip()
            role = str(element.get("role") or element.get("type") or "").strip()
            if label and role:
                actions.append(f"{role}:{label}")
            elif label:
                actions.append(label)
        return self._dedupe_texts(actions, limit=24)

    @staticmethod
    def _has_page_surface_evidence(page_info: dict[str, Any]) -> bool:
        if not isinstance(page_info, dict):
            return False
        if page_info.get("loading"):
            return False
        if page_info.get("error") and not any(
            page_info.get(field)
            for field in (
                "title",
                "headings",
                "visible_texts",
                "forms",
                "tables",
                "interactive_elements",
                "nav_items",
                "frames",
                "shadow_dom",
            )
        ):
            return False
        return bool(
            str(page_info.get("url") or "").strip()
            and (
                str(page_info.get("title") or "").strip()
                or page_info.get("headings")
                or page_info.get("visible_texts")
                or page_info.get("forms")
                or page_info.get("tables")
                or page_info.get("interactive_elements")
                or page_info.get("nav_items")
                or page_info.get("frames")
                or page_info.get("shadow_dom")
            )
        )

    def _exploration_evidence_refs(
        self,
        page_info: dict[str, Any],
    ) -> list[str]:
        refs: list[str] = []
        url = str(page_info.get("url") or "").strip()
        title = str(page_info.get("title") or "").strip()
        if url:
            refs.append(f"page_url: {url}")
        if title:
            refs.append(f"page_title: {title}")
        refs.extend(
            f"heading: {str(value).strip()}"
            for value in page_info.get("headings", [])[:3]
            if str(value or "").strip()
        )
        refs.extend(
            f"visible_text: {str(value).strip()}"
            for value in page_info.get("visible_texts", [])[:5]
            if str(value or "").strip()
        )
        refs.extend(
            f"form: {str(form.get('name') or form.get('id') or form.get('action') or '').strip()}"
            for form in page_info.get("forms", [])[:3]
            if str(
                form.get("name")
                or form.get("id")
                or form.get("action")
                or ""
            ).strip()
        )
        semantic_source = str(
            (page_info.get("semantic_extraction") or {}).get("source") or ""
        ).strip()
        if semantic_source:
            refs.append(f"semantic_source: {semantic_source}")
        return self._dedupe_texts(refs, limit=16)

    def _exploration_budget_exhausted(self) -> bool:
        max_pages = max(1, int(os.getenv("MAX_EXPLORE_PAGES", "20")))
        return (
            self._explore_observation_count >= max_pages
            or (
                self._explore_deadline > 0
                and time.monotonic() >= self._explore_deadline
            )
        )

    async def _evaluate_goal_evidence(
        self,
        goal: ExplorationGoal,
        page_info: dict[str, Any],
    ) -> bool:
        prompt = f"""判断当前页面证据是否足以满足探索目标，只返回 JSON。

探索目标：{goal.goal}
预期证据：{goal.expected_evidence}
停止条件：{goal.stop_condition}
当前页面：{json.dumps(page_info, ensure_ascii=False)[:10000]}

必须能从当前页面内容直接核验，不得凭常识推断。
返回：{{"evidence_sufficient":true或false,"reasoning":"..."}}
"""
        from core.llm_client import safe_structured_invoke

        result = await safe_structured_invoke(
            prompt,
            GoalEvidenceAssessment,
            model_type="haiku",
        )
        return bool(result and result.evidence_sufficient)

    async def _observe_page(self) -> dict[str, Any]:
        from core.page_semantic import extract_page_semantics

        timeout_seconds = float(os.getenv("PAGE_SEMANTIC_TIMEOUT_SECONDS", "8"))
        try:
            page_info = await asyncio.wait_for(
                extract_page_semantics(self.page),
                timeout=timeout_seconds,
            )
            self._locator_metrics.record_semantic_extraction(
                page_info.get("semantic_extraction")
            )
            return page_info
        except asyncio.TimeoutError:
            return {
                "url": self.page.url if self.page else "",
                "error": (
                    "semantic_extraction_timeout:"
                    f" {timeout_seconds:g}s"
                ),
            }
        except Exception as exc:
            if self._should_recover_browser(str(exc)):
                try:
                    await self._reset_browser_state()
                    recovered = await asyncio.wait_for(
                        extract_page_semantics(self.page),
                        timeout=timeout_seconds,
                    )
                    self._locator_metrics.record_semantic_extraction(
                        recovered.get("semantic_extraction")
                    )
                    recovered["_browser_recovered"] = True
                    recovered["_recovery_reason"] = str(exc)
                    return recovered
                except Exception as recovery_exc:
                    return {
                        "url": self.page.url if self.page else "",
                        "error": str(exc),
                        "recovery_attempted": True,
                        "recovery_error": str(recovery_exc),
                    }
            return {
                "url": self.page.url if self.page else "",
                "error": str(exc),
            }

    async def _get_browser_action_fingerprint(self) -> str:
        if self.page is None:
            return ""
        try:
            from core.cdp_client import get_dom_fingerprint

            return str(await get_dom_fingerprint(self.page, self._cdp_session))
        except Exception:
            return ""

    @staticmethod
    def _should_recover_browser(message: str) -> bool:
        normalized = message.strip().lower()
        if not normalized:
            return False
        recovery_markers = (
            "target page, context or browser has been closed",
            "browser has been closed",
            "browser closed",
            "page has been closed",
            "context closed",
            "execution context was destroyed",
            "target closed",
            "has been disconnected",
        )
        return any(marker in normalized for marker in recovery_markers)

    def _check_stop_condition(
        self,
        goal: ExplorationGoal,
        page_info: dict[str, Any],
    ) -> bool:
        page_text = json.dumps(page_info, ensure_ascii=False).lower()
        sources = [goal.goal, goal.stop_condition, *goal.expected_evidence]
        candidates: set[str] = {
            source.strip().lower()
            for source in sources
            if source and len(source.strip()) >= 3
        }
        for source in sources:
            if not source:
                continue
            candidates.update(
                value.strip().lower()
                for value in re.findall(
                    r"""["'“”‘’]([^"'“”‘’]{3,})["'“”‘’]""",
                    source,
                )
            )
            candidates.update(
                value.lower()
                for value in re.findall(r"https?://[^\s,，。]+", source)
            )
            candidates.update(
                value.lower()
                for value in re.findall(
                    r"\b[A-Z][A-Za-z0-9_-]*(?:\s+[A-Z][A-Za-z0-9_-]*)+\b",
                    source,
                )
            )
        return any(candidate in page_text for candidate in candidates)

    async def _decide_explore_action(
        self,
        goal: ExplorationGoal,
        page_info: dict[str, Any],
        step_count: int,
    ) -> dict[str, Any] | None:
        page_snapshot = self._exploration_decision_snapshot(page_info)
        prompt = f"""你是 Web 探索 agent。只返回一个 JSON 对象。

目标：{goal.goal}
预期证据：{goal.expected_evidence}
停止条件：{goal.stop_condition}
已执行步数：{step_count}
当前页面语义：
{json.dumps(page_snapshot, ensure_ascii=False)[:8000]}

{format_tool_prompt_line(EXPLORATION_ACTION_TOOLS)}
{format_tool_example("click")}

规则：
1. click/select_option 的 selector 必须使用当前页面语义中真实存在的元素 id，例如 #1。
2. 不得猜测不存在的 selector、URL、菜单或页面。
3. 当前证据足够时使用 mark_task_complete；页面明确不支持目标且无法继续时使用 mark_task_failed。
4. 优先选择与目标直接相关且当前可交互的控件，避免重复 wait 或无方向 scroll。
"""
        return await self._invoke_json(prompt, "你负责收集可核验的页面证据。")

    def _exploration_decision_snapshot(
        self,
        page_info: dict[str, Any],
    ) -> dict[str, Any]:
        interactive_elements: list[dict[str, Any]] = []
        allowed_element_fields = (
            "id",
            "type",
            "input_type",
            "role",
            "label",
            "text",
            "placeholder",
            "href",
            "options",
            "enabled",
            "interactable",
            "readonly",
            "required",
            "checked",
            "expanded",
        )
        for element in page_info.get("interactive_elements", [])[:40]:
            compact = {
                field: element[field]
                for field in allowed_element_fields
                if field in element
                and element[field] not in ("", None, [], {})
            }
            if compact:
                interactive_elements.append(compact)

        forms: list[dict[str, Any]] = []
        for form in page_info.get("forms", [])[:10]:
            compact_fields = []
            for field in form.get("fields", [])[:20]:
                compact_fields.append({
                    key: field[key]
                    for key in (
                        "field_type",
                        "name",
                        "id",
                        "label",
                        "placeholder",
                        "required",
                        "disabled",
                        "options",
                    )
                    if key in field
                    and field[key] not in ("", None, [], {})
                })
            forms.append({
                key: value
                for key, value in {
                    "id": form.get("id"),
                    "name": form.get("name"),
                    "action": form.get("action"),
                    "method": form.get("method"),
                    "fields": compact_fields,
                    "submit_count": form.get("submit_count"),
                }.items()
                if value not in ("", None, [], {})
            })

        return {
            "url": page_info.get("url", ""),
            "title": page_info.get("title", ""),
            "headings": page_info.get("headings", [])[:8],
            "visible_texts": page_info.get("visible_texts", [])[:20],
            "nav_items": page_info.get("nav_items", [])[:20],
            "interactive_elements": interactive_elements,
            "forms": forms,
            "tables": page_info.get("tables", [])[:5],
            "modals": page_info.get("modals", [])[:5],
            "frames": page_info.get("frames", [])[:10],
            "shadow_dom": page_info.get("shadow_dom", [])[:10],
            "tabs": page_info.get("tabs", [])[:10],
            "error_messages": page_info.get("error_messages", [])[:10],
            "loading": bool(page_info.get("loading")),
        }

    async def _execute_explore_action(
        self,
        action: dict[str, Any],
    ) -> RuntimeToolResult:
        return await self._execute_browser_action(action, phase="exploration")

    async def _execute_single_case(
        self,
        case: RuntimeExecutableCase,
    ) -> CaseResult:
        started_at = _now_iso()
        self._locator_metrics = RuntimeLocatorMetrics()
        precondition_result = await self._check_preconditions(case, started_at)
        if precondition_result is not None:
            return precondition_result
        await self._prepare_case_start_state(case)

        max_steps = int(os.getenv("MAX_STEPS_PER_CASE", "15"))
        evidence: list[str] = []
        step_index = 0
        while step_index < max_steps:
            self._active_step_index = step_index
            self._current_evidence = evidence
            page_info = await self._observe_page()
            self._last_page_info = page_info
            terminal = await self._evaluate_terminal_assertion(
                case,
                page_info,
                evidence,
            )
            if terminal is not None:
                passed = self._all_terminal_satisfied(terminal)
                terminal_evidence = self._terminal_evidence_refs(
                    evidence,
                    page_info,
                    terminal,
                )
                return CaseResult(
                    run_id="",
                    candidate_case_id=case.id,
                    terminal_status="passed" if passed else "failed",
                    attempt_count=1,
                    started_at=started_at,
                    completed_at=_now_iso(),
                    summary=f"{'通过' if passed else '失败'}: {case.objective}",
                    evidence_refs=terminal_evidence,
                    failure_reason=None if passed else terminal.reasoning,
                )

            action = None
            if await self._execute_invalid_login_sequence(
                case,
                evidence,
            ):
                page_info = await self._observe_page()
                self._last_page_info = page_info
                terminal = await self._evaluate_terminal_assertion(
                    case,
                    page_info,
                    evidence,
                )
                if terminal is not None:
                    passed = self._all_terminal_satisfied(terminal)
                    terminal_evidence = self._terminal_evidence_refs(
                        evidence,
                        page_info,
                        terminal,
                    )
                    return CaseResult(
                        run_id="",
                        candidate_case_id=case.id,
                        terminal_status="passed" if passed else "failed",
                        attempt_count=1,
                        started_at=started_at,
                        completed_at=_now_iso(),
                        summary=f"{'通过' if passed else '失败'}: {case.objective}",
                        evidence_refs=terminal_evidence,
                        failure_reason=None if passed else terminal.reasoning,
                    )
                step_index = self._active_step_index
                continue

            action = await self._deterministic_quick_fill_action(case, evidence)

            if action is None and await self._execute_configured_login_sequence(
                case,
                evidence,
            ):
                page_info = await self._observe_page()
                self._last_page_info = page_info
                terminal = await self._evaluate_terminal_assertion(
                    case,
                    page_info,
                    evidence,
                )
                if terminal is not None:
                    passed = self._all_terminal_satisfied(terminal)
                    terminal_evidence = self._terminal_evidence_refs(
                        evidence,
                        page_info,
                        terminal,
                    )
                    return CaseResult(
                        run_id="",
                        candidate_case_id=case.id,
                        terminal_status="passed" if passed else "failed",
                        attempt_count=1,
                        started_at=started_at,
                        completed_at=_now_iso(),
                        summary=f"{'閫氳繃' if passed else '澶辫触'}: {case.objective}",
                        evidence_refs=terminal_evidence,
                        failure_reason=None if passed else terminal.reasoning,
                    )
                step_index = self._active_step_index
                continue

            if action is None and await self._execute_agent_write_sequence(
                case,
                evidence,
            ):
                page_info = await self._observe_page()
                self._last_page_info = page_info
                terminal = await self._evaluate_terminal_assertion(
                    case,
                    page_info,
                    evidence,
                )
                if terminal is not None:
                    passed = self._all_terminal_satisfied(terminal)
                    terminal_evidence = self._terminal_evidence_refs(
                        evidence,
                        page_info,
                        terminal,
                    )
                    return CaseResult(
                        run_id="",
                        candidate_case_id=case.id,
                        terminal_status="passed" if passed else "failed",
                        attempt_count=1,
                        started_at=started_at,
                        completed_at=_now_iso(),
                        summary=f"{'通过' if passed else '失败'}: {case.objective}",
                        evidence_refs=terminal_evidence,
                        failure_reason=None if passed else terminal.reasoning,
                    )
                step_index = self._active_step_index
                continue

            if action is None and await self._execute_dataset_write_sequence(
                case,
                evidence,
            ):
                page_info = await self._observe_page()
                self._last_page_info = page_info
                terminal = await self._evaluate_terminal_assertion(
                    case,
                    page_info,
                    evidence,
                )
                if terminal is not None:
                    passed = self._all_terminal_satisfied(terminal)
                    terminal_evidence = self._terminal_evidence_refs(
                        evidence,
                        page_info,
                        terminal,
                    )
                    return CaseResult(
                        run_id="",
                        candidate_case_id=case.id,
                        terminal_status="passed" if passed else "failed",
                        attempt_count=1,
                        started_at=started_at,
                        completed_at=_now_iso(),
                        summary=f"{'通过' if passed else '失败'}: {case.objective}",
                        evidence_refs=terminal_evidence,
                        failure_reason=None if passed else terminal.reasoning,
                    )
                step_index = self._active_step_index
                continue

            if action is None and await self._execute_skill_write_sequence(
                case,
                evidence,
            ):
                page_info = await self._observe_page()
                self._last_page_info = page_info
                terminal = await self._evaluate_terminal_assertion(
                    case,
                    page_info,
                    evidence,
                )
                if terminal is not None:
                    passed = self._all_terminal_satisfied(terminal)
                    terminal_evidence = self._terminal_evidence_refs(
                        evidence,
                        page_info,
                        terminal,
                    )
                    return CaseResult(
                        run_id="",
                        candidate_case_id=case.id,
                        terminal_status="passed" if passed else "failed",
                        attempt_count=1,
                        started_at=started_at,
                        completed_at=_now_iso(),
                        summary=f"{'通过' if passed else '失败'}: {case.objective}",
                        evidence_refs=terminal_evidence,
                        failure_reason=None if passed else terminal.reasoning,
                    )
                step_index = self._active_step_index
                continue

            if action is None:
                action = await self._decide_execute_action(
                    case,
                    page_info,
                    step_index,
                )
            if action is None:
                self.remember_case_feedback(
                    case.id,
                    "decision_error: invalid_or_empty_action",
                )
                tool_result = self._make_runtime_tool_result(
                    {
                        "tool": "decision_error",
                        "args": {"reason": "invalid_or_empty_action"},
                    },
                    phase="execution",
                    status="failed",
                    error_code="decision.invalid_or_empty_action",
                    message="模型未返回可执行的结构化动作",
                    llm_feedback="error: decision.invalid_or_empty_action",
                )
                await self._record_step(
                    case.id,
                    {
                        "tool": "decision_error",
                        "args": {"reason": "invalid_or_empty_action"},
                    },
                    "模型未返回可执行的结构化动作",
                    tool_result,
                )
                break
            if action.get("tool") == "mark_task_complete":
                args = action.get("args", {})
                summary = str(
                    args.get("summary")
                    or args.get("reason")
                    or args.get("message")
                    or args.get("target")
                    or ""
                )
                if not self._completion_action_allowed(case, evidence):
                    reason = (
                        "completion rejected: required user-action evidence "
                        "is missing"
                    )
                    self.remember_case_feedback(case.id, reason)
                    tool_result = self._make_runtime_tool_result(
                        action,
                        phase="execution",
                        status="completion_rejected",
                        error_code="completion.missing_action_evidence",
                        message=reason,
                        llm_feedback=f"error: {reason}",
                    )
                    await self._record_step(case.id, action, reason, tool_result)
                    step_index = self._active_step_index
                    continue

                tool_result = self._make_runtime_tool_result(
                    action,
                    phase="execution",
                    status="success",
                    message=f"completed: {summary}",
                    llm_feedback=summary or "completed",
                )
                result = tool_result.feedback_text()
                await self._record_step(case.id, action, result, tool_result)
                terminal_evidence = self._evidence_refs_with_locator_metrics(
                    [*evidence, result]
                )
                terminal_evidence.append(
                    "terminal_assertion: completion_action: "
                    f"{summary or case.expected}"
                )
                return CaseResult(
                    run_id="",
                    candidate_case_id=case.id,
                    terminal_status="passed",
                    attempt_count=1,
                    started_at=started_at,
                    completed_at=_now_iso(),
                    summary=f"閫氳繃: {case.objective}",
                    evidence_refs=terminal_evidence,
                    failure_reason=None,
                )
            if action.get("tool") == "mark_task_failed":
                reason = str(action.get("args", {}).get("reason", "执行判定失败"))
                self.remember_case_feedback(case.id, reason)
                tool_result = self._make_runtime_tool_result(
                    action,
                    phase="execution",
                    status="success",
                    message=f"failed: {reason}",
                    llm_feedback=reason,
                )
                await self._record_step(case.id, action, reason, tool_result)
                return CaseResult(
                    run_id="",
                    candidate_case_id=case.id,
                    terminal_status="failed",
                    attempt_count=1,
                    started_at=started_at,
                    completed_at=_now_iso(),
                    summary=f"失败: {case.objective}",
                    evidence_refs=self._evidence_refs_with_locator_metrics(evidence),
                    failure_reason=reason,
                )

            tool_result = await self._execute_test_action(action)
            result = tool_result.feedback_text()
            if result:
                evidence.append(result)
                if tool_result.is_failure():
                    self.remember_case_feedback(case.id, result)
            await self._record_step(case.id, action, result, tool_result)
            if not tool_result.is_failure():
                terminal = await self._deterministic_input_value_assertion(
                    case,
                    evidence,
                )
                if terminal is not None:
                    passed = self._all_terminal_satisfied(terminal)
                    terminal_evidence = self._evidence_refs_with_locator_metrics(
                        evidence
                    )
                    terminal_evidence.append(
                        f"terminal_assertion: {terminal.reasoning}"
                    )
                    return CaseResult(
                        run_id="",
                        candidate_case_id=case.id,
                        terminal_status="passed" if passed else "failed",
                        attempt_count=1,
                        started_at=started_at,
                        completed_at=_now_iso(),
                        summary=f"{'通过' if passed else '失败'}: {case.objective}",
                        evidence_refs=terminal_evidence,
                        failure_reason=None if passed else terminal.reasoning,
                    )
            step_index = self._active_step_index

        page_info = await self._observe_page()
        self._last_page_info = page_info
        terminal = await self._evaluate_terminal_assertion(
            case,
            page_info,
            evidence,
        )
        if terminal is not None:
            passed = self._all_terminal_satisfied(terminal)
            terminal_evidence = self._terminal_evidence_refs(
                evidence,
                page_info,
                terminal,
            )
            return CaseResult(
                run_id="",
                candidate_case_id=case.id,
                terminal_status="passed" if passed else "failed",
                attempt_count=1,
                started_at=started_at,
                completed_at=_now_iso(),
                summary=f"{'通过' if passed else '失败'}: {case.objective}",
                evidence_refs=terminal_evidence,
                failure_reason=None if passed else terminal.reasoning,
            )

        return CaseResult(
            run_id="",
            candidate_case_id=case.id,
            terminal_status="incomplete",
            attempt_count=1,
            started_at=started_at,
            completed_at=_now_iso(),
            summary=f"未完成: {case.objective}",
            evidence_refs=self._evidence_refs_with_locator_metrics(evidence),
            failure_reason=f"达到最大步数 {max_steps} 或无法继续",
        )

    def _terminal_evidence_refs(
        self,
        evidence: list[str],
        page_info: dict[str, Any],
        terminal: TerminalAssertion,
    ) -> list[str]:
        terminal_evidence = list(evidence)
        current_url = str(page_info.get("url") or "")
        current_title = str(page_info.get("title") or "")
        if current_url:
            terminal_evidence.append(f"page_url: {current_url}")
        if current_title:
            terminal_evidence.append(f"page_title: {current_title}")
        if terminal.reasoning:
            terminal_evidence.append(
                f"terminal_assertion: {terminal.reasoning}"
            )
        return self._evidence_refs_with_locator_metrics(terminal_evidence)

    def _evidence_refs_with_locator_metrics(
        self,
        evidence: list[str],
    ) -> list[str]:
        refs = list(evidence)
        if self._locator_metrics.has_signal():
            refs.append(self._locator_metrics.evidence_ref())
        return refs

    async def _check_preconditions(
        self,
        case: RuntimeExecutableCase,
        started_at: str,
    ) -> CaseResult | None:
        for precondition in case.preconditions:
            if not precondition.satisfiable_by_agent:
                return CaseResult(
                    run_id="",
                    candidate_case_id=case.id,
                    terminal_status=precondition.failure_policy,
                    attempt_count=0,
                    started_at=started_at,
                    completed_at=_now_iso(),
                    summary=f"前置条件不可满足: {precondition.description}",
                    failure_reason=(
                        f"precondition_{precondition.failure_policy}: "
                        f"{precondition.description}"
                    ),
                )
            if (
                precondition.type == "account_role"
                and not precondition.required_role
            ):
                return CaseResult(
                    run_id="",
                    candidate_case_id=case.id,
                    terminal_status="incomplete",
                    attempt_count=0,
                    started_at=started_at,
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
        if not self._has_required_action_evidence(case, evidence_refs):
            return None

        agent_assertion = await self._deterministic_agent_write_terminal_assertion(
            case,
            page_info,
            evidence_refs,
        )
        if agent_assertion is not None:
            return agent_assertion

        dataset_assertion = await self._deterministic_dataset_write_terminal_assertion(
            case,
            page_info,
            evidence_refs,
        )
        if dataset_assertion is not None:
            return dataset_assertion

        skill_assertion = await self._deterministic_skill_write_terminal_assertion(
            case,
            page_info,
            evidence_refs,
        )
        if skill_assertion is not None:
            return skill_assertion

        invalid_login_assertion = (
            self._deterministic_invalid_login_terminal_assertion(
                case,
                page_info,
                evidence_refs,
            )
        )
        if invalid_login_assertion is not None:
            return invalid_login_assertion

        login_assertion = self._deterministic_configured_login_terminal_assertion(
            case,
            page_info,
            evidence_refs,
        )
        if login_assertion is not None:
            return login_assertion
        deterministic = self._deterministic_terminal_assertion(
            case,
            page_info,
        )
        if deterministic is not None:
            return deterministic
        dom_assertion = await self._deterministic_dom_terminal_assertion(
            case,
            page_info,
        )
        if dom_assertion is not None:
            return dom_assertion
        input_value_assertion = await self._deterministic_input_value_assertion(
            case,
            evidence_refs,
        )
        if input_value_assertion is not None:
            return input_value_assertion
        prompt = f"""评估当前页面是否已到测试终态，只返回 JSON。

目标：{case.objective}
预期结果：{case.expected}
当前页面：{json.dumps(page_info, ensure_ascii=False)[:8000]}
动作证据：{evidence_refs[-5:]}

如果当前页面证据已经足够做出最终结论：
- 通过：objective_satisfied=true、expected_result_supported=true、terminal_evidence_sufficient=true
- 失败：objective_satisfied=false、expected_result_supported=false、terminal_evidence_sufficient=true，
  reasoning 必须明确写出与预期直接矛盾的页面证据
- 继续观察：need_more_observation=true、terminal_evidence_sufficient=false

返回：
{{"objective_satisfied":false,"expected_result_supported":false,
"terminal_evidence_sufficient":false,"reasoning":"..."}}
"""
        from core.llm_client import safe_structured_invoke

        prompt += (
            "\nIf more browser actions are required, set "
            "need_more_observation=true. Otherwise set it to false."
        )
        assessment = await safe_structured_invoke(
            prompt,
            TerminalAssessment,
            model_type="haiku",
        )
        if (
            assessment is None
            or assessment.need_more_observation
            or not assessment.terminal_evidence_sufficient
        ):
            return None
        return TerminalAssertion(
            objective_satisfied=assessment.objective_satisfied,
            expected_result_supported=assessment.expected_result_supported,
            terminal_evidence_sufficient=assessment.terminal_evidence_sufficient,
            reasoning=assessment.reasoning,
        )

    def _deterministic_invalid_login_terminal_assertion(
        self,
        case: RuntimeExecutableCase,
        page_info: dict[str, Any],
        evidence_refs: list[str],
    ) -> TerminalAssertion | None:
        if not self._case_requires_invalid_login_submission(case):
            return None
        if not any(
            str(item or "").lower().startswith("clicked:")
            and "#login-submit-button" in str(item or "")
            for item in evidence_refs
        ):
            return None

        stable_text = self._page_text_for_login_assertion(page_info)
        dashboard_markers = (
            "\u667a\u80fd\u4f53\u5e7f\u573a",
            "\u77e5\u8bc6\u5e93\u7ba1\u7406",
            "\u6280\u80fd\u7ba1\u7406",
            "\u63a7\u5236\u53f0",
            "dashboard",
        )
        matched_dashboard = [
            marker for marker in dashboard_markers if marker.lower() in stable_text
        ]
        if len(matched_dashboard) >= 2:
            return TerminalAssertion(
                objective_satisfied=False,
                expected_result_supported=False,
                terminal_evidence_sufficient=True,
                reasoning=(
                    "Invalid login unexpectedly reached dashboard markers: "
                    + ", ".join(matched_dashboard[:3])
                ),
            )

        error_markers = (
            "\u5bc6\u7801\u9519\u8bef",
            "\u8d26\u53f7\u6216\u5bc6\u7801\u9519\u8bef",
            "\u767b\u5f55\u5931\u8d25",
            "\u9519\u8bef",
            "invalid password",
            "wrong password",
            "incorrect",
            "login failed",
        )
        login_page_markers = (
            "\u7acb\u5373\u767b\u5f55",
            "\u7528\u6237\u540d",
            "\u5bc6\u7801",
            "login",
            "username",
            "password",
        )
        matched_errors = [
            marker for marker in error_markers if marker.lower() in stable_text
        ]
        has_login_page = any(
            marker.lower() in stable_text for marker in login_page_markers
        )
        if matched_errors and has_login_page:
            return TerminalAssertion(
                objective_satisfied=True,
                expected_result_supported=True,
                terminal_evidence_sufficient=True,
                reasoning=(
                    "Invalid login stayed on login page with error evidence: "
                    + ", ".join(matched_errors[:2])
                ),
            )
        return None

    def _deterministic_configured_login_terminal_assertion(
        self,
        case: RuntimeExecutableCase,
        page_info: dict[str, Any],
        evidence_refs: list[str],
    ) -> TerminalAssertion | None:
        if self._case_requires_agent_write(case):
            return None
        if self._case_requires_dataset_write(case):
            return None
        if self._case_requires_skill_write(case):
            return None
        if not self._case_requires_configured_login(case):
            return None
        if not any(
            str(item or "").lower().startswith("clicked:")
            and "#login-submit-button" in str(item or "")
            for item in evidence_refs
        ):
            return None

        account = self._first_configured_account()
        if account is None:
            return None
        aliases = self._configured_account_aliases(account)
        if not aliases:
            return None

        stable_text = self._page_text_for_login_assertion(page_info)
        matched_alias = next(
            (alias for alias in aliases if alias.lower() in stable_text),
            "",
        )
        if not matched_alias:
            return None

        dashboard_markers = (
            "\u667a\u80fd\u4f53\u5e7f\u573a",
            "\u77e5\u8bc6\u5e93\u7ba1\u7406",
            "\u6280\u80fd\u7ba1\u7406",
            "\u63a7\u5236\u53f0",
            "dashboard",
        )
        matched_markers = [
            marker for marker in dashboard_markers if marker.lower() in stable_text
        ]
        if len(matched_markers) < 2:
            return None

        return TerminalAssertion(
            objective_satisfied=True,
            expected_result_supported=True,
            terminal_evidence_sufficient=True,
            reasoning=(
                "Configured login succeeded: visible account identity "
                f"'{matched_alias}' and dashboard markers "
                f"{', '.join(matched_markers[:3])} were found after submit."
            ),
        )

    @staticmethod
    def _page_text_for_login_assertion(page_info: dict[str, Any]) -> str:
        text_units: list[str] = [
            str(page_info.get("url") or ""),
            str(page_info.get("title") or ""),
            *[str(value) for value in page_info.get("headings", [])],
            *[str(value) for value in page_info.get("visible_texts", [])],
            *[str(value) for value in page_info.get("error_messages", [])],
        ]
        for element in page_info.get("interactive_elements", []) or []:
            if not isinstance(element, Mapping):
                continue
            text_units.extend(
                [
                    str(element.get("text") or ""),
                    str(element.get("label") or ""),
                    str(element.get("aria_label") or ""),
                    str(element.get("placeholder") or ""),
                ]
                )
        return "\n".join(text_units).lower()

    async def _deterministic_agent_write_terminal_assertion(
        self,
        case: RuntimeExecutableCase,
        page_info: dict[str, Any],
        evidence_refs: list[str],
    ) -> TerminalAssertion | None:
        if not self._case_requires_agent_write(case):
            return None
        if not self._has_agent_save_evidence(evidence_refs):
            return None

        data = self._agent_write_data_for_case(case)
        if data is None:
            return None
        name, _, gateway = data
        stable_text = self._page_text_for_login_assertion(page_info)

        if self._case_requires_agent_invalid_gateway(case):
            form_state = await self._agent_form_state()
            if form_state is not None:
                current_gateway = str(form_state.get("gateway") or "")
                gateway_valid = bool(form_state.get("gatewayValid"))
                if current_gateway == "not-url" and not gateway_valid:
                    return TerminalAssertion(
                        objective_satisfied=True,
                        expected_result_supported=True,
                        terminal_evidence_sufficient=True,
                        reasoning=(
                            "Invalid agent gateway was blocked by the visible "
                            "agent form: gatewayUrl=not-url is invalid and the "
                            "save dialog remains open."
                        ),
                    )
            if name and name.lower() in stable_text:
                return TerminalAssertion(
                    objective_satisfied=False,
                    expected_result_supported=False,
                    terminal_evidence_sufficient=True,
                    reasoning=(
                        "Invalid gateway case appears to have created a visible "
                        f"agent record: {name}."
                    ),
                )
            return None

        if name and name.lower() in stable_text:
            return TerminalAssertion(
                objective_satisfied=True,
                expected_result_supported=True,
                terminal_evidence_sufficient=True,
                reasoning=(
                    "Agent creation succeeded through UI: visible agent record "
                    f"{name} was found after saving gateway {gateway}."
                ),
            )

        error_markers = (
            "操作失败",
            "创建失败",
            "网关地址格式不正确",
            "不能为空",
            "error",
            "failed",
        )
        matched_errors = [
            marker for marker in error_markers if marker.lower() in stable_text
        ]
        if matched_errors:
            return TerminalAssertion(
                objective_satisfied=False,
                expected_result_supported=False,
                terminal_evidence_sufficient=True,
                reasoning=(
                    "Agent creation failed with visible error evidence: "
                    + ", ".join(matched_errors[:2])
                ),
            )
        return None

    async def _deterministic_dataset_write_terminal_assertion(
        self,
        case: RuntimeExecutableCase,
        page_info: dict[str, Any],
        evidence_refs: list[str],
    ) -> TerminalAssertion | None:
        if not self._case_requires_dataset_write(case):
            return None
        if not self._has_dataset_save_evidence(evidence_refs):
            return None

        data = self._dataset_write_data_for_case(case)
        if data is None:
            return None
        name, _, empty_marker = data
        stable_text = self._page_text_for_login_assertion(page_info)

        if self._case_requires_dataset_empty_name(case):
            form_state = await self._dataset_form_state()
            if form_state is not None:
                current_name = str(form_state.get("name") or "")
                name_valid = bool(form_state.get("nameValid"))
                save_visible = bool(form_state.get("saveVisible"))
                title_visible = bool(form_state.get("titleVisible"))
                if current_name == "" and not name_valid and save_visible and title_visible:
                    return TerminalAssertion(
                        objective_satisfied=True,
                        expected_result_supported=True,
                        terminal_evidence_sufficient=True,
                        reasoning=(
                            "Empty dataset name was blocked by the visible "
                            "knowledge-base form: the name field is invalid "
                            "and the save dialog remains open."
                        ),
                    )
            return None

        if name and name.lower() in stable_text:
            return TerminalAssertion(
                objective_satisfied=True,
                expected_result_supported=True,
                terminal_evidence_sufficient=True,
                reasoning=(
                    "Dataset creation succeeded through UI: visible "
                    f"knowledge-base record {name} was found after saving."
                ),
            )

        error_markers = (
            "操作失败",
            "创建失败",
            "知识库名称已存在",
            "不能为空",
            "error",
            "failed",
        )
        matched_errors = [
            marker for marker in error_markers if marker.lower() in stable_text
        ]
        if matched_errors:
            return TerminalAssertion(
                objective_satisfied=False,
                expected_result_supported=False,
                terminal_evidence_sufficient=True,
                reasoning=(
                    "Dataset creation failed with visible error evidence: "
                    + ", ".join(matched_errors[:2])
                ),
            )
        if empty_marker.lower() in stable_text:
            return TerminalAssertion(
                objective_satisfied=False,
                expected_result_supported=False,
                terminal_evidence_sufficient=True,
                reasoning=(
                    "Unexpected empty-name dataset marker is visible in the "
                    f"list: {empty_marker}."
                ),
            )
        return None

    async def _deterministic_skill_write_terminal_assertion(
        self,
        case: RuntimeExecutableCase,
        page_info: dict[str, Any],
        evidence_refs: list[str],
    ) -> TerminalAssertion | None:
        if not self._case_requires_skill_write(case):
            return None
        if not self._has_skill_save_evidence(evidence_refs):
            return None

        data = self._skill_write_data_for_case(case)
        if data is None:
            return None
        name, _, _ = data
        stable_text = self._page_text_for_login_assertion(page_info)

        if self._case_requires_skill_duplicate_core_file(case):
            duplicate_evidence = [
                str(item or "")
                for item in evidence_refs
                if "SKILL.md" in str(item or "")
                and any(
                    marker in str(item or "")
                    for marker in ("重复", "不可重复", "核心文件", "禁止", "已存在", "duplicate")
                )
            ]
            if duplicate_evidence:
                return TerminalAssertion(
                    objective_satisfied=True,
                    expected_result_supported=True,
                    terminal_evidence_sufficient=True,
                    reasoning=(
                        "Duplicate SKILL.md creation was blocked by the UI/API "
                        f"dialog evidence: {duplicate_evidence[-1]}"
                    ),
                )
            return None

        file_tree_evidence = any(
            "skill_file_tree:" in str(item or "").lower()
            and "skill.md" in str(item or "").lower()
            and "index.js" in str(item or "").lower()
            for item in evidence_refs
        )
        required_markers = (name.lower(), "skill.md", "index.js")
        if all(marker in stable_text for marker in required_markers) or (
            name.lower() in stable_text and file_tree_evidence
        ):
            return TerminalAssertion(
                objective_satisfied=True,
                expected_result_supported=True,
                terminal_evidence_sufficient=True,
                reasoning=(
                    "Skill scaffold succeeded through UI: the renamed skill "
                    f"{name} is visible and the editor/file tree exposes "
                    "SKILL.md and index.js."
                ),
            )

        error_markers = (
            "创建脚手架失败",
            "加载技能详情失败",
            "保存失败",
            "网络异常",
            "error",
            "failed",
        )
        matched_errors = [
            marker for marker in error_markers if marker.lower() in stable_text
        ]
        if matched_errors:
            return TerminalAssertion(
                objective_satisfied=False,
                expected_result_supported=False,
                terminal_evidence_sufficient=True,
                reasoning=(
                    "Skill scaffold failed with visible error evidence: "
                    + ", ".join(matched_errors[:2])
                ),
            )
        return None

    @staticmethod
    def _has_agent_save_evidence(evidence_refs: list[str]) -> bool:
        return any(
            str(item or "").lower().startswith("clicked:")
            and (
                "保存" in str(item or "")
                or 'button[type="submit"]' in str(item or "")
            )
            for item in evidence_refs
        )

    @staticmethod
    def _has_skill_save_evidence(evidence_refs: list[str]) -> bool:
        return any(
            (
                str(item or "").lower().startswith("clicked:")
                and (
                    "快速初始化脚手架" in str(item or "")
                    or "编译构建并加载" in str(item or "")
                    or "skill-scaffold" in str(item or "")
                )
            )
            or str(item or "").lower().startswith("dialog:")
            or str(item or "").lower().startswith("pressed:")
            for item in evidence_refs
        )

    @staticmethod
    def _has_dataset_save_evidence(evidence_refs: list[str]) -> bool:
        return any(
            str(item or "").lower().startswith("clicked:")
            and (
                "保存" in str(item or "")
                or 'button[type="submit"]' in str(item or "")
            )
            for item in evidence_refs
        )

    @staticmethod
    def _has_required_action_evidence(
        case: RuntimeExecutableCase,
        evidence_refs: list[str],
    ) -> bool:
        if not Runtime._case_requires_action_evidence(case):
            return True

        lowered_evidence = [
            str(item or "").strip().lower()
            for item in evidence_refs
        ]
        has_input = any(item.startswith("input:") for item in lowered_evidence)
        has_click_or_navigation = any(
            item.startswith(("clicked:", "navigated:", "selected:"))
            for item in lowered_evidence
        )
        has_user_action = has_input or has_click_or_navigation
        if not has_user_action:
            return False

        case_text = Runtime._case_action_text(case)
        quick_fill_markers = (
            "\u4e00\u952e\u586b\u503c",
            "username=admin",
            "password=cangjie*2026",
            "quick fill",
            "quick-fill",
            "one-click",
            "preset credential",
        )
        if any(marker in case_text for marker in quick_fill_markers):
            return True

        input_markers = (
            "\u8f93\u5165",
            "\u586b\u5199",
            "\u586b\u5165",
            " input",
            " enter",
            " type",
            " fill",
        )
        submit_markers = (
            "\u63d0\u4ea4",
            "\u767b\u5f55",
            "\u7acb\u5373\u767b\u5f55",
            " submit",
            " login",
            " sign in",
        )
        click_markers = (
            "\u70b9\u51fb",
            " click",
        )
        expects_input = any(marker in case_text for marker in input_markers)
        expects_submit = any(marker in case_text for marker in submit_markers)
        expects_click = any(marker in case_text for marker in click_markers)
        if expects_input and expects_submit:
            return has_input and has_click_or_navigation
        if expects_input and expects_click:
            return has_input or has_click_or_navigation
        if expects_input:
            return has_input
        if expects_submit:
            return has_click_or_navigation
        if expects_click:
            return has_click_or_navigation
        return has_user_action

    @staticmethod
    def _completion_action_allowed(
        case: RuntimeExecutableCase,
        evidence_refs: list[str],
    ) -> bool:
        if Runtime._case_is_passive_observation(case):
            return True
        return Runtime._has_required_action_evidence(case, evidence_refs)

    @staticmethod
    def _case_is_passive_observation(case: RuntimeExecutableCase) -> bool:
        case_text = Runtime._case_action_text(case)
        passive_markers = (
            "\u5b58\u5728",
            "\u53ef\u89c1",
            "\u663e\u793a",
            "\u5c55\u793a",
            "\u63d0\u4f9b",
            "\u52a0\u8f7d",
            " exist",
            " visible",
            " display",
            " show",
            " provide",
            " load",
        )
        action_markers = (
            "\u70b9\u51fb",
            "\u8f93\u5165",
            "\u586b\u5199",
            "\u586b\u5165",
            "\u63d0\u4ea4",
            "\u89e6\u53d1",
            " click",
            " input",
            " enter",
            " type",
            " fill",
            " submit",
            " trigger",
        )
        return (
            any(marker in case_text for marker in passive_markers)
            and not any(marker in case_text for marker in action_markers)
        )

    @staticmethod
    def _case_requires_action_evidence(case: RuntimeExecutableCase) -> bool:
        case_text = Runtime._case_action_text(case)
        markers = (
            "\u8f93\u5165",
            "\u586b\u5199",
            "\u586b\u5165",
            "\u70b9\u51fb",
            "\u63d0\u4ea4",
            "\u767b\u5f55",
            "\u9009\u62e9",
            "\u52fe\u9009",
            "\u641c\u7d22",
            "\u89e6\u53d1",
            "\u65e0\u6548\u5bc6\u7801",
            "\u9519\u8bef\u5bc6\u7801",
            "\u4e00\u952e\u586b\u503c",
            " input",
            " enter",
            " type",
            " fill",
            " click",
            " submit",
            " login",
            " sign in",
            " select",
            " choose",
            " toggle",
            " search",
            " invalid password",
            " wrong password",
            " quick fill",
            " quick-fill",
            " one-click",
        )
        return any(marker in case_text for marker in markers)

    @staticmethod
    def _case_action_text(case: RuntimeExecutableCase) -> str:
        return (
            f" {case.objective}\n{case.expected}\n{case.hints} "
        ).lower()

    async def _deterministic_input_value_assertion(
        self,
        case: RuntimeExecutableCase,
        evidence_refs: list[str],
    ) -> TerminalAssertion | None:
        if self.page is None:
            return None

        case_text = "\n".join(
            filter(None, [case.objective, case.expected, case.hints])
        )
        quick_fill_markers = (
            "一键填值",
            "预设凭据",
            "quick fill",
            "quick-fill",
            "one-click",
            "preset credential",
        )
        lowered_case_text = case_text.lower()
        explicit_field_value_case = (
            "username=admin" in lowered_case_text
            and "password=cangjie*2026" in lowered_case_text
        )
        quick_fill_action = self._has_quick_fill_action_evidence(evidence_refs)
        has_expected_quick_fill_values = (
            "admin" in lowered_case_text
            and "cangjie*2026" in lowered_case_text
        )
        business_outcome_markers = (
            "\u63a7\u5236\u53f0",
            "\u767b\u5f55\u6210\u529f",
            "\u9519\u8bef\u63d0\u793a",
            "\u767b\u5f55\u5931\u8d25",
            "\u667a\u80fd\u4f53\u5e7f\u573a",
            "\u77e5\u8bc6\u5e93\u7ba1\u7406",
            "\u6280\u80fd\u7ba1\u7406",
            "dashboard",
            "access_token",
            "login success",
            "login failed",
            "error message",
        )
        field_value_case_from_action = (
            quick_fill_action
            and has_expected_quick_fill_values
            and not any(
                marker in lowered_case_text
                for marker in business_outcome_markers
            )
        )
        if not (explicit_field_value_case or field_value_case_from_action) and not any(
            keyword in lowered_case_text for keyword in quick_fill_markers
        ):
            return None

        expected_username = "admin" if "admin" in lowered_case_text else ""
        expected_password = ""
        for candidate in ("cangjie*2026", "admin123"):
            if candidate in case_text:
                expected_password = candidate
                break
        if not (expected_username and expected_password):
            return None

        try:
            values = await self.page.evaluate(
                """
() => Array.from(document.querySelectorAll("input, textarea")).map((el) => {
  const rect = el.getBoundingClientRect();
  const style = window.getComputedStyle(el);
  return {
    id: el.id || "",
    name: el.getAttribute("name") || "",
    type: (el.getAttribute("type") || el.tagName || "").toLowerCase(),
    placeholder: el.getAttribute("placeholder") || "",
    value: "value" in el ? el.value : "",
    visible: rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden"
  };
}).filter((item) => item.visible);
"""
            )
        except Exception:
            return None

        if not isinstance(values, list):
            return None

        def _matches_username(item: object) -> bool:
            if not isinstance(item, Mapping):
                return False
            field_type = str(item.get("type") or "").lower()
            if field_type == "password":
                return False
            return str(item.get("value") or "") == expected_username

        def _matches_password(item: object) -> bool:
            if not isinstance(item, Mapping):
                return False
            field_type = str(item.get("type") or "").lower()
            return (
                field_type == "password"
                and str(item.get("value") or "") == expected_password
            )

        username_ok = not expected_username or any(
            _matches_username(item) for item in values
        )
        password_ok = not expected_password or any(
            _matches_password(item) for item in values
        )
        if not (username_ok and password_ok):
            return None

        matched_parts = []
        if expected_username:
            matched_parts.append(f"username={expected_username}")
        if expected_password:
            matched_parts.append("password=expected credential")
        return TerminalAssertion(
            objective_satisfied=True,
            expected_result_supported=True,
            terminal_evidence_sufficient=True,
            reasoning=(
                "确定性表单值证据匹配: "
                + ", ".join(matched_parts)
            ),
        )

    @staticmethod
    def _has_quick_fill_action_evidence(evidence_refs: list[str]) -> bool:
        quick_fill_markers = (
            "\u4e00\u952e\u586b\u503c",
            "quick fill",
            "quick-fill",
            "one-click",
            "preset credential",
        )
        for item in evidence_refs:
            text = str(item or "").lower()
            if text.startswith("clicked:") and any(
                marker in text for marker in quick_fill_markers
            ):
                return True
        return False

    @staticmethod
    def _deterministic_terminal_assertion(
        case: RuntimeExecutableCase,
        page_info: dict[str, Any],
    ) -> TerminalAssertion | None:
        case_text = f"{case.objective}\n{case.expected}\n{case.hints}"
        formula_spec = Runtime._formula_spec_for_case(case_text)
        if formula_spec is not None:
            return Runtime._deterministic_formula_terminal_assertion(
                formula_spec,
                page_info,
            )

        quoted = re.findall(
            r"""["'“”‘’]([^"'“”‘’]{2,80})["'“”‘’]""",
            f"{case.objective}\n{case.expected}",
        )
        expected_paths = Runtime._expected_paths_from_text(case.expected)
        stable_text = "\n".join([
            str(page_info.get("title") or ""),
            *[str(value) for value in page_info.get("headings", [])],
            *[str(value) for value in page_info.get("visible_texts", [])],
            *[str(value) for value in page_info.get("error_messages", [])],
            *[
                str(value.get("text") or "")
                for value in page_info.get("modals", [])
                if isinstance(value, dict)
            ],
        ])
        current_url = str(page_info.get("url") or "")
        matched_text = next(
            (literal for literal in quoted if literal in stable_text),
            "",
        )
        matched_path = next(
            (path for path in expected_paths if path in current_url),
            "",
        )
        if not matched_text and not matched_path:
            return None
        evidence = matched_text or matched_path
        return TerminalAssertion(
            objective_satisfied=True,
            expected_result_supported=True,
            terminal_evidence_sufficient=True,
            reasoning=f"确定性页面证据匹配: {evidence}",
        )

    @staticmethod
    def _expected_paths_from_text(text: str) -> list[str]:
        url_pattern = r"https?://[^\s\"'<>)]*"
        urls = re.findall(url_pattern, text or "")
        paths: list[str] = []
        for raw_url in urls:
            cleaned = raw_url.rstrip(".,;:!?)]}\"'\u3002\uff0c\uff1b")
            parsed = urlparse(cleaned)
            if parsed.path and parsed.path != "/":
                paths.append(parsed.path)

        scrubbed = re.sub(url_pattern, " ", text or "")
        paths.extend(
            re.findall(
                r"(?<![\w:-])/[A-Za-z0-9][A-Za-z0-9_./-]*",
                scrubbed,
            )
        )

        deduped: list[str] = []
        for path in paths:
            normalized = path.rstrip(".,;:!?)]}\"'\u3002\uff0c\uff1b")
            if normalized == "/" or normalized.startswith("//"):
                continue
            if normalized not in deduped:
                deduped.append(normalized)
        return deduped

    @staticmethod
    def _formula_spec_for_case(case_text: str) -> dict[str, Any] | None:
        compact = re.sub(r"\s+", "", case_text)
        formula_keywords = ("等于", "之和", "求和", "公式", "计算", "汇总")
        if not any(keyword in compact for keyword in formula_keywords):
            return None
        for spec in _DASHBOARD_FORMULA_SPECS:
            target = str(spec["target"])
            parts = tuple(str(part) for part in spec["parts"])
            if target in compact and all(part in compact for part in parts):
                return spec
        return None

    @staticmethod
    def _deterministic_formula_terminal_assertion(
        spec: dict[str, Any],
        page_info: dict[str, Any],
    ) -> TerminalAssertion | None:
        units = Runtime._stable_page_text_units(page_info)
        if not units:
            return None

        target = str(spec["target"])
        parts = tuple(str(part) for part in spec["parts"])
        exclusions_by_label = dict(spec.get("exclusions") or {})

        target_value = Runtime._extract_number_for_label(target, units)
        part_values: dict[str, float] = {}
        for part in parts:
            value = Runtime._extract_number_for_label(
                part,
                units,
                exclusions=tuple(exclusions_by_label.get(part) or ()),
            )
            if value is None:
                return None
            part_values[part] = value

        if target_value is None:
            return None

        expected_value = sum(part_values.values())
        parts_text = " + ".join(
            f"{label}={Runtime._format_number(value)}"
            for label, value in part_values.items()
        )
        target_text = (
            f"{target}={Runtime._format_number(target_value)}"
        )
        if abs(target_value - expected_value) < 0.000001:
            return TerminalAssertion(
                objective_satisfied=True,
                expected_result_supported=True,
                terminal_evidence_sufficient=True,
                reasoning=(
                    "确定性公式证据匹配: "
                    f"{target_text}，{parts_text}"
                ),
            )

        return TerminalAssertion(
            objective_satisfied=False,
            expected_result_supported=False,
            terminal_evidence_sufficient=True,
            reasoning=(
                "确定性公式证据不匹配: "
                f"{target_text}，但 {parts_text} 之和为 "
                f"{Runtime._format_number(expected_value)}"
            ),
        )

    @staticmethod
    def _stable_page_text_units(page_info: dict[str, Any]) -> list[str]:
        units: list[str] = []
        raw_values: list[Any] = [
            page_info.get("title"),
            *list(page_info.get("headings") or []),
            *list(page_info.get("visible_texts") or []),
            *list(page_info.get("error_messages") or []),
        ]
        for modal in page_info.get("modals") or []:
            if isinstance(modal, dict):
                raw_values.append(modal.get("text"))
        for table in page_info.get("tables") or []:
            if not isinstance(table, dict):
                continue
            raw_values.append(table.get("caption"))
            raw_values.extend(table.get("headers") or [])
            raw_values.extend(table.get("cells") or [])
        for value in raw_values:
            text = re.sub(r"\s+", " ", str(value or "")).strip()
            if text:
                units.append(text)
        return units

    @staticmethod
    def _extract_number_for_label(
        label: str,
        units: list[str],
        *,
        exclusions: tuple[str, ...] = (),
    ) -> float | None:
        compact_label = re.sub(r"\s+", "", label)
        for index, unit in enumerate(units):
            compact_unit = re.sub(r"\s+", "", unit)
            if compact_label not in compact_unit:
                continue
            if "/" in compact_unit and "/" not in compact_label:
                continue
            if any(
                exclusion
                and exclusion != label
                and re.sub(r"\s+", "", exclusion) in compact_unit
                for exclusion in exclusions
            ):
                continue

            same_label_unit = compact_unit.strip("：:") == compact_label
            number = Runtime._first_number(unit)
            if number is not None:
                return number
            if not same_label_unit:
                continue
            for next_unit in units[index + 1:index + 3]:
                number = Runtime._first_number(next_unit)
                if number is not None:
                    return number
        return None

    @staticmethod
    def _first_number(text: str) -> float | None:
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        if not match:
            return None
        return float(match.group(0))

    @staticmethod
    def _format_number(value: float) -> str:
        if float(value).is_integer():
            return str(int(value))
        return f"{value:g}"

    async def _deterministic_dom_terminal_assertion(
        self,
        case: RuntimeExecutableCase,
        page_info: dict[str, Any],
    ) -> TerminalAssertion | None:
        if self.page is None:
            return None

        case_text = "\n".join(
            filter(None, [case.objective, case.expected, case.hints])
        ).lower()
        if "contenteditable" not in case_text:
            return None

        current_url = str(
            page_info.get("url") or getattr(self.page, "url", "") or ""
        )
        if not self._is_same_route_family(current_url, self.target_url):
            return None

        try:
            inspection = await self.page.evaluate(
                """
() => {
  const MAX_SAMPLES = 5;
  const SKIP_TAGS = new Set(["html", "body", "input", "textarea", "select", "button", "option"]);
  const INTERACTIVE_ROLES = new Set(["textbox", "searchbox", "combobox", "button", "option", "checkbox", "radio", "switch", "slider", "spinbutton"]);
  const REGION_ROLES = new Set(["table", "grid", "region", "article", "main"]);
  const REGION_TOKENS = ["card", "panel", "widget", "table", "grid", "chart", "summary", "list", "container", "dashboard"];

  const trimText = (value) => (value || "").replace(/\\s+/g, " ").trim().slice(0, 80);
  const normalizedAttr = (el) => {
    const value = el.getAttribute("contenteditable");
    return value === null ? null : value.trim().toLowerCase();
  };
  const isVisible = (el) => {
    const style = window.getComputedStyle(el);
    if (!style || style.display === "none" || style.visibility === "hidden" || Number(style.opacity || "1") === 0) {
      return false;
    }
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const describe = (el, attrValue, reason) => ({
    tag: el.tagName.toLowerCase(),
    id: el.id || "",
    role: (el.getAttribute("role") || "").toLowerCase(),
    className: typeof el.className === "string" ? el.className.slice(0, 80) : "",
    text: trimText(el.textContent),
    attrValue,
    reason,
  });
  const looksLikeRegion = (el) => {
    const tag = el.tagName.toLowerCase();
    const role = (el.getAttribute("role") || "").toLowerCase();
    if (tag === "table" || tag === "section" || tag === "article" || tag === "main") {
      return true;
    }
    if (REGION_ROLES.has(role)) {
      return true;
    }
    const idText = (el.id || "").toLowerCase();
    const classText = typeof el.className === "string" ? el.className.toLowerCase() : "";
    const dataText = [el.getAttribute("data-testid") || "", el.getAttribute("data-test") || ""]
      .join(" ")
      .toLowerCase();
    return REGION_TOKENS.some((token) => idText.includes(token) || classText.includes(token) || dataText.includes(token));
  };
  const hasViolatingAncestor = (el) => {
    let current = el.parentElement;
    while (current) {
      const attrValue = normalizedAttr(current);
      if ((attrValue !== null && attrValue !== "false") || current.isContentEditable) {
        return true;
      }
      current = current.parentElement;
    }
    return false;
  };

  const result = {
    inspectedCount: 0,
    regionCount: 0,
    regionViolations: [],
    visibleEditableViolations: [],
  };

  for (const el of document.querySelectorAll("*")) {
    if (!(el instanceof HTMLElement)) {
      continue;
    }
    const tag = el.tagName.toLowerCase();
    if (SKIP_TAGS.has(tag)) {
      continue;
    }
    const role = (el.getAttribute("role") || "").toLowerCase();
    if (INTERACTIVE_ROLES.has(role)) {
      continue;
    }
    if (!isVisible(el) || hasViolatingAncestor(el)) {
      continue;
    }

    result.inspectedCount += 1;
    const attrValue = normalizedAttr(el);
    const violatingAttr = attrValue !== null && attrValue !== "false";
    const violatingEditableState = el.isContentEditable;
    const violates = violatingAttr || violatingEditableState;
    const reason = violatingEditableState ? "isContentEditable" : "contenteditable_attribute";

    if (violates && result.visibleEditableViolations.length < MAX_SAMPLES) {
      result.visibleEditableViolations.push(describe(el, attrValue, reason));
    }

    if (!looksLikeRegion(el)) {
      continue;
    }

    result.regionCount += 1;
    if (violates && result.regionViolations.length < MAX_SAMPLES) {
      result.regionViolations.push(describe(el, attrValue, reason));
    }
  }

  return result;
}
                """
            )
        except Exception:
            return None

        region_violations = list(inspection.get("regionViolations") or [])
        visible_violations = list(
            inspection.get("visibleEditableViolations") or []
        )
        if region_violations or visible_violations:
            samples = region_violations or visible_violations
            return TerminalAssertion(
                objective_satisfied=False,
                expected_result_supported=False,
                terminal_evidence_sufficient=True,
                reasoning=(
                    "DOM 属性校验发现 contenteditable 风险元素: "
                    + "; ".join(
                        self._format_dom_violation(item)
                        for item in samples[:3]
                    )
                ),
            )

        if not self._has_dom_surface_evidence(page_info, inspection):
            return None

        return TerminalAssertion(
            objective_satisfied=True,
            expected_result_supported=True,
            terminal_evidence_sufficient=True,
            reasoning=(
                "DOM 属性校验通过: "
                f"已检查 {int(inspection.get('regionCount') or 0)} 个展示区域，"
                "未发现 contenteditable 风险"
            ),
        )

    @staticmethod
    def _is_same_route_family(current_url: str, target_url: str) -> bool:
        current = urlparse(current_url)
        target = urlparse(target_url)
        if target.scheme and current.scheme and target.netloc != current.netloc:
            return False
        current_path = current.path.rstrip("/")
        target_path = target.path.rstrip("/")
        if not target_path:
            return current_path == "" or current_path == "/"
        return current_path == target_path or current_path.startswith(
            f"{target_path}/"
        )

    @staticmethod
    def _has_dom_surface_evidence(
        page_info: dict[str, Any],
        inspection: dict[str, Any],
    ) -> bool:
        if page_info.get("loading"):
            return False
        if page_info.get("error_messages"):
            return False
        if int(inspection.get("regionCount") or 0) <= 0:
            return False
        if not str(page_info.get("url") or "").strip():
            return False
        return bool(
            page_info.get("headings")
            or page_info.get("visible_texts")
            or page_info.get("tables")
            or page_info.get("interactive_elements")
            or page_info.get("forms")
            or str(page_info.get("title") or "").strip()
        )

    @staticmethod
    def _format_dom_violation(item: dict[str, Any]) -> str:
        tag = str(item.get("tag") or "element")
        element_id = str(item.get("id") or "").strip()
        role = str(item.get("role") or "").strip()
        attr_value = item.get("attrValue")
        reason = str(item.get("reason") or "").strip()
        text = str(item.get("text") or "").strip()

        descriptor = tag
        if element_id:
            descriptor += f"#{element_id}"
        if role:
            descriptor += f"[role={role}]"
        detail_parts = []
        if attr_value is not None:
            detail_parts.append(f"attr={attr_value}")
        if reason:
            detail_parts.append(f"reason={reason}")
        if text:
            detail_parts.append(f"text={text}")
        if detail_parts:
            descriptor += f" ({', '.join(detail_parts)})"
        return descriptor

    @staticmethod
    def _all_terminal_satisfied(terminal: TerminalAssertion) -> bool:
        return (
            terminal.objective_satisfied
            and terminal.expected_result_supported
            and terminal.terminal_evidence_sufficient
        )

    async def _prepare_case_start_state(
        self,
        case: RuntimeExecutableCase,
    ) -> None:
        if self.page is None or not self._case_needs_clean_login_page(case):
            return
        await self._reset_browser_state()
        await self._ensure_login_page_start(case)

    async def _ensure_login_page_start(self, case: RuntimeExecutableCase) -> None:
        if self.page is None or not self._case_needs_clean_login_page(case):
            return
        if await self._login_form_state() is not None:
            return

        logout_selectors = (
            'button:has-text("退出系统")',
            'a:has-text("退出系统")',
            'text=退出系统',
            'button:has-text("退出登录")',
            'a:has-text("退出登录")',
            'button:has-text("Logout")',
            'a:has-text("Logout")',
        )
        for selector in logout_selectors:
            try:
                locator = self.page.locator(selector).first()
                if not await locator.is_visible(timeout=500):
                    continue
                await locator.click(timeout=1500)
                await self.page.wait_for_timeout(500)
                await self._clear_current_page_storage()
                await self._clear_cdp_storage_for_url(self.target_url)
                await self.page.goto(
                    self.target_url,
                    wait_until="networkidle",
                    timeout=30000,
                )
                return
            except Exception:
                continue

    @staticmethod
    def _case_needs_clean_login_page(case: RuntimeExecutableCase) -> bool:
        return (
            Runtime._case_requires_configured_login(case)
            or Runtime._case_requires_quick_fill_action(case)
            or Runtime._case_requires_invalid_login_submission(case)
            or Runtime._case_requires_agent_write(case)
            or Runtime._case_requires_dataset_write(case)
            or Runtime._case_requires_skill_write(case)
        )

    async def _login_form_state(self) -> Mapping[str, Any] | None:
        if self.page is None:
            return None
        try:
            values = await self.page.evaluate(
                """
() => ({
  usernamePresent: Boolean(document.querySelector("#username-input")),
  passwordPresent: Boolean(document.querySelector("#password-input")),
  username: document.querySelector("#username-input")?.value || "",
  password: document.querySelector("#password-input")?.value || "",
  submitVisible: Boolean(document.querySelector("#login-submit-button"))
})
"""
            )
        except Exception:
            return None
        if not isinstance(values, Mapping):
            return None
        if not (
            values.get("usernamePresent")
            and values.get("passwordPresent")
            and values.get("submitVisible")
        ):
            return None
        return values

    async def _deterministic_login_action(
        self,
        case: RuntimeExecutableCase,
    ) -> dict[str, Any] | None:
        account = self._first_configured_account()
        if account is None:
            return None
        if not self._case_requires_configured_login(case):
            return None

        username = str(account.get("username") or "")
        password = str(account.get("password") or "")
        if not (username and password):
            return None

        values = await self._login_form_state()
        if values is None:
            return None

        if str(values.get("username") or "") != username:
            return {
                "tool": "input_text",
                "args": {"selector": "#username-input", "text": username},
            }
        if str(values.get("password") or "") != password:
            return {
                "tool": "input_text",
                "args": {"selector": "#password-input", "text": password},
            }
        if values.get("submitVisible"):
            return {"tool": "click", "args": {"selector": "#login-submit-button"}}
        return None

    async def _deterministic_quick_fill_action(
        self,
        case: RuntimeExecutableCase,
        evidence_refs: list[str],
    ) -> dict[str, Any] | None:
        if self.page is None:
            return None
        if not self._case_requires_quick_fill_action(case):
            return None
        if self._has_quick_fill_action_evidence(evidence_refs):
            return None
        return {
            "tool": "click",
            "args": {"selector": "button:has-text(\"一键填值体验\")"},
        }

    async def _execute_configured_login_sequence(
        self,
        case: RuntimeExecutableCase,
        evidence: list[str],
    ) -> bool:
        if self.page is None or not self._case_requires_configured_login(case):
            return False
        account = self._first_configured_account()
        if account is None:
            return False
        username = str(account.get("username") or "")
        password = str(account.get("password") or "")
        if not (username and password):
            return False
        if await self._login_form_state() is None:
            return False

        executed = False
        actions = [
            {
                "tool": "input_text",
                "args": {"selector": "#username-input", "text": username},
            },
            {
                "tool": "input_text",
                "args": {"selector": "#password-input", "text": password},
            },
            {"tool": "click", "args": {"selector": "#login-submit-button"}},
        ]
        for action in actions:
            executed = True
            tool_result = await self._execute_test_action(action)
            result = tool_result.feedback_text()
            if result:
                evidence.append(result)
                if tool_result.is_failure():
                    self.remember_case_feedback(case.id, result)
            await self._record_step(case.id, action, result, tool_result)
            if tool_result.is_failure():
                break

            args = action.get("args", {})
            if (
                action.get("tool") == "click"
                and str(args.get("selector") or "") == "#login-submit-button"
            ):
                await self.page.wait_for_timeout(500)
                break

        return executed

    async def _execute_invalid_login_sequence(
        self,
        case: RuntimeExecutableCase,
        evidence: list[str],
    ) -> bool:
        if self.page is None or not self._case_requires_invalid_login_submission(case):
            return False
        if await self._login_form_state() is None:
            return False
        username = self._invalid_login_username_for_case(case)
        password = self._invalid_login_password_for_case(case)
        if not (username and password):
            return False

        actions = [
            {
                "tool": "input_text",
                "args": {"selector": "#username-input", "text": username},
            },
            {
                "tool": "input_text",
                "args": {"selector": "#password-input", "text": password},
            },
            {"tool": "click", "args": {"selector": "#login-submit-button"}},
        ]
        executed = False
        for action in actions:
            executed = True
            tool_result = await self._execute_test_action(action)
            result = tool_result.feedback_text()
            if result:
                evidence.append(result)
                if tool_result.is_failure():
                    self.remember_case_feedback(case.id, result)
            await self._record_step(case.id, action, result, tool_result)
            if tool_result.is_failure():
                break
            args = action.get("args", {})
            if (
                action.get("tool") == "click"
                and str(args.get("selector") or "") == "#login-submit-button"
            ):
                await self.page.wait_for_timeout(500)
                break
        return executed

    async def _execute_agent_write_sequence(
        self,
        case: RuntimeExecutableCase,
        evidence: list[str],
    ) -> bool:
        if self.page is None or not self._case_requires_agent_write(case):
            return False
        if await self._login_form_state() is not None:
            return False
        if self._has_agent_save_evidence(evidence):
            return False

        data = self._agent_write_data_for_case(case)
        if data is None:
            return False
        name, description, gateway = data
        if not name or not gateway:
            return False

        actions: list[dict[str, Any]] = []
        form_state = await self._agent_form_state()
        if form_state is None:
            actions.append({
                "tool": "click",
                "args": {"selector": "button:has-text(\"新增智能体\")"},
            })
        actions.extend([
            {
                "tool": "input_text",
                "args": {
                    "selector": "input[placeholder=\"例如：法律合规审核顾问\"]",
                    "text": name,
                },
            },
            {
                "tool": "input_text",
                "args": {
                    "selector": "textarea[placeholder=\"补充业务职责...\"]",
                    "text": description,
                },
            },
            {
                "tool": "input_text",
                "args": {
                    "selector": "input[placeholder=\"https://...\"]",
                    "text": gateway,
                },
            },
            {
                "tool": "click",
                "args": {"selector": "button[type=\"submit\"]:has-text(\"保存\")"},
            },
        ])

        executed = False
        for action in actions:
            executed = True
            tool_result = await self._execute_test_action(action)
            result = tool_result.feedback_text()
            if result:
                evidence.append(result)
                if tool_result.is_failure():
                    self.remember_case_feedback(case.id, result)
            await self._record_step(case.id, action, result, tool_result)
            if tool_result.is_failure():
                break
            if action.get("tool") == "click":
                await self.page.wait_for_timeout(700)
        return executed

    async def _execute_dataset_write_sequence(
        self,
        case: RuntimeExecutableCase,
        evidence: list[str],
    ) -> bool:
        if self.page is None or not self._case_requires_dataset_write(case):
            return False
        if await self._login_form_state() is not None:
            return False
        if self._has_dataset_save_evidence(evidence):
            return False

        data = self._dataset_write_data_for_case(case)
        if data is None:
            return False
        name, intro, _ = data
        is_empty_name_case = self._case_requires_dataset_empty_name(case)

        actions: list[dict[str, Any]] = []
        form_state = await self._dataset_form_state()
        if form_state is None:
            actions.extend([
                {
                    "tool": "click",
                    "args": {"selector": "#tab-kb-mgmt"},
                },
                {
                    "tool": "click",
                    "args": {"selector": "button:has-text(\"新建知识库\")"},
                },
            ])
        if not is_empty_name_case:
            if not name:
                return False
            actions.append({
                "tool": "input_text",
                "args": {
                    "selector": "input[placeholder=\"例如：财务政策库\"]",
                    "text": name,
                },
            })
        actions.extend([
            {
                "tool": "input_text",
                "args": {
                    "selector": "textarea[placeholder=\"对知识库范围进行说明...\"]",
                    "text": intro,
                },
            },
            {
                "tool": "click",
                "args": {"selector": "button[type=\"submit\"]:has-text(\"保存\")"},
            },
        ])

        executed = False
        for action in actions:
            executed = True
            tool_result = await self._execute_test_action(action)
            result = tool_result.feedback_text()
            if result:
                evidence.append(result)
                if tool_result.is_failure():
                    self.remember_case_feedback(case.id, result)
            await self._record_step(case.id, action, result, tool_result)
            if tool_result.is_failure():
                break
            if action.get("tool") == "click":
                await self.page.wait_for_timeout(700)
        return executed

    async def _execute_skill_write_sequence(
        self,
        case: RuntimeExecutableCase,
        evidence: list[str],
    ) -> bool:
        if self.page is None or not self._case_requires_skill_write(case):
            return False
        if await self._login_form_state() is not None:
            return False
        if self._has_skill_save_evidence(evidence):
            return False

        data = self._skill_write_data_for_case(case)
        if data is None:
            return False
        name, author, description = data

        executed = False

        async def execute_action(action: dict[str, Any]) -> bool:
            nonlocal executed
            executed = True
            tool_result = await self._execute_test_action(action)
            result = tool_result.feedback_text()
            if result:
                evidence.append(result)
                if tool_result.is_failure():
                    self.remember_case_feedback(case.id, result)
            await self._record_step(case.id, action, result, tool_result)
            if action.get("tool") == "click":
                await self.page.wait_for_timeout(700)
            return not tool_result.is_failure()

        async def close_visible_skill_editor_modal(reason: str) -> bool:
            try:
                state = await self.page.evaluate(
                    """
() => {
  const overlay =
    document.querySelector('div.fixed.inset-0') ||
    document.querySelector('div[class*="fixed"][class*="inset-0"]');
  if (!overlay) {
    return {modal: false, closed: false};
  }
  const panel = overlay.firstElementChild || overlay;
  const header = panel.firstElementChild || panel;
  const headerButtons = Array.from(header.querySelectorAll('button'));
  const allButtons = Array.from(panel.querySelectorAll('button'));
  const closeButton =
    headerButtons.find((button) => {
      const text = (button.innerText || button.textContent || '').trim().toLowerCase();
      const aria = (button.getAttribute('aria-label') || '').trim().toLowerCase();
      return ['x', '×', '✕', 'close', '关闭'].includes(text)
        || aria.includes('close')
        || aria.includes('关闭');
    }) ||
    headerButtons[headerButtons.length - 1] ||
    allButtons.find((button) => {
      const text = (button.innerText || button.textContent || '').trim().toLowerCase();
      return ['x', '×', '✕', 'close', '关闭'].includes(text);
    });
  if (closeButton) {
    closeButton.click();
    return {modal: true, closed: true};
  }
  return {modal: true, closed: false};
}
"""
                )
                if not isinstance(state, Mapping) or not state.get("modal"):
                    return False
                if not state.get("closed"):
                    await self.page.keyboard.press("Escape")
                await self.page.wait_for_timeout(300)
                evidence.append(f"closed: skill editor modal ({reason})")
                return True
            except Exception:
                return False

        async def capture_skill_file_tree_evidence() -> None:
            try:
                state = await self.page.evaluate(
                    """
() => {
  const overlay =
    document.querySelector('div.fixed.inset-0') ||
    document.querySelector('div[class*="fixed"][class*="inset-0"]');
  const text = (overlay?.innerText || document.body?.innerText || '').trim();
  return {
    hasSkillMd: text.includes('SKILL.md'),
    hasIndexJs: text.includes('index.js'),
    excerpt: text.replace(/\\s+/g, ' ').slice(0, 500)
  };
}
"""
                )
            except Exception as exc:
                evidence.append(f"skill_file_tree_capture_failed: {exc}")
                return
            if not isinstance(state, Mapping):
                return
            if state.get("hasSkillMd") and state.get("hasIndexJs"):
                evidence.append("skill_file_tree: SKILL.md,index.js")
                return
            excerpt = str(state.get("excerpt") or "")
            if excerpt:
                evidence.append(f"skill_file_tree_missing: {excerpt[:240]}")

        async def capture_duplicate_block_evidence() -> None:
            try:
                state = await self.page.evaluate(
                    """
() => {
  const text = (document.body?.innerText || '').trim();
  const lower = text.toLowerCase();
  const markers = ['重复', '不可重复', '核心文件', '禁止', '已存在', 'duplicate', 'core file', 'already exists'];
  return {
    hasSkillMd: text.includes('SKILL.md'),
    matched: markers.filter((marker) => text.includes(marker) || lower.includes(marker)),
    excerpt: text.replace(/\\s+/g, ' ').slice(-600)
  };
}
"""
                )
            except Exception as exc:
                evidence.append(f"skill_duplicate_block_capture_failed: {exc}")
                return
            if not isinstance(state, Mapping):
                return
            matched = state.get("matched")
            if state.get("hasSkillMd") and isinstance(matched, list) and matched:
                evidence.append("duplicate_block_visible: SKILL.md duplicate core file")

        async def click_skill_editor_button(target_name: str = "") -> bool:
            nonlocal executed
            executed = True
            try:
                button_id = await self.page.evaluate(
                    """
(targetName) => {
  const cards = Array.from(document.querySelectorAll('#skills-list-container > div'));
  let card = null;
  if (targetName) {
    card = cards.find((item) => item.innerText.includes(targetName)) || null;
    if (!card) return "";
  }
  if (!card) {
    card = cards[0] || null;
  }
  const button = card?.querySelector('button[id^="edit-skill-btn-"]');
  return button?.getAttribute('id') || "";
}
""",
                    target_name,
                )
                if not button_id:
                    raise RuntimeError("skill editor button not found")
                locator = self.page.locator(f"#{button_id}")
                await locator.click(timeout=5000)
                await self.page.wait_for_timeout(900)
                evidence.append(f"clicked: skill editor button #{button_id}")
                return True
            except Exception as exc:
                result = f"skill_editor_open_failed: {exc}"
                evidence.append(result)
                self.remember_case_feedback(case.id, result)
                return False

        async def save_editor_metadata() -> bool:
            actions = [
                {
                    "tool": "input_text",
                    "args": {"selector": 'div.fixed input[type="text"] >> nth=0', "text": name},
                },
                {
                    "tool": "input_text",
                    "args": {"selector": 'div.fixed input[type="text"] >> nth=1', "text": "1.0.0"},
                },
                {
                    "tool": "input_text",
                    "args": {"selector": 'div.fixed input[type="text"] >> nth=2', "text": author},
                },
                {
                    "tool": "input_text",
                    "args": {"selector": "div.fixed textarea >> nth=0", "text": description},
                },
                {
                    "tool": "click",
                    "args": {"selector": 'div.fixed button:has-text("编译构建并加载")'},
                },
            ]
            for action in actions:
                if not await execute_action(action):
                    return False
            return True

        async def attempt_duplicate_skill_md() -> bool:
            nonlocal executed
            executed = True
            messages: list[str] = []

            async def handle_dialog(dialog: Any) -> None:
                messages.append(str(dialog.message))
                await dialog.accept()

            def schedule_dialog(dialog: Any) -> None:
                asyncio.create_task(handle_dialog(dialog))

            self.page.once("dialog", schedule_dialog)
            try:
                base_locator = self.page.locator('div.fixed form input[type="text"]')
                first_locator = getattr(base_locator, "first", None)
                locator = (
                    first_locator()
                    if callable(first_locator)
                    else first_locator or base_locator
                )
                await locator.fill("SKILL.md", timeout=5000)
                evidence.append("input: div.fixed form input[type=\"text\"] -> SKILL.md")
                await locator.press("Enter", timeout=5000)
                evidence.append("pressed: Enter on SKILL.md duplicate file path")
                await self.page.wait_for_timeout(1200)
                await capture_duplicate_block_evidence()
            except Exception as exc:
                result = f"skill_duplicate_submit_failed: {exc}"
                evidence.append(result)
                self.remember_case_feedback(case.id, result)
                return True
            for message in messages:
                evidence.append(f"dialog: {message}")
            return True

        await close_visible_skill_editor_modal("pre-case cleanup")

        if not await execute_action({"tool": "click", "args": {"selector": "#tab-skills-mgmt"}}):
            return executed

        if self._case_requires_skill_scaffold(case):
            if not await execute_action(
                {"tool": "click", "args": {"selector": 'button:has-text("快速初始化脚手架")'}}
            ):
                return executed
            if not await click_skill_editor_button():
                return executed
            if await save_editor_metadata():
                if await click_skill_editor_button(name):
                    await capture_skill_file_tree_evidence()
                    await close_visible_skill_editor_modal("after scaffold evidence")
            return executed

        if self._case_requires_skill_duplicate_core_file(case):
            if not await click_skill_editor_button(name):
                if not await execute_action(
                    {"tool": "click", "args": {"selector": 'button:has-text("快速初始化脚手架")'}}
                ):
                    return executed
                if not await click_skill_editor_button():
                    return executed
                if not await save_editor_metadata():
                    return executed
                if not await click_skill_editor_button(name):
                    return executed
            await attempt_duplicate_skill_md()
            await close_visible_skill_editor_modal("after duplicate attempt")
            return executed

        return executed

    async def _agent_form_state(self) -> Mapping[str, Any] | None:
        if self.page is None:
            return None
        try:
            values = await self.page.evaluate(
                """
() => {
  const name = document.querySelector('input[placeholder="例如：法律合规审核顾问"]');
  const desc = document.querySelector('textarea[placeholder="补充业务职责..."]');
  const gateway = document.querySelector('input[placeholder="https://..."]');
  const visible = (el) => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
  };
  if (!visible(name) || !visible(gateway)) return null;
  return {
    name: name.value || "",
    description: desc?.value || "",
    gateway: gateway.value || "",
    gatewayValid: Boolean(gateway.validity?.valid),
    gatewayValidation: gateway.validationMessage || "",
    saveVisible: Boolean(Array.from(document.querySelectorAll('button[type="submit"]')).find((el) => visible(el) && el.innerText.includes("保存"))),
    titleVisible: document.body.innerText.includes("新增智能体") || document.body.innerText.includes("编辑智能体")
  };
}
"""
            )
        except Exception:
            return None
        if not isinstance(values, Mapping):
            return None
        return values

    async def _dataset_form_state(self) -> Mapping[str, Any] | None:
        if self.page is None:
            return None
        try:
            values = await self.page.evaluate(
                """
() => {
  const name = document.querySelector('input[placeholder="例如：财务政策库"]');
  const intro = document.querySelector('textarea[placeholder="对知识库范围进行说明..."]');
  const visible = (el) => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
  };
  if (!visible(name)) return null;
  return {
    name: name.value || "",
    intro: intro?.value || "",
    nameValid: Boolean(name.validity?.valid),
    nameValidation: name.validationMessage || "",
    saveVisible: Boolean(Array.from(document.querySelectorAll('button[type="submit"]')).find((el) => visible(el) && el.innerText.includes("保存"))),
    titleVisible: document.body.innerText.includes("新建知识库") || document.body.innerText.includes("编辑知识库")
  };
}
"""
            )
        except Exception:
            return None
        if not isinstance(values, Mapping):
            return None
        return values

    def _first_configured_account(self) -> Mapping[str, Any] | None:
        accounts = self.task_config.get("accounts") or []
        if not isinstance(accounts, list):
            return None
        for account in accounts:
            if (
                isinstance(account, Mapping)
                and account.get("username")
                and account.get("password")
            ):
                return account
        return None

    @staticmethod
    def _configured_account_aliases(account: Mapping[str, Any]) -> list[str]:
        alias_fields = (
            "username",
            "display_name",
            "displayName",
            "nick_name",
            "nickName",
            "nickname",
        )
        aliases: list[str] = []
        for field in alias_fields:
            value = str(account.get(field) or "").strip()
            if value and value not in aliases:
                aliases.append(value)
        raw_aliases = account.get("aliases")
        if isinstance(raw_aliases, list):
            for value in raw_aliases:
                alias = str(value or "").strip()
                if alias and alias not in aliases:
                    aliases.append(alias)
        return aliases

    def _invalid_login_username_for_case(
        self,
        case: RuntimeExecutableCase,
    ) -> str:
        account = self._first_configured_account()
        configured_username = (
            str(account.get("username") or "").strip()
            if account is not None
            else ""
        )
        case_text = Runtime._case_action_text(case)
        credential_match = re.search(
            r"([a-zA-Z0-9_.@-]+)\s*/\s*([^\s,，。；;]+)",
            case_text,
        )
        if credential_match:
            return credential_match.group(1)
        return configured_username or "admin"

    def _invalid_login_password_for_case(
        self,
        case: RuntimeExecutableCase,
    ) -> str:
        account = self._first_configured_account()
        configured_password = (
            str(account.get("password") or "").strip()
            if account is not None
            else ""
        )
        case_text = Runtime._case_action_text(case)
        credential_matches = re.findall(
            r"[a-zA-Z0-9_.@-]+\s*/\s*([^\s,，。；;]+)",
            case_text,
        )
        for candidate in credential_matches:
            candidate = candidate.strip(")）]】》>\"'“”‘’.。")
            if candidate and candidate != configured_password:
                return candidate
        for candidate in ("cangjie*2026", "wrong-password", "invalid-password"):
            if candidate in case_text and candidate != configured_password:
                return candidate
        config_text = json.dumps(self.task_config, ensure_ascii=False).lower()
        if "cangjie*2026" in config_text and "cangjie*2026" != configured_password:
            return "cangjie*2026"
        return ""

    @staticmethod
    def _case_requires_configured_login(case: RuntimeExecutableCase) -> bool:
        if Runtime._case_requires_agent_write(case):
            return True
        if Runtime._case_requires_dataset_write(case):
            return True
        if Runtime._case_requires_skill_write(case):
            return True
        case_text = Runtime._case_action_text(case)
        positive_markers = (
            "\u6709\u6548\u51ed\u636e",
            "\u767b\u5f55\u6210\u529f",
            "\u63a7\u5236\u53f0",
            "\u667a\u80fd\u4f53\u5e7f\u573a",
            "\u77e5\u8bc6\u5e93\u7ba1\u7406",
            "valid login",
            "valid credential",
            "dashboard",
        )
        negative_markers = (
            "\u4e00\u952e\u586b\u503c",
            "\u9519\u8bef",
            "\u5931\u8d25",
            "quick fill",
            "quick-fill",
            "one-click",
            "wrong password",
            "invalid password",
            "login failed",
        )
        if any(marker in case_text for marker in negative_markers):
            return False
        if case.required_roles:
            return True
        return any(marker in case_text for marker in positive_markers)

    @staticmethod
    def _case_requires_agent_write(case: RuntimeExecutableCase) -> bool:
        return (
            Runtime._case_requires_agent_create(case)
            or Runtime._case_requires_agent_invalid_gateway(case)
        )

    @staticmethod
    def _case_requires_agent_create(case: RuntimeExecutableCase) -> bool:
        case_text = Runtime._case_action_text(case)
        return (
            "智能体" in case_text
            and any(marker in case_text for marker in ("新增", "创建", "create"))
            and any(marker in case_text for marker in ("ta-20260704-auto", "gateway"))
            and not Runtime._case_requires_agent_invalid_gateway(case)
        )

    @staticmethod
    def _case_requires_agent_invalid_gateway(case: RuntimeExecutableCase) -> bool:
        case_text = Runtime._case_action_text(case)
        return (
            "智能体" in case_text
            and any(marker in case_text for marker in ("gateway", "网关地址", "url"))
            and any(marker in case_text for marker in ("not-url", "非法", "格式", "校验", "阻断", "invalid"))
        )

    @staticmethod
    def _agent_write_data_for_case(
        case: RuntimeExecutableCase,
    ) -> tuple[str, str, str] | None:
        case_text = "\n".join(
            filter(None, [case.objective, case.expected, case.hints])
        )
        if Runtime._case_requires_agent_invalid_gateway(case):
            name = "测试智能体-TA-20260704-INVALID"
            gateway = "not-url"
        elif Runtime._case_requires_agent_create(case):
            name = "测试智能体-TA-20260704-AUTO"
            gateway = "https://agent-gateway.cangjie.ai/v1/ta-20260704-auto"
        else:
            return None

        name_match = re.search(
            r"测试智能体-[^\s,，。；;\"'）)]*TA-20260704-(?:AUTO|INVALID)",
            case_text,
            flags=re.I,
        )
        if name_match:
            name = name_match.group(0)
        gateway_match = re.search(
            r"https://[^\s,，。；;\"'）)]*ta-20260704-auto",
            case_text,
            flags=re.I,
        )
        if gateway_match and gateway != "not-url":
            gateway = gateway_match.group(0)
        return (
            name,
            "由 test_agent 自动化验收创建，可安全清理 TA-20260704",
            gateway,
        )

    @staticmethod
    def _case_requires_dataset_write(case: RuntimeExecutableCase) -> bool:
        return (
            Runtime._case_requires_dataset_create(case)
            or Runtime._case_requires_dataset_empty_name(case)
        )

    @staticmethod
    def _case_requires_dataset_create(case: RuntimeExecutableCase) -> bool:
        case_text = Runtime._case_action_text(case)
        return (
            "知识库" in case_text
            and any(marker in case_text for marker in ("新建", "新增", "创建", "create"))
            and any(marker in case_text for marker in ("测试知识库", "ta-20260704-auto"))
            and not Runtime._case_requires_dataset_empty_name(case)
        )

    @staticmethod
    def _case_requires_dataset_empty_name(case: RuntimeExecutableCase) -> bool:
        case_text = Runtime._case_action_text(case)
        return (
            "知识库" in case_text
            and any(marker in case_text for marker in ("名称留空", "空名称", "required", "必填"))
            and any(marker in case_text for marker in ("ta-20260704-empty", "阻断", "不能创建", "未创建"))
        )

    @staticmethod
    def _dataset_write_data_for_case(
        case: RuntimeExecutableCase,
    ) -> tuple[str, str, str] | None:
        case_text = "\n".join(
            filter(None, [case.objective, case.expected, case.hints])
        )
        empty_marker = "TA-20260704-EMPTY"
        empty_match = re.search(r"TA-20260704-EMPTY", case_text, flags=re.I)
        if empty_match:
            empty_marker = empty_match.group(0)

        if Runtime._case_requires_dataset_empty_name(case):
            return (
                "",
                f"测试空名称-{empty_marker}",
                empty_marker,
            )
        if not Runtime._case_requires_dataset_create(case):
            return None

        name = "测试知识库-TA-20260704-AUTO"
        name_match = re.search(
            r"测试知识库-[^\s,，。；;\"'）)]*TA-20260704-AUTO",
            case_text,
            flags=re.I,
        )
        if name_match:
            name = name_match.group(0)
        return (
            name,
            "由 test_agent 自动化验收创建，可安全清理 TA-20260704",
            empty_marker,
        )

    @staticmethod
    def _case_requires_skill_write(case: RuntimeExecutableCase) -> bool:
        return (
            Runtime._case_requires_skill_scaffold(case)
            or Runtime._case_requires_skill_duplicate_core_file(case)
        )

    @staticmethod
    def _case_requires_skill_scaffold(case: RuntimeExecutableCase) -> bool:
        case_text = Runtime._case_action_text(case)
        return (
            any(marker in case_text for marker in ("技能", "skill"))
            and any(marker in case_text for marker in ("脚手架", "scaffold", "初始化"))
            and any(marker in case_text for marker in ("ta-20260704-auto", "skill.md", "index.js"))
            and not Runtime._case_requires_skill_duplicate_core_file(case)
        )

    @staticmethod
    def _case_requires_skill_duplicate_core_file(case: RuntimeExecutableCase) -> bool:
        case_text = Runtime._case_action_text(case)
        return (
            any(marker in case_text for marker in ("技能", "skill"))
            and "skill.md" in case_text
            and any(marker in case_text for marker in ("重复", "不可重复", "阻断", "禁止", "duplicate"))
        )

    @staticmethod
    def _skill_write_data_for_case(
        case: RuntimeExecutableCase,
    ) -> tuple[str, str, str] | None:
        if not Runtime._case_requires_skill_write(case):
            return None
        case_text = "\n".join(
            filter(None, [case.objective, case.expected, case.hints])
        )
        name = "测试技能-TA-20260704-AUTO"
        name_match = re.search(
            r"测试技能-[^\s,，。；;\"'）)]*TA-20260704-AUTO",
            case_text,
            flags=re.I,
        )
        if name_match:
            name = name_match.group(0)
        return (
            name,
            "test_agent",
            "由 test_agent 自动化验收创建，可安全清理 TA-20260704",
        )

    @staticmethod
    def _case_requires_invalid_login_submission(case: RuntimeExecutableCase) -> bool:
        if Runtime._case_requires_agent_write(case):
            return False
        if Runtime._case_requires_dataset_write(case):
            return False
        if Runtime._case_requires_skill_write(case):
            return False
        case_text = Runtime._case_action_text(case)
        invalid_markers = (
            "\u9519\u8bef\u5bc6\u7801",
            "\u65e0\u6548\u5bc6\u7801",
            "\u5bc6\u7801\u9519\u8bef",
            "\u9519\u8bef\u51ed\u636e",
            "\u9519\u8bef\u8f93\u5165",
            "\u9519\u8bef\u63d0\u793a",
            "\u9519\u8bef\u6d41\u7a0b",
            "\u62d2\u7edd\u767b\u5f55",
            "\u767b\u5f55\u5931\u8d25",
            "\u505c\u7559\u5728\u767b\u5f55\u9875",
            "invalid credential",
            "wrong credential",
            "wrong password",
            "invalid password",
            "error prompt",
            "login failed",
        )
        submit_markers = (
            "\u63d0\u4ea4",
            "\u767b\u5f55",
            "\u7acb\u5373\u767b\u5f55",
            "submit",
            "login",
            "sign in",
        )
        quick_fill_value_only = (
            "\u4e00\u952e\u586b\u503c" in case_text
            and not any(marker in case_text for marker in invalid_markers)
        )
        return (
            not quick_fill_value_only
            and any(marker in case_text for marker in invalid_markers)
            and any(marker in case_text for marker in submit_markers)
        )

    @staticmethod
    def _case_requires_quick_fill_action(case: RuntimeExecutableCase) -> bool:
        if Runtime._case_is_passive_observation(case):
            return False
        case_text = Runtime._case_action_text(case)
        quick_fill_markers = (
            "\u4e00\u952e\u586b\u503c",
            "quick fill",
            "quick-fill",
            "one-click",
        )
        value_markers = (
            "username=admin",
            "password=cangjie*2026",
            "cangjie*2026",
        )
        action_markers = (
            "\u70b9\u51fb",
            "\u89e6\u53d1",
            "\u586b\u5145",
            " click",
            " trigger",
            " after ",
        )
        return (
            any(marker in case_text for marker in quick_fill_markers)
            and (
                any(marker in case_text for marker in value_markers)
                or any(marker in case_text for marker in action_markers)
            )
        )

    async def _decide_execute_action(
        self,
        case: RuntimeExecutableCase,
        page_info: dict[str, Any],
        step_count: int,
    ) -> dict[str, Any] | None:
        prompt = f"""执行 Web 测试用例，只返回一个 JSON 对象。

目标：{case.objective}
预期：{case.expected}
提示：{case.hints}
当前页面：{json.dumps(page_info, ensure_ascii=False)[:8000]}
已执行步数：{step_count}
最近动作证据：{self._current_evidence[-5:]}
最近失败反馈：{self._case_feedback.get(case.id, [])[-5:]}
{self._execution_memory_context_section()}
{self._execution_account_context_section(case)}

约束：
1. 只能在当前站点内导航，禁止跳到其他域名。
2. 不要尝试 devtools、view-source、浏览器 chrome UI、body/html/document 这类泛化选择器。
3. 选择器必须尽量具体；如果刚刚因为歧义或找不到失败，要换一个更具体的定位。
4. 如果当前页面的 headings、visible_texts、tables 已足够直接核验结果，不要反复 scroll 或 wait。
5. scroll 或 wait 只在明确为了暴露新内容或等待刚触发的状态变化时使用。
6. 无法继续时使用 mark_task_failed，并说明原因。

{format_tool_prompt_line(EXECUTION_ACTION_TOOLS)}
{format_tool_example("click")}
"""
        return await self._invoke_json(prompt, "你负责通过工具调用执行测试意图。")

    def _execution_memory_context_section(self) -> str:
        if not self._memory_context_text:
            return ""
        return (
            "\nMemoryContext（只读提示，不是需求事实或通过依据）：\n"
            f"{self._memory_context_text[:3000]}\n"
        )

    def _execution_account_context_section(
        self,
        case: RuntimeExecutableCase,
    ) -> str:
        accounts = self.task_config.get("accounts") or []
        if not isinstance(accounts, list) or not accounts:
            return ""

        lines = ["\nConfigured test accounts for this task:"]
        if case.required_roles:
            lines.append(f"- required_roles for this case: {case.required_roles}")
        for account in accounts:
            if not isinstance(account, Mapping):
                continue
            role = str(account.get("role") or "")
            username = str(account.get("username") or "")
            password = str(account.get("password") or "")
            aliases = [
                alias
                for alias in self._configured_account_aliases(account)
                if alias != username
            ]
            if not username and not password:
                continue
            alias_text = (
                f", visible_identity_aliases={aliases}" if aliases else ""
            )
            lines.append(
                f"- role={role or 'unknown'}, username={username}, "
                f"password={password}{alias_text}"
            )
        lines.append(
            "- When this case requires valid login, use the configured account "
            "credentials above. Do not treat quick-fill/demo credentials such "
            "as cangjie*2026 as valid-login credentials unless the case "
            "explicitly only verifies field values."
        )
        return "\n".join(lines) + "\n"

    async def _execute_test_action(
        self,
        action: dict[str, Any],
    ) -> RuntimeToolResult:
        return await self._execute_browser_action(action, phase="execution")

    async def _execute_browser_action(
        self,
        action: dict[str, Any],
        *,
        phase: RuntimePhase,
    ) -> RuntimeToolResult:
        started = time.perf_counter()
        before_url = self.page.url if self.page else self.target_url
        before_fingerprint = await self._get_browser_action_fingerprint()

        async def evidence_with_transition(
            extra: Mapping[str, Any] | None = None,
        ) -> dict[str, Any]:
            evidence_data = dict(extra or {})
            after_fingerprint = await self._get_browser_action_fingerprint()
            if before_fingerprint or after_fingerprint:
                evidence_data["dom_fingerprint"] = {
                    "before": before_fingerprint,
                    "after": after_fingerprint,
                    "changed": bool(
                        before_fingerprint
                        and after_fingerprint
                        and before_fingerprint != after_fingerprint
                    ),
                }
            return evidence_data

        decision = enforce_runtime_action_policy(
            action,
            target_url=self.target_url,
            current_url=before_url,
        )
        if not decision.allowed:
            return self._make_runtime_tool_result(
                action,
                phase=phase,
                status="blocked",
                error_code=decision.error_code or "policy.blocked",
                message=f"action blocked: {decision.reason}",
                llm_feedback=(
                    f"error: action_blocked:"
                    f"{decision.error_code or decision.reason}"
                ),
                before_url=before_url,
                policy_decision=self._policy_decision_snapshot(decision),
                started_at=started,
            )

        normalized_action = decision.normalized_action or dict(action)
        tool = normalized_action.get("tool", "")
        args = normalized_action.get("args", {})
        selector_resolution: dict[str, Any] = {}
        try:
            if tool == "mark_task_complete":
                message = (
                    f"completed: {args.get('summary') or args.get('reason') or ''}"
                )
                return self._make_runtime_tool_result(
                    action,
                    phase=phase,
                    status="success",
                    message=message,
                    normalized_action=normalized_action,
                    before_url=before_url,
                    started_at=started,
                )
            if tool == "mark_task_failed":
                message = (
                    f"failed: {args.get('reason') or args.get('summary') or ''}"
                )
                return self._make_runtime_tool_result(
                    action,
                    phase=phase,
                    status="success",
                    message=message,
                    normalized_action=normalized_action,
                    before_url=before_url,
                    started_at=started,
                )
            if tool == "click" and args.get("selector"):
                locator, resolved = await self._resolve_locator(
                    str(args["selector"]),
                    require_unique=True,
                )
                selector_resolution = {
                    "selector": str(args["selector"]),
                    "resolved": resolved,
                    "status": "resolved",
                }
                select_result = await self._select_parent_option_if_needed(
                    locator,
                    str(args["selector"]),
                )
                if select_result is not None:
                    return self._make_runtime_tool_result(
                        action,
                        phase=phase,
                        status="success",
                        message=select_result,
                        normalized_action=normalized_action,
                        selector_resolution=selector_resolution,
                        evidence=await evidence_with_transition(),
                        before_url=before_url,
                        started_at=started,
                    )
                await locator.click()
                await self.page.wait_for_timeout(300)
                return self._make_runtime_tool_result(
                    action,
                    phase=phase,
                    status="success",
                    message=f"clicked: {args['selector']} -> {resolved}",
                    normalized_action=normalized_action,
                    selector_resolution=selector_resolution,
                    evidence=await evidence_with_transition(),
                    before_url=before_url,
                    started_at=started,
                )
            if tool == "navigate" and args.get("url"):
                await self.page.goto(
                    args["url"],
                    wait_until="load",
                    timeout=30000,
                )
                return self._make_runtime_tool_result(
                    action,
                    phase=phase,
                    status="success",
                    message=f"navigated: {args['url']}",
                    normalized_action=normalized_action,
                    evidence=await evidence_with_transition(),
                    before_url=before_url,
                    started_at=started,
                )
            if tool == "scroll":
                direction = args.get("direction", "down")
                delta = 500 if direction == "down" else -500
                await self.page.evaluate(f"window.scrollBy(0, {delta})")
                return self._make_runtime_tool_result(
                    action,
                    phase=phase,
                    status="success",
                    message=f"scrolled: {direction}",
                    normalized_action=normalized_action,
                    evidence=await evidence_with_transition(),
                    before_url=before_url,
                    started_at=started,
                )
            if tool == "input_text" and args.get("selector"):
                locator, resolved = await self._resolve_locator(
                    str(args["selector"]),
                    require_unique=True,
                )
                selector_resolution = {
                    "selector": str(args["selector"]),
                    "resolved": resolved,
                    "status": "resolved",
                }
                await locator.fill(
                    str(args.get("text", "")),
                )
                return self._make_runtime_tool_result(
                    action,
                    phase=phase,
                    status="success",
                    message=f"input: {args['selector']} -> {resolved}",
                    normalized_action=normalized_action,
                    selector_resolution=selector_resolution,
                    evidence=await evidence_with_transition({
                        "filled_value": self._redact_input_value(args),
                    }),
                    before_url=before_url,
                    started_at=started,
                )
            if tool == "select_option" and args.get("selector"):
                locator, resolved = await self._resolve_locator(
                    str(args["selector"]),
                    require_unique=True,
                )
                selector_resolution = {
                    "selector": str(args["selector"]),
                    "resolved": resolved,
                    "status": "resolved",
                }
                select_args = self._build_select_option_args(args)
                if not select_args:
                    return self._make_runtime_tool_result(
                        action,
                        phase=phase,
                        status="failed",
                        error_code="tool.missing_select_option_value",
                        message="missing select option value",
                        llm_feedback="error: tool.missing_select_option_value",
                        normalized_action=normalized_action,
                        selector_resolution=selector_resolution,
                        evidence=await evidence_with_transition(),
                        before_url=before_url,
                        started_at=started,
                    )
                await locator.select_option(**select_args)
                await self.page.wait_for_timeout(300)
                message = (
                    f"selected: {args['selector']} -> {resolved} "
                    f"{select_args}"
                )
                return self._make_runtime_tool_result(
                    action,
                    phase=phase,
                    status="success",
                    message=message,
                    normalized_action=normalized_action,
                    selector_resolution=selector_resolution,
                    evidence=await evidence_with_transition(),
                    before_url=before_url,
                    started_at=started,
                )
            if tool == "wait":
                milliseconds = int(args.get("ms", 1000))
                await self.page.wait_for_timeout(milliseconds)
                return self._make_runtime_tool_result(
                    action,
                    phase=phase,
                    status="success",
                    message=f"waited: {milliseconds}ms",
                    normalized_action=normalized_action,
                    evidence=await evidence_with_transition(),
                    before_url=before_url,
                    started_at=started,
                )
        except PlaywrightTimeoutError as exc:
            return self._make_runtime_tool_result(
                action,
                phase=phase,
                status="timeout",
                error_code="tool.timeout",
                message=str(exc),
                llm_feedback=f"error: tool.timeout: {exc}",
                normalized_action=normalized_action,
                selector_resolution=selector_resolution,
                before_url=before_url,
                started_at=started,
            )
        except Exception as exc:
            status, error_code = self._classify_tool_exception(exc)
            return self._make_runtime_tool_result(
                action,
                phase=phase,
                status=status,
                error_code=error_code,
                message=str(exc),
                llm_feedback=f"error: {error_code}: {exc}",
                normalized_action=normalized_action,
                selector_resolution=selector_resolution,
                before_url=before_url,
                started_at=started,
            )
        return self._make_runtime_tool_result(
            action,
            phase=phase,
            status="noop",
            error_code="tool.noop",
            message="tool produced no operation",
            llm_feedback="error: tool.noop",
            normalized_action=normalized_action,
            before_url=before_url,
            started_at=started,
        )

    def _make_runtime_tool_result(
        self,
        action: Mapping[str, Any] | None,
        *,
        phase: RuntimePhase,
        status: str,
        error_code: str = "",
        message: str = "",
        llm_feedback: str = "",
        normalized_action: Mapping[str, Any] | None = None,
        before_url: str | None = None,
        selector_resolution: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
        policy_decision: Mapping[str, Any] | None = None,
        hitl_required: bool = False,
        hitl_reason: str = "",
        started_at: float | None = None,
    ) -> RuntimeToolResult:
        raw_tool = ""
        raw_args: Mapping[str, Any] | None = None
        if isinstance(action, Mapping):
            raw_tool = str(action.get("tool", "") or "unknown")
            maybe_raw_args = action.get("args")
            raw_args = maybe_raw_args if isinstance(maybe_raw_args, Mapping) else {}

        normalized_tool = raw_tool
        normalized_args: Mapping[str, Any] | None = raw_args
        if isinstance(normalized_action, Mapping):
            normalized_tool = str(normalized_action.get("tool", raw_tool) or raw_tool)
            maybe_args = normalized_action.get("args")
            normalized_args = maybe_args if isinstance(maybe_args, Mapping) else {}

        before = before_url if before_url is not None else (
            self.page.url if self.page else self.target_url
        )
        after = self.page.url if self.page else before
        duration_ms = (
            max(0, int((time.perf_counter() - started_at) * 1000))
            if started_at is not None
            else 0
        )
        feedback = llm_feedback or message
        url_changed = before != after
        evidence_snapshot = evidence or {}
        dom_fingerprint = (
            evidence_snapshot.get("dom_fingerprint")
            if isinstance(evidence_snapshot, Mapping)
            else None
        )
        dom_fingerprint_changed = (
            bool(dom_fingerprint.get("changed"))
            if isinstance(dom_fingerprint, Mapping)
            else False
        )
        page_changed = url_changed or dom_fingerprint_changed
        changed_signals = {
            "status": status,
            "error_code": error_code,
            "message": message,
            "url_changed": url_changed,
            "dom_fingerprint_changed": dom_fingerprint_changed,
            "page_changed": page_changed,
        }
        policy_snapshot = (
            normalize_args_for_storage(policy_decision)
            if isinstance(policy_decision, Mapping)
            else {
                "allowed": True,
                "reason": "",
                "error_code": "",
                "permission_level": permission_level_for_tool(normalized_tool),
                "normalized_action": {
                    "tool": normalized_tool or "unknown",
                    "args": normalize_args_for_storage(normalized_args),
                },
            }
        )
        return RuntimeToolResult(
            tool=normalized_tool or "unknown",
            phase=phase,
            permission_level=permission_level_for_tool(normalized_tool),
            status=status,  # type: ignore[arg-type]
            error_code=error_code,
            message=message,
            llm_feedback=feedback,
            args=normalize_args_for_storage(raw_args),
            normalized_args=normalize_args_for_storage(normalized_args),
            before_url=before,
            after_url=after,
            url_changed=url_changed,
            page_changed=page_changed,
            changed_signals=changed_signals,
            selector_resolution=selector_resolution or {},
            policy_decision=policy_snapshot,
            duration_ms=duration_ms,
            evidence=evidence_snapshot,
            hitl_required=hitl_required,
            hitl_reason=hitl_reason,
        )

    @staticmethod
    def _policy_decision_snapshot(decision: Any) -> dict[str, Any]:
        return {
            "allowed": bool(getattr(decision, "allowed", False)),
            "reason": str(getattr(decision, "reason", "") or ""),
            "error_code": str(getattr(decision, "error_code", "") or ""),
            "permission_level": str(
                getattr(decision, "permission_level", "") or ""
            ),
            "normalized_action": (
                getattr(decision, "normalized_action", None) or {}
            ),
        }

    @staticmethod
    def _classify_tool_exception(exc: Exception) -> tuple[str, str]:
        message = str(exc)
        if "selector_not_found" in message:
            return "not_found", "selector.not_found"
        if "selector_ambiguous" in message:
            return "failed", "selector.ambiguous"
        if "strict mode violation" in message.lower():
            return "failed", "selector.ambiguous"
        return "failed", "tool.exception"

    @staticmethod
    def _redact_input_value(args: Mapping[str, Any]) -> str:
        text = str(args.get("text", ""))
        if not text:
            return ""
        if len(text) <= 2:
            return "*" * len(text)
        return f"{text[:2]}****"

    @staticmethod
    def _build_select_option_args(args: dict[str, Any]) -> dict[str, str]:
        for key in ("value", "label", "text"):
            value = str(args.get(key) or "").strip()
            if not value:
                continue
            if key == "text":
                return {"label": value}
            return {key: value}
        return {}

    async def _select_parent_option_if_needed(
        self,
        locator: Any,
        selector: str,
    ) -> str | None:
        try:
            tag_name = await locator.evaluate(
                "(el) => (el.tagName || '').toLowerCase()"
            )
        except Exception:
            return None
        if tag_name != "option":
            return None

        option_value = str(await locator.get_attribute("value") or "").strip()
        option_text = str(await locator.text_content() or "").strip()
        parent_select = locator.locator("xpath=ancestor::select[1]")
        try:
            count = await parent_select.count()
        except Exception:
            return None
        if count != 1:
            return None

        select_args = (
            {"value": option_value}
            if option_value
            else {"label": option_text}
            if option_text
            else {}
        )
        if not select_args:
            return None

        await parent_select.select_option(**select_args)
        await self.page.wait_for_timeout(300)
        return (
            f"selected_option_via_parent: {selector} -> "
            f"{select_args.get('value') or select_args.get('label')}"
        )

    async def _resolve_locator(
        self,
        selector: str,
        *,
        require_unique: bool = False,
    ) -> tuple[Any, str]:
        self._locator_metrics.record_locator_attempt()
        semantic_id = self._semantic_element_id_from_selector(selector)
        if semantic_id:
            for element in self._last_page_info.get("interactive_elements", []):
                if element.get("id") != semantic_id:
                    continue
                text = str(
                    element.get("text")
                    or element.get("label")
                    or ""
                ).strip()
                element_type = str(element.get("type") or "")
                for locator, resolved, strategy in self._semantic_locator_candidates(
                    element
                ):
                    try:
                        return await self._ensure_locator_ready(
                            locator,
                            resolved,
                            require_unique=require_unique,
                            metric_strategy=strategy,
                        )
                    except Exception:
                        continue
                if text:
                    role = {
                        "a": "link",
                        "link": "link",
                        "button": "button",
                    }.get(element_type)
                    if role:
                        role_locator = self.page.get_by_role(
                            role,
                            name=text,
                            exact=True,
                        )
                        if await role_locator.count() == 1:
                            self._locator_metrics.record_locator_success(
                                "semantic_role"
                            )
                            return role_locator, f"role={role}, name={text}"
                    text_locator = self.page.get_by_text(text, exact=True)
                    if await text_locator.count() == 1:
                        self._locator_metrics.record_locator_success(
                            "semantic_text"
                        )
                        return text_locator, f"text={text}"
                xpath = element.get("xpath")
                if xpath:
                    resolved = f"xpath={xpath}"
                    locator = self.page.locator(resolved)
                    return await self._ensure_locator_ready(
                        locator,
                        resolved,
                        require_unique=require_unique,
                        metric_strategy="semantic_xpath",
                    )
        label_target_id = self._label_for_selector_target_id(selector)
        if label_target_id:
            label_locator = self.page.locator(selector)
            try:
                label_count = await label_locator.count()
            except Exception:
                label_count = -1
            if label_count == 0:
                resolved = self._id_selector_for_target_id(label_target_id)
                locator = self.page.locator(resolved)
                return await self._ensure_locator_ready(
                    locator,
                    resolved,
                    require_unique=require_unique,
                    metric_strategy="label_for_id_fallback",
                )
        locator = self.page.locator(selector)
        return await self._ensure_locator_ready(
            locator,
            selector,
            require_unique=require_unique,
            metric_strategy="css",
        )

    @staticmethod
    def _label_for_selector_target_id(selector: str) -> str | None:
        candidate = str(selector or "").strip()
        match = re.fullmatch(
            r"""label\s*\[\s*for\s*=\s*(?:"([^"]+)"|'([^']+)'|([^\]\s]+))\s*\]""",
            candidate,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        return next((group for group in match.groups() if group), None)

    @staticmethod
    def _id_selector_for_target_id(target_id: str) -> str:
        return Runtime._attribute_selector("id", target_id)

    @staticmethod
    def _attribute_selector(attribute: str, value: str) -> str:
        escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
        return f'[{attribute}="{escaped}"]'

    def _semantic_locator_candidates(
        self,
        element: Mapping[str, Any],
    ) -> list[tuple[Any, str, str]]:
        element_type = str(element.get("type") or "").lower()
        candidates: list[tuple[Any, str, str]] = []

        html_id = str(
            element.get("html_id")
            or element.get("dom_id")
            or element.get("element_id")
            or ""
        ).strip()
        if html_id:
            selector = self._id_selector_for_target_id(html_id)
            candidates.append((
                self.page.locator(selector),
                selector,
                "semantic_html_id",
            ))

        name = str(element.get("name") or "").strip()
        if name:
            selector = self._attribute_selector("name", name)
            candidates.append((
                self.page.locator(selector),
                selector,
                "semantic_name",
            ))

        if element_type in {"input", "textarea", "select"}:
            placeholder = str(element.get("placeholder") or "").strip()
            if placeholder:
                candidates.append((
                    self.page.get_by_placeholder(placeholder, exact=True),
                    f"placeholder={placeholder}",
                    "semantic_placeholder",
                ))

            label = str(
                element.get("label")
                or element.get("aria_label")
                or ""
            ).strip()
            if label:
                candidates.append((
                    self.page.get_by_label(label, exact=True),
                    f"label={label}",
                    "semantic_label",
                ))

        return candidates

    def _semantic_element_id_from_selector(self, selector: str) -> str | None:
        candidate = str(selector or "").strip()
        match = re.fullmatch(r"(?:[A-Za-z][\w-]*)?(#\d+)", candidate)
        if not match:
            return None
        semantic_id = match.group(1)
        if any(
            element.get("id") == semantic_id
            for element in self._last_page_info.get("interactive_elements", [])
        ):
            return semantic_id
        return None

    async def _ensure_locator_ready(
        self,
        locator: Any,
        resolved: str,
        *,
        require_unique: bool,
        metric_strategy: str,
    ) -> tuple[Any, str]:
        if not require_unique:
            self._locator_metrics.record_locator_success(metric_strategy)
            return locator, resolved
        try:
            count = await locator.count()
        except Exception:
            self._locator_metrics.record_locator_failure("selector_error")
            raise
        if count == 0:
            self._locator_metrics.record_locator_failure("not_found")
            raise RuntimeError(f"selector_not_found: {resolved}")
        if count > 1:
            self._locator_metrics.record_locator_failure("ambiguous")
            raise RuntimeError(
                f"selector_ambiguous: {resolved} ({count} matches)"
            )
        self._locator_metrics.record_locator_success(metric_strategy)
        return locator, resolved

    async def _record_step(
        self,
        candidate_case_id: str,
        action: dict[str, Any],
        result: str,
        tool_result: RuntimeToolResult | None = None,
    ) -> None:
        if not self._active_run_id:
            return
        from core.execution_store import append_task_step

        step_index = self._active_step_index
        step = await append_task_step(
            task_id=int(self.task_id),
            run_id=self._active_run_id,
            candidate_case_id=candidate_case_id,
            attempt_no=self._active_attempt_no,
            step_index=step_index,
            action=action,
            result=result,
            tool_result=tool_result,
        )
        self._active_step_index = step_index + 1
        if self._event_sink is not None:
            await self._event_sink(
                "case_step",
                candidate_case_id=candidate_case_id,
                attempt_no=self._active_attempt_no,
                step_index=step_index,
                action=action,
                result=result,
                tool_result=(
                    tool_result.model_dump(mode="json")
                    if tool_result is not None
                    else None
                ),
                step_id=step.id,
            )

    async def _invoke_json(
        self,
        prompt: str,
        system_prompt: str,
    ) -> dict[str, Any] | None:
        try:
            from core.llm_client import safe_structured_invoke

            result = await safe_structured_invoke(
                f"{system_prompt}\n\n{prompt}",
                BrowserAction,
                model_type="haiku",
            )
            return result.model_dump() if result is not None else None
        except Exception:
            return None
        return None
