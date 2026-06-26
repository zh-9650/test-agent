"""Goal-driven browser runtime.

The production lifecycle lives in ``RuntimeSession`` and the API orchestrator.
This module only owns browser resources, exploration, and one execution attempt.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlparse

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
    format_tool_example,
    format_tool_prompt_line,
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
    ) -> None:
        await self._record_step(candidate_case_id, action, result)

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
        try:
            if self.context:
                trace_path = os.path.join(
                    "data", "sessions", self.task_id, "trace.zip"
                )
                await self.context.tracing.stop(path=trace_path)
                await self.context.close()
        except Exception:
            pass
        try:
            if self.browser_session:
                await self.browser_session.close()
        except Exception:
            pass
        try:
            if self.browser:
                await self.browser.close()
            if self._playwright:
                await self._playwright.stop()
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
            await self.page.evaluate("localStorage.clear(); sessionStorage.clear();")
            await self.page.goto(
                "about:blank",
                wait_until="domcontentloaded",
                timeout=15000,
            )
            await self.page.goto(
                self.target_url,
                wait_until="networkidle",
                timeout=30000,
            )
        except Exception:
            await self._close_browser()
            await self._launch_browser()

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
            if action_result and not action_result.startswith("error:"):
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

        try:
            page_info = await extract_page_semantics(self.page)
            self._locator_metrics.record_semantic_extraction(
                page_info.get("semantic_extraction")
            )
            return page_info
        except Exception as exc:
            if self._should_recover_browser(str(exc)):
                try:
                    await self._reset_browser_state()
                    recovered = await extract_page_semantics(self.page)
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

    async def _execute_explore_action(self, action: dict[str, Any]) -> str:
        return await self._execute_browser_action(action)

    async def _execute_single_case(
        self,
        case: RuntimeExecutableCase,
    ) -> CaseResult:
        started_at = _now_iso()
        self._locator_metrics = RuntimeLocatorMetrics()
        precondition_result = await self._check_preconditions(case, started_at)
        if precondition_result is not None:
            return precondition_result

        max_steps = int(os.getenv("MAX_STEPS_PER_CASE", "15"))
        evidence: list[str] = []
        for step_index in range(max_steps):
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
                await self._record_step(
                    case.id,
                    {
                        "tool": "decision_error",
                        "args": {"reason": "invalid_or_empty_action"},
                    },
                    "模型未返回可执行的结构化动作",
                )
                break
            if action.get("tool") == "mark_task_failed":
                reason = str(action.get("args", {}).get("reason", "执行判定失败"))
                self.remember_case_feedback(case.id, reason)
                await self._record_step(case.id, action, reason)
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

            result = await self._execute_test_action(action)
            if result:
                evidence.append(result)
                if result.startswith("error:"):
                    self.remember_case_feedback(case.id, result)
            await self._record_step(case.id, action, result or "")

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
        expected_paths = re.findall(
            r"(?<![\w-])/[A-Za-z0-9][A-Za-z0-9_./-]*",
            case.expected,
        )
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

    async def _execute_test_action(
        self,
        action: dict[str, Any],
    ) -> str | None:
        return await self._execute_browser_action(action)

    async def _execute_browser_action(
        self,
        action: dict[str, Any],
    ) -> str | None:
        decision = enforce_runtime_action_policy(
            action,
            target_url=self.target_url,
            current_url=self.page.url if self.page else self.target_url,
        )
        if not decision.allowed:
            return f"error: action_blocked:{decision.reason}"

        normalized_action = decision.normalized_action or dict(action)
        tool = normalized_action.get("tool", "")
        args = normalized_action.get("args", {})
        try:
            if tool == "mark_task_complete":
                return f"completed: {args.get('summary') or args.get('reason') or ''}"
            if tool == "mark_task_failed":
                return f"failed: {args.get('reason') or args.get('summary') or ''}"
            if tool == "click" and args.get("selector"):
                locator, resolved = await self._resolve_locator(
                    str(args["selector"]),
                    require_unique=True,
                )
                select_result = await self._select_parent_option_if_needed(
                    locator,
                    str(args["selector"]),
                )
                if select_result is not None:
                    return select_result
                await locator.click()
                await self.page.wait_for_timeout(300)
                return f"clicked: {args['selector']} -> {resolved}"
            if tool == "navigate" and args.get("url"):
                await self.page.goto(
                    args["url"],
                    wait_until="load",
                    timeout=30000,
                )
                return f"navigated: {args['url']}"
            if tool == "scroll":
                direction = args.get("direction", "down")
                delta = 500 if direction == "down" else -500
                await self.page.evaluate(f"window.scrollBy(0, {delta})")
                return f"scrolled: {direction}"
            if tool == "input_text" and args.get("selector"):
                locator, resolved = await self._resolve_locator(
                    str(args["selector"]),
                    require_unique=True,
                )
                await locator.fill(
                    str(args.get("text", "")),
                )
                return f"input: {args['selector']} -> {resolved}"
            if tool == "select_option" and args.get("selector"):
                locator, resolved = await self._resolve_locator(
                    str(args["selector"]),
                    require_unique=True,
                )
                select_args = self._build_select_option_args(args)
                if not select_args:
                    return "error: missing_select_option_value"
                await locator.select_option(**select_args)
                await self.page.wait_for_timeout(300)
                return (
                    f"selected: {args['selector']} -> {resolved} "
                    f"{select_args}"
                )
            if tool == "wait":
                milliseconds = int(args.get("ms", 1000))
                await self.page.wait_for_timeout(milliseconds)
                return f"waited: {milliseconds}ms"
        except Exception as exc:
            return f"error: {exc}"
        return None

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
        locator = self.page.locator(selector)
        return await self._ensure_locator_ready(
            locator,
            selector,
            require_unique=require_unique,
            metric_strategy="css",
        )

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
