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


def adapt_legacy_goal(raw: dict) -> ExplorationGoal:
    """将旧格式 goal dict 转换为严格 ExplorationGoal，标记为 legacy。

    旧格式可能缺少 id / assertion_refs / expected_evidence / stop_condition。
    本函数在缺失时填充默认值，避免旧数据直接导致 model_validate 报错。
    """
    goal_text = raw.get("goal", "")
    priority = raw.get("priority", "medium")
    if priority not in ("high", "medium", "low"):
        priority = "medium"

    goal_id = raw.get("id") or _stable_hash("GOAL", goal_text, priority)
    assertion_refs = raw.get("assertion_refs") or []
    expected_evidence = raw.get("expected_evidence") or (
        [f"页面或系统状态能证明：{goal_text}"] if goal_text else []
    )
    stop_condition = raw.get("stop_condition") or (
        f"已观察到支持 {goal_text[:60]} 的证据，或达到探索限制" if goal_text else ""
    )
    source_refs = raw.get("source_refs") or []

    return ExplorationGoal(
        schema_version="exploration_goal.v2-legacy",
        id=goal_id,
        assertion_refs=assertion_refs or ["LEGACY"],
        goal=goal_text or "未知目标",
        expected_evidence=expected_evidence,
        stop_condition=stop_condition,
        priority=priority,
        source_refs=source_refs,
    )


def adapt_legacy_goals(raw_goals: list[dict]) -> list[ExplorationGoal]:
    """批量转换旧格式 goal dicts 为严格 ExplorationGoal。"""
    return [adapt_legacy_goal(g) for g in raw_goals if isinstance(g, dict)]


def _stable_hash(prefix: str, *parts: str) -> str:
    """基于内容生成稳定短哈希 ID。"""
    normalized = "|".join(p.strip().casefold() for p in parts)
    return f"{prefix}-{hashlib.sha1(normalized.encode('utf-8')).hexdigest()[:10]}"


def _normalize_all_ids(package: TestAssetPackage) -> TestAssetPackage:
    """后处理：将所有产物 ID 归一化为内容寻址 ID，并更新所有交叉引用。

    LLM 生成的顺序 ID (FACT-001, ASSERT-001 等) 只在 prompt 层保留，
    此函数在 package 组装完成后统一重写，确保：
    - 相同语义内容生成相同 ID
    - 所有下游引用保持一致
    - 模型输出的 ID 不影响最终包的稳定性
    """
    # --- 1. 为每种产物生成新 ID ---
    old_to_new: dict[str, str] = {}

    for fact in package.facts:
        new_id = _stable_hash(
            "FACT",
            fact.source_type, fact.subject, fact.action,
            fact.object or "", fact.condition or "", fact.outcome or "",
            fact.quote[:120],
        )
        old_to_new[fact.id] = new_id

    for assertion in package.assertions:
        new_id = _stable_hash(
            "ASSERT",
            ",".join(sorted(assertion.fact_ids)),
            assertion.assertion_text,
            assertion.assertion_type,
        )
        old_to_new[assertion.id] = new_id

    for cond in package.test_conditions:
        new_id = _stable_hash(
            "COND",
            old_to_new.get(cond.assertion_ref, cond.assertion_ref),
            cond.condition_type,
            cond.statement[:120],
        )
        old_to_new[cond.id] = new_id

    for tech in package.test_design_techniques:
        new_id = _stable_hash(
            "TECH",
            old_to_new.get(tech.condition_id, tech.condition_id),
            tech.primary_technique,
        )
        old_to_new[tech.id] = new_id

    for cov in package.coverage_items:
        new_id = _stable_hash(
            "COV",
            old_to_new.get(cov.condition_id, cov.condition_id),
            old_to_new.get(cov.technique_id, cov.technique_id),
            cov.coverage_dimension,
            cov.goal[:80],
        )
        old_to_new[cov.id] = new_id

    for case in package.candidate_cases:
        new_id = _stable_hash(
            "TC",
            ",".join(sorted(old_to_new.get(r, r) for r in case.trace_references)),
            case.goal[:80],
            case.expected_result[:80],
        )
        old_to_new[case.id] = new_id

    # --- 2. 更新所有交叉引用 ---
    # Facts
    new_facts = []
    for f in package.facts:
        new_f = f.model_copy(update={"id": old_to_new[f.id]})
        new_facts.append(new_f)

    # Assertions
    new_assertions = []
    for a in package.assertions:
        new_a = a.model_copy(update={
            "id": old_to_new[a.id],
            "fact_ids": [old_to_new.get(fid, fid) for fid in a.fact_ids],
        })
        new_assertions.append(new_a)

    # Goals — 更新 assertion_refs
    new_goals = []
    for g in package.exploration_goals:
        new_g = g.model_copy(update={
            "assertion_refs": [old_to_new.get(aid, aid) for aid in g.assertion_refs],
        })
        new_goals.append(new_g)

    # Conditions
    new_conditions = []
    for c in package.test_conditions:
        new_c = c.model_copy(update={
            "id": old_to_new[c.id],
            "assertion_ref": old_to_new.get(c.assertion_ref, c.assertion_ref),
        })
        new_conditions.append(new_c)

    # Techniques
    new_techniques = []
    for t in package.test_design_techniques:
        new_t = t.model_copy(update={
            "id": old_to_new[t.id],
            "condition_id": old_to_new.get(t.condition_id, t.condition_id),
        })
        new_techniques.append(new_t)

    # Coverage items
    new_covs = []
    for c in package.coverage_items:
        new_c = c.model_copy(update={
            "id": old_to_new[c.id],
            "condition_id": old_to_new.get(c.condition_id, c.condition_id),
            "technique_id": old_to_new.get(c.technique_id, c.technique_id),
        })
        new_covs.append(new_c)

    # Candidate cases
    new_cases = []
    for c in package.candidate_cases:
        new_c = c.model_copy(update={
            "id": old_to_new[c.id],
            "trace_references": [old_to_new.get(r, r) for r in c.trace_references],
        })
        new_cases.append(new_c)

    # Traceability matrix
    new_tm = None
    if package.traceability_matrix:
        new_rows = []
        for row in package.traceability_matrix.rows:
            new_rows.append(row.model_copy(update={
                "fact_id": old_to_new.get(row.fact_id, row.fact_id),
                "assertion_ids": [old_to_new.get(aid, aid) for aid in row.assertion_ids],
                "condition_ids": [old_to_new.get(cid, cid) for cid in row.condition_ids],
                "technique_ids": [old_to_new.get(tid, tid) for tid in row.technique_ids],
                "coverage_item_ids": [old_to_new.get(cid, cid) for cid in row.coverage_item_ids],
                "candidate_case_ids": [old_to_new.get(cid, cid) for cid in row.candidate_case_ids],
            }))
        new_tm = package.traceability_matrix.model_copy(update={"rows": new_rows})

    # --- 3. 重新组装 package ---
    package_dict = package.model_dump()
    package_dict["facts"] = [f.model_dump() for f in new_facts]
    package_dict["assertions"] = [a.model_dump() for a in new_assertions]
    package_dict["exploration_goals"] = [g.model_dump() for g in new_goals]
    package_dict["test_conditions"] = [c.model_dump() for c in new_conditions]
    package_dict["test_design_techniques"] = [t.model_dump() for t in new_techniques]
    package_dict["coverage_items"] = [c.model_dump() for c in new_covs]
    package_dict["candidate_cases"] = [c.model_dump() for c in new_cases]
    if new_tm:
        package_dict["traceability_matrix"] = new_tm.model_dump()

    package_dict["runtime_hints"]["id_mapping"] = old_to_new
    package_dict["runtime_hints"]["id_normalization_version"] = "content-addressed.v1"

    return TestAssetPackage.model_validate(package_dict)



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

    # 后处理：将所有 LLM 生成的顺序 ID 归一化为内容寻址 ID
    package = _normalize_all_ids(package)

    return package
