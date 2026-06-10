"""core/skills/l2_pipeline.py — L2 Analysis Pipeline Orchestrator.

编排 L2 分析管道（fact → assertion → condition → technique → coverage → case → traceability → package）。

两阶段设计:
  Phase 1 (探索前): extract_facts → derive_assertions → review_gate → generate_goals
    - 仅从 confirmed 断言生成 ExplorationGoal
    - 被 gate 拦截的断言不会产生 goal
  Phase 2 (探索后): analyze_conditions (with system_map) → ... → assemble_package
    - 使用真实 UI 证据 (SystemMapEvid) 分析条件

Review Gate:
  仅 security/data_rule 类型的 high + auto_generated 断言会被门禁拦截，
  不会进入条件分析，而是作为 manual_review_items 标记，等待人工确认后才能继续下游流程。
"""
import hashlib

from core.interfaces import (
    RequirementFact, RequirementAssertion, ExplorationGoal,
    SystemMapEvid, TestCondition, TestDesignTechnique,
    CoverageItem, CandidateTestCase, TraceabilityMatrix,
    TestAssetPackage,
)


def _split_by_review_gate(
    assertions: list[RequirementAssertion],
) -> tuple[list[RequirementAssertion], list[RequirementAssertion]]:
    """Review Gate: 将断言分为"已确认可进入下游"和"需人工审查"两组。

    规则 (优化后，降低拦截率):
    - review_status == "rejected" → 丢弃（不进入任何组）
    - risk_level == "high" AND review_status == "auto_generated" AND
      assertion_type in (security, data_rule) → 需人工审查 (仅核心安全/数据规则)
    - 其他 (low/medium, 或已 human_confirmed, 或非核心类型) → 可进入下游

    设计理由:
    - security 和 data_rule 类型的高风险断言涉及权限和数据完整性，必须人工确认
    - functional/validation/error_handling 等类型的高风险断言可直接放行
    - 目标拦截率从 ~32% 降至 ~15%
    """
    GATE_TYPES = {"security", "data_rule"}
    passed: list[RequirementAssertion] = []
    blocked: list[RequirementAssertion] = []
    for a in assertions:
        if a.review_status == "rejected":
            continue
        if (a.risk_level == "high"
                and a.review_status == "auto_generated"
                and a.assertion_type in GATE_TYPES):
            blocked.append(a)
        else:
            passed.append(a)
    return passed, blocked


def _manual_review_label(assertion: RequirementAssertion) -> str:
    return (
        f"[高风险需人工确认] {assertion.id}: {assertion.assertion_text} "
        f"(源自事实: {', '.join(assertion.fact_ids)})"
    )


def _dedupe_manual_review_items(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def _normalize_goal_assertion_text(text: str) -> str:
    """规范化断言文本，用于稳定的语义 ID 计算。"""
    return " ".join(text.split()).casefold()



def _goals_from_confirmed_assertions(
    confirmed: list[RequirementAssertion],
) -> list[ExplorationGoal]:
    """仅从已确认断言生成探索目标（不包含被 gate 拦截的断言）。

    优先级映射规则 (解决所有 goals 均为 medium 的问题):
    - 原始 high 风险但已通过 gate (human_confirmed) → high
    - assertion_type 为 security/data_rule/state_transition → high (核心业务规则)
    - assertion_type 为 validation/error_handling → medium
    - assertion_type 为 functional 且 risk_level=medium → medium
    - assertion_type 为 functional 且 risk_level=low → low
    - 其余 → medium

    Goal ID 规则:
    - 仅基于断言语义字段生成稳定 ID（sorted fact_ids + normalized assertion_text + assertion_type）
    - risk_level 只参与 priority 计算，不参与 goal id hash，避免同语义断言因风险分级变化而产生新 ID
    """
    # 高优先级断言类型：涉及核心业务规则和安全
    HIGH_TYPES = {"security", "data_rule", "state_transition"}
    # 中优先级断言类型：功能验证和校验
    MEDIUM_TYPES = {"validation", "error_handling", "functional"}

    goals: list[ExplorationGoal] = []
    for a in confirmed:
        if a.risk_level == "low" and a.assertion_type == "functional":
            priority = "low"
        elif a.risk_level == "high" or a.assertion_type in HIGH_TYPES:
            priority = "high"
        elif a.assertion_type in MEDIUM_TYPES:
            priority = "medium"
        else:
            priority = "medium"

        semantic_parts = [
            ",".join(sorted(a.fact_ids)),
            _normalize_goal_assertion_text(a.assertion_text),
            a.assertion_type,
        ]
        normalized = "|".join(semantic_parts)
        goal_id = "GOAL-" + hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
        expected = f"页面或系统状态能证明：{a.assertion_text}"
        goals.append(ExplorationGoal(
            id=goal_id,
            assertion_refs=[a.id],
            goal=f"验证: {a.assertion_text[:80]}",
            expected_evidence=[expected],
            stop_condition=f"已观察到支持断言 {a.id} 的证据，或达到探索限制后标记 evidence_gap",
            priority=priority,
            source_refs=list(a.source_references or a.fact_ids),
        ))
    return goals


async def generate_exploration_goals(
    prd_content: str = "",
    api_doc_content: str = "",
    changelog_content: str = "",
    prototype_notes: str = "",
    architecture_notes: str = "",
    rules: str = "",
) -> tuple[list[ExplorationGoal], list[str], list[RequirementFact], list[RequirementAssertion]]:
    """Phase 1 (探索前): 提取事实 → 推导断言 → review gate → 生成探索目标。

    仅从 confirmed 断言生成 goal，被 gate 拦截的高风险断言不会驱动探索。

    Returns:
        (exploration_goals, manual_review_items, facts, assertions)
        facts 和 assertions 供 Phase 2 复用，避免重复 LLM 调用。
    """
    from core.skills.fact_extractor import extract_facts
    from core.skills.assertion_deriver import derive_assertions

    facts = await extract_facts(
        prd_content=prd_content,
        api_doc_content=api_doc_content,
        changelog_content=changelog_content,
        prototype_notes=prototype_notes,
        architecture_notes=architecture_notes,
        rules=rules,
    )
    if not facts:
        return [], [], [], []

    assertions = await derive_assertions(facts)
    if not assertions:
        return [], [], facts, []

    confirmed, blocked = _split_by_review_gate(assertions)
    manual_review_items = [_manual_review_label(a) for a in blocked]

    goals = _goals_from_confirmed_assertions(confirmed)
    print(f"[L2Pipeline] Phase 1: {len(facts)} facts, {len(assertions)} assertions, "
          f"{len(confirmed)} confirmed, {len(blocked)} blocked, {len(goals)} goals.")

    return goals, manual_review_items, facts, assertions


async def run_l2_pipeline(
    prd_content: str = "",
    api_doc_content: str = "",
    changelog_content: str = "",
    prototype_notes: str = "",
    architecture_notes: str = "",
    rules: str = "",
    system_map: SystemMapEvid | None = None,
    precomputed_facts: list[RequirementFact] | None = None,
    precomputed_assertions: list[RequirementAssertion] | None = None,
    precomputed_goals: list[ExplorationGoal] | None = None,
    precomputed_review_items: list[str] | None = None,
) -> TestAssetPackage:
    """Phase 2 (探索后): 运行完整的 L2 分析管道。

    可接受 Phase 1 的预计算结果 (facts/assertions/goals) 以避免重复 LLM 调用。
    若未提供预计算结果，则从头提取。

    执行顺序:
    1. extract_facts (或复用 precomputed) → 2. derive_assertions (或复用)
    3. [Review Gate] 高风险 auto_generated 断言被拦截
    4. analyze_conditions (仅已确认断言, 需要 system_map)
    5. select_techniques → 6. analyze_coverage → 7. generate_cases
    8. build_traceability → 9. assemble_package
    """
    from core.skills.asset_packager import assemble_package

    # --- Phase 1 数据: 复用或重新提取 ---
    if precomputed_facts is not None and precomputed_assertions is not None:
        facts = precomputed_facts
        assertions = precomputed_assertions
        exploration_goals = precomputed_goals or []
        manual_review_items = precomputed_review_items or []
        print(f"[L2Pipeline] Phase 2: reusing {len(facts)} facts, {len(assertions)} assertions from Phase 1.")
    else:
        goals, manual_review_items, facts, assertions = await generate_exploration_goals(
            prd_content=prd_content,
            api_doc_content=api_doc_content,
            changelog_content=changelog_content,
            prototype_notes=prototype_notes,
            architecture_notes=architecture_notes,
            rules=rules,
        )
        exploration_goals = goals

    if not facts:
        return TestAssetPackage()

    if not assertions:
        return assemble_package(facts=facts, assertions=[])

    # --- Review Gate (无论是否 precomputed，统一复用同一门禁逻辑) ---
    confirmed_assertions, blocked_assertions = _split_by_review_gate(assertions)
    blocked_review_items = [_manual_review_label(a) for a in blocked_assertions]
    manual_review_items = _dedupe_manual_review_items((manual_review_items or []) + blocked_review_items)

    if not confirmed_assertions:
        # 即使没有 confirmed assertions，也要构建 traceability，
        # 确保 blocked assertions 保留在追溯矩阵中（status=human_review）。
        from core.skills.traceability_builder import build_traceability
        traceability = build_traceability(facts, assertions, [], [], [], [])
        return assemble_package(
            facts=facts,
            assertions=assertions,
            exploration_goals=exploration_goals,
            traceability_matrix=traceability,
            manual_review_items=manual_review_items,
        )

    # --- Phase 2 核心: 条件分析需要 system_map ---
    if system_map is None:
        print("[L2Pipeline] 警告: system_map 为空，条件分析将仅基于文档断言，无真实 UI 证据。")

    from core.skills.condition_analyzer import analyze_conditions
    from core.skills.technique_selector import select_techniques
    from core.skills.coverage_analyzer import analyze_coverage
    from core.skills.case_generator import generate_cases
    from core.skills.traceability_builder import build_traceability

    conditions = await analyze_conditions(confirmed_assertions, system_map)
    if not conditions:
        from core.skills.traceability_builder import build_traceability
        traceability = build_traceability(facts, assertions, [], [], [], [])
        return assemble_package(
            facts=facts,
            assertions=assertions,
            exploration_goals=exploration_goals,
            traceability_matrix=traceability,
            manual_review_items=manual_review_items,
        )

    techniques = await select_techniques(conditions)
    coverage_items = await analyze_coverage(conditions, techniques)
    cases = await generate_cases(coverage_items)
    traceability = build_traceability(
        facts, assertions, conditions, techniques, coverage_items, cases
    )

    package = assemble_package(
        facts=facts,
        assertions=assertions,
        exploration_goals=exploration_goals,
        system_map=system_map,
        test_conditions=conditions,
        test_design_techniques=techniques,
        coverage_items=coverage_items,
        candidate_cases=cases,
        traceability_matrix=traceability,
        manual_review_items=manual_review_items,
    )

    return package
