"""tests/core/test_l2_new_pipeline.py — New L2 Pipeline Mocked Tests.

Tests the new L2 pipeline (RequirementFact → TestAssetPackage) with mocked LLM
calls to verify prompt → schema → inter-node contract without burning tokens.

Usage:
    pytest tests/core/test_l2_new_pipeline.py -v
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from core.interfaces import (
    RequirementFact, RequirementAssertion, TestCondition as ConditionModel,
    TestDesignTechnique as TechniqueModel, CoverageItem, CandidateTestCase,
    CoverageBlueprint,
)
from core.skills.fact_extractor import FactExtractionResult
from core.skills.assertion_deriver import AssertionDerivationResult
from core.skills.condition_analyzer import ConditionResult
from core.skills.technique_selector import TechniqueResult
from core.skills.coverage_analyzer import CoverageResult
from core.skills.case_generator import CaseGenerationResult


SAMPLE_PRD = """
# 采购管理系统

## 功能需求
1. 用户可以通过系统创建采购申请单。
2. 采购金额超过 5000 元需要部门经理审批。
3. 采购金额超过 10000 元需要总监审批。
4. 已审批的采购单可以生成采购订单。
5. 采购订单确认后发送给供应商。
"""


def _make_sample_facts() -> list[RequirementFact]:
    return [
        RequirementFact(
            id="FACT-001", source_type="prd", source_reference="PRD §1",
            quote="用户可以通过系统创建采购申请单",
            subject="用户", action="创建", object="采购申请单",
            confidence=1.0,
        ),
        RequirementFact(
            id="FACT-002", source_type="prd", source_reference="PRD §2",
            quote="采购金额超过 5000 元需要部门经理审批",
            subject="采购申请单", action="需要审批", condition="金额>5000",
            outcome="部门经理审批", confidence=1.0,
        ),
        RequirementFact(
            id="FACT-003", source_type="prd", source_reference="PRD §3",
            quote="采购金额超过 10000 元需要总监审批",
            subject="采购申请单", action="需要审批", condition="金额>10000",
            outcome="总监审批", confidence=1.0,
        ),
    ]


def _make_sample_assertions() -> list[RequirementAssertion]:
    return [
        RequirementAssertion(
            id="ASSERT-001", fact_ids=["FACT-001"],
            assertion_text="用户必须能够创建采购申请单",
            assertion_type="functional", risk_level="high",
        ),
        RequirementAssertion(
            id="ASSERT-002", fact_ids=["FACT-002"],
            assertion_text="金额超过5000元时系统必须触发部门经理审批",
            assertion_type="data_rule", risk_level="high",
        ),
    ]


def _make_sample_conditions() -> list[ConditionModel]:
    return [
        ConditionModel(
            id="COND-001", assertion_ref="ASSERT-001",
            condition_type="functional",
            statement="登录用户在采购页面点击创建申请按钮",
            oracle="系统展示采购申请创建表单",
            oracle_type="ui_state",
        ),
        ConditionModel(
            id="COND-002", assertion_ref="ASSERT-002",
            condition_type="data_rule",
            statement="在采购申请中输入金额6000元并提交",
            precondition="已登录",
            oracle="系统自动流转到部门经理审批",
            oracle_type="business_rule",
            risk_level="high",
        ),
    ]


def _make_sample_techniques() -> list[TechniqueModel]:
    return [
        TechniqueModel(
            id="TECH-COND-001",
            condition_id="COND-001",
            primary_technique="equivalence_partitioning",
            rationale="按操作流程划分等价类",
        ),
        TechniqueModel(
            id="TECH-COND-002",
            condition_id="COND-002",
            primary_technique="boundary_value_analysis",
            supplementary_techniques=["error_guessing"],
            rationale="5000是关键边界值",
        ),
    ]


def _make_sample_covs() -> list[CoverageItem]:
    return [
        CoverageItem(
            id="COV-001", condition_id="COND-001",
            technique_id="COND-001:equivalence_partitioning",
            coverage_dimension="normal",
            goal="验证用户能正常打开创建申请表单",
        ),
        CoverageItem(
            id="COV-002", condition_id="COND-002",
            technique_id="COND-002:boundary_value_analysis",
            coverage_dimension="boundary",
            goal="验证金额刚好超过5000时触发审批",
        ),
    ]


def _make_sample_cases() -> list[CandidateTestCase]:
    return [
        CandidateTestCase(
            id="TC-CAND-001", title="打开采购申请创建表单",
            goal="验证用户能正常打开创建申请表单",
            expected_result="表单正确显示", priority="high",
            trace_references=["COV-001"],
            execution_hint="可能需要先登录",
        ),
        CandidateTestCase(
            id="TC-CAND-002", title="金额超过5000触发审批",
            goal="验证金额6000时触发部门经理审批",
            preconditions=[
                {
                    "type": "account_role",
                    "description": "已登录",
                    "required_role": "purchaser",
                    "satisfiable_by_agent": True,
                    "failure_policy": "incomplete",
                },
                {
                    "type": "business_state",
                    "description": "有采购申请权限",
                    "satisfiable_by_agent": True,
                    "failure_policy": "failed",
                },
            ],
            required_roles=["purchaser"],
            input_data=[
                {
                    "name": "金额",
                    "value": "6000",
                    "source": "fixture",
                    "sensitivity": "public",
                    "generation_strategy": "boundary",
                    "boundary_category": "above_threshold",
                }
            ],
            expected_result="系统提示需要部门经理审批",
            priority="high",
            trace_references=["COV-002"],
        ),
    ]


# ---------------------------------------------------------------------------
# Mocked pipeline tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fact_extractor_mocked():
    """Mocked: extract_facts returns valid RequirementFact list."""
    mock_facts = _make_sample_facts()

    with patch("core.skills.fact_extractor.safe_structured_invoke", new=AsyncMock()) as mock:
        mock.return_value = FactExtractionResult(facts=mock_facts)

        from core.skills.fact_extractor import extract_facts
        result = await extract_facts(prd_content=SAMPLE_PRD)

        assert len(result) == 3
        assert all(isinstance(f, RequirementFact) for f in result)
        assert result[0].id == "FACT-001"
        assert result[1].source_type == "prd"


@pytest.mark.asyncio
async def test_fact_extractor_empty_fallback():
    """When LLM returns None, fact extractor returns empty list."""
    with patch("core.skills.fact_extractor.safe_structured_invoke", new=AsyncMock()) as mock:
        mock.return_value = None

        from core.skills.fact_extractor import extract_facts
        result = await extract_facts(prd_content=SAMPLE_PRD)
        assert result == []


@pytest.mark.asyncio
async def test_fact_extractor_chunks_long_markdown_and_normalizes_ids(monkeypatch):
    monkeypatch.setenv("L1_CHUNK_MAX_CHARS", "1000")
    long_prd = "\n\n".join([
        "# 模块一\n" + ("需求一内容。" * 140),
        "# 模块二\n" + ("需求二内容。" * 140),
    ])
    first = RequirementFact(
        id="FACT-001",
        source_type="prd",
        source_reference="模块一",
        quote="需求一内容",
        subject="模块一",
        action="展示",
        object="内容",
        confidence=0.9,
        status="confirmed",
    )
    second = RequirementFact(
        id="FACT-001",
        source_type="prd",
        source_reference="模块二",
        quote="需求二内容",
        subject="模块二",
        action="展示",
        object="内容",
        confidence=0.9,
        status="confirmed",
    )

    with patch(
        "core.skills.fact_extractor.safe_structured_invoke",
        new=AsyncMock(side_effect=[
            FactExtractionResult(facts=[first]),
            FactExtractionResult(facts=[second]),
        ]),
    ) as mock:
        from core.skills.fact_extractor import extract_facts
        result = await extract_facts(prd_content=long_prd)

    assert mock.await_count == 2
    assert [fact.id for fact in result] == ["FACT-001", "FACT-002"]
    assert result[0].source_reference.startswith("PRD > 模块一")
    assert result[1].source_reference.startswith("PRD > 模块二")


@pytest.mark.asyncio
async def test_fact_extractor_scopes_chunks_by_focus(monkeypatch):
    monkeypatch.setenv("L1_CHUNK_MAX_CHARS", "1000")
    long_prd = "\n\n".join([
        "# 15-数据看板\n" + ("看板指标内容。 " * 160),
        "# 01-开发者配置中心\n" + ("配置中心内容。 " * 160),
    ])
    dashboard_fact = RequirementFact(
        id="FACT-001",
        source_type="prd",
        source_reference="PRD > 15-数据看板",
        quote="看板指标内容",
        subject="系统",
        action="展示",
        object="数据看板",
        confidence=0.9,
        status="confirmed",
    )

    with patch(
        "core.skills.fact_extractor.safe_structured_invoke",
        new=AsyncMock(return_value=FactExtractionResult(facts=[dashboard_fact])),
    ) as mock:
        from core.skills.fact_extractor import extract_facts

        result = await extract_facts(
            prd_content=long_prd,
            focus_areas="dashboard",
            target_url="http://localhost:5000/dashboard",
        )

    assert mock.await_count == 2
    assert [fact.id for fact in result] == ["FACT-001"]


@pytest.mark.asyncio
async def test_assertion_deriver_mocked():
    """Mocked: derive_assertions returns valid RequirementAssertion list."""
    mock_assertions = _make_sample_assertions()
    facts = _make_sample_facts()

    with patch("core.skills.assertion_deriver.safe_structured_invoke", new=AsyncMock()) as mock:
        mock.return_value = AssertionDerivationResult(assertions=mock_assertions)

        from core.skills.assertion_deriver import derive_assertions
        result = await derive_assertions(facts)

        assert len(result) == 2
        assert all(isinstance(a, RequirementAssertion) for a in result)
        assert result[0].assertion_type == "functional"
        assert result[0].risk_level == "high"


@pytest.mark.asyncio
async def test_assertion_deriver_batches_and_normalizes_references(monkeypatch):
    monkeypatch.setenv("L1_ASSERTION_BATCH_SIZE", "5")
    facts = [
        RequirementFact(
            id=f"FACT-{index:03d}",
            source_type="prd",
            source_reference="PRD",
            quote=f"原文 {index}",
            subject=f"主体 {index}",
            action="展示",
            object="内容",
            confidence=0.9,
            status="confirmed",
        )
        for index in range(1, 7)
    ]
    first = RequirementAssertion(
        id="ASSERT-001",
        fact_ids=["FACT-001", "FACT-NOT-FOUND"],
        assertion_text="系统必须展示第一批内容",
        assertion_type="functional",
        risk_level="medium",
        review_status="auto_generated",
    )
    second = RequirementAssertion(
        id="ASSERT-001",
        fact_ids=["FACT-006"],
        assertion_text="系统必须展示第二批内容",
        assertion_type="functional",
        risk_level="medium",
        review_status="auto_generated",
    )

    with patch(
        "core.skills.assertion_deriver.safe_structured_invoke",
        new=AsyncMock(side_effect=[
            AssertionDerivationResult(assertions=[first]),
            AssertionDerivationResult(assertions=[second]),
        ]),
    ) as mock:
        from core.skills.assertion_deriver import derive_assertions
        result = await derive_assertions(facts)

    assert mock.await_count == 2
    assert [assertion.id for assertion in result] == ["ASSERT-001", "ASSERT-002"]
    assert result[0].fact_ids == ["FACT-001"]
    assert result[1].fact_ids == ["FACT-006"]


@pytest.mark.asyncio
async def test_assertion_deriver_empty_facts():
    """Empty input → empty output."""
    from core.skills.assertion_deriver import derive_assertions
    result = await derive_assertions([])
    assert result == []


@pytest.mark.asyncio
async def test_generate_exploration_goals_respects_focus_areas():
    dashboard_fact = RequirementFact(
        id="FACT-001",
        source_type="prd",
        source_reference="PRD > 15-数据看板",
        quote="系统展示数据看板指标",
        subject="系统",
        action="展示",
        object="数据看板指标",
        confidence=0.9,
        status="confirmed",
    )
    admin_fact = RequirementFact(
        id="FACT-002",
        source_type="prd",
        source_reference="PRD > 01-开发者配置中心",
        quote="系统展示7个核心业务Tab",
        subject="系统",
        action="展示",
        object="7个核心业务Tab",
        confidence=0.9,
        status="confirmed",
    )
    dashboard_assertion = RequirementAssertion(
        id="ASSERT-001",
        fact_ids=["FACT-001"],
        assertion_text="系统必须展示数据看板核心指标卡",
        assertion_type="functional",
        risk_level="medium",
        source_references=["PRD > 15-数据看板"],
    )
    admin_assertion = RequirementAssertion(
        id="ASSERT-002",
        fact_ids=["FACT-002"],
        assertion_text="系统必须展示开发者配置中心的7个业务Tab",
        assertion_type="functional",
        risk_level="medium",
        source_references=["PRD > 01-开发者配置中心"],
    )

    with patch(
        "core.skills.fact_extractor.extract_facts",
        new=AsyncMock(return_value=[dashboard_fact, admin_fact]),
    ), patch(
        "core.skills.assertion_deriver.derive_assertions",
        new=AsyncMock(return_value=[dashboard_assertion, admin_assertion]),
    ):
        from core.skills.l2_pipeline import generate_exploration_goals

        goals, review_items, facts, assertions = await generate_exploration_goals(
            prd_content=SAMPLE_PRD,
            focus_areas="dashboard",
            target_url="http://localhost:5000/dashboard",
        )

    assert review_items == []
    assert [fact.id for fact in facts] == ["FACT-001"]
    assert [assertion.id for assertion in assertions] == ["ASSERT-001"]
    assert len(goals) == 1
    assert goals[0].assertion_refs == ["ASSERT-001"]


@pytest.mark.asyncio
async def test_run_l2_pipeline_scopes_downstream_assets_by_focus():
    dashboard_fact = RequirementFact(
        id="FACT-001",
        source_type="prd",
        source_reference="PRD > 15-数据看板",
        quote="系统展示数据看板指标",
        subject="系统",
        action="展示",
        object="数据看板指标",
        confidence=0.9,
        status="confirmed",
    )
    admin_fact = RequirementFact(
        id="FACT-002",
        source_type="prd",
        source_reference="PRD > 01-开发者配置中心",
        quote="系统展示7个核心业务Tab",
        subject="系统",
        action="展示",
        object="7个核心业务Tab",
        confidence=0.9,
        status="confirmed",
    )
    dashboard_assertion = RequirementAssertion(
        id="ASSERT-001",
        fact_ids=["FACT-001"],
        assertion_text="系统必须展示数据看板核心指标卡",
        assertion_type="functional",
        risk_level="medium",
        source_references=["PRD > 15-数据看板"],
    )
    admin_assertion = RequirementAssertion(
        id="ASSERT-002",
        fact_ids=["FACT-002"],
        assertion_text="系统必须展示开发者配置中心的7个业务Tab",
        assertion_type="functional",
        risk_level="medium",
        source_references=["PRD > 01-开发者配置中心"],
    )

    with patch(
        "core.skills.fact_extractor.extract_facts",
        new=AsyncMock(return_value=[dashboard_fact, admin_fact]),
    ), patch(
        "core.skills.assertion_deriver.derive_assertions",
        new=AsyncMock(return_value=[dashboard_assertion, admin_assertion]),
    ), patch(
        "core.skills.coverage_planner.plan_coverage_blueprint",
        new=AsyncMock(return_value=CoverageBlueprint()),
    ), patch(
        "core.skills.condition_analyzer.analyze_conditions",
        new=AsyncMock(return_value=[]),
    ):
        from core.skills.l2_pipeline import run_l2_pipeline

        package = await run_l2_pipeline(
            prd_content=SAMPLE_PRD,
            focus_areas="dashboard",
            target_url="http://localhost:5000/dashboard",
        )

    assert [fact.id for fact in package.facts] == ["FACT-001"]
    assert [assertion.id for assertion in package.assertions] == ["ASSERT-001"]
    assert len(package.exploration_goals) == 1
    assert package.exploration_goals[0].assertion_refs == ["ASSERT-001"]


@pytest.mark.asyncio
async def test_condition_analyzer_mocked():
    """Mocked: analyze_conditions returns valid TestCondition list."""
    assertions = _make_sample_assertions()
    mock_conditions = _make_sample_conditions()

    with patch("core.skills.condition_analyzer.safe_structured_invoke", new=AsyncMock()) as mock:
        mock.return_value = ConditionResult(conditions=mock_conditions)

        from core.skills.condition_analyzer import analyze_conditions
        result = await analyze_conditions(assertions)

        assert len(result) == 2
        assert all(isinstance(c, ConditionModel) for c in result)
        assert result[0].oracle_type == "ui_state"


@pytest.mark.asyncio
async def test_technique_selector_mocked():
    """Mocked: select_techniques returns valid TestDesignTechnique list."""
    conditions = _make_sample_conditions()
    mock_techniques = _make_sample_techniques()

    with patch("core.skills.technique_selector.safe_structured_invoke", new=AsyncMock()) as mock:
        mock.return_value = TechniqueResult(techniques=mock_techniques)

        from core.skills.technique_selector import select_techniques
        result = await select_techniques(conditions)

        assert len(result) == 2
        assert result[0].primary_technique == "equivalence_partitioning"
        assert result[0].rationale


@pytest.mark.asyncio
async def test_technique_selector_has_deterministic_empty_fallback():
    from core.skills.technique_selector import select_techniques

    conditions = _make_sample_conditions()
    with patch(
        "core.skills.technique_selector.safe_structured_invoke",
        new=AsyncMock(return_value=None),
    ):
        result = await select_techniques(conditions)

    assert len(result) == len(conditions)
    assert {item.condition_id for item in result} == {
        condition.id for condition in conditions
    }


@pytest.mark.asyncio
async def test_coverage_analyzer_mocked():
    """Mocked: analyze_coverage returns valid CoverageItem list."""
    conditions = _make_sample_conditions()
    techniques = _make_sample_techniques()
    mock_covs = _make_sample_covs()

    with patch("core.skills.coverage_analyzer.safe_structured_invoke", new=AsyncMock()) as mock:
        mock.return_value = CoverageResult(items=mock_covs)

        from core.skills.coverage_analyzer import analyze_coverage
        result = await analyze_coverage(conditions, techniques)

        assert len(result) == 2
        assert result[0].coverage_dimension == "normal"


@pytest.mark.asyncio
async def test_coverage_analyzer_has_deterministic_empty_fallback():
    from core.skills.coverage_analyzer import analyze_coverage
    from core.skills.technique_selector import fallback_techniques

    conditions = _make_sample_conditions()
    techniques = fallback_techniques(conditions)
    with patch(
        "core.skills.coverage_analyzer.safe_structured_invoke",
        new=AsyncMock(return_value=None),
    ):
        result = await analyze_coverage(conditions, techniques)

    assert len(result) == len(conditions)
    assert {item.condition_id for item in result} == {
        condition.id for condition in conditions
    }


def test_coverage_normalization_preserves_distinct_variants():
    from core.skills.coverage_analyzer import normalize_coverage

    condition = _make_sample_conditions()[0].model_copy(
        update={"risk_level": "medium"}
    )
    technique = _make_sample_techniques()[0].model_copy(
        update={"condition_id": condition.id}
    )
    items = [
        CoverageItem(
            id=f"COV-{index}",
            condition_id=condition.id,
            technique_id=technique.id,
            coverage_dimension=dimension,
            goal=goal,
            risk_level="medium",
        )
        for index, (dimension, goal) in enumerate([
            ("exception", "模拟网络错误"),
            ("normal", "验证正常导航"),
            ("boundary", "快速连续点击"),
        ], start=1)
    ]

    result = normalize_coverage([condition], [technique], items)

    assert len(result) == 3
    assert {item.coverage_dimension for item in result} == {
        "exception", "normal", "boundary"
    }


@pytest.mark.asyncio
async def test_case_generator_mocked():
    """Mocked: generate_cases returns valid CandidateTestCase list."""
    covs = _make_sample_covs()
    mock_cases = _make_sample_cases()

    with patch("core.skills.case_generator.safe_structured_invoke", new=AsyncMock()) as mock:
        mock.return_value = CaseGenerationResult(cases=mock_cases)

        from core.skills.case_generator import generate_cases
        result = await generate_cases(covs)

        assert len(result) == 2
        assert result[0].priority == "high"
        assert result[0].trace_references == ["COV-001"]


@pytest.mark.asyncio
async def test_l2_pipeline_orchestrator_mocked():
    """Mocked: full L2 pipeline runs end-to-end with all nodes mocked."""
    mock_facts = _make_sample_facts()
    mock_assertions = _make_sample_assertions()
    mock_conditions = _make_sample_conditions()
    mock_techniques = _make_sample_techniques()
    mock_covs = _make_sample_covs()
    mock_cases = _make_sample_cases()

    # 新 review gate 规则: 仅 security/data_rule 类型的 high+auto_generated 被拦截
    # ASSERT-001 (functional/high) → 直接通过
    # ASSERT-002 (data_rule/high) → 设置为 human_confirmed 以通过门禁
    mock_assertions[1].review_status = "human_confirmed"

    with patch("core.skills.fact_extractor.safe_structured_invoke", new=AsyncMock()) as f_mock, \
         patch("core.skills.assertion_deriver.safe_structured_invoke", new=AsyncMock()) as a_mock, \
         patch("core.skills.condition_analyzer.safe_structured_invoke", new=AsyncMock()) as c_mock, \
         patch("core.skills.technique_selector.safe_structured_invoke", new=AsyncMock()) as t_mock, \
         patch("core.skills.coverage_analyzer.safe_structured_invoke", new=AsyncMock()) as cv_mock, \
         patch("core.skills.case_generator.safe_structured_invoke", new=AsyncMock()) as cs_mock:

        f_mock.return_value = FactExtractionResult(facts=mock_facts)
        a_mock.return_value = AssertionDerivationResult(assertions=mock_assertions)
        c_mock.return_value = ConditionResult(conditions=mock_conditions)
        t_mock.return_value = TechniqueResult(techniques=mock_techniques)
        cv_mock.return_value = CoverageResult(items=mock_covs)
        cs_mock.return_value = CaseGenerationResult(cases=mock_cases)

        from core.skills.l2_pipeline import run_l2_pipeline
        package = await run_l2_pipeline(prd_content=SAMPLE_PRD)

        assert len(package.facts) == 3
        assert len(package.assertions) == 2
        # 新规则: functional/high 直接通过, data_rule/high+human_confirmed 也通过
        # → manual_review_items 为 0
        assert len(package.manual_review_items) == 0
        # 两条断言都进入下游分析
        assert len(package.test_conditions) >= 1
        assert len(package.test_design_techniques) >= 1
        assert len(package.coverage_items) >= 1
        assert len(package.candidate_cases) >= 1
        assert package.traceability_matrix is not None
        assert len(package.traceability_matrix.rows) == 3  # 3 facts


@pytest.mark.asyncio
async def test_l2_pipeline_empty_input():
    """Empty input should produce empty package."""
    from core.skills.l2_pipeline import run_l2_pipeline
    package = await run_l2_pipeline()
    assert len(package.facts) == 0
    assert package.traceability_matrix is None


# ---------------------------------------------------------------------------
# Data-only (no LLM) skill tests
# ---------------------------------------------------------------------------

from core.skills.asset_packager import assemble_package


def test_assemble_package_detects_conflicts():
    """Package auto-detects conflicted facts."""
    facts = [
        RequirementFact(
            id="FACT-001", source_type="prd", source_reference="PRD",
            quote="金额>5000需经理审批",
            subject="采购单", action="审批", confidence=1.0,
            status="conflicted",
            conflict_references=["FACT-002"],
        ),
        RequirementFact(
            id="FACT-002", source_type="swagger", source_reference="swagger",
            quote="金额>5000需总监审批",
            subject="采购单", action="审批", confidence=0.6,
        ),
    ]
    package = assemble_package(facts=facts, assertions=[])
    assert len(package.conflicts) > 0
    assert "FACT-001" in package.conflicts[0]


def test_assemble_package_manual_review():
    """High-risk auto_generated assertions become manual_review_items."""
    assertions = [
        RequirementAssertion(
            id="ASSERT-001", fact_ids=["FACT-001"],
            assertion_text="高风险的审批逻辑",
            assertion_type="functional", risk_level="high",
        ),
        RequirementAssertion(
            id="ASSERT-002", fact_ids=["FACT-002"],
            assertion_text="低风险的展示逻辑",
            assertion_type="functional", risk_level="low",
            review_status="human_confirmed",
        ),
    ]
    package = assemble_package(facts=[], assertions=assertions)
    assert len(package.manual_review_items) == 0  # assemble_package doesn't auto detect from assertions


def test_build_traceability_invariance():
    """Rebuilding with same inputs produces same output."""
    from core.skills.traceability_builder import build_traceability

    facts = _make_sample_facts()
    assertions = _make_sample_assertions()
    conditions = _make_sample_conditions()
    techniques = _make_sample_techniques()
    covs = _make_sample_covs()
    cases = _make_sample_cases()

    m1 = build_traceability(facts, assertions, conditions, techniques, covs, cases)
    m2 = build_traceability(facts, assertions, conditions, techniques, covs, cases)
    assert len(m1.rows) == len(m2.rows)
    for r1, r2 in zip(m1.rows, m2.rows):
        assert r1.status == r2.status
        assert r1.candidate_case_ids == r2.candidate_case_ids


# ---------------------------------------------------------------------------
# Review Gate & Goal Priority tests
# ---------------------------------------------------------------------------

from core.skills.l2_pipeline import _split_by_review_gate, _goals_from_confirmed_assertions


def test_review_gate_blocks_security_and_data_rule():
    """Review gate should block security/data_rule high+auto_generated, but pass functional."""
    assertions = [
        RequirementAssertion(
            id="ASSERT-SEC", fact_ids=["FACT-001"],
            assertion_text="系统必须实施角色权限隔离",
            assertion_type="security", risk_level="high",
            review_status="auto_generated",
        ),
        RequirementAssertion(
            id="ASSERT-DR", fact_ids=["FACT-001"],
            assertion_text="绩效权重之和必须等于100%",
            assertion_type="data_rule", risk_level="high",
            review_status="auto_generated",
        ),
        RequirementAssertion(
            id="ASSERT-FUNC", fact_ids=["FACT-001"],
            assertion_text="用户能够创建采购申请",
            assertion_type="functional", risk_level="high",
            review_status="auto_generated",
        ),
        RequirementAssertion(
            id="ASSERT-VAL", fact_ids=["FACT-001"],
            assertion_text="名称长度不超过50字符",
            assertion_type="validation", risk_level="medium",
            review_status="auto_generated",
        ),
    ]
    passed, blocked = _split_by_review_gate(assertions)

    blocked_ids = {a.id for a in blocked}
    passed_ids = {a.id for a in passed}

    # security/high+auto → blocked
    assert "ASSERT-SEC" in blocked_ids
    # data_rule/high+auto → blocked
    assert "ASSERT-DR" in blocked_ids
    # functional/high+auto → passed (not in gate types)
    assert "ASSERT-FUNC" in passed_ids
    # validation/medium → passed
    assert "ASSERT-VAL" in passed_ids
    assert len(blocked) == 2
    assert len(passed) == 2


def test_review_gate_human_confirmed_passes():
    """Human-confirmed assertions should always pass regardless of type/risk."""
    assertions = [
        RequirementAssertion(
            id="ASSERT-SEC-CONF", fact_ids=["FACT-001"],
            assertion_text="系统必须实施权限控制",
            assertion_type="security", risk_level="high",
            review_status="human_confirmed",
        ),
    ]
    passed, blocked = _split_by_review_gate(assertions)
    assert len(passed) == 1
    assert len(blocked) == 0


def test_review_gate_rejected_discarded():
    """Rejected assertions should be discarded (not in either group)."""
    assertions = [
        RequirementAssertion(
            id="ASSERT-REJ", fact_ids=["FACT-001"],
            assertion_text="过时的断言",
            assertion_type="functional", risk_level="medium",
            review_status="rejected",
        ),
    ]
    passed, blocked = _split_by_review_gate(assertions)
    assert len(passed) == 0
    assert len(blocked) == 0


def test_goal_priority_layering():
    """Each assertion should map to the expected goal priority."""
    confirmed = [
        # security type → high priority
        RequirementAssertion(
            id="A1", fact_ids=["FACT-001"],
            assertion_text="系统必须实施权限隔离",
            assertion_type="security", risk_level="medium",
        ),
        # data_rule type → high priority
        RequirementAssertion(
            id="A2", fact_ids=["FACT-001"],
            assertion_text="权重之和必须等于100%",
            assertion_type="data_rule", risk_level="medium",
        ),
        # state_transition type → high priority
        RequirementAssertion(
            id="A3", fact_ids=["FACT-001"],
            assertion_text="状态必须正确转换",
            assertion_type="state_transition", risk_level="medium",
        ),
        # functional/medium → medium priority
        RequirementAssertion(
            id="A4", fact_ids=["FACT-001"],
            assertion_text="用户能够创建申请单",
            assertion_type="functional", risk_level="medium",
        ),
        # validation/medium → medium priority
        RequirementAssertion(
            id="A5", fact_ids=["FACT-001"],
            assertion_text="名称不超过50字符",
            assertion_type="validation", risk_level="medium",
        ),
        # functional/low → low priority
        RequirementAssertion(
            id="A6", fact_ids=["FACT-001"],
            assertion_text="页面显示图标",
            assertion_type="functional", risk_level="low",
        ),
    ]
    goals = _goals_from_confirmed_assertions(confirmed)
    priority_by_assertion_id = {
        goal.assertion_refs[0]: goal.priority
        for goal in goals
    }

    assert priority_by_assertion_id == {
        "A1": "high",
        "A2": "high",
        "A3": "high",
        "A4": "medium",
        "A5": "medium",
        "A6": "low",
    }


def test_goal_id_is_semantic_and_stable():
    """Goal ID should be derived from semantic fields, while risk_level only affects priority."""
    base_kwargs = {
        "assertion_text": "用户必须能够创建采购申请单",
        "assertion_type": "functional",
        "source_references": ["PRD §1"],
    }
    goal1 = _goals_from_confirmed_assertions([
        RequirementAssertion(
            id="ASSERT-OLD",
            fact_ids=["FACT-002", "FACT-001"],
            risk_level="high",
            **base_kwargs,
        )
    ])[0]
    goal2 = _goals_from_confirmed_assertions([
        RequirementAssertion(
            id="ASSERT-NEW",
            fact_ids=["FACT-001", "FACT-002"],
            risk_level="low",
            **base_kwargs,
        )
    ])[0]

    assert goal1.id.startswith("GOAL-")
    assert goal1.id == goal2.id
    assert goal1.priority == "high"
    assert goal2.priority == "low"


@pytest.mark.asyncio
async def test_phase2_precomputed_review_gate_matches_phase1_for_functional_high():
    """Phase 2 precomputed path should keep functional/high assertions aligned with Phase 1 gate."""
    facts = _make_sample_facts()[:2]
    assertions = [
        RequirementAssertion(
            id="ASSERT-FUNC-HIGH", fact_ids=["FACT-001"],
            assertion_text="用户必须能够创建采购申请单",
            assertion_type="functional", risk_level="high",
            review_status="auto_generated",
        ),
        RequirementAssertion(
            id="ASSERT-SEC-HIGH", fact_ids=["FACT-002"],
            assertion_text="系统必须实施角色权限隔离",
            assertion_type="security", risk_level="high",
            review_status="auto_generated",
        ),
    ]

    with patch("core.skills.fact_extractor.extract_facts", new=AsyncMock(return_value=facts)), \
         patch("core.skills.assertion_deriver.derive_assertions", new=AsyncMock(return_value=assertions)):
        from core.skills.l2_pipeline import generate_exploration_goals
        phase1_goals, phase1_review_items, phase1_facts, phase1_assertions = await generate_exploration_goals(
            prd_content=SAMPLE_PRD
        )

    observed_assertion_ids: list[str] = []

    async def fake_analyze_conditions(confirmed_assertions, system_map, blueprint):
        observed_assertion_ids.extend(a.id for a in confirmed_assertions)
        return []

    with patch("core.skills.condition_analyzer.analyze_conditions", new=fake_analyze_conditions):
        from core.skills.l2_pipeline import run_l2_pipeline
        package = await run_l2_pipeline(
            precomputed_facts=phase1_facts,
            precomputed_assertions=phase1_assertions,
            precomputed_goals=phase1_goals,
            precomputed_review_items=phase1_review_items,
        )

    assert [goal.assertion_refs[0] for goal in phase1_goals] == ["ASSERT-FUNC-HIGH"]
    assert observed_assertion_ids == ["ASSERT-FUNC-HIGH"]
    assert package.manual_review_items == phase1_review_items
    assert len(package.manual_review_items) == 1
    assert "ASSERT-SEC-HIGH" in package.manual_review_items[0]


def test_goals_from_confirmed_assertions_are_strict():
    from core.skills.l2_pipeline import _goals_from_confirmed_assertions

    assertions = [
        RequirementAssertion(
            id="ASSERT-LOGIN",
            fact_ids=["FACT-LOGIN"],
            assertion_text="用户必须能够使用有效账号登录系统",
            assertion_type="functional",
            risk_level="high",
            source_references=["FACT-LOGIN"],
        )
    ]

    goals = _goals_from_confirmed_assertions(assertions)

    assert len(goals) == 1
    goal = goals[0]
    assert goal.id.startswith("GOAL-")
    assert goal.assertion_refs == ["ASSERT-LOGIN"]
    assert goal.expected_evidence
    assert goal.stop_condition
    assert goal.source_refs == ["FACT-LOGIN"]
    assert goal.priority == "high"


def test_l1_prompts_forbid_meta_requirements_and_fact_quotas():
    from core.skills.assertion_deriver import _assertion_prompt
    from core.skills.document_chunking import DocumentChunk
    from core.skills.fact_extractor import _fact_prompt

    fact_prompt = _fact_prompt(
        DocumentChunk(
            source_type="prd",
            source_reference="PRD > 极简",
            content="用于验证 fast path。用户登录后可访问首页。",
        ),
        1,
    )
    assertion_prompt = _assertion_prompt([])

    assert "提取 0-" in fact_prompt
    assert "文档目的、测试说明" in fact_prompt
    assert "禁止反向脑补" in assertion_prompt
    assert "允许零断言" in assertion_prompt


# ---------------------------------------------------------------------------
# Confidence Calibration tests
# ---------------------------------------------------------------------------

from core.skills.fact_extractor import _calibrate_confidence, calibrate_facts


def test_calibrate_confidence_prd_with_good_quote():
    """PRD source with long quote → high confidence."""
    fact = RequirementFact(
        id="FACT-001", source_type="prd", source_reference="PRD §模块概述",
        quote="系统必须支持多维度评估体系，包含自评、上级评、下级评和同级评",
        subject="评估体系", action="支持", object="多维度评估",
        confidence=1.0,
    )
    cal = _calibrate_confidence(fact)
    assert cal >= 0.90  # prd baseline 0.95 + long quote bonus


def test_calibrate_confidence_inferred_no_quote():
    """Inferred source with no quote → significantly lower confidence."""
    fact = RequirementFact(
        id="FACT-002", source_type="inferred", source_reference="推导",
        quote="N/A",
        subject="系统行为", action="推断", object="某功能",
        confidence=1.0,
    )
    cal = _calibrate_confidence(fact)
    assert cal <= 0.55  # inferred baseline 0.60 - no quote penalty


def test_calibrate_confidence_with_condition_and_outcome():
    """Fact with both condition and outcome → bonus."""
    fact_with = RequirementFact(
        id="FACT-003", source_type="prd", source_reference="PRD",
        quote="当金额超过5000元时需经理审批，审批通过后生成采购单",
        subject="采购审批", action="审批", object="采购单",
        condition="金额>5000元", outcome="生成采购单",
        confidence=1.0,
    )
    fact_without = RequirementFact(
        id="FACT-004", source_type="prd", source_reference="PRD",
        quote="采购单支持多级审批流程",
        subject="采购单", action="支持", object="多级审批",
        condition=None, outcome=None,
        confidence=1.0,
    )
    cal_with = _calibrate_confidence(fact_with)
    cal_without = _calibrate_confidence(fact_without)
    assert cal_with > cal_without


def test_calibrate_facts_reduces_overconfident():
    """calibrate_facts should reduce confidence for low-quality facts."""
    facts = [
        RequirementFact(
            id="FACT-005", source_type="inferred", source_reference="推导",
            quote="N/A",
            subject="未知系统行为A", action="执行", object="某操作",
            confidence=1.0,  # LLM 过度自信
        ),
        RequirementFact(
            id="FACT-006", source_type="prd", source_reference="PRD §模块",
            quote="系统必须支持员工自助查询绩效结果，包含各维度得分明细",
            subject="绩效查询", action="支持", object="员工自助查询",
            confidence=1.0,
        ),
    ]
    calibrated = calibrate_facts(facts)
    # inferred + no quote → confidence should be reduced
    assert calibrated[0].confidence < 1.0
    # prd + good quote → confidence stays high
    assert calibrated[1].confidence >= 0.90


def test_calibrate_facts_distribution():
    """After calibration, should have meaningful confidence distribution."""
    facts = [
        RequirementFact(
            id=f"FACT-{i:03d}", source_type=src, source_reference=f"Ref {i}",
            quote=quote, subject=f"Subject {i}", action="do", object=f"Object {i}",
            confidence=1.0,
        )
        for i, (src, quote) in enumerate([
            ("prd", "这是一段足够长的原文引用来支持事实提取的精确性验证"),
            ("prd", "短引用"),
            ("inferred", "N/A"),
            ("inferred", "N/A"),
            ("swagger", "API接口定义的详细描述文本用于验证系统行为"),
            ("changelog", ""),
            ("prd", "正常引用"),
            ("inferred", "N/A"),
        ])
    ]
    calibrated = calibrate_facts(facts)
    conf_values = [f.confidence for f in calibrated]
    low_count = sum(1 for c in conf_values if c < 1.0)
    # Should have at least some low-confidence facts
    assert low_count >= 3, f"Expected ≥3 low-confidence facts, got {low_count}"
    # Should have diversity
    assert len(set(conf_values)) >= 3, f"Expected ≥3 distinct confidence values"
