"""tests/core/test_traceability_builder.py — TraceabilityBuilder unit tests.

Tests the deterministic (non-LLM) traceability building logic in
core/skills/traceability_builder.py.
"""
from __future__ import annotations

import pytest

from core.interfaces import (
    RequirementFact, RequirementAssertion, TestCondition as ConditionModel,
    TestDesignTechnique as TechniqueModel, CoverageItem, CandidateTestCase,
)
from core.skills.traceability_builder import build_traceability


def _make_fact(fid: str) -> RequirementFact:
    return RequirementFact(
        id=fid, source_type="prd", source_reference="PRD",
        quote=f"quote {fid}", subject="sys", action="do", confidence=1.0,
    )


def _make_assertion(aid: str, fact_ids: list[str]) -> RequirementAssertion:
    return RequirementAssertion(
        id=aid, fact_ids=fact_ids,
        assertion_text=f"assertion {aid}",
        assertion_type="functional", risk_level="medium",
    )


def _make_condition(cid: str, assertion_ref: str) -> ConditionModel:
    return ConditionModel(
        id=cid, assertion_ref=assertion_ref,
        condition_type="functional", statement=f"cond {cid}",
        oracle=f"oracle {cid}", oracle_type="ui_state",
    )


def _make_technique(tid: str, condition_id: str) -> TechniqueModel:
    return TechniqueModel(
        id=tid,
        condition_id=condition_id,
        primary_technique="equivalence_partitioning",
        rationale="standard",
    )


def _make_cov(item_id: str, condition_id: str) -> CoverageItem:
    return CoverageItem(
        id=item_id, condition_id=condition_id,
        technique_id=f"{condition_id}:ep",
        coverage_dimension="normal", goal=f"cov {item_id}",
    )


def _make_case(case_id: str, cov_refs: list[str]) -> CandidateTestCase:
    return CandidateTestCase(
        id=case_id, title=f"case {case_id}",
        goal=f"goal {case_id}",
        expected_result="pass", priority="medium",
        trace_references=cov_refs,
    )


class TestBuildTraceability:

    def test_empty_inputs(self):
        matrix = build_traceability([], [], [], [], [], [])
        assert matrix.rows == []

    def test_fact_with_no_assertion_is_gap(self):
        facts = [_make_fact("FACT-001")]
        matrix = build_traceability(facts, [], [], [], [], [])
        assert len(matrix.rows) == 1
        assert matrix.rows[0].status == "gap"

    def test_fact_with_assertion_no_conditions_is_partial(self):
        facts = [_make_fact("FACT-001")]
        assertions = [_make_assertion("ASSERT-001", ["FACT-001"])]
        matrix = build_traceability(facts, assertions, [], [], [], [])
        assert len(matrix.rows) == 1
        assert matrix.rows[0].status == "partial"

    def test_full_coverage(self):
        facts = [_make_fact("FACT-001")]
        assertions = [_make_assertion("ASSERT-001", ["FACT-001"])]
        conditions = [_make_condition("COND-001", "ASSERT-001")]
        techniques = [_make_technique("TECH-COND-001", "COND-001")]
        covs = [_make_cov("COV-001", "COND-001")]
        cases = [_make_case("TC-CAND-001", ["COV-001"])]

        matrix = build_traceability(facts, assertions, conditions, techniques, covs, cases)
        assert len(matrix.rows) == 1
        assert matrix.rows[0].status == "covered"
        assert "TC-CAND-001" in matrix.rows[0].candidate_case_ids

    def test_missing_case_still_partial(self):
        facts = [_make_fact("FACT-001")]
        assertions = [_make_assertion("ASSERT-001", ["FACT-001"])]
        conditions = [_make_condition("COND-001", "ASSERT-001")]
        techniques = [_make_technique("TECH-COND-001", "COND-001")]
        covs = [_make_cov("COV-001", "COND-001")]
        # no cases -> partial
        matrix = build_traceability(facts, assertions, conditions, techniques, covs, [])
        assert matrix.rows[0].status == "partial"

    def test_multiple_facts_mixed_coverage(self):
        facts = [
            _make_fact("FACT-001"),
            _make_fact("FACT-002"),
            _make_fact("FACT-003"),
        ]
        assertions = [
            _make_assertion("ASSERT-001", ["FACT-001"]),
            _make_assertion("ASSERT-002", ["FACT-002"]),
            # FACT-003 has no assertion -> gap
        ]
        conditions = [_make_condition("COND-001", "ASSERT-001")]
        techniques = [_make_technique("TECH-COND-001", "COND-001")]
        covs = [_make_cov("COV-001", "COND-001")]
        cases = [_make_case("TC-CAND-001", ["COV-001"])]

        matrix = build_traceability(facts, assertions, conditions, techniques, covs, cases)
        assert len(matrix.rows) == 3

        status_by_fact = {r.fact_id: r.status for r in matrix.rows}
        assert status_by_fact["FACT-001"] == "covered"
        assert status_by_fact["FACT-002"] == "partial"  # assertion exists but no conditions
        assert status_by_fact["FACT-003"] == "gap"  # no assertion

    def test_blocked_high_risk_assertion_is_human_review_not_removed(self):
        facts = [_make_fact("FACT-001")]
        assertions = [RequirementAssertion(
            id="ASSERT-SEC-001",
            fact_ids=["FACT-001"],
            assertion_text="系统必须限制未授权访问",
            assertion_type="security",
            risk_level="high",
            review_status="auto_generated",
        )]

        matrix = build_traceability(facts, assertions, [], [], [], [])

        assert len(matrix.rows) == 1
        assert matrix.rows[0].status == "human_review"
        assert matrix.rows[0].assertion_ids == ["ASSERT-SEC-001"]

    def test_functional_high_assertion_is_not_human_review_when_gate_allows_it(self):
        facts = [_make_fact("FACT-001")]
        assertions = [RequirementAssertion(
            id="ASSERT-FUNC-001",
            fact_ids=["FACT-001"],
            assertion_text="用户必须能够创建申请单",
            assertion_type="functional",
            risk_level="high",
            review_status="auto_generated",
        )]

        matrix = build_traceability(facts, assertions, [], [], [], [])

        assert matrix.rows[0].status == "partial"
        assert matrix.rows[0].assertion_ids == ["ASSERT-FUNC-001"]

    def test_human_confirmed_security_assertion_is_not_human_review(self):
        facts = [_make_fact("FACT-001")]
        assertions = [RequirementAssertion(
            id="ASSERT-SEC-001",
            fact_ids=["FACT-001"],
            assertion_text="系统必须限制未授权访问",
            assertion_type="security",
            risk_level="high",
            review_status="human_confirmed",
        )]

        matrix = build_traceability(facts, assertions, [], [], [], [])

        assert matrix.rows[0].status == "partial"
        assert matrix.rows[0].assertion_ids == ["ASSERT-SEC-001"]

    def test_traceability_ids_correct(self):
        facts = [_make_fact("FACT-001")]
        assertions = [_make_assertion("ASSERT-001", ["FACT-001"])]
        conditions = [_make_condition("COND-001", "ASSERT-001")]
        covs = [_make_cov("COV-001", "COND-001")]
        cases = [_make_case("TC-CAND-001", ["COV-001"])]

        matrix = build_traceability(facts, assertions, conditions, [], covs, cases)
        row = matrix.rows[0]
        assert row.fact_id == "FACT-001"
        assert "ASSERT-001" in row.assertion_ids
        assert row.condition_ids == ["COND-001"]
        assert row.coverage_item_ids == ["COV-001"]
        assert row.candidate_case_ids == ["TC-CAND-001"]
