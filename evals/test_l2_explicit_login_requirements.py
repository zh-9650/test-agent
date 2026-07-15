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
    SourceAnchor,
    TestCondition,
    TestDesignTechnique,
    StructuredPrecondition,
)
from core.skills.l2_pipeline import (
    _augment_explicit_login_requirement_cases,
    _filter_no_write_business_cases,
    _split_by_review_gate,
)
from core.skills.quality_gates import run_quality_gates
from core.interfaces import TestAssetPackage


def _valid_login_assets() -> tuple[
    list[RequirementFact],
    list[RequirementAssertion],
    list[TestCondition],
    list[TestDesignTechnique],
    list[CoverageItem],
    list[CandidateTestCase],
]:
    fact = RequirementFact(
        id="FACT-valid-login",
        source_type="prd",
        source_reference="prd",
        quote="真实凭据 admin/admin123 登录成功后进入控制台。",
        subject="登录页",
        action="允许有效凭据登录",
        object="admin/admin123",
        outcome="进入控制台",
        confidence=1.0,
    )
    assertion = RequirementAssertion(
        id="ASSERT-valid-login",
        fact_ids=[fact.id],
        assertion_text="admin 登录成功后进入控制台",
        assertion_type="functional",
        risk_level="medium",
    )
    condition = TestCondition(
        id="COND-valid-login",
        assertion_ref=assertion.id,
        condition_type="functional",
        statement="admin 登录成功后进入控制台",
        trigger="输入 admin/admin123 并点击登录",
        oracle="显示控制台",
        oracle_type="ui_state",
        branch_type="positive",
    )
    technique = TestDesignTechnique(
        id="TECH-valid-login",
        condition_id=condition.id,
        primary_technique="equivalence_partitioning",
    )
    coverage = CoverageItem(
        id="COV-valid-login",
        condition_id=condition.id,
        technique_id=technique.id,
        coverage_dimension="normal",
        goal=condition.statement,
    )
    case = CandidateTestCase(
        id="TC-valid-login",
        title="有效凭据登录",
        goal="验证用户使用有效凭据(admin/cangjie*2026)登录后进入控制台",
        expected_result="登录成功后显示控制台",
        trace_references=[coverage.id],
        required_roles=["admin"],
    )
    return [fact], [assertion], [condition], [technique], [coverage], [case]


def test_explicit_wrong_password_requirement_adds_negative_case() -> None:
    source_text = """
    当前真实凭据为 admin/admin123。
    至少生成 1 条 UI 错误密码用例：使用 admin/cangjie*2026 提交登录，
    预期仍停留在登录页并显示密码错误提示。
    """
    augmented = _augment_explicit_login_requirement_cases(
        *_valid_login_assets(),
        source_text,
    )
    facts, assertions, conditions, techniques, coverage_items, cases = augmented

    assert len(facts) == 2
    assert len(assertions) == 2
    assert len(conditions) == 2
    assert len(techniques) == 2
    assert len(coverage_items) == 2
    assert len(cases) == 2
    assert any(case.branch_type == "negative" for case in cases)
    assert any("admin/admin123" in case.goal for case in cases)
    assert not any(
        "有效凭据(admin/cangjie*2026)" in case.goal for case in cases
    )


def test_api_wrong_password_case_does_not_block_ui_negative_augmentation() -> None:
    facts, assertions, conditions, techniques, coverage_items, cases = _valid_login_assets()
    cases.append(
        CandidateTestCase(
            id="TC-api-invalid-login",
            title="API 错误密码",
            goal="调用登录 API 使用 admin/cangjie*2026 返回非 200 状态码",
            expected_result="响应体包含密码错误",
            trace_references=[coverage_items[0].id],
            branch_type="negative",
        )
    )
    augmented = _augment_explicit_login_requirement_cases(
        facts,
        assertions,
        conditions,
        techniques,
        coverage_items,
        cases,
        "必须覆盖 UI 错误密码用例：使用 admin/cangjie*2026 提交登录，预期仍停留在登录页。",
    )
    normalized_cases = augmented[-1]

    assert any(case.id == "TC-EXPLICIT-INVALID-LOGIN" for case in normalized_cases)
    assert next(
        case for case in normalized_cases if case.id == "TC-EXPLICIT-INVALID-LOGIN"
    ).priority == "high"


def test_explicit_quick_fill_requirement_adds_high_priority_case() -> None:
    augmented = _augment_explicit_login_requirement_cases(
        *_valid_login_assets(),
        "必须覆盖一键填值体验：点击后用户名应为 admin，当前密码实测为 cangjie*2026。",
    )
    quick_fill_case = next(
        case for case in augmented[-1] if case.id == "TC-EXPLICIT-QUICK-FILL"
    )

    assert quick_fill_case.priority == "high"
    assert quick_fill_case.expected_result == "username=admin，password=cangjie*2026"


def test_existing_quick_fill_case_is_promoted_to_high_priority() -> None:
    facts, assertions, conditions, techniques, coverage_items, cases = _valid_login_assets()
    cases.append(
        CandidateTestCase(
            id="TC-existing-quick-fill",
            title="一键填值体验",
            goal="验证一键填值体验按钮自动填充 admin 和 cangjie*2026",
            expected_result="字段值符合预期",
            trace_references=[coverage_items[0].id],
            priority="medium",
        )
    )
    augmented = _augment_explicit_login_requirement_cases(
        facts,
        assertions,
        conditions,
        techniques,
        coverage_items,
        cases,
        "必须覆盖一键填值体验：点击后用户名应为 admin，当前密码实测为 cangjie*2026。",
    )
    quick_fill_case = next(
        case for case in augmented[-1] if case.id == "TC-existing-quick-fill"
    )

    assert quick_fill_case.priority == "high"
    assert quick_fill_case.expected_result == "username=admin，password=cangjie*2026"


def test_quick_fill_success_wording_is_normalized_to_field_value_case() -> None:
    facts, assertions, conditions, techniques, coverage_items, cases = _valid_login_assets()
    cases.append(
        CandidateTestCase(
            id="TC-ambiguous-quick-fill",
            title="一键填值成功登录",
            goal="验证一键填值体验按钮填充有效凭据后，登录流程成功完成。",
            expected_result="跳转控制台并显示昵称。",
            execution_hint="回到登录页，点击一键填值体验按钮并观察输入框值。",
            trace_references=[coverage_items[0].id],
            priority="medium",
        )
    )
    augmented = _augment_explicit_login_requirement_cases(
        facts,
        assertions,
        conditions,
        techniques,
        coverage_items,
        cases,
        (
            "必须覆盖一键填值体验：点击后用户名应为 admin，"
            "当前密码实测为 cangjie*2026；不要把它当作成功登录凭据。"
        ),
    )
    quick_fill_case = next(
        case for case in augmented[-1] if case.id == "TC-ambiguous-quick-fill"
    )

    assert quick_fill_case.goal == (
        "点击一键填值体验后验证 username=admin 且 password=cangjie*2026"
    )
    assert quick_fill_case.expected_result == "username=admin，password=cangjie*2026"


def test_existing_valid_login_case_is_promoted_to_high_priority() -> None:
    augmented = _augment_explicit_login_requirement_cases(
        *_valid_login_assets(),
        "必须覆盖真实凭据：admin/admin123 应登录成功并进入控制台；一键填值当前为 admin/cangjie*2026。",
    )
    valid_case = next(case for case in augmented[-1] if case.id == "TC-valid-login")

    assert valid_case.priority == "high"
    assert "控制台" in valid_case.expected_result


def test_no_write_source_filters_business_write_cases() -> None:
    cases = [
        CandidateTestCase(
            id="TC-agent-invalid",
            title="非法 gatewayUrl 新增智能体被阻断",
            goal="通过 UI 新增智能体并填写 gatewayUrl=not-url。",
            expected_result="不能创建记录。",
            trace_references=["COV-agent"],
        ),
        CandidateTestCase(
            id="TC-login",
            title="有效登录",
            goal="输入 admin/admin123 并点击立即登录后验证进入控制台",
            expected_result="进入控制台。",
            trace_references=["COV-login"],
        ),
    ]

    filtered = _filter_no_write_business_cases(
        cases,
        "本轮只做低副作用路径，不新增、编辑或删除业务数据。",
    )

    assert [case.id for case in filtered] == ["TC-login"]


def test_quality_gate_accepts_validation_negative_branch() -> None:
    source_text = """
    当前真实凭据为 admin/admin123。
    至少生成 1 条 UI 错误密码用例：使用 admin/cangjie*2026 提交登录，
    预期仍停留在登录页并显示密码错误提示。
    """
    facts, assertions, conditions, techniques, coverage_items, cases = (
        _augment_explicit_login_requirement_cases(
            *_valid_login_assets(),
            source_text,
        )
    )
    report = run_quality_gates(
        TestAssetPackage(
            facts=facts,
            assertions=assertions,
            source_registry=[
                SourceAnchor(
                    source_id="prd",
                    source_type="prd",
                    content_hash="prd-hash",
                    quote="真实凭据 admin/admin123 登录成功后进入控制台。",
                ),
                SourceAnchor(
                    source_id="rules",
                    source_type="rule",
                    content_hash="rules-hash",
                    quote="使用 admin/cangjie*2026 提交登录，预期仍停留在登录页。",
                ),
            ],
            test_conditions=conditions,
            test_design_techniques=techniques,
            coverage_items=coverage_items,
            candidate_cases=cases,
        )
    )

    assert report.passed
    assert not any(
        finding.code == "missing_positive_condition"
        and finding.artifact_id == "ASSERT-EXPLICIT-INVALID-LOGIN"
        for finding in report.findings
    )


def test_existing_wrong_password_case_is_normalized_to_negative() -> None:
    facts, assertions, conditions, techniques, coverage_items, cases = _valid_login_assets()
    cases.append(
        CandidateTestCase(
            id="TC-existing-invalid-login",
            title="错误密码登录失败",
            goal="使用 admin/cangjie*2026 提交登录时停留在登录页并显示密码错误",
            expected_result="登录失败",
            trace_references=[coverage_items[0].id],
            branch_type="positive",
            required_roles=["admin"],
            preconditions=[
                StructuredPrecondition(
                    type="account_role",
                    description="存在 admin 账号",
                    required_role="admin",
                    satisfiable_by_agent=True,
                )
            ],
        )
    )
    augmented = _augment_explicit_login_requirement_cases(
        facts,
        assertions,
        conditions,
        techniques,
        coverage_items,
        cases,
        "真实凭据 admin/admin123；错误密码 admin/cangjie*2026 应停留在登录页。",
    )
    normalized_cases = augmented[-1]
    wrong_password_case = next(
        case for case in normalized_cases if case.id == "TC-existing-invalid-login"
    )

    assert wrong_password_case.branch_type == "negative"
    assert wrong_password_case.required_roles == []
    assert wrong_password_case.preconditions[0].type == "data"


def test_explicit_test_account_login_security_assertion_skips_review_gate() -> None:
    assertion = RequirementAssertion(
        id="ASSERT-login-auth",
        fact_ids=["FACT-login-auth"],
        assertion_text="系统必须支持使用用户名 admin 和密码 admin123 进行身份验证。",
        assertion_type="security",
        risk_level="high",
        review_status="auto_generated",
    )

    passed, blocked = _split_by_review_gate([assertion])

    assert passed == [assertion]
    assert blocked == []


def test_explicit_fixture_account_assertion_skips_review_gate() -> None:
    assertion = RequirementAssertion(
        id="ASSERT-account-fixture",
        fact_ids=["FACT-account-fixture"],
        assertion_text="系统必须存在管理员账号 admin，且其密码为 admin123",
        assertion_type="security",
        risk_level="high",
        review_status="auto_generated",
    )

    passed, blocked = _split_by_review_gate([assertion])

    assert passed == [assertion]
    assert blocked == []


if __name__ == "__main__":
    test_explicit_wrong_password_requirement_adds_negative_case()
    test_api_wrong_password_case_does_not_block_ui_negative_augmentation()
    test_explicit_quick_fill_requirement_adds_high_priority_case()
    test_existing_quick_fill_case_is_promoted_to_high_priority()
    test_quick_fill_success_wording_is_normalized_to_field_value_case()
    test_existing_valid_login_case_is_promoted_to_high_priority()
    test_no_write_source_filters_business_write_cases()
    test_quality_gate_accepts_validation_negative_branch()
    test_existing_wrong_password_case_is_normalized_to_negative()
    test_explicit_test_account_login_security_assertion_skips_review_gate()
    test_explicit_fixture_account_assertion_skips_review_gate()
    print("explicit login requirement regression checks passed")
