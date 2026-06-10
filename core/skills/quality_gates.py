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
    """运行确定性质量门，检查最基础的引用完整性和必填证据字段。"""
    findings: list[QualityGateFinding] = []

    source_ids = {anchor.source_id for anchor in package.source_registry}
    fact_ids = {fact.id for fact in package.facts}
    assertion_ids = {assertion.id for assertion in package.assertions}

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
                    severity="warning",
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

    return QualityGateReport(
        passed=not any(finding.severity == "error" for finding in findings),
        findings=findings,
    )
