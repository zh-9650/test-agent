"""core/skills/asset_packager.py — N4.5 (New): TestAssetPackage Assembler.

L1 Pipeline Position:
  上游: 所有上游产物
  下游: 持久化 + 报告
  本节点职责: 组装最终的 TestAssetPackage 交付物（确定性逻辑，不调 LLM）
"""
import hashlib

from core.interfaces import (
    RequirementFact, RequirementAssertion, ExplorationGoal,
    SourceAnchor, SystemMapEvid, TestCondition, TestDesignTechnique,
    CoverageItem, CandidateTestCase, TraceabilityMatrix,
    CoverageBlueprint, TestAssetPackage,
)


def build_source_registry(
    facts: list[RequirementFact],
    source_contents: dict[str, str],
) -> list[SourceAnchor]:
    """Build auditable anchors for inline or fetched task inputs."""
    anchors: dict[str, SourceAnchor] = {}
    for fact in facts:
        if fact.source_type == "inferred" or not fact.source_reference:
            continue
        content = source_contents.get(fact.source_type, "")
        if not content:
            continue
        quote = fact.quote or ""
        start = content.find(quote) if quote else -1
        anchors[fact.source_reference] = SourceAnchor(
            source_id=fact.source_reference,
            source_type=fact.source_type,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            path_or_url=fact.source_reference,
            start_offset=start if start >= 0 else None,
            end_offset=start + len(quote) if start >= 0 else None,
            quote=quote,
            quote_hash=hashlib.sha256(quote.encode("utf-8")).hexdigest(),
            is_derived=False,
        )
    return list(anchors.values())


def _derive_source_registry_from_facts(facts: list[RequirementFact]) -> list[SourceAnchor]:
    """Derive minimal source anchors from legacy fact source references.

    M1 introduces Source Registry before the full ingestion pipeline can provide
    offset-level anchors. To keep the production path useful, the packager creates
    a conservative source anchor per non-inferred `source_reference`. This avoids
    permanent legacy warnings while still allowing direct package construction
    without registry to surface a warning in quality gates.
    """
    anchors: dict[str, SourceAnchor] = {}
    for fact in facts:
        if fact.source_type == "inferred" or not fact.source_reference:
            continue
        if fact.source_reference in anchors:
            continue
        anchors[fact.source_reference] = SourceAnchor(
            source_id=fact.source_reference,
            source_type=fact.source_type,
            content_hash="legacy-unknown",
            path_or_url=fact.source_reference,
            quote=fact.quote,
            quote_hash="legacy-unknown",
            is_derived=True,
        )
    return list(anchors.values())


def assemble_package(
    facts: list[RequirementFact],
    assertions: list[RequirementAssertion],
    source_registry: list[SourceAnchor] | None = None,
    exploration_goals: list[ExplorationGoal] | None = None,
    system_map: SystemMapEvid | None = None,
    coverage_blueprint: CoverageBlueprint | None = None,
    test_conditions: list[TestCondition] | None = None,
    test_design_techniques: list[TestDesignTechnique] | None = None,
    coverage_items: list[CoverageItem] | None = None,
    candidate_cases: list[CandidateTestCase] | None = None,
    traceability_matrix: TraceabilityMatrix | None = None,
    ambiguities: list[str] | None = None,
    conflicts: list[str] | None = None,
    manual_review_items: list[str] | None = None,
) -> TestAssetPackage:
    """N4.5 (New): 组装最终交付的 TestAssetPackage。

    确定性逻辑，不调用 LLM。
    """
    # 自动检测冲突
    detected_conflicts: list[str] = []
    for fact in facts:
        if fact.status == "conflicted":
            for ref in fact.conflict_references:
                detected_conflicts.append(f"事实 {fact.id} 与 {ref} 冲突: {fact.quote[:80]}")

    package = TestAssetPackage(
        facts=facts,
        assertions=assertions,
        source_registry=source_registry if source_registry is not None else _derive_source_registry_from_facts(facts),
        exploration_goals=exploration_goals or [],
        system_map=system_map,
        coverage_blueprint=coverage_blueprint or CoverageBlueprint(),
        test_conditions=test_conditions or [],
        test_design_techniques=test_design_techniques or [],
        coverage_items=coverage_items or [],
        candidate_cases=candidate_cases or [],
        traceability_matrix=traceability_matrix,
        ambiguities=ambiguities or [],
        conflicts=conflicts or detected_conflicts,
        manual_review_items=manual_review_items or [],
    )

    from core.skills.quality_gates import run_quality_gates
    report = run_quality_gates(package)
    package.quality_gate_report = report
    package.runtime_hints["quality_gate_passed"] = report.passed
    package.runtime_hints["quality_gate_error_count"] = sum(
        1 for finding in report.findings if finding.severity == "error"
    )
    return package
