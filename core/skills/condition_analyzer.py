"""Generate TestCondition assets from assertions and live exploration evidence."""

from __future__ import annotations

import asyncio
import os

from pydantic import BaseModel, Field

from core.diag_logger import get_diag_auto
from core.interfaces import (
    CoverageBlueprint,
    RequirementAssertion,
    SystemMapEvid,
    TestCondition,
)
from core.llm_client import get_last_raw, safe_structured_invoke


class ConditionResult(BaseModel):
    conditions: list[TestCondition] = Field(description="生成的测试条件列表")


_STANDARD_TALENT_LABELS = [
    "明星人才",
    "明日之星",
    "核心人才",
    "有潜力",
    "关键资源",
    "高专业度者",
    "业绩不佳者",
    "稳定贡献者",
    "关注",
]
_STANDARD_TALENT_LABELS_TEXT = "、".join(_STANDARD_TALENT_LABELS)


def _is_review_blocked(assertion: RequirementAssertion) -> bool:
    return (
        assertion.risk_level == "high"
        and assertion.review_status == "auto_generated"
        and assertion.assertion_type in {"security", "data_rule"}
    )


def _map_assertion_type_to_condition_type(assertion_type: str) -> str:
    return {
        "functional": "functional",
        "validation": "validation",
        "security": "risk_case",
        "performance": "risk_case",
        "compatibility": "risk_case",
        "data_rule": "data_rule",
        "state_transition": "state_transition",
        "error_handling": "error_handling",
    }.get(assertion_type, "functional")


def _looks_read_only_assertion(assertion_text: str) -> bool:
    text = assertion_text.lower()
    keywords = (
        "只读",
        "仅展示",
        "不可编辑",
        "不可在线编辑",
        "不能编辑",
        "禁止编辑",
        "只展示",
        "只查看",
        "禁用",
        "readonly",
        "read-only",
        "disabled",
    )
    return any(keyword in text for keyword in keywords)


def _inherit_trace_values(
    linked_conditions: list[TestCondition],
    attr_name: str,
) -> list[str]:
    values: list[str] = []
    for condition in linked_conditions:
        for value in getattr(condition, attr_name, []):
            if value and value not in values:
                values.append(value)
    return values


def _requires_standard_talent_label_guard(assertion: RequirementAssertion) -> bool:
    text = assertion.assertion_text
    return (
        "人才标签分布" in text
        and "12-九宫格定位" in text
        and "标准人才标签" in text
    )


def _normalize_standard_talent_label_condition(
    condition: TestCondition,
) -> TestCondition:
    trigger = condition.trigger or "页面加载完成后，查看“人才标签分布”模块。"
    return condition.model_copy(
        update={
            "statement": (
                "验证数据看板“人才标签分布”图表中展示的所有标签均属于 "
                "12-九宫格定位模块定义的九大标准人才标签。"
            ),
            "trigger": trigger,
            "oracle": (
                "图表仅包含以下九大标准人才标签："
                f"{_STANDARD_TALENT_LABELS_TEXT}；不存在非标准或自定义标签。"
            ),
            "oracle_type": "ui_state",
            "measurability": "measurable",
        }
    )


def _normalize_read_only_display_condition(
    condition: TestCondition,
    assertion: RequirementAssertion,
) -> TestCondition:
    trigger = (
        condition.trigger
        or "打开对应页面并观察统计展示区域，不执行编辑型业务操作。"
    )
    return condition.model_copy(
        update={
            "statement": (
                f"{assertion.assertion_text}，验证业务数据区域仅展示统计结果，"
                "不提供新增、编辑、删除、保存、提交、修改等业务写入入口；"
                "导航、筛选、角色切换等只改变视图范围的控件不视为违规。"
            ),
            "trigger": trigger,
            "oracle": (
                "页面可以包含导航、筛选、视图切换或角色切换等非写入控件；"
                "不得出现用于修改业务数据的输入框，或新增、编辑、删除、保存、"
                "提交、修改、校准、导入等业务写入动作。"
            ),
            "oracle_type": "ui_state",
            "measurability": "measurable",
        }
    )


def _normalize_conditions(
    assertions: list[RequirementAssertion],
    conditions: list[TestCondition],
) -> list[TestCondition]:
    assertions_by_id = {assertion.id: assertion for assertion in assertions}
    normalized: list[TestCondition] = []
    for condition in conditions:
        assertion = assertions_by_id.get(condition.assertion_ref)
        if (
            assertion is not None
            and condition.branch_type == "positive"
            and _requires_standard_talent_label_guard(assertion)
        ):
            normalized.append(
                _normalize_standard_talent_label_condition(condition)
            )
            continue
        if (
            assertion is not None
            and condition.branch_type == "positive"
            and _looks_read_only_assertion(assertion.assertion_text)
        ):
            normalized.append(
                _normalize_read_only_display_condition(condition, assertion)
            )
            continue
        normalized.append(condition)
    return normalized


def _build_positive_condition(
    assertion: RequirementAssertion,
    linked_conditions: list[TestCondition],
) -> TestCondition:
    is_read_only = _looks_read_only_assertion(assertion.assertion_text)
    condition_type = _map_assertion_type_to_condition_type(assertion.assertion_type)
    statement = (
        f"{assertion.assertion_text}，页面保持只读展示且不暴露业务写入入口；导航、筛选或视图切换控件不视为违规"
        if is_read_only
        else assertion.assertion_text
    )
    trigger = (
        "打开对应页面并观察相关展示区域，不执行编辑型操作"
        if is_read_only
        else "满足业务前置条件后触发对应操作并观察结果"
    )
    oracle = (
        "相关内容以只读方式展示；允许导航、筛选、视图切换等非写入控件，"
        "但不得出现可编辑业务输入、保存、提交、修改、新增或删除动作"
        if is_read_only
        else assertion.assertion_text
    )
    oracle_type = "ui_state" if is_read_only else "business_rule"
    return TestCondition(
        id=f"COND-BACKFILL-{assertion.id}",
        assertion_ref=assertion.id,
        condition_type=condition_type,
        statement=statement,
        precondition="目标页面可访问且页面已完成加载",
        trigger=trigger,
        oracle=oracle,
        oracle_type=oracle_type,
        risk_level=assertion.risk_level,
        measurability="measurable" if oracle_type == "ui_state" else "partially_measurable",
        source_references=assertion.source_references,
        module_ids=_inherit_trace_values(linked_conditions, "module_ids"),
        business_flow_ids=_inherit_trace_values(linked_conditions, "business_flow_ids"),
        dependency_ids=_inherit_trace_values(linked_conditions, "dependency_ids"),
        branch_type="positive",
    )


def _ensure_positive_conditions(
    assertions: list[RequirementAssertion],
    conditions: list[TestCondition],
) -> list[TestCondition]:
    by_assertion: dict[str, list[TestCondition]] = {}
    for condition in conditions:
        by_assertion.setdefault(condition.assertion_ref, []).append(condition)

    completed = list(conditions)
    for assertion in assertions:
        linked_conditions = by_assertion.get(assertion.id, [])
        if assertion.review_status == "rejected" or _is_review_blocked(assertion):
            continue
        if any(condition.branch_type == "positive" for condition in linked_conditions):
            continue
        completed.append(_build_positive_condition(assertion, linked_conditions))
    return completed


def _risk_rank(risk_level: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(risk_level, 3)


def _ensure_core_flow_e2e_conditions(
    assertions: list[RequirementAssertion],
    conditions: list[TestCondition],
    blueprint: CoverageBlueprint | None,
) -> list[TestCondition]:
    if blueprint is None or not blueprint.business_flows:
        return conditions

    assertions_by_id = {assertion.id: assertion for assertion in assertions}
    completed = list(conditions)
    for flow in blueprint.business_flows:
        if not flow.is_core:
            continue
        if any(
            condition.branch_type == "e2e"
            and flow.id in condition.business_flow_ids
            for condition in completed
        ):
            continue

        flow_conditions = [
            condition
            for condition in completed
            if flow.id in condition.business_flow_ids
            and condition.branch_type == "positive"
            and condition.measurability != "human_review"
        ]
        flow_conditions.sort(
            key=lambda condition: (
                0 if condition.assertion_ref in flow.assertion_ids else 1,
                _risk_rank(condition.risk_level),
            )
        )

        if flow_conditions:
            base = flow_conditions[0]
            source_references = base.source_references
            module_ids = list(dict.fromkeys([*flow.module_ids, *base.module_ids]))
            dependency_ids = base.dependency_ids
            assertion_ref = base.assertion_ref
            risk_level = base.risk_level
            oracle_type = base.oracle_type
            condition_type = base.condition_type
            base_statement = base.statement
            base_precondition = base.precondition
            base_oracle = base.oracle
        else:
            assertion = next(
                (
                    assertions_by_id[assertion_id]
                    for assertion_id in flow.assertion_ids
                    if assertion_id in assertions_by_id
                ),
                assertions[0] if assertions else None,
            )
            if assertion is None:
                continue
            source_references = assertion.source_references
            module_ids = list(flow.module_ids)
            dependency_ids = []
            assertion_ref = assertion.id
            risk_level = assertion.risk_level
            oracle_type = "ui_state"
            condition_type = _map_assertion_type_to_condition_type(
                assertion.assertion_type
            )
            base_statement = assertion.assertion_text
            base_precondition = "目标页面可访问且页面已完成加载"
            base_oracle = assertion.assertion_text

        completed.append(
            TestCondition(
                id=f"COND-E2E-{flow.id}",
                assertion_ref=assertion_ref,
                condition_type=condition_type,
                statement=(
                    f"端到端验证核心业务流程“{flow.name}”：{base_statement}"
                ),
                precondition=base_precondition or "目标页面可访问且页面已完成加载",
                trigger=(
                    f"从目标入口进入并完成“{flow.name}”的主要查看或切换路径，"
                    "观察最终页面状态。"
                ),
                oracle=flow.expected_outcome or base_oracle or base_statement,
                oracle_type=oracle_type,
                risk_level=risk_level,
                measurability="measurable",
                source_references=source_references,
                module_ids=module_ids,
                business_flow_ids=[flow.id],
                dependency_ids=dependency_ids,
                branch_type="e2e",
            )
        )
    return completed


async def analyze_conditions(
    assertions: list[RequirementAssertion],
    system_map: SystemMapEvid | None = None,
    blueprint: CoverageBlueprint | None = None,
) -> list[TestCondition]:
    """Generate TestCondition objects from assertions."""
    if not assertions:
        return []

    batch_size = max(1, int(os.getenv("L2_CONDITION_BATCH_SIZE", "20")))
    concurrency = max(1, int(os.getenv("L2_DESIGN_MAX_CONCURRENCY", "3")))
    semaphore = asyncio.Semaphore(concurrency)

    async def analyze_batch(batch: list[RequirementAssertion]) -> list[TestCondition]:
        async with semaphore:
            return await _analyze_condition_batch(batch, system_map, blueprint)

    batches = [
        assertions[index:index + batch_size]
        for index in range(0, len(assertions), batch_size)
    ]
    results = await asyncio.gather(*(analyze_batch(batch) for batch in batches))
    if any(not result for result in results):
        raise RuntimeError("condition_analysis_batch_failed")
    conditions = [condition for result in results for condition in result]
    conditions = _normalize_conditions(assertions, conditions)
    conditions = _ensure_positive_conditions(assertions, conditions)
    conditions = _ensure_core_flow_e2e_conditions(
        assertions,
        conditions,
        blueprint,
    )
    for index, condition in enumerate(conditions, start=1):
        condition.id = f"COND-{index:03d}"
    return conditions


async def _analyze_condition_batch(
    assertions: list[RequirementAssertion],
    system_map: SystemMapEvid | None,
    blueprint: CoverageBlueprint | None,
) -> list[TestCondition]:
    assertions_json = [assertion.model_dump() for assertion in assertions]
    system_map_json = system_map.model_dump() if system_map else {}
    blueprint_json = blueprint.model_dump() if blueprint else {}

    prompt = f"""<role>
你是一个测试条件分析师。你的唯一职责是把“需要验证什么（断言）”转化为精确的“可测试条件（TestCondition）”。
条件回答的是“在什么场景下，用什么可观察结果来验证这条断言”。
</role>

<context>
你位于新的 L2 测试分析与设计链路中。
- 上游：assertion_deriver 输出的 RequirementAssertion，以及探索阶段带回的 SystemMap 证据
- 下游：technique_selector 根据条件选择设计技术
- 成功标准：每条条件都具备明确的 oracle、可追溯来源、以及正确的 branch_type
</context>

<task>
基于以下断言列表、覆盖蓝图和系统探索证据，为每条断言生成多分支 TestCondition。
每条条件都必须说明：在什么前置状态下，由什么触发，观察什么结果，才能证明该断言成立或暴露风险。
</task>

<rules>
1. 条件不是断言：断言描述“系统必须如何”，条件描述“在什么场景下如何验证”。
2. 一条断言可以拆成多条条件，但每条条件都必须只表达一个清晰场景。
3. oracle_type 必须明确，只能从以下枚举中选择：ui_state、api_response、database、business_rule、network、document、human_review。
4. 无法确定能否自动验证时，measurability 必须诚实标记为 human_review 或 partially_measurable。
5. 如果提供了 SystemMap，请优先利用真实页面、操作、表单、导航证据来细化条件。
6. condition_type 只能是 functional、validation、boundary、permission、state_transition、error_handling、data_rule、risk_case。
7. 每条未被拒绝、未被 review gate 阻塞的断言都至少需要一条 positive 条件；其他 negative、boundary、permission、state、exception、recovery 分支只在来源明确支持时再生成。
8. 每个核心 flow 至少生成一条 e2e 条件，但 e2e 只能写在 branch_type 字段，condition_type 仍必须从上述枚举中选择。
9. module_ids、business_flow_ids、dependency_ids 必须引用覆盖蓝图中存在的 ID。
10. 涉及标准标签、卡片名、字段名、状态名时，必须复用断言中的原词；如果断言没有枚举具体标签，不要自行扩展或改写成另一套名称。
11. “只读”“仅展示”“不可在线编辑”表示不得修改业务数据；不要扩大解释为页面不能存在导航、筛选、视图切换、角色切换等非写入控件。
</rules>

<output_contract>
Return ONLY the following JSON object. No markdown fences. No explanation. No preamble.

{{
  "conditions": [
    {{
      "id": str,
      "assertion_ref": str,
      "condition_type": "functional" | "validation" | "boundary" | "permission" | "state_transition" | "error_handling" | "data_rule" | "risk_case",
      "statement": str,
      "precondition": str,
      "trigger": str,
      "oracle": str,
      "oracle_type": "ui_state" | "api_response" | "database" | "business_rule" | "network" | "document" | "human_review",
      "risk_level": "high" | "medium" | "low",
      "measurability": "measurable" | "partially_measurable" | "human_review",
      "source_references": [str],
      "module_ids": [str],
      "business_flow_ids": [str],
      "dependency_ids": [str],
      "branch_type": "positive" | "negative" | "boundary" | "permission" | "state" | "exception" | "recovery" | "e2e"
    }}
  ]
}}

字段约束：
- id 格式形如 COND-001
- assertion_ref 必须引用存在的断言 ID
- oracle_type 不能为空
- 不要编造未知系统事实
</output_contract>

### 输入: RequirementAssertion 列表（共 {len(assertions)} 条）
```json
{{
  "assertions": {assertions_json}
}}
```

### 系统证据（SystemMap）
```json
{system_map_json}
```

### 覆盖蓝图
```json
{blueprint_json}
```
"""
    result = await safe_structured_invoke(prompt, ConditionResult, model_type="default")
    if result is None or not result.conditions:
        get_diag_auto().dump(
            "03_l2_condition",
            node="N2_condition_analyzer",
            output=[],
            status="empty_fallback",
            raw_content=get_last_raw(),
        )
        return []

    get_diag_auto().dump(
        "03_l2_condition",
        node="N2_condition_analyzer",
        output=result,
        status="ok",
        conditions_count=len(result.conditions),
        raw_content=get_last_raw(),
    )
    return result.conditions
