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
    TestCondition,
    TestDesignTechnique,
)
from core.skills.l2_pipeline import (
    _augment_explicit_agent_requirement_cases,
    _split_by_review_gate,
)


def _base_assets() -> tuple[
    list[RequirementFact],
    list[RequirementAssertion],
    list[TestCondition],
    list[TestDesignTechnique],
    list[CoverageItem],
    list[CandidateTestCase],
]:
    fact = RequirementFact(
        id="FACT-agent-list",
        source_type="prd",
        source_reference="prd",
        quote="智能体广场支持搜索。",
        subject="智能体广场",
        action="搜索",
        object="智能体",
        confidence=1.0,
    )
    assertion = RequirementAssertion(
        id="ASSERT-agent-list",
        fact_ids=[fact.id],
        assertion_text="智能体广场支持搜索",
        assertion_type="functional",
        risk_level="medium",
    )
    condition = TestCondition(
        id="COND-agent-list",
        assertion_ref=assertion.id,
        condition_type="functional",
        statement="智能体广场支持搜索",
        oracle_type="ui_state",
    )
    technique = TestDesignTechnique(
        id="TECH-agent-list",
        condition_id=condition.id,
        primary_technique="equivalence_partitioning",
    )
    coverage = CoverageItem(
        id="COV-agent-list",
        condition_id=condition.id,
        technique_id=technique.id,
        coverage_dimension="normal",
        goal="搜索智能体",
    )
    case = CandidateTestCase(
        id="TC-agent-list",
        title="搜索智能体",
        goal="登录后搜索智能体",
        expected_result="列表稳定加载",
        trace_references=[coverage.id],
    )
    return [fact], [assertion], [condition], [technique], [coverage], [case]


def test_explicit_agent_create_and_invalid_gateway_cases_are_added() -> None:
    source_text = """
    必须覆盖新增智能体正向路径：使用名称 测试智能体-TA-20260704-AUTO
    和 gatewayUrl=https://agent-gateway.cangjie.ai/v1/ta-20260704-auto。
    必须覆盖新增智能体负向路径：gatewayUrl=not-url 应被校验阻断，
    且搜索 TA-20260704-INVALID 不应创建成功。
    """

    augmented = _augment_explicit_agent_requirement_cases(*_base_assets(), source_text)
    cases = augmented[-1]

    create_case = next(case for case in cases if case.id == "TC-EXPLICIT-AGENT-CREATE")
    invalid_case = next(
        case for case in cases if case.id == "TC-EXPLICIT-AGENT-INVALID-GATEWAY"
    )
    assert create_case.priority == "high"
    assert create_case.branch_type == "e2e"
    assert "TA-20260704-AUTO" in create_case.goal
    assert invalid_case.priority == "high"
    assert invalid_case.branch_type == "negative"
    assert "not-url" in invalid_case.goal


def test_existing_agent_write_cases_are_promoted() -> None:
    facts, assertions, conditions, techniques, coverage_items, cases = _base_assets()
    cases.extend(
        [
            CandidateTestCase(
                id="TC-existing-agent-create",
                title="端到端验证登录后创建智能体，并能通过列表确认该智能体已生成。",
                goal="创建智能体后通过列表确认",
                expected_result="列表有记录",
                trace_references=[coverage_items[0].id],
                priority="medium",
            ),
            CandidateTestCase(
                id="TC-existing-agent-invalid",
                title="非法gatewayUrl被系统校验阻断且不产生可搜索的记录。",
                goal="新增智能体时 gatewayUrl 填 not-url",
                expected_result="不会创建记录",
                trace_references=[coverage_items[0].id],
                priority="medium",
                branch_type="positive",
            ),
        ]
    )

    augmented = _augment_explicit_agent_requirement_cases(
        facts,
        assertions,
        conditions,
        techniques,
        coverage_items,
        cases,
        "必须覆盖新增智能体正向路径 TA-20260704-AUTO；必须覆盖 gatewayUrl=not-url 负向路径。",
    )
    normalized_cases = {case.id: case for case in augmented[-1]}

    assert normalized_cases["TC-existing-agent-create"].priority == "high"
    assert normalized_cases["TC-existing-agent-create"].branch_type == "e2e"
    assert normalized_cases["TC-existing-agent-invalid"].priority == "high"
    assert normalized_cases["TC-existing-agent-invalid"].branch_type == "negative"


def test_network_header_security_assertion_skips_manual_review_gate() -> None:
    assertion = RequirementAssertion(
        id="ASSERT-auth-header",
        fact_ids=["FACT-auth-header"],
        assertion_text="前端登录后发出的 API 请求必须包含 Authorization 请求头，其值为 Bearer token。",
        assertion_type="security",
        risk_level="high",
        review_status="auto_generated",
    )

    passed, blocked = _split_by_review_gate([assertion])

    assert passed == [assertion]
    assert blocked == []


if __name__ == "__main__":
    test_explicit_agent_create_and_invalid_gateway_cases_are_added()
    test_existing_agent_write_cases_are_promoted()
    test_network_header_security_assertion_skips_manual_review_gate()
    print("explicit agent requirement regression checks passed")
