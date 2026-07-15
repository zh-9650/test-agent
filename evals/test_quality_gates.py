from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.interfaces import (
    CandidateTestCase,
    CoverageItem,
    RequirementAssertion,
    RequirementFact,
    TestAssetPackage,
    TestCondition,
    TestDesignTechnique,
)
from core.skills.quality_gates import run_quality_gates


def test_e2e_condition_counts_as_positive_assertion_coverage() -> None:
    fact = RequirementFact(
        id="FACT-e2e",
        source_type="inferred",
        source_reference="regression",
        quote="Regression fact for E2E positive coverage.",
        subject="知识库管理",
        action="新建",
        object="知识库",
        confidence=1.0,
    )
    assertion = RequirementAssertion(
        id="ASSERT-e2e",
        fact_ids=[fact.id],
        assertion_text="知识库可以通过 UI 新建并在列表命中。",
        assertion_type="functional",
        risk_level="high",
        review_status="human_confirmed",
    )
    condition = TestCondition(
        id="COND-e2e",
        assertion_ref=assertion.id,
        condition_type="functional",
        statement=assertion.assertion_text,
        oracle_type="ui_state",
        branch_type="e2e",
    )
    technique = TestDesignTechnique(
        id="TECH-e2e",
        condition_id=condition.id,
        primary_technique="equivalence_partitioning",
    )
    coverage = CoverageItem(
        id="COV-e2e",
        condition_id=condition.id,
        technique_id=technique.id,
        coverage_dimension="normal",
        goal=condition.statement,
        branch_type="e2e",
    )
    case = CandidateTestCase(
        id="TC-e2e",
        title="通过 UI 新建知识库并列表命中",
        goal="通过 UI 新建知识库 测试知识库-TA-20260704-AUTO",
        expected_result="列表显示测试知识库-TA-20260704-AUTO。",
        trace_references=[coverage.id],
        branch_type="e2e",
    )

    report = run_quality_gates(
        TestAssetPackage(
            facts=[fact],
            assertions=[assertion],
            test_conditions=[condition],
            test_design_techniques=[technique],
            coverage_items=[coverage],
            candidate_cases=[case],
        )
    )

    assert "missing_positive_condition" not in {
        finding.code for finding in report.findings
    }


if __name__ == "__main__":
    test_e2e_condition_counts_as_positive_assertion_coverage()
    print("quality gate regression checks passed")
