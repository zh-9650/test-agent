from unittest.mock import AsyncMock, patch

import pytest

from core.interfaces import (
    BusinessFlow,
    CoverageBlueprint,
    RequirementAssertion,
    TestCondition as ConditionModel,
)
from core.llm_client import _coerce_to_pydantic
from core.skills.condition_analyzer import ConditionResult, analyze_conditions


def _assertion(
    *,
    assertion_id: str = "ASSERT-1",
    assertion_text: str = "所有统计数据必须为只读，不允许编辑",
    assertion_type: str = "validation",
    risk_level: str = "medium",
    review_status: str = "auto_generated",
) -> RequirementAssertion:
    return RequirementAssertion(
        id=assertion_id,
        fact_ids=["FACT-1"],
        assertion_text=assertion_text,
        assertion_type=assertion_type,
        risk_level=risk_level,
        review_status=review_status,
        source_references=["FACT-1"],
    )


def _condition(
    *,
    condition_id: str = "COND-900",
    assertion_ref: str = "ASSERT-1",
    condition_type: str = "validation",
    branch_type: str = "negative",
) -> ConditionModel:
    return ConditionModel(
        id=condition_id,
        assertion_ref=assertion_ref,
        condition_type=condition_type,
        statement="尝试寻找可编辑控件并验证不会出现编辑入口",
        precondition="已进入 dashboard 页面",
        trigger="观察统计卡片和表格区域",
        oracle="页面不允许编辑",
        oracle_type="ui_state",
        risk_level="medium",
        measurability="measurable",
        source_references=["FACT-1"],
        module_ids=["MOD-1"],
        business_flow_ids=["FLOW-1"],
        dependency_ids=["DEP-1"],
        branch_type=branch_type,
    )


def test_coerce_normalizes_e2e_condition_type_alias():
    result = _coerce_to_pydantic(
        {
            "conditions": [
                {
                    "id": "COND-901",
                    "assertion_ref": "ASSERT-1",
                    "condition_type": "e2e",
                    "statement": "按业务主路径完成 dashboard 浏览",
                    "precondition": "系统可访问",
                    "trigger": "进入首页后查看看板",
                    "oracle": "主路径正常完成",
                    "oracle_type": "ui_state",
                    "risk_level": "medium",
                    "measurability": "measurable",
                    "source_references": ["FACT-1"],
                    "module_ids": ["MOD-1"],
                    "business_flow_ids": ["FLOW-1"],
                    "dependency_ids": ["DEP-1"],
                }
            ]
        },
        ConditionResult,
    )

    condition = result.conditions[0]
    assert condition.condition_type == "functional"
    assert condition.branch_type == "e2e"


@pytest.mark.asyncio
async def test_analyze_conditions_backfills_positive_for_non_blocked_assertion():
    assertion = _assertion()
    only_negative = _condition()

    with patch(
        "core.skills.condition_analyzer.safe_structured_invoke",
        new=AsyncMock(return_value=ConditionResult(conditions=[only_negative])),
    ):
        result = await analyze_conditions([assertion])

    assert len(result) == 2
    positive = next(condition for condition in result if condition.branch_type == "positive")
    assert positive.assertion_ref == assertion.id
    assert positive.condition_type == "validation"
    assert positive.oracle_type == "ui_state"
    assert "只读展示" in positive.statement
    assert "筛选" in positive.oracle
    assert "业务输入" in positive.oracle
    assert positive.module_ids == ["MOD-1"]
    assert positive.business_flow_ids == ["FLOW-1"]
    assert positive.dependency_ids == ["DEP-1"]


@pytest.mark.asyncio
async def test_analyze_conditions_normalizes_read_only_control_semantics():
    assertion = _assertion(
        assertion_text="数据看板仅展示统计数据，不可在线编辑或操作业务。",
        assertion_type="validation",
    )
    overstrict = ConditionModel(
        id="COND-903",
        assertion_ref=assertion.id,
        condition_type="validation",
        statement="验证页面不包含任何输入框、下拉框、可点击编辑按钮或操作按钮。",
        precondition="已进入 dashboard 页面",
        trigger="查看页面所有控件",
        oracle="页面不存在任何下拉框或操作按钮。",
        oracle_type="ui_state",
        risk_level="medium",
        measurability="measurable",
        source_references=["FACT-1"],
        module_ids=["MOD-1"],
        business_flow_ids=["FLOW-1"],
        dependency_ids=["DEP-1"],
        branch_type="positive",
    )

    with patch(
        "core.skills.condition_analyzer.safe_structured_invoke",
        new=AsyncMock(return_value=ConditionResult(conditions=[overstrict])),
    ):
        result = await analyze_conditions([assertion])

    condition = result[0]
    assert "业务写入入口" in condition.statement
    assert "导航、筛选、角色切换" in condition.statement
    assert "非写入控件" in condition.oracle
    assert "不得出现用于修改业务数据" in condition.oracle


@pytest.mark.asyncio
async def test_analyze_conditions_backfills_core_flow_e2e_condition():
    assertion = _assertion(
        assertion_text="数据看板必须展示核心指标卡片。",
        assertion_type="functional",
    )
    positive = _condition(
        condition_type="functional",
        branch_type="positive",
    )
    positive.business_flow_ids = ["BF-001"]
    blueprint = CoverageBlueprint(
        business_flows=[
            BusinessFlow(
                id="BF-001",
                name="数据看板查看流程",
                module_ids=["MOD-1"],
                assertion_ids=[assertion.id],
                expected_outcome="用户完成看板查看并看到核心指标。",
                is_core=True,
            )
        ]
    )

    with patch(
        "core.skills.condition_analyzer.safe_structured_invoke",
        new=AsyncMock(return_value=ConditionResult(conditions=[positive])),
    ):
        result = await analyze_conditions([assertion], blueprint=blueprint)

    e2e = next(condition for condition in result if condition.branch_type == "e2e")
    assert e2e.business_flow_ids == ["BF-001"]
    assert "端到端验证核心业务流程" in e2e.statement
    assert e2e.oracle == "用户完成看板查看并看到核心指标。"


@pytest.mark.asyncio
async def test_analyze_conditions_skips_positive_backfill_for_review_blocked_assertion():
    assertion = _assertion(
        assertion_text="敏感数据字段必须满足脱敏规则",
        assertion_type="data_rule",
        risk_level="high",
    )
    only_negative = _condition(condition_type="data_rule")

    with patch(
        "core.skills.condition_analyzer.safe_structured_invoke",
        new=AsyncMock(return_value=ConditionResult(conditions=[only_negative])),
    ):
        result = await analyze_conditions([assertion])

    assert len(result) == 1
    assert all(condition.branch_type != "positive" for condition in result)


@pytest.mark.asyncio
async def test_analyze_conditions_normalizes_standard_talent_labels():
    assertion = _assertion(
        assertion_text=(
            "系统在展示人才标签分布时，必须严格按照12-九宫格定位模块定义的"
            "九大标准人才标签进行人数统计。"
        ),
        assertion_type="data_rule",
    )
    drifted = ConditionModel(
        id="COND-902",
        assertion_ref=assertion.id,
        condition_type="data_rule",
        statement="验证人才标签分布图表中所有标签均为标准九大标签。",
        precondition="已进入 dashboard 页面",
        trigger="查看‘人才标签分布’模块",
        oracle=(
            "图表中的标签属于以下九大标准标签之一：明星人才、核心人才、骨干人才、"
            "潜力之星、待观察人才、成熟专才、业绩不佳者、关注人才、其他。"
        ),
        oracle_type="database",
        risk_level="medium",
        measurability="partially_measurable",
        source_references=["FACT-1"],
        module_ids=["MOD-1"],
        business_flow_ids=["FLOW-1"],
        dependency_ids=["DEP-1"],
        branch_type="positive",
    )

    with patch(
        "core.skills.condition_analyzer.safe_structured_invoke",
        new=AsyncMock(return_value=ConditionResult(conditions=[drifted])),
    ):
        result = await analyze_conditions([assertion])

    condition = result[0]
    assert condition.oracle_type == "ui_state"
    assert condition.measurability == "measurable"
    assert "明日之星" in condition.oracle
    assert "关键资源" in condition.oracle
    assert "稳定贡献者" in condition.oracle
    assert "骨干人才" not in condition.oracle
    assert "关注人才" not in condition.oracle
