from __future__ import annotations

"""deterministic quality gates for TestAssetPackage."""

from core.interfaces import QualityGateFinding, QualityGateReport, TestAssetPackage


def _is_blank(value: str | None) -> bool:
    return value is None or not value.strip()


def _add_finding(
    findings: list[QualityGateFinding],
    *,
    code: str,
    message: str,
    artifact_type: str,
    artifact_id: str,
    severity: str = "error",
) -> None:
    findings.append(
        QualityGateFinding(
            code=code,
            severity=severity,
            message=message,
            artifact_type=artifact_type,
            artifact_id=artifact_id,
        )
    )


def run_quality_gates(package: TestAssetPackage) -> QualityGateReport:
    """运行确定性质量门，检查完整追溯链和引用完整性。"""
    findings: list[QualityGateFinding] = []

    # --- Source Registry ---
    source_ids = {anchor.source_id for anchor in package.source_registry}
    real_anchor_ids = {anchor.source_id for anchor in package.source_registry if not anchor.is_derived}
    fact_ids = {fact.id for fact in package.facts}
    assertion_ids = {assertion.id for assertion in package.assertions}

    # 如果有 source_registry 但全部是 derived（legacy 占位），标记为不可信
    if package.source_registry and not real_anchor_ids:
        _add_finding(
            findings,
            code="no_real_source_anchor",
            message="source_registry 中没有真实来源锚点（全部为 legacy 自动派生），groundedness 不可验证。",
            artifact_type="source_registry",
            artifact_id="",
        )

    for anchor in package.source_registry:
        if anchor.is_derived:
            _add_finding(
                findings,
                code="derived_legacy_source_anchor",
                message=f"来源 {anchor.source_id} 由 legacy source_reference 自动派生，缺少 offset 级证据。",
                artifact_type="source_anchor",
                artifact_id=anchor.source_id,
                severity="warning",
            )

    for fact in package.facts:
        if fact.source_type != "inferred" and _is_blank(fact.quote):
            _add_finding(
                findings,
                code="missing_fact_quote",
                message=f"事实 {fact.id} 缺少可审计原文引用。",
                artifact_type="fact",
                artifact_id=fact.id,
            )

        if fact.source_type != "inferred":
            if not source_ids:
                _add_finding(
                    findings,
                    code="missing_source_registry",
                    message=f"事实 {fact.id} 缺少可校验的 source_registry。",
                    artifact_type="fact",
                    artifact_id=fact.id,
                )
            elif fact.source_reference not in source_ids:
                _add_finding(
                    findings,
                    code="invalid_fact_source_reference",
                    message=f"事实 {fact.id} 的 source_reference 未在 source_registry 中注册。",
                    artifact_type="fact",
                    artifact_id=fact.id,
                )

    for assertion in package.assertions:
        missing_fact_ids = [fact_id for fact_id in assertion.fact_ids if fact_id not in fact_ids]
        for missing_fact_id in missing_fact_ids:
            _add_finding(
                findings,
                code="dangling_assertion_fact_ref",
                message=f"断言 {assertion.id} 引用了不存在的事实 {missing_fact_id}。",
                artifact_type="assertion",
                artifact_id=assertion.id,
            )

    for goal in package.exploration_goals:
        if _is_blank(goal.id):
            _add_finding(
                findings,
                code="missing_goal_id",
                message="探索目标缺少稳定 ID。",
                artifact_type="exploration_goal",
                artifact_id=goal.id,
            )

        non_blank_evidence = [item for item in goal.expected_evidence if not _is_blank(item)]
        if not non_blank_evidence:
            _add_finding(
                findings,
                code="missing_goal_expected_evidence",
                message=f"探索目标 {goal.id or '<unknown>'} 缺少 expected_evidence。",
                artifact_type="exploration_goal",
                artifact_id=goal.id,
            )

        if _is_blank(goal.stop_condition):
            _add_finding(
                findings,
                code="missing_goal_stop_condition",
                message=f"探索目标 {goal.id or '<unknown>'} 缺少 stop_condition。",
                artifact_type="exploration_goal",
                artifact_id=goal.id,
            )

        if not goal.assertion_refs:
            _add_finding(
                findings,
                code="missing_goal_assertion_refs",
                message=f"探索目标 {goal.id or '<unknown>'} 缺少 assertion_refs。",
                artifact_type="exploration_goal",
                artifact_id=goal.id,
            )
            continue

        missing_assertion_ids = [assertion_id for assertion_id in goal.assertion_refs if assertion_id not in assertion_ids]
        for missing_assertion_id in missing_assertion_ids:
            _add_finding(
                findings,
                code="dangling_goal_assertion_ref",
                message=f"探索目标 {goal.id or '<unknown>'} 引用了不存在的断言 {missing_assertion_id}。",
                artifact_type="exploration_goal",
                artifact_id=goal.id,
            )

    # --- 下游引用检查: Condition / Technique / Coverage / CandidateCase ---
    condition_ids = {c.id for c in package.test_conditions}
    technique_ids = {t.id for t in package.test_design_techniques}
    coverage_ids = {c.id for c in package.coverage_items}
    case_ids = {c.id for c in package.candidate_cases}

    for cond in package.test_conditions:
        if cond.assertion_ref not in assertion_ids:
            _add_finding(
                findings,
                code="dangling_condition_assertion_ref",
                message=f"条件 {cond.id} 引用了不存在的断言 {cond.assertion_ref}。",
                artifact_type="test_condition",
                artifact_id=cond.id,
            )

    for tech in package.test_design_techniques:
        if tech.condition_id not in condition_ids:
            _add_finding(
                findings,
                code="dangling_technique_condition_ref",
                message=f"技术 {tech.id} 引用了不存在的条件 {tech.condition_id}。",
                artifact_type="test_design_technique",
                artifact_id=tech.id,
            )

    for cov in package.coverage_items:
        if cov.condition_id not in condition_ids:
            _add_finding(
                findings,
                code="dangling_coverage_condition_ref",
                message=f"覆盖项 {cov.id} 引用了不存在的条件 {cov.condition_id}。",
                artifact_type="coverage_item",
                artifact_id=cov.id,
            )
        if cov.technique_id not in technique_ids:
            _add_finding(
                findings,
                code="dangling_coverage_technique_ref",
                message=f"覆盖项 {cov.id} 引用了不存在的技术 {cov.technique_id}。",
                artifact_type="coverage_item",
                artifact_id=cov.id,
            )

    for case in package.candidate_cases:
        for ref in case.trace_references:
            if ref not in coverage_ids:
                _add_finding(
                    findings,
                    code="dangling_case_coverage_ref",
                    message=f"候选用例 {case.id} 引用了不存在的覆盖项 {ref}。",
                    artifact_type="candidate_test_case",
                    artifact_id=case.id,
                )

    # --- TraceabilityMatrix 引用检查 ---
    if package.traceability_matrix:
        for row in package.traceability_matrix.rows:
            if row.fact_id not in fact_ids:
                _add_finding(
                    findings,
                    code="dangling_traceability_fact_ref",
                    message=f"追溯行引用了不存在的事实 {row.fact_id}。",
                    artifact_type="traceability_matrix",
                    artifact_id=row.fact_id,
                )
            for aid in row.assertion_ids:
                if aid not in assertion_ids:
                    _add_finding(
                        findings,
                        code="dangling_traceability_assertion_ref",
                        message=f"追溯行 {row.fact_id} 引用了不存在的断言 {aid}。",
                        artifact_type="traceability_matrix",
                        artifact_id=row.fact_id,
                    )
            for cid in row.condition_ids:
                if cid not in condition_ids:
                    _add_finding(
                        findings,
                        code="dangling_traceability_condition_ref",
                        message=f"追溯行 {row.fact_id} 引用了不存在的条件 {cid}。",
                        artifact_type="traceability_matrix",
                        artifact_id=row.fact_id,
                    )
            for tid in row.technique_ids:
                if tid not in technique_ids:
                    _add_finding(
                        findings,
                        code="dangling_traceability_technique_ref",
                        message=f"追溯行 {row.fact_id} 引用了不存在的技术 {tid}。",
                        artifact_type="traceability_matrix",
                        artifact_id=row.fact_id,
                    )
            for cid in row.coverage_item_ids:
                if cid not in coverage_ids:
                    _add_finding(
                        findings,
                        code="dangling_traceability_coverage_ref",
                        message=f"追溯行 {row.fact_id} 引用了不存在的覆盖项 {cid}。",
                        artifact_type="traceability_matrix",
                        artifact_id=row.fact_id,
                    )
            for cid in row.candidate_case_ids:
                if cid not in case_ids:
                    _add_finding(
                        findings,
                        code="dangling_traceability_case_ref",
                        message=f"追溯行 {row.fact_id} 引用了不存在的候选用例 {cid}。",
                        artifact_type="traceability_matrix",
                        artifact_id=row.fact_id,
                    )

    # --- 重复 ID 检查 ---
    _check_duplicate_ids(findings, "fact", [f.id for f in package.facts])
    _check_duplicate_ids(findings, "assertion", [a.id for a in package.assertions])
    _check_duplicate_ids(findings, "condition", [c.id for c in package.test_conditions])
    _check_duplicate_ids(findings, "technique", [t.id for t in package.test_design_techniques])
    _check_duplicate_ids(findings, "coverage_item", [c.id for c in package.coverage_items])
    _check_duplicate_ids(findings, "candidate_case", [c.id for c in package.candidate_cases])

    # --- Schema 版本校验 (W2 修复) ---
    for case in package.candidate_cases:
        if _is_blank(getattr(case, "schema_version", "")):
            _add_finding(
                findings,
                code="missing_schema_version",
                message=f"候选用例 {case.id} 缺少 schema_version，无法进行 schema 版本校验。",
                artifact_type="candidate_test_case",
                artifact_id=case.id,
            )

    # --- required_roles 验证 (W3 修复) ---
    # 如果用例包含 account_role 类型的前置条件 (通过 StructuredPrecondition 表达)，
    # 但 required_roles 为空，则该用例可能无法解析账号角色。
    # 注意：当前 CandidateTestCase.preconditions 是 list[str]，尚未结构化。
    # 此检查仅验证新的 required_roles 字段（如果该用例通过 adapter 已升级）。
    for case in package.candidate_cases:
        required_roles = getattr(case, "required_roles", [])
        if not required_roles:
            # 检查 preconditions 是否包含 account_role 关键词
            precond_text = " ".join(case.preconditions or []).lower()
            has_role_keyword = any(
                kw in precond_text
                for kw in ("登录", "login", "账号", "角色", "权限", "role", "admin")
            )
            if has_role_keyword:
                _add_finding(
                    findings,
                    code="missing_required_roles",
                    message=f"候选用例 {case.id} 的前置条件涉及账号角色，但 required_roles 为空。",
                    artifact_type="candidate_test_case",
                    artifact_id=case.id,
                    severity="warning",
                )

    return QualityGateReport(
        passed=not any(finding.severity == "error" for finding in findings),
        findings=findings,
    )


def _check_duplicate_ids(
    findings: list[QualityGateFinding],
    artifact_type: str,
    ids: list[str],
) -> None:
    """检查重复 ID。"""
    seen: set[str] = set()
    for id_ in ids:
        if id_ in seen:
            _add_finding(
                findings,
                code=f"duplicate_{artifact_type}_id",
                message=f"存在重复的 {artifact_type} ID: {id_}。",
                artifact_type=artifact_type,
                artifact_id=id_,
            )
        seen.add(id_)
