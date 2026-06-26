import asyncio
from typing import get_args
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.interfaces import (
    CaseResult,
    ExplorationGoal,
    RuntimeExecutableCase,
    StructuredPrecondition,
    SystemMapEvid,
    TerminalAssertion,
)
from core.runtime import BrowserAction, Runtime
from core.runtime_locator_metrics import RuntimeLocatorMetrics
from core.runtime_session import RuntimeSession
from core.runtime_tool_contract import (
    EXECUTION_ACTION_TOOLS,
    EXPLORATION_ACTION_TOOLS,
    RUNTIME_ACTION_TOOLS,
    TOOL_ARGUMENT_EXAMPLES,
    format_tool_prompt_line,
)


def executable_case(**overrides):
    data = {
        "id": "CASE-1",
        "objective": "提交表单",
        "expected": "显示成功提示",
        "trace_references": ["COV-1"],
    }
    data.update(overrides)
    return RuntimeExecutableCase(**data)


def case_result(status: str, attempt: int = 1) -> CaseResult:
    return CaseResult(
        run_id="",
        candidate_case_id="CASE-1",
        terminal_status=status,
        attempt_count=attempt,
        started_at="2026-06-11T00:00:00+00:00",
        completed_at="2026-06-11T00:00:01+00:00",
        summary=status,
    )


def test_runtime_has_no_legacy_session_entrypoints():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})
    assert not hasattr(runtime, "run")
    assert not hasattr(runtime, "run_stream")
    assert not hasattr(runtime, "_execute_test_case")


def test_runtime_tool_contract_matches_browser_action_schema():
    schema_tools = get_args(BrowserAction.model_fields["tool"].annotation)

    assert schema_tools == RUNTIME_ACTION_TOOLS
    assert set(EXPLORATION_ACTION_TOOLS) <= set(schema_tools)
    assert set(EXECUTION_ACTION_TOOLS) <= set(schema_tools)
    assert set(TOOL_ARGUMENT_EXAMPLES) == set(schema_tools)


def test_terminal_assertion_requires_all_three_conditions():
    complete = TerminalAssertion(
        objective_satisfied=True,
        expected_result_supported=True,
        terminal_evidence_sufficient=True,
    )
    missing_evidence = complete.model_copy(
        update={"terminal_evidence_sufficient": False}
    )
    assert Runtime._all_terminal_satisfied(complete) is True
    assert Runtime._all_terminal_satisfied(missing_evidence) is False


def test_exploration_stops_when_one_expected_evidence_is_observed():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})
    goal = ExplorationGoal(
        id="GOAL-1",
        goal="验证首页",
        assertion_refs=["ASSERT-1"],
        expected_evidence=["Example Domain", "不存在的次要证据"],
        stop_condition="发现任一明确页面证据",
        priority="medium",
    )
    assert runtime._check_stop_condition(
        goal,
        {"title": "Example Domain"},
    ) is True


def test_exploration_matches_distinctive_literal_inside_semantic_evidence():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})
    goal = ExplorationGoal(
        id="GOAL-1",
        goal="验证首页标题是否为 Example Domain",
        assertion_refs=["ASSERT-1"],
        expected_evidence=["页面清晰显示标题“Example Domain”"],
        stop_condition="标题内容可直接核验",
        priority="medium",
    )

    assert runtime._check_stop_condition(
        goal,
        {
            "url": "https://example.com/",
            "title": "Example Domain",
            "headings": ["Example Domain"],
        },
    ) is True


def test_exploration_does_not_match_generic_semantic_description():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})
    goal = ExplorationGoal(
        id="GOAL-1",
        goal="验证首页符合需求",
        assertion_refs=["ASSERT-1"],
        expected_evidence=["页面呈现约定的主标题"],
        stop_condition="标题内容可直接核验",
        priority="medium",
    )

    assert runtime._check_stop_condition(
        goal,
        {"url": "https://example.com/", "title": "Unrelated"},
    ) is False


@pytest.mark.asyncio
async def test_exploration_global_budget_marks_remaining_goals_insufficient(
    monkeypatch,
):
    monkeypatch.setenv("MAX_EXPLORE_PAGES", "1")
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})
    runtime._observe_page = AsyncMock(
        return_value={"url": "https://example.com", "title": "Example"}
    )
    runtime._evaluate_goal_evidence = AsyncMock(return_value=False)
    runtime._decide_explore_action = AsyncMock(return_value=None)
    goals = [
        ExplorationGoal(
            id=f"GOAL-{index}",
            goal=f"目标 {index}",
            assertion_refs=[f"ASSERT-{index}"],
            expected_evidence=[f"证据 {index}"],
            stop_condition="发现证据",
            priority="medium",
        )
        for index in range(2)
    ]

    result = await runtime.explore(goals)

    assert runtime._observe_page.await_count == 1
    assert [item.status for item in result.goal_results] == [
        "insufficient",
        "insufficient",
    ]
    assert "全局探索" in result.goal_results[1].stop_reason


@pytest.mark.asyncio
async def test_exploration_retains_page_map_without_found_goal():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})
    runtime._observe_page = AsyncMock(
        return_value={
            "url": "https://example.com/dashboard",
            "title": "Dashboard",
            "headings": ["Overview"],
            "forms": [{"name": "SearchForm"}],
            "interactive_elements": [
                {"role": "button", "label": "Search"},
                {"role": "link", "text": "Details"},
            ],
            "tables": [{"headers": ["Name", "Status"]}],
        }
    )
    runtime._evaluate_goal_evidence = AsyncMock(return_value=False)
    runtime._decide_explore_action = AsyncMock(return_value=None)
    goals = [
        ExplorationGoal(
            id="GOAL-1",
            goal="Inspect dashboard",
            assertion_refs=["ASSERT-1"],
            expected_evidence=["A hidden compliance marker"],
            stop_condition="Dashboard content is confirmed",
            priority="medium",
        )
    ]

    result = await runtime.explore(goals)

    assert result.goal_results[0].status == "insufficient"
    assert len(result.system_map.pages) == 1
    page = result.system_map.pages[0]
    assert page.url_pattern == "https://example.com/dashboard"
    assert "Overview" in page.elements
    assert "form:SearchForm" in page.elements
    assert "button:Search" in page.discovered_actions
    assert any(
        action.action_name == "Search"
        and action.trigger == "button"
        and action.source_page == "Overview"
        and "page_url: https://example.com/dashboard" in action.evidence_refs
        for action in result.system_map.actions
    )
    assert any(
        action.action_name == "Details"
        and action.trigger == "link"
        for action in result.system_map.actions
    )
    assert len(result.system_map.forms) == 1
    assert result.system_map.forms[0].form_name == "SearchForm"
    assert result.system_map.forms[0].page == "Overview"
    assert result.system_map.forms[0].evidence_refs == [
        "page_url: https://example.com/dashboard",
        "form: SearchForm",
    ]


@pytest.mark.asyncio
async def test_exploration_records_navigation_after_successful_action():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})
    runtime._observe_page = AsyncMock(side_effect=[
        {
            "url": "https://example.com/purchases?tab=open",
            "title": "Purchases",
            "headings": ["采购申请"],
            "interactive_elements": [
                {
                    "id": "#1",
                    "role": "link",
                    "type": "link",
                    "text": "新建采购申请",
                    "href": "/purchases/new",
                }
            ],
        },
        {
            "url": "https://example.com/purchases/new",
            "title": "Create Purchase",
            "headings": ["创建采购申请"],
            "forms": [
                {
                    "id": "purchase-form",
                    "fields": [
                        {
                            "field_type": "number",
                            "label": "采购金额",
                        },
                        {
                            "field_type": "textarea",
                            "label": "采购说明",
                        },
                    ],
                }
            ],
            "interactive_elements": [
                {
                    "id": "#1",
                    "role": "textbox",
                    "type": "input",
                    "label": "采购金额",
                },
                {
                    "id": "#2",
                    "role": "button",
                    "type": "button",
                    "button_type": "submit",
                    "text": "提交申请",
                },
            ],
        },
    ])
    runtime._check_stop_condition = MagicMock(side_effect=[False, True])
    runtime._evaluate_goal_evidence = AsyncMock(return_value=False)
    runtime._decide_explore_action = AsyncMock(return_value={
        "tool": "click",
        "args": {"selector": "link#1"},
    })
    runtime._execute_explore_action = AsyncMock(return_value="clicked: #1")
    goal = ExplorationGoal(
        id="GOAL-1",
        goal="发现采购申请表单",
        assertion_refs=["ASSERT-1"],
        expected_evidence=["创建采购申请"],
        stop_condition="采购申请表单可观察",
        priority="high",
    )

    result = await runtime.explore([goal])

    assert result.goal_results[0].status == "found"
    assert len(result.system_map.pages) == 2
    assert len(result.system_map.navigations) == 1
    navigation = result.system_map.navigations[0]
    assert navigation.source == "采购申请"
    assert navigation.target == "创建采购申请"
    assert navigation.via == "click"
    assert navigation.action == "新建采购申请"
    assert navigation.evidence_refs == [
        "source_url: https://example.com/purchases",
        "target_url: https://example.com/purchases/new",
        "action: 新建采购申请",
    ]
    assert result.system_map.forms[0].form_name == "purchase-form"
    assert result.system_map.forms[0].fields == [
        "number:采购金额",
        "textarea:采购说明",
    ]
    assert result.system_map.forms[0].submit_action == "提交申请"
    create_action = next(
        action
        for action in result.system_map.actions
        if action.action_name == "新建采购申请"
    )
    assert create_action.target_page == "https://example.com/purchases/new"
    assert create_action.source_page == "采购申请"
    assert result.goal_results[0].evidence_refs[:3] == [
        "page_url: https://example.com/purchases/new",
        "page_title: Create Purchase",
        "heading: 创建采购申请",
    ]


def test_same_named_actions_on_different_pages_remain_distinct():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})
    system_map = SystemMapEvid()

    runtime._remember_exploration_observation(system_map, {
        "url": "https://example.com/purchases/new",
        "title": "Create Purchase",
        "headings": ["创建采购申请"],
        "interactive_elements": [
            {
                "id": "#1",
                "type": "button",
                "role": "button",
                "text": "提交",
            }
        ],
    })
    runtime._remember_exploration_observation(system_map, {
        "url": "https://example.com/approvals/1",
        "title": "Approval",
        "headings": ["审批详情"],
        "interactive_elements": [
            {
                "id": "#1",
                "type": "button",
                "role": "button",
                "text": "提交",
            }
        ],
    })

    submit_actions = [
        action
        for action in system_map.actions
        if action.action_name == "提交"
    ]
    assert len(submit_actions) == 2
    assert {action.source_page for action in submit_actions} == {
        "创建采购申请",
        "审批详情",
    }


def test_page_identity_ignores_query_and_fragment_noise():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})

    assert runtime._canonical_page_url(
        "https://example.com/dashboard?role=manager#summary"
    ) == "https://example.com/dashboard"
    assert runtime._canonical_page_url(
        "https://example.com/approvals/123?tab=history"
    ) == "https://example.com/approvals/:id"
    assert runtime._canonical_page_url(
        "https://example.com/users/550e8400-e29b-41d4-a716-446655440000"
    ) == "https://example.com/users/:id"
    assert runtime._is_same_page_map(
        runtime._build_page_map({
            "url": "https://example.com/dashboard?role=manager",
            "title": "Dashboard",
            "headings": ["Dashboard"],
        }),
        runtime._build_page_map({
            "url": "https://example.com/dashboard?role=employee",
            "title": "Dashboard",
            "headings": ["Dashboard"],
        }),
    )


@pytest.mark.asyncio
async def test_execute_browser_action_supports_select_option_tool():
    runtime = Runtime(
        {"task_id": "1", "target_url": "https://example.com/dashboard"}
    )
    runtime.page = MagicMock()
    runtime.page.url = "https://example.com/dashboard"
    runtime.page.wait_for_timeout = AsyncMock()
    locator = MagicMock()
    locator.select_option = AsyncMock()
    runtime._resolve_locator = AsyncMock(
        return_value=(locator, "select[name=plan]")
    )

    result = await runtime._execute_browser_action(
        {
            "tool": "select_option",
            "args": {"selector": "#plan", "value": "all"},
        }
    )

    assert "selected:" in result
    locator.select_option.assert_awaited_once_with(value="all")


@pytest.mark.asyncio
async def test_execute_browser_action_rewrites_option_click_to_parent_select():
    runtime = Runtime(
        {"task_id": "1", "target_url": "https://example.com/dashboard"}
    )
    runtime.page = MagicMock()
    runtime.page.url = "https://example.com/dashboard"
    runtime.page.wait_for_timeout = AsyncMock()

    option_locator = MagicMock()
    option_locator.evaluate = AsyncMock(return_value="option")
    option_locator.get_attribute = AsyncMock(return_value="all")
    option_locator.text_content = AsyncMock(return_value="All plans")
    parent_select = MagicMock()
    parent_select.count = AsyncMock(return_value=1)
    parent_select.select_option = AsyncMock()
    option_locator.locator.return_value = parent_select

    runtime._resolve_locator = AsyncMock(return_value=(option_locator, "#10"))

    result = await runtime._execute_browser_action(
        {"tool": "click", "args": {"selector": "#10"}}
    )

    assert "selected_option_via_parent" in result
    parent_select.select_option.assert_awaited_once_with(value="all")


@pytest.mark.asyncio
async def test_unsatisfied_structured_precondition_returns_explicit_terminal():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})
    case = executable_case(
        preconditions=[
            StructuredPrecondition(
                type="business_state",
                description="订单必须已支付",
                satisfiable_by_agent=False,
                failure_policy="skipped",
            )
        ]
    )
    result = await runtime._execute_single_case(case)
    assert result.terminal_status == "skipped"
    assert result.attempt_count == 0
    assert "precondition_skipped" in (result.failure_reason or "")


@pytest.mark.asyncio
async def test_semantic_goal_evidence_requires_explicit_positive_result():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})
    goal = ExplorationGoal(
        id="GOAL-1",
        goal="验证首页标题",
        assertion_refs=["ASSERT-1"],
        expected_evidence=["页面呈现约定的主标题"],
        stop_condition="标题可核验",
        priority="medium",
    )
    with patch(
        "core.llm_client.safe_structured_invoke",
        new=AsyncMock(
            return_value=type(
                "Assessment",
                (),
                {"evidence_sufficient": True},
            )()
        ),
    ):
        assert await runtime._evaluate_goal_evidence(
            goal,
            {"title": "Example Domain"},
        ) is True


@pytest.mark.asyncio
async def test_observe_page_recovers_after_browser_closed_error():
    runtime = Runtime(
        {"task_id": "1", "target_url": "https://example.com/dashboard"}
    )
    runtime.page = MagicMock()
    runtime.page.url = "https://example.com/dashboard"
    runtime._reset_browser_state = AsyncMock()

    with patch(
        "core.page_semantic.extract_page_semantics",
        new=AsyncMock(
            side_effect=[
                RuntimeError("Target page, context or browser has been closed"),
                {
                    "url": "https://example.com/dashboard",
                    "title": "Dashboard",
                    "headings": ["数据看板"],
                },
            ]
        ),
    ):
        result = await runtime._observe_page()

    assert result["title"] == "Dashboard"
    assert result["_browser_recovered"] is True
    assert "closed" in result["_recovery_reason"].lower()
    runtime._reset_browser_state.assert_awaited_once()


@pytest.mark.asyncio
async def test_terminal_assessment_without_sufficient_evidence_keeps_observing():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})
    assessment = type(
        "Assessment",
        (),
        {
            "need_more_observation": False,
            "objective_satisfied": False,
            "expected_result_supported": False,
            "terminal_evidence_sufficient": False,
            "reasoning": "当前证据不足",
        },
    )()

    with patch(
        "core.llm_client.safe_structured_invoke",
        new=AsyncMock(return_value=assessment),
    ):
        result = await runtime._evaluate_terminal_assertion(
            executable_case(),
            {"url": "https://example.com", "title": "Example Domain"},
            [],
        )

    assert result is None


@pytest.mark.asyncio
async def test_terminal_failure_requires_sufficient_evidence():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})
    assessment = type(
        "Assessment",
        (),
        {
            "need_more_observation": False,
            "objective_satisfied": False,
            "expected_result_supported": False,
            "terminal_evidence_sufficient": True,
            "reasoning": "页面稳定且明确不满足预期",
        },
    )()

    with patch(
        "core.llm_client.safe_structured_invoke",
        new=AsyncMock(return_value=assessment),
    ):
        result = await runtime._evaluate_terminal_assertion(
            executable_case(),
            {"url": "https://example.com", "title": "Example Domain"},
            ["clicked: #submit"],
        )

    assert result is not None
    assert result.terminal_evidence_sufficient is True
    assert Runtime._all_terminal_satisfied(result) is False


@pytest.mark.asyncio
async def test_terminal_failure_can_finish_from_page_evidence_without_actions():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})
    assessment = type(
        "Assessment",
        (),
        {
            "need_more_observation": False,
            "objective_satisfied": False,
            "expected_result_supported": False,
            "terminal_evidence_sufficient": True,
            "reasoning": "页面已直接展示非标准标签，预期不成立",
        },
    )()

    with patch(
        "core.llm_client.safe_structured_invoke",
        new=AsyncMock(return_value=assessment),
    ):
        result = await runtime._evaluate_terminal_assertion(
            executable_case(
                objective="验证标准标签",
                expected="仅显示标准标签",
            ),
            {
                "url": "https://example.com/dashboard",
                "title": "Dashboard",
                "visible_texts": ["明星人才 · 4人", "关键人才 · 3人"],
            },
            [],
        )

    assert result is not None
    assert result.terminal_evidence_sufficient is True
    assert Runtime._all_terminal_satisfied(result) is False


@pytest.mark.asyncio
async def test_runtime_session_retries_update_one_case_result():
    session = RuntimeSession(
        {"task_id": "1", "target_url": "https://example.com"}
    )
    session.runtime._execute_single_case = AsyncMock(
        side_effect=[
            case_result("failed"),
            case_result("incomplete"),
            case_result("passed"),
        ]
    )
    session.runtime._reset_browser_state = AsyncMock()

    with patch(
        "core.runtime_session.upsert_case_result",
        new_callable=AsyncMock,
    ) as upsert:
        results = await session.execute("RUN-1", [executable_case()])

    assert len(results) == 1
    assert results[0].terminal_status == "passed"
    assert results[0].attempt_count == 3
    upsert.assert_awaited_once()
    assert session.runtime._reset_browser_state.await_count == 2


@pytest.mark.asyncio
async def test_failed_retry_exhaustion_remains_failed(monkeypatch):
    monkeypatch.setenv("MAX_TEST_CASE_RETRIES", "1")
    session = RuntimeSession(
        {"task_id": "1", "target_url": "https://example.com"}
    )
    session.runtime._execute_single_case = AsyncMock(
        side_effect=[case_result("failed"), case_result("failed")]
    )
    session.runtime._reset_browser_state = AsyncMock()

    with patch(
        "core.runtime_session.upsert_case_result",
        new_callable=AsyncMock,
    ):
        results = await session.execute("RUN-1", [executable_case()])

    assert results[0].terminal_status == "failed"
    assert results[0].attempt_count == 2


@pytest.mark.asyncio
async def test_incomplete_retry_exhaustion_requires_human_review(monkeypatch):
    monkeypatch.setenv("MAX_TEST_CASE_RETRIES", "1")
    session = RuntimeSession(
        {"task_id": "1", "target_url": "https://example.com"}
    )
    session.runtime._execute_single_case = AsyncMock(
        side_effect=[case_result("incomplete"), case_result("incomplete")]
    )
    session.runtime._reset_browser_state = AsyncMock()

    with patch(
        "core.runtime_session.upsert_case_result",
        new_callable=AsyncMock,
    ):
        results = await session.execute("RUN-1", [executable_case()])

    assert results[0].terminal_status == "human_review_required"
    assert results[0].attempt_count == 2


@pytest.mark.asyncio
async def test_precondition_terminal_is_not_retried(monkeypatch):
    monkeypatch.setenv("MAX_TEST_CASE_RETRIES", "2")
    session = RuntimeSession(
        {"task_id": "1", "target_url": "https://example.com"}
    )
    precondition = case_result("failed", attempt=0)
    session.runtime._execute_single_case = AsyncMock(
        return_value=precondition
    )
    session.runtime._reset_browser_state = AsyncMock()

    with patch(
        "core.runtime_session.upsert_case_result",
        new_callable=AsyncMock,
    ):
        results = await session.execute("RUN-1", [executable_case()])

    assert results[0].attempt_count == 0
    session.runtime._execute_single_case.assert_awaited_once()
    session.runtime._reset_browser_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_case_attempt_timeout_is_bounded(monkeypatch):
    monkeypatch.setenv("MAX_TEST_CASE_RETRIES", "0")
    monkeypatch.setenv("MAX_CASE_ATTEMPT_SECONDS", "0.01")
    session = RuntimeSession(
        {"task_id": "1", "target_url": "https://example.com"}
    )

    async def never_finishes(_case):
        await asyncio.sleep(1)

    session.runtime._execute_single_case = never_finishes
    session.runtime._record_step = AsyncMock()

    with patch(
        "core.runtime_session.upsert_case_result",
        new_callable=AsyncMock,
    ):
        results = await session.execute("RUN-1", [executable_case()])

    assert results[0].terminal_status == "human_review_required"
    assert results[0].attempt_count == 1
    assert results[0].failure_reason == "case_attempt_timeout: 0.01s"


@pytest.mark.asyncio
async def test_runtime_emits_persisted_case_step():
    event_sink = AsyncMock()
    session = RuntimeSession(
        {"task_id": "1", "target_url": "https://example.com"},
        event_sink=event_sink,
    )
    session.runtime._check_preconditions = AsyncMock(return_value=None)
    session.runtime._observe_page = AsyncMock(return_value={"url": "https://example.com"})
    session.runtime._evaluate_terminal_assertion = AsyncMock(
        side_effect=[
            None,
            TerminalAssertion(
                objective_satisfied=True,
                expected_result_supported=True,
                terminal_evidence_sufficient=True,
                reasoning="已验证",
            ),
        ]
    )
    session.runtime._decide_execute_action = AsyncMock(
        return_value={"tool": "wait", "args": {"ms": 1}}
    )
    session.runtime._execute_test_action = AsyncMock(return_value="waited: 1ms")
    session.runtime._active_run_id = "RUN-1"
    session.runtime._active_attempt_no = 2

    persisted_step = type("PersistedStep", (), {"id": 42})()
    with patch(
        "core.execution_store.append_task_step",
        new=AsyncMock(return_value=persisted_step),
    ):
        await session.runtime._execute_single_case(executable_case())

    event_sink.assert_awaited_once()
    event_type, payload = event_sink.await_args.args
    assert event_type == "case_step"
    assert payload["candidate_case_id"] == "CASE-1"
    assert payload["attempt_no"] == 2
    assert payload["step_index"] == 0
    assert payload["step_id"] == 42


@pytest.mark.asyncio
async def test_semantic_element_id_prefers_unique_role_and_text():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})
    role_locator = MagicMock()
    role_locator.count = AsyncMock(return_value=1)
    runtime.page = MagicMock()
    runtime.page.get_by_role.return_value = role_locator
    runtime._last_page_info = {
        "interactive_elements": [
            {
                "id": "#7",
                "type": "link",
                "text": "能力趋势洞察",
                "xpath": "//a[7]",
            }
        ]
    }

    locator, resolved = await runtime._resolve_locator("#7")

    assert locator is role_locator
    assert resolved == "role=link, name=能力趋势洞察"
    assert runtime._locator_metrics.as_dict()["locator_success_by_strategy"] == {
        "semantic_role": 1,
    }


@pytest.mark.asyncio
async def test_semantic_element_id_accepts_tag_prefixed_reference():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})
    role_locator = MagicMock()
    role_locator.count = AsyncMock(return_value=1)
    runtime.page = MagicMock()
    runtime.page.get_by_role.return_value = role_locator
    runtime._last_page_info = {
        "interactive_elements": [
            {
                "id": "#3",
                "type": "button",
                "text": "部门领导",
                "xpath": "//button[3]",
            }
        ]
    }

    locator, resolved = await runtime._resolve_locator("button#3")

    assert locator is role_locator
    assert resolved == "role=button, name=部门领导"


@pytest.mark.asyncio
async def test_observe_page_records_semantic_extraction_source():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})
    runtime.page = MagicMock()

    with patch(
        "core.page_semantic.extract_page_semantics",
        new=AsyncMock(
            return_value={
                "url": "https://example.com",
                "semantic_extraction": {
                    "source": "cdp",
                    "element_count": 5,
                    "cdp_available": True,
                },
            }
        ),
    ):
        await runtime._observe_page()

    metrics = runtime._locator_metrics.as_dict()
    assert metrics["semantic_observations"] == 1
    assert metrics["semantic_source_counts"] == {"cdp": 1}


def test_locator_metrics_evidence_ref_is_compact_json():
    metrics = RuntimeLocatorMetrics()
    metrics.record_locator_attempt()
    metrics.record_locator_success("css")
    metrics.record_semantic_extraction({"source": "playwright_locator"})

    evidence = metrics.evidence_ref()

    assert evidence.startswith("locator_metrics: ")
    assert '"locator_attempts": 1' in evidence
    assert '"semantic_source_counts": {"playwright_locator": 1}' in evidence


def test_runtime_appends_locator_metrics_to_evidence_refs():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})
    runtime._locator_metrics.record_locator_attempt()
    runtime._locator_metrics.record_locator_failure("ambiguous")

    refs = runtime._evidence_refs_with_locator_metrics(["clicked: #1"])

    assert refs[0] == "clicked: #1"
    assert refs[1].startswith("locator_metrics: ")


def test_deterministic_terminal_uses_stable_heading_not_navigation_text():
    case = executable_case(
        objective="点击'能力趋势洞察'后进入目标页面",
        expected="页面主体显示“能力趋势洞察”标题",
    )

    initial = Runtime._deterministic_terminal_assertion(
        case,
        {
            "url": "http://localhost:5000/dashboard",
            "title": "TalentMap",
            "headings": ["数据看板"],
            "interactive_elements": [{"text": "能力趋势洞察"}],
        },
    )
    completed = Runtime._deterministic_terminal_assertion(
        case,
        {
            "url": "http://localhost:5000/reports",
            "title": "TalentMap",
            "headings": ["能力趋势洞察"],
        },
    )

    assert initial is None
    assert completed is not None
    assert Runtime._all_terminal_satisfied(completed) is True


def test_deterministic_terminal_can_match_visible_read_only_text():
    case = executable_case(
        objective="验证首页指标卡片展示",
        expected="页面显示“明星/核心人才”卡片",
    )

    result = Runtime._deterministic_terminal_assertion(
        case,
        {
            "url": "http://localhost:5000/dashboard",
            "title": "TalentMap",
            "headings": ["数据看板"],
            "visible_texts": ["盘点项目", "明星/核心人才", "待关注人员"],
        },
    )

    assert result is not None
    assert Runtime._all_terminal_satisfied(result) is True


def test_deterministic_terminal_does_not_pass_formula_from_label_only():
    case = executable_case(
        objective="验证明星/核心人才卡片公式",
        expected="“明星/核心人才”人数等于“明星人才”与“核心人才”人数之和。",
    )

    result = Runtime._deterministic_terminal_assertion(
        case,
        {
            "url": "http://localhost:5000/dashboard",
            "title": "TalentMap",
            "headings": ["数据看板"],
            "visible_texts": ["明星/核心人才", "明星人才", "核心人才"],
        },
    )

    assert result is None


def test_deterministic_terminal_validates_dashboard_formula_numbers():
    case = executable_case(
        objective="验证明星/核心人才卡片公式",
        expected="“明星/核心人才”人数等于“明星人才”与“核心人才”人数之和。",
    )

    result = Runtime._deterministic_terminal_assertion(
        case,
        {
            "url": "http://localhost:5000/dashboard",
            "title": "TalentMap",
            "headings": ["数据看板"],
            "visible_texts": [
                "明星/核心人才",
                "10人",
                "明星人才 · 4人",
                "核心人才 · 6人",
            ],
        },
    )

    assert result is not None
    assert Runtime._all_terminal_satisfied(result) is True
    assert "确定性公式证据匹配" in result.reasoning


def test_deterministic_terminal_fails_dashboard_formula_mismatch():
    case = executable_case(
        objective="验证待关注人员卡片公式",
        expected="“待关注人员”人数等于“业绩不佳者”与“关注”人数之和。",
    )

    result = Runtime._deterministic_terminal_assertion(
        case,
        {
            "url": "http://localhost:5000/dashboard",
            "title": "TalentMap",
            "headings": ["数据看板"],
            "visible_texts": [
                "待关注人员",
                "3人",
                "业绩不佳者 · 2人",
                "关注 · 2人",
            ],
        },
    )

    assert result is not None
    assert Runtime._all_terminal_satisfied(result) is False
    assert "确定性公式证据不匹配" in result.reasoning


@pytest.mark.asyncio
async def test_contenteditable_dom_assertion_passes_without_llm():
    runtime = Runtime(
        {"task_id": "1", "target_url": "https://example.com/dashboard"}
    )
    runtime.page = MagicMock()
    runtime.page.url = "https://example.com/dashboard"
    runtime.page.evaluate = AsyncMock(
        return_value={
            "inspectedCount": 42,
            "regionCount": 6,
            "regionViolations": [],
            "visibleEditableViolations": [],
        }
    )
    case = executable_case(
        objective="验证所有展示区域的 contenteditable 属性处于边界状态",
        expected="通过 DOM API 检查所有元素的 contenteditable 属性值严格等于 false 或不存在",
    )

    with patch(
        "core.llm_client.safe_structured_invoke",
        new=AsyncMock(return_value=None),
    ) as invoke:
        result = await runtime._evaluate_terminal_assertion(
            case,
            {
                "url": "https://example.com/dashboard",
                "title": "TalentMap",
                "headings": ["数据看板"],
                "interactive_elements": [{"id": "#1"}],
                "tables": [],
                "error_messages": [],
                "loading": False,
            },
            [],
        )

    assert result is not None
    assert Runtime._all_terminal_satisfied(result) is True
    assert "DOM 属性校验通过" in result.reasoning
    invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_contenteditable_dom_assertion_fails_on_editable_region():
    runtime = Runtime(
        {"task_id": "1", "target_url": "https://example.com/dashboard"}
    )
    runtime.page = MagicMock()
    runtime.page.url = "https://example.com/dashboard"
    runtime.page.evaluate = AsyncMock(
        return_value={
            "inspectedCount": 35,
            "regionCount": 4,
            "regionViolations": [
                {
                    "tag": "div",
                    "id": "dashboard-card",
                    "role": "region",
                    "attrValue": "true",
                    "reason": "isContentEditable",
                    "text": "能力趋势洞察",
                }
            ],
            "visibleEditableViolations": [],
        }
    )
    case = executable_case(
        objective="验证所有展示区域的 contenteditable 属性处于边界状态",
        expected="通过 DOM API 检查所有元素的 contenteditable 属性值严格等于 false 或不存在",
    )

    with patch(
        "core.llm_client.safe_structured_invoke",
        new=AsyncMock(return_value=None),
    ) as invoke:
        result = await runtime._evaluate_terminal_assertion(
            case,
            {
                "url": "https://example.com/dashboard",
                "title": "TalentMap",
                "headings": ["数据看板"],
                "interactive_elements": [{"id": "#1"}],
                "tables": [],
                "error_messages": [],
                "loading": False,
            },
            [],
        )

    assert result is not None
    assert Runtime._all_terminal_satisfied(result) is False
    assert result.terminal_evidence_sufficient is True
    assert "contenteditable 风险元素" in result.reasoning
    assert "dashboard-card" in result.reasoning
    invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_contenteditable_dom_assertion_requires_target_route_context():
    runtime = Runtime(
        {"task_id": "1", "target_url": "https://example.com/dashboard"}
    )
    runtime.page = MagicMock()
    runtime.page.url = "https://example.com/login"
    runtime.page.evaluate = AsyncMock(
        return_value={
            "inspectedCount": 30,
            "regionCount": 5,
            "regionViolations": [],
            "visibleEditableViolations": [],
        }
    )
    case = executable_case(
        objective="验证所有展示区域的 contenteditable 属性处于边界状态",
        expected="通过 DOM API 检查所有元素的 contenteditable 属性值严格等于 false 或不存在",
    )

    with patch(
        "core.llm_client.safe_structured_invoke",
        new=AsyncMock(return_value=None),
    ) as invoke:
        result = await runtime._evaluate_terminal_assertion(
            case,
            {
                "url": "https://example.com/login",
                "title": "登录",
                "headings": ["登录"],
                "interactive_elements": [{"id": "#1"}],
                "tables": [],
                "error_messages": [],
                "loading": False,
            },
            [],
        )

    assert result is None
    runtime.page.evaluate.assert_not_awaited()
    invoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_invalid_action_is_persisted_as_decision_error():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})
    runtime._active_run_id = "RUN-1"
    runtime._check_preconditions = AsyncMock(return_value=None)
    runtime._observe_page = AsyncMock(return_value={"url": "https://example.com"})
    runtime._evaluate_terminal_assertion = AsyncMock(return_value=None)
    runtime._decide_execute_action = AsyncMock(return_value=None)
    runtime._record_step = AsyncMock()

    result = await runtime._execute_single_case(executable_case())

    assert result.terminal_status == "incomplete"
    runtime._record_step.assert_awaited_once()
    action = runtime._record_step.await_args.args[1]
    assert action["tool"] == "decision_error"


@pytest.mark.asyncio
async def test_case_result_keeps_terminal_assertion_reason_as_evidence():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})
    runtime._check_preconditions = AsyncMock(return_value=None)
    runtime._observe_page = AsyncMock(
        return_value={
            "url": "https://example.com/reports",
            "title": "TalentMap",
            "headings": ["能力趋势洞察"],
        }
    )
    case = executable_case(
        objective="打开'能力趋势洞察'",
        expected="页面显示“能力趋势洞察”标题",
    )

    result = await runtime._execute_single_case(case)

    assert result.terminal_status == "passed"
    assert any(
        ref.startswith("terminal_assertion: 确定性页面证据匹配")
        for ref in result.evidence_refs
    )


@pytest.mark.asyncio
async def test_context_manager_always_closes_browser():
    session = RuntimeSession(
        {"task_id": "1", "target_url": "https://example.com"}
    )
    session.runtime._launch_browser = AsyncMock()
    session.runtime._close_browser = AsyncMock()

    with pytest.raises(RuntimeError):
        async with session:
            raise RuntimeError("boom")

    session.runtime._launch_browser.assert_awaited_once()
    session.runtime._close_browser.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_browser_action_blocks_forbidden_navigation_target():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})

    result = await runtime._execute_browser_action(
        {"tool": "navigate", "args": {"url": "view-source:https://example.com"}}
    )

    assert result == "error: action_blocked:forbidden_navigation_target"


@pytest.mark.asyncio
async def test_execute_browser_action_blocks_generic_container_selector():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})

    result = await runtime._execute_browser_action(
        {"tool": "input_text", "args": {"selector": "body", "text": "hello"}}
    )

    assert result == "error: action_blocked:generic_container_selector_blocked"


@pytest.mark.asyncio
async def test_execute_browser_action_fails_fast_on_ambiguous_selector():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})
    runtime.page = MagicMock()
    runtime.page.url = "https://example.com/dashboard"
    locator = MagicMock()
    locator.count = AsyncMock(return_value=2)
    runtime.page.locator.return_value = locator

    result = await runtime._execute_browser_action(
        {"tool": "click", "args": {"selector": ".card-title"}}
    )

    assert result == "error: selector_ambiguous: .card-title (2 matches)"
    metrics = runtime._locator_metrics.as_dict()
    assert metrics["locator_failures"] == 1
    assert metrics["locator_failure_by_reason"] == {"ambiguous": 1}


@pytest.mark.asyncio
async def test_decide_execute_action_includes_retry_feedback():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})
    runtime.remember_case_feedback(
        "CASE-1",
        "error: action_blocked:browser_chrome_selector_blocked",
    )
    runtime._invoke_json = AsyncMock(return_value=None)

    await runtime._decide_execute_action(
        executable_case(),
        {"url": "https://example.com/dashboard", "title": "Dashboard"},
        1,
    )

    prompt = runtime._invoke_json.await_args.args[0]
    assert "最近失败反馈" in prompt
    assert "browser_chrome_selector_blocked" in prompt


@pytest.mark.asyncio
async def test_decision_prompts_use_shared_tool_contract():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})
    runtime._invoke_json = AsyncMock(return_value=None)

    await runtime._decide_explore_action(
        ExplorationGoal(
            id="GOAL-1",
            goal="查看数据看板",
            assertion_refs=["ASSERT-1"],
            expected_evidence=["数据看板"],
            stop_condition="看到标题",
            priority="medium",
        ),
        {
            "url": "https://example.com/dashboard",
            "title": "Dashboard",
            "headings": ["数据看板"],
            "interactive_elements": [
                {
                    "id": "#1",
                    "type": "button",
                    "role": "button",
                    "label": "查看详情",
                    "value": "sensitive-value-must-not-leak",
                    "enabled": True,
                }
            ],
        },
        1,
    )
    explore_prompt = runtime._invoke_json.await_args.args[0]

    await runtime._decide_execute_action(
        executable_case(),
        {"url": "https://example.com/dashboard", "title": "Dashboard"},
        1,
    )
    execute_prompt = runtime._invoke_json.await_args.args[0]

    assert format_tool_prompt_line(EXPLORATION_ACTION_TOOLS) in explore_prompt
    assert "当前页面语义" in explore_prompt
    assert '"id": "#1"' in explore_prompt
    assert "查看详情" in explore_prompt
    assert "sensitive-value-must-not-leak" not in explore_prompt
    assert "不得猜测不存在的 selector" in explore_prompt
    assert format_tool_prompt_line(EXECUTION_ACTION_TOOLS) in execute_prompt
    assert "input_text" not in explore_prompt
    assert "mark_task_complete" not in execute_prompt


@pytest.mark.asyncio
async def test_execute_browser_action_blocks_unsupported_tool():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})

    result = await runtime._execute_browser_action(
        {"tool": "hover", "args": {"selector": "#1"}}
    )

    assert result == "error: action_blocked:unsupported_tool"


@pytest.mark.asyncio
async def test_execute_browser_action_blocks_select_without_selector():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})

    result = await runtime._execute_browser_action(
        {"tool": "select_option", "args": {"value": "all"}}
    )

    assert result == "error: action_blocked:missing_selector"


@pytest.mark.asyncio
async def test_execute_browser_action_handles_task_marker_tools():
    runtime = Runtime({"task_id": "1", "target_url": "https://example.com"})

    complete = await runtime._execute_browser_action(
        {"tool": "mark_task_complete", "args": {"summary": "证据已满足"}}
    )
    failed = await runtime._execute_browser_action(
        {"tool": "mark_task_failed", "args": {"reason": "证据不足"}}
    )

    assert complete == "completed: 证据已满足"
    assert failed == "failed: 证据不足"


@pytest.mark.asyncio
async def test_runtime_session_timeout_remembers_case_feedback(monkeypatch):
    monkeypatch.setenv("MAX_TEST_CASE_RETRIES", "0")
    monkeypatch.setenv("MAX_CASE_ATTEMPT_SECONDS", "0.01")
    session = RuntimeSession(
        {"task_id": "1", "target_url": "https://example.com"}
    )
    session.runtime.remember_case_feedback = MagicMock()
    session.runtime.clear_case_feedback = MagicMock()
    session.runtime._record_step = AsyncMock()

    async def never_finishes(_case):
        await asyncio.sleep(1)

    session.runtime._execute_single_case = never_finishes

    with patch(
        "core.runtime_session.upsert_case_result",
        new_callable=AsyncMock,
    ):
        await session.execute("RUN-1", [executable_case()])

    session.runtime.remember_case_feedback.assert_called_once_with(
        "CASE-1",
        "case_attempt_timeout: 0.01s",
    )
    session.runtime.clear_case_feedback.assert_called_once_with("CASE-1")
