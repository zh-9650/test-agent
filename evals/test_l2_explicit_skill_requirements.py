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
from core.skills.l2_pipeline import _augment_explicit_skill_requirement_cases


def _base_assets() -> tuple[
    list[RequirementFact],
    list[RequirementAssertion],
    list[TestCondition],
    list[TestDesignTechnique],
    list[CoverageItem],
    list[CandidateTestCase],
]:
    fact = RequirementFact(
        id="FACT-skill-list",
        source_type="prd",
        source_reference="prd",
        quote="技能管理支持列表查看。",
        subject="技能管理",
        action="查看",
        object="技能列表",
        confidence=1.0,
    )
    assertion = RequirementAssertion(
        id="ASSERT-skill-list",
        fact_ids=[fact.id],
        assertion_text="技能管理支持列表查看。",
        assertion_type="functional",
        risk_level="medium",
    )
    condition = TestCondition(
        id="COND-skill-list",
        assertion_ref=assertion.id,
        condition_type="functional",
        statement="技能管理支持列表查看。",
        oracle_type="ui_state",
    )
    technique = TestDesignTechnique(
        id="TECH-skill-list",
        condition_id=condition.id,
        primary_technique="equivalence_partitioning",
    )
    coverage = CoverageItem(
        id="COV-skill-list",
        condition_id=condition.id,
        technique_id=technique.id,
        coverage_dimension="normal",
        goal="查看技能列表。",
    )
    case = CandidateTestCase(
        id="TC-skill-list",
        title="查看技能列表",
        goal="登录后查看技能管理列表",
        expected_result="技能管理列表稳定加载",
        trace_references=[coverage.id],
    )
    return [fact], [assertion], [condition], [technique], [coverage], [case]


def test_explicit_skill_scaffold_and_duplicate_core_cases_are_added() -> None:
    source_text = """
    必须覆盖技能管理写路径：通过 UI 点击快速初始化脚手架，然后将元数据保存为
    测试技能-TA-20260704-AUTO；保存后技能列表必须命中，文件树必须包含
    SKILL.md 和 index.js。必须覆盖重复创建 SKILL.md 被阻断，核心文件不可重复。
    """

    augmented = _augment_explicit_skill_requirement_cases(*_base_assets(), source_text)
    cases = {case.id: case for case in augmented[-1]}

    scaffold = cases["TC-EXPLICIT-SKILL-SCAFFOLD"]
    duplicate = cases["TC-EXPLICIT-SKILL-SCAFFOLD-DUPLICATE-CORE-FILE"]
    assert scaffold.priority == "high"
    assert scaffold.branch_type == "e2e"
    assert "测试技能-TA-20260704-AUTO" in scaffold.goal
    assert "SKILL.md" in scaffold.expected_result
    assert "index.js" in scaffold.expected_result
    assert duplicate.priority == "high"
    assert duplicate.branch_type == "negative"
    assert "SKILL.md" in duplicate.goal


def test_existing_skill_cases_are_promoted() -> None:
    facts, assertions, conditions, techniques, coverage_items, cases = _base_assets()
    cases.extend(
        [
            CandidateTestCase(
                id="TC-existing-skill-scaffold",
                title="通过 UI 快速初始化技能脚手架并验证 SKILL.md 与 index.js。",
                goal="初始化技能脚手架后列表命中 TA-20260704-AUTO",
                expected_result="列表和文件树正确",
                trace_references=[coverage_items[0].id],
                priority="medium",
            ),
            CandidateTestCase(
                id="TC-existing-skill-duplicate",
                title="重复创建 SKILL.md 核心文件应被阻断。",
                goal="在线修编中新建重复 SKILL.md",
                expected_result="核心文件重复创建被阻断",
                trace_references=[coverage_items[0].id],
                priority="medium",
                branch_type="positive",
            ),
        ]
    )

    augmented = _augment_explicit_skill_requirement_cases(
        facts,
        assertions,
        conditions,
        techniques,
        coverage_items,
        cases,
        "技能管理必须通过 UI 初始化脚手架 测试技能-TA-20260704-AUTO，并阻断重复创建 SKILL.md 核心文件。",
    )
    normalized = {case.id: case for case in augmented[-1]}

    assert normalized["TC-existing-skill-scaffold"].priority == "high"
    assert normalized["TC-existing-skill-scaffold"].branch_type == "e2e"
    assert normalized["TC-existing-skill-duplicate"].priority == "high"
    assert normalized["TC-existing-skill-duplicate"].branch_type == "negative"


if __name__ == "__main__":
    test_explicit_skill_scaffold_and_duplicate_core_cases_are_added()
    test_existing_skill_cases_are_promoted()
    print("explicit skill requirement regression checks passed")
