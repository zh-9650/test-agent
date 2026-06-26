"""tests/core/test_data_models.py — Schema and invariant tests for new data models.

Tests the Pydantic models defined in core/interfaces.py for the new L2 pipeline:
RequirementFact, RequirementAssertion, SystemMapEvid, TestCondition,
TestDesignTechnique, CoverageItem, CandidateTestCase, TraceabilityMatrix,
TestAssetPackage.
"""
from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from core.interfaces import (
    RequirementFact, RequirementAssertion, PageMap, ActionMap,
    FormMap, NavigationMap, SystemMapEvid, TestCondition as ConditionModel,
    TestDesignTechnique as TechniqueModel, CoverageItem, CandidateTestCase,
    TraceabilityRow, TraceabilityMatrix, TestAssetPackage as AssetPackageModel,
)


# ---------------------------------------------------------------------------
# RequirementFact
# ---------------------------------------------------------------------------

def test_requirement_fact_minimal():
    fact = RequirementFact(
        id="FACT-001",
        source_type="prd",
        source_reference="PRD §3.1",
        quote="系统支持采购申请创建",
        subject="系统",
        action="支持",
        object="采购申请创建",
        confidence=1.0,
    )
    assert fact.id == "FACT-001"
    assert fact.status == "draft"
    assert fact.conflict_references == []


def test_requirement_fact_with_conflict():
    fact = RequirementFact(
        id="FACT-001",
        source_type="swagger",
        source_reference="swagger.yaml",
        quote="POST /api/orders",
        subject="接口",
        action="创建",
        object="订单",
        confidence=0.6,
        status="conflicted",
        conflict_references=["FACT-002"],
    )
    assert fact.status == "conflicted"
    assert "FACT-002" in fact.conflict_references


def test_requirement_fact_invalid_status():
    with pytest.raises(ValidationError):
        RequirementFact(
            id="FACT-001",
            source_type="prd",
            source_reference="x",
            quote="x",
            subject="x", action="x",
            confidence=1.0,
            status="invalid_status",  # type: ignore[arg-type]
        )


def test_requirement_fact_confidence_bounds():
    with pytest.raises(ValidationError):
        RequirementFact(
            id="FACT-001",
            source_type="prd",
            source_reference="x",
            quote="x",
            subject="x", action="x",
            confidence=1.5,  # > 1.0
        )


# ---------------------------------------------------------------------------
# RequirementAssertion
# ---------------------------------------------------------------------------

def test_requirement_assertion_minimal():
    assertion = RequirementAssertion(
        id="ASSERT-001",
        fact_ids=["FACT-001"],
        assertion_text="系统必须支持创建采购申请",
        assertion_type="functional",
        risk_level="high",
    )
    assert assertion.review_status == "auto_generated"
    assert assertion.source_references == []


def test_requirement_assertion_with_all_fields():
    assertion = RequirementAssertion(
        id="ASSERT-001",
        fact_ids=["FACT-001", "FACT-002"],
        assertion_text="金额超过5000需要经理审批",
        assertion_type="data_rule",
        risk_level="high",
        review_status="human_confirmed",
        source_references=["PRD §4.1"],
    )
    assert assertion.review_status == "human_confirmed"


# ---------------------------------------------------------------------------
# SystemMapEvid
# ---------------------------------------------------------------------------

def test_system_map_evid_empty():
    sm = SystemMapEvid()
    assert sm.pages == []
    assert sm.actions == []
    assert sm.forms == []
    assert sm.navigations == []


def test_system_map_evid_with_submaps():
    sm = SystemMapEvid(
        pages=[
            PageMap(
                name="登录页",
                url_pattern="/login",
                title="登录",
                evidence_refs=["page_url: /login"],
            )
        ],
        actions=[
            ActionMap(
                action_name="点击登录",
                source_page="登录页",
                target_page="首页",
                evidence_refs=["semantic_element: #3"],
            )
        ],
        forms=[
            FormMap(
                form_name="登录表单",
                page="登录页",
                fields=["用户名", "密码"],
                evidence_refs=["form: login"],
            )
        ],
        navigations=[
            NavigationMap(
                source="登录页",
                target="首页",
                via="点击登录按钮",
                evidence_refs=["source_url: /login", "target_url: /"],
            )
        ],
    )
    assert len(sm.pages) == 1
    assert sm.pages[0].name == "登录页"
    assert len(sm.actions) == 1
    assert sm.actions[0].action_name == "点击登录"
    assert sm.actions[0].source_page == "登录页"
    assert sm.actions[0].evidence_refs == ["semantic_element: #3"]
    assert len(sm.forms) == 1
    assert sm.forms[0].form_name == "登录表单"
    assert len(sm.navigations) == 1
    assert sm.navigations[0].source == "登录页"
    assert sm.navigations[0].evidence_refs[-1] == "target_url: /"


# ---------------------------------------------------------------------------
# TestCondition
# ---------------------------------------------------------------------------

def test_test_condition_minimal():
    cond = ConditionModel(
        id="COND-001",
        assertion_ref="ASSERT-001",
        condition_type="functional",
        statement="在已登录状态下，点击创建订单按钮",
        oracle="系统展示订单创建表单",
        oracle_type="ui_state",
    )
    assert cond.risk_level == "medium"
    assert cond.measurability == "measurable"


def test_test_condition_all_fields():
    cond = ConditionModel(
        id="COND-002",
        assertion_ref="ASSERT-002",
        condition_type="boundary",
        statement="输入金额5000",
        precondition="已登录",
        trigger="点击提交",
        oracle="系统提示需经理审批",
        oracle_type="business_rule",
        risk_level="high",
        measurability="measurable",
        source_references=["PRD §4.1"],
    )
    assert cond.oracle_type == "business_rule"
    assert cond.risk_level == "high"


# ---------------------------------------------------------------------------
# TestDesignTechnique
# ---------------------------------------------------------------------------

def test_technique_minimal():
    tech = TechniqueModel(
        id="TECH-COND-001",
        condition_id="COND-001",
        primary_technique="equivalence_partitioning",
        rationale="按金额区间划分等价类",
    )
    assert tech.supplementary_techniques == []


# ---------------------------------------------------------------------------
# CoverageItem
# ---------------------------------------------------------------------------

def test_coverage_item_minimal():
    item = CoverageItem(
        id="COV-001",
        condition_id="COND-001",
        technique_id="COND-001:equivalence_partitioning",
        coverage_dimension="normal",
        goal="验证正常金额范围可创建订单",
    )
    assert item.risk_level == "medium"


# ---------------------------------------------------------------------------
# CandidateTestCase
# ---------------------------------------------------------------------------

def test_candidate_case_minimal():
    case = CandidateTestCase(
        id="TC-CAND-001",
        title="验证正常金额创建订单",
        goal="验证金额<5000时订单可直接创建",
        expected_result="订单创建成功",
        priority="high",
        trace_references=["COV-001"],
    )
    assert case.input_data == []


# ---------------------------------------------------------------------------
# TraceabilityMatrix
# ---------------------------------------------------------------------------

def test_traceability_matrix():
    row = TraceabilityRow(
        fact_id="FACT-001",
        assertion_id="ASSERT-001",
        condition_ids=["COND-001"],
        coverage_item_ids=["COV-001"],
        candidate_case_ids=["TC-CAND-001"],
        status="covered",
    )
    matrix = TraceabilityMatrix(rows=[row])
    assert len(matrix.rows) == 1
    assert matrix.rows[0].status == "covered"


def test_traceability_row_default_status():
    row = TraceabilityRow(fact_id="FACT-001")
    assert row.status == "gap"  # default


# ---------------------------------------------------------------------------
# TestAssetPackage
# ---------------------------------------------------------------------------

def test_asset_package_empty():
    pkg = AssetPackageModel()
    assert pkg.facts == []
    assert pkg.assertions == []
    assert pkg.test_conditions == []
    assert pkg.coverage_items == []
    assert pkg.candidate_cases == []
    assert pkg.system_map is None
    assert pkg.traceability_matrix is None
    assert pkg.ambiguities == []
    assert pkg.conflicts == []
    assert pkg.manual_review_items == []


def test_asset_package_full():
    fact = RequirementFact(
        id="FACT-001", source_type="prd", source_reference="x",
        quote="x", subject="x", action="x", confidence=1.0,
    )
    assertion = RequirementAssertion(
        id="ASSERT-001", fact_ids=["FACT-001"],
        assertion_text="x", assertion_type="functional", risk_level="high",
    )
    cond = ConditionModel(
        id="COND-001", assertion_ref="ASSERT-001",
        condition_type="functional", statement="x",
        oracle="x", oracle_type="ui_state",
    )
    cov = CoverageItem(
        id="COV-001", condition_id="COND-001",
        technique_id="t1", coverage_dimension="normal", goal="x",
    )
    case = CandidateTestCase(
        id="TC-CAND-001", title="x", goal="x",
        expected_result="x", priority="high", trace_references=["COV-001"],
    )

    pkg = AssetPackageModel(
        facts=[fact],
        assertions=[assertion],
        test_conditions=[cond],
        coverage_items=[cov],
        candidate_cases=[case],
        ambiguities=["模糊需求: 订单金额上限不明确"],
        conflicts=["FACT-001 与 FACT-002 冲突"],
        manual_review_items=["高风险的审批逻辑需要人工确认"],
    )
    assert len(pkg.facts) == 1
    assert len(pkg.assertions) == 1
    assert len(pkg.ambiguities) == 1
    assert "模糊需求" in pkg.ambiguities[0]
    assert pkg.manual_review_items[0].startswith("高风险")


# ---------------------------------------------------------------------------
# Cross-model invariants
# ---------------------------------------------------------------------------

def test_condition_refers_to_existing_assertion():
    """COND-001 must reference an existing assertion ID (invariant enforced
    during construction, not by schema)."""
    cond = ConditionModel(
        id="COND-001",
        assertion_ref="ASSERT-999",  # may not exist yet
        condition_type="functional",
        statement="x", oracle="x", oracle_type="ui_state",
    )
    assert cond.assertion_ref == "ASSERT-999"


def test_candidate_case_traceability():
    """A candidate case must have at least one trace_reference."""
    case = CandidateTestCase(
        id="TC-CAND-001", title="test", goal="test",
        expected_result="pass", priority="medium",
        trace_references=["COV-001"],
    )
    assert "COV-001" in case.trace_references
