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
    _augment_explicit_dataset_requirement_cases,
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
        id="FACT-dataset-list",
        source_type="prd",
        source_reference="prd",
        quote="知识库管理支持列表查看。",
        subject="知识库管理",
        action="查看",
        object="知识库",
        confidence=1.0,
    )
    assertion = RequirementAssertion(
        id="ASSERT-dataset-list",
        fact_ids=[fact.id],
        assertion_text="知识库管理支持列表查看",
        assertion_type="functional",
        risk_level="medium",
    )
    condition = TestCondition(
        id="COND-dataset-list",
        assertion_ref=assertion.id,
        condition_type="functional",
        statement="知识库管理支持列表查看",
        oracle_type="ui_state",
    )
    technique = TestDesignTechnique(
        id="TECH-dataset-list",
        condition_id=condition.id,
        primary_technique="equivalence_partitioning",
    )
    coverage = CoverageItem(
        id="COV-dataset-list",
        condition_id=condition.id,
        technique_id=technique.id,
        coverage_dimension="normal",
        goal="查看知识库列表",
    )
    case = CandidateTestCase(
        id="TC-dataset-list",
        title="查看知识库列表",
        goal="登录后查看知识库列表",
        expected_result="列表稳定加载",
        trace_references=[coverage.id],
    )
    return [fact], [assertion], [condition], [technique], [coverage], [case]


def test_explicit_dataset_create_and_empty_name_cases_are_added() -> None:
    source_text = """
    必须覆盖知识库管理写操作：通过 UI 新建知识库，名称
    测试知识库-TA-20260704-AUTO，描述包含 TA-20260704。
    必须覆盖名称留空负向路径：描述填写测试空名称-TA-20260704-EMPTY，
    保存应被 required 或必填校验阻断，且不能创建记录。
    """

    augmented = _augment_explicit_dataset_requirement_cases(*_base_assets(), source_text)
    cases = {case.id: case for case in augmented[-1]}

    create_case = cases["TC-EXPLICIT-DATASET-CREATE"]
    empty_case = cases["TC-EXPLICIT-DATASET-EMPTY-NAME"]
    assert create_case.priority == "high"
    assert create_case.branch_type == "e2e"
    assert "测试知识库-TA-20260704-AUTO" in create_case.goal
    assert "/fastgpt/dataset/list" in create_case.expected_result
    assert empty_case.priority == "high"
    assert empty_case.branch_type == "negative"
    assert "TA-20260704-EMPTY" in empty_case.goal


def test_dataset_requirement_does_not_trigger_agent_write_case() -> None:
    source_text = """
    知识库新增后初始状态为未绑定智能体，必须通过 UI 新建
    测试知识库-TA-20260704-AUTO，并用 TA-20260704 清理数据。
    """

    augmented = _augment_explicit_agent_requirement_cases(*_base_assets(), source_text)
    case_ids = {case.id for case in augmented[-1]}

    assert "TC-EXPLICIT-AGENT-CREATE" not in case_ids
    assert "TC-EXPLICIT-AGENT-INVALID-GATEWAY" not in case_ids


def test_existing_dataset_write_cases_are_promoted() -> None:
    facts, assertions, conditions, techniques, coverage_items, cases = _base_assets()
    cases.extend(
        [
            CandidateTestCase(
                id="TC-existing-dataset-create",
                title="通过 UI 新建知识库并在列表搜索测试知识库-TA-20260704-AUTO。",
                goal="新建知识库后列表命中",
                expected_result="列表有记录",
                trace_references=[coverage_items[0].id],
                priority="medium",
            ),
            CandidateTestCase(
                id="TC-existing-dataset-empty",
                title="新建知识库时名称留空，描述为 TA-20260704-EMPTY，应被必填阻断。",
                goal="空名称知识库不能创建",
                expected_result="不会创建记录",
                trace_references=[coverage_items[0].id],
                priority="medium",
                branch_type="positive",
            ),
        ]
    )

    augmented = _augment_explicit_dataset_requirement_cases(
        facts,
        assertions,
        conditions,
        techniques,
        coverage_items,
        cases,
        "必须通过 UI 新建知识库 测试知识库-TA-20260704-AUTO；名称留空 TA-20260704-EMPTY 必须阻断。",
    )
    normalized_cases = {case.id: case for case in augmented[-1]}

    assert normalized_cases["TC-existing-dataset-create"].priority == "high"
    assert normalized_cases["TC-existing-dataset-create"].branch_type == "e2e"
    assert normalized_cases["TC-existing-dataset-empty"].priority == "high"
    assert normalized_cases["TC-existing-dataset-empty"].branch_type == "negative"


if __name__ == "__main__":
    test_explicit_dataset_create_and_empty_name_cases_are_added()
    test_dataset_requirement_does_not_trigger_agent_write_case()
    test_existing_dataset_write_cases_are_promoted()
    print("explicit dataset requirement regression checks passed")
