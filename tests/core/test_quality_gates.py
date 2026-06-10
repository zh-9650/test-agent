from __future__ import annotations

from core.interfaces import RequirementFact, RequirementAssertion, ExplorationGoal, TestAssetPackage as AssetPackage


def _strict_goal() -> ExplorationGoal:
    return ExplorationGoal(
        id="GOAL-1",
        assertion_refs=["ASSERT-1"],
        goal="验证登录",
        expected_evidence=["看到首页"],
        stop_condition="看到首页后停止",
        priority="high",
        source_refs=["FACT-1"],
    )


def test_source_anchor_model_supports_grounding_fields():
    from core.interfaces import SourceAnchor

    anchor = SourceAnchor(
        source_id="SRC-001",
        source_type="prd",
        content_hash="abc123",
        path_or_url="requirements.md",
        start_offset=10,
        end_offset=20,
        quote="用户可以登录",
        quote_hash="def456",
    )

    assert anchor.schema_version == "source_anchor.v1"
    assert anchor.source_id == "SRC-001"


def test_quality_gate_detects_invalid_goal_assertion_ref():
    from core.skills.quality_gates import run_quality_gates

    package = AssetPackage(
        facts=[RequirementFact(
            id="FACT-1", source_type="prd", source_reference="SRC-1",
            quote="用户可以登录", subject="用户", action="登录", confidence=1.0,
        )],
        assertions=[],
        exploration_goals=[_strict_goal()],
    )

    report = run_quality_gates(package)

    assert not report.passed
    assert any(f.code == "dangling_goal_assertion_ref" for f in report.findings)


def test_quality_gate_warns_missing_source_registry_for_non_inferred_fact():
    from core.skills.quality_gates import run_quality_gates

    package = AssetPackage(
        facts=[RequirementFact(
            id="FACT-1", source_type="prd", source_reference="SRC-1",
            quote="用户可以登录", subject="用户", action="登录", confidence=1.0,
        )],
    )

    report = run_quality_gates(package)

    assert report.passed
    finding = next(f for f in report.findings if f.code == "missing_source_registry")
    assert finding.severity == "warning"


def test_quality_gate_allows_inferred_fact_without_source_registry():
    from core.skills.quality_gates import run_quality_gates

    package = AssetPackage(
        facts=[RequirementFact(
            id="FACT-1", source_type="inferred", source_reference="推断自 PRD 上下文",
            quote="根据上下文推断", subject="用户", action="登录", confidence=0.5,
        )],
    )

    report = run_quality_gates(package)

    assert report.passed
    assert not any(f.code == "missing_source_registry" for f in report.findings)


def test_quality_gate_passes_valid_minimal_package():
    from core.interfaces import SourceAnchor
    from core.skills.quality_gates import run_quality_gates

    package = AssetPackage(
        source_registry=[SourceAnchor(
            source_id="SRC-1", source_type="prd", content_hash="hash",
            path_or_url="requirements.md", quote="用户可以登录", quote_hash="qh",
        )],
        facts=[RequirementFact(
            id="FACT-1", source_type="prd", source_reference="SRC-1",
            quote="用户可以登录", subject="用户", action="登录", confidence=1.0,
        )],
        assertions=[RequirementAssertion(
            id="ASSERT-1", fact_ids=["FACT-1"], assertion_text="用户必须可以登录",
            assertion_type="functional", risk_level="high", source_references=["FACT-1"],
        )],
        exploration_goals=[_strict_goal()],
    )

    report = run_quality_gates(package)

    assert report.passed
    assert report.findings == []


def test_quality_gate_detects_invalid_fact_source_reference_when_registry_exists():
    from core.interfaces import SourceAnchor
    from core.skills.quality_gates import run_quality_gates

    package = AssetPackage(
        source_registry=[SourceAnchor(
            source_id="SRC-1", source_type="prd", content_hash="hash",
            path_or_url="requirements.md", quote="用户可以登录", quote_hash="qh",
        )],
        facts=[RequirementFact(
            id="FACT-1", source_type="prd", source_reference="LEGACY-REF",
            quote="用户可以登录", subject="用户", action="登录", confidence=1.0,
        )],
    )

    report = run_quality_gates(package)

    assert not report.passed
    finding = next(f for f in report.findings if f.code == "invalid_fact_source_reference")
    assert finding.severity == "error"


def test_asset_packager_derives_source_registry_for_legacy_call():
    from core.skills.asset_packager import assemble_package

    package = assemble_package(
        facts=[RequirementFact(
            id="FACT-1", source_type="prd", source_reference="PRD §1",
            quote="用户可以登录", subject="用户", action="登录", confidence=1.0,
        )],
        assertions=[RequirementAssertion(
            id="ASSERT-1", fact_ids=["FACT-1"], assertion_text="用户必须可以登录",
            assertion_type="functional", risk_level="high", source_references=["FACT-1"],
        )],
        exploration_goals=[_strict_goal()],
    )

    assert package.source_registry
    assert package.source_registry[0].source_id == "PRD §1"
    assert package.source_registry[0].is_derived is True
    assert package.quality_gate_report is not None
    assert package.quality_gate_report.passed
    assert package.runtime_hints["quality_gate_passed"] is True
    assert not any(
        f.code == "missing_source_registry"
        for f in package.quality_gate_report.findings
    )
    warning = next(f for f in package.quality_gate_report.findings if f.code == "derived_legacy_source_anchor")
    assert warning.severity == "warning"


def test_asset_packager_attaches_quality_gate_report():
    from core.interfaces import SourceAnchor
    from core.skills.asset_packager import assemble_package

    package = assemble_package(
        source_registry=[SourceAnchor(
            source_id="SRC-1", source_type="prd", content_hash="hash",
            path_or_url="requirements.md", quote="用户可以登录", quote_hash="qh",
        )],
        facts=[RequirementFact(
            id="FACT-1", source_type="prd", source_reference="SRC-1",
            quote="用户可以登录", subject="用户", action="登录", confidence=1.0,
        )],
        assertions=[RequirementAssertion(
            id="ASSERT-1", fact_ids=["FACT-1"], assertion_text="用户必须可以登录",
            assertion_type="functional", risk_level="high", source_references=["FACT-1"],
        )],
        exploration_goals=[_strict_goal()],
    )

    assert package.quality_gate_report is not None
    assert package.quality_gate_report.passed
    assert package.runtime_hints["quality_gate_passed"] is True
    assert package.runtime_hints["quality_gate_error_count"] == 0
