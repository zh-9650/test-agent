"""core/skills/traceability_builder.py — N4 (New): TraceabilityMatrix Builder.

L1 Pipeline Position:
  上游: 所有上游产物 (facts, assertions, conditions, techniques, coverage items, cases)
  下游: N4.5 asset_packager
  本节点职责: 构建从源事实到候选用例的完整追溯矩阵（确定性逻辑，不调 LLM）

覆盖状态判定规则:
  - "covered" = 该事实的所有断言分支，每条都有至少一个候选用例
  - "partial" = 有断言但至少一个分支尚无用例
  - "gap" = 事实没有任何断言关联
  - "conflict" = 事实状态为 conflicted
  - "human_review" = 事实关联高风险断言
"""
from core.interfaces import (
    RequirementFact, RequirementAssertion, TestCondition,
    TestDesignTechnique, CoverageItem, CandidateTestCase,
    TraceabilityMatrix, TraceabilityRow,
)


def _build_lookup_maps(
    facts: list[RequirementFact],
    assertions: list[RequirementAssertion],
    conditions: list[TestCondition],
    techniques: list[TestDesignTechnique],
    coverage_items: list[CoverageItem],
    candidate_cases: list[CandidateTestCase],
) -> tuple[
    dict[str, list[RequirementAssertion]],   # fact_id → assertions
    dict[str, list[TestCondition]],          # assertion_id → conditions
    dict[str, list[TestDesignTechnique]],    # condition_id → techniques
    dict[str, list[CoverageItem]],           # condition_id → coverage items
    dict[str, list[CandidateTestCase]],      # coverage_id → cases
]:
    fact_to_assertions: dict[str, list[RequirementAssertion]] = {}
    for a in assertions:
        for fid in a.fact_ids:
            fact_to_assertions.setdefault(fid, []).append(a)

    assertion_to_conditions: dict[str, list[TestCondition]] = {}
    for c in conditions:
        assertion_to_conditions.setdefault(c.assertion_ref, []).append(c)

    condition_to_techniques: dict[str, list[TestDesignTechnique]] = {}
    for t in techniques:
        condition_to_techniques.setdefault(t.condition_id, []).append(t)

    condition_to_coverage: dict[str, list[CoverageItem]] = {}
    for ci in coverage_items:
        condition_to_coverage.setdefault(ci.condition_id, []).append(ci)

    cov_to_cases: dict[str, list[CandidateTestCase]] = {}
    for case in candidate_cases:
        for ref in case.trace_references:
            cov_to_cases.setdefault(ref, []).append(case)

    return (
        fact_to_assertions,
        assertion_to_conditions,
        condition_to_techniques,
        condition_to_coverage,
        cov_to_cases,
    )


def _trace_assertion_branch(
    assertion: RequirementAssertion,
    assertion_to_conditions: dict[str, list[TestCondition]],
    condition_to_techniques: dict[str, list[TestDesignTechnique]],
    condition_to_coverage: dict[str, list[CoverageItem]],
    cov_to_cases: dict[str, list[CandidateTestCase]],
) -> tuple[list[str], list[str], list[str], list[str], bool]:
    """回溯一个断言分支的完整链路，返回条件/技术/覆盖/用例 ID 列表，
    以及该分支是否被完全覆盖（有至少一个用例）。"""
    cond_ids: list[str] = []
    tech_ids: list[str] = []
    cov_ids: list[str] = []
    case_ids: list[str] = []

    for cond in assertion_to_conditions.get(assertion.id, []):
        cond_ids.append(cond.id)
        for tech in condition_to_techniques.get(cond.id, []):
            tech_ids.append(tech.id)
        for cov in condition_to_coverage.get(cond.id, []):
            cov_ids.append(cov.id)
            for case in cov_to_cases.get(cov.id, []):
                case_ids.append(case.id)

    has_cases = len(case_ids) > 0
    return cond_ids, tech_ids, cov_ids, case_ids, has_cases


def build_traceability(
    facts: list[RequirementFact],
    assertions: list[RequirementAssertion],
    conditions: list[TestCondition],
    techniques: list[TestDesignTechnique],
    coverage_items: list[CoverageItem],
    candidate_cases: list[CandidateTestCase],
) -> TraceabilityMatrix:
    """构建完整追溯矩阵。

    每条事实一行，记录到其所关联的所有断言、条件、技术、覆盖项和候选用例的追溯链路。
    覆盖状态判定:
      - "covered": 事实的所有断言分支都至少有 1 个用例
      - "partial": 有断言但至少一个分支没有用例
      - "gap": 事实没有任何断言关联
      - "human_review": 关联高风险断言（需要人工审查）
    """
    (fact_to_assertions,
     assertion_to_conditions,
     condition_to_techniques,
     condition_to_coverage,
     cov_to_cases) = _build_lookup_maps(
        facts, assertions, conditions, techniques, coverage_items, candidate_cases
    )

    rows: list[TraceabilityRow] = []

    for fact in facts:
        related_assertions = fact_to_assertions.get(fact.id, [])
        all_assertion_ids: list[str] = [a.id for a in related_assertions]
        all_cond_ids: list[str] = []
        all_tech_ids: list[str] = []
        all_cov_ids: list[str] = []
        all_case_ids: list[str] = []
        branches_covered: int = 0
        branches_with_cases: int = 0
        has_blocked_by_review_gate: bool = False

        for assertion in related_assertions:
            if (
                assertion.risk_level == "high"
                and assertion.review_status == "auto_generated"
                and assertion.assertion_type in {"security", "data_rule"}
            ):
                has_blocked_by_review_gate = True
            cond_ids, tech_ids, cov_ids, case_ids, has_cases = _trace_assertion_branch(
                assertion,
                assertion_to_conditions,
                condition_to_techniques,
                condition_to_coverage,
                cov_to_cases,
            )
            all_cond_ids.extend(cond_ids)
            all_tech_ids.extend(tech_ids)
            all_cov_ids.extend(cov_ids)
            all_case_ids.extend(case_ids)
            branches_covered += 1
            if has_cases:
                branches_with_cases += 1

        # 判定状态
        if not related_assertions:
            status = "gap"
        elif has_blocked_by_review_gate:
            status = "human_review"
        elif branches_with_cases >= branches_covered:
            status = "covered"
        elif branches_with_cases > 0:
            status = "partial"
        else:
            status = "partial"

        # 冲突覆盖
        if fact.status == "conflicted" and status == "covered":
            status = "conflict"

        rows.append(TraceabilityRow(
            fact_id=fact.id,
            assertion_ids=all_assertion_ids,
            condition_ids=all_cond_ids,
            technique_ids=all_tech_ids,
            coverage_item_ids=all_cov_ids,
            candidate_case_ids=all_case_ids,
            status=status,
        ))

    return TraceabilityMatrix(rows=rows)
