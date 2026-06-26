import json
from pathlib import Path

import pytest

from core.human_oracle import (
    evaluate_test_asset_package,
    load_human_oracle,
    main,
)
from core.interfaces import (
    ActionMap,
    CandidateTestCase,
    FormMap,
    NavigationMap,
    PageMap,
    QualityGateReport,
    RequirementAssertion,
    RequirementFact,
    SystemMapEvid,
    TestAssetPackage as AssetPackage,
    TraceabilityMatrix,
    TraceabilityRow,
)


FIXTURE_ROOT = Path(__file__).parents[2] / "data" / "fixtures"
ORACLE_ROOT = FIXTURE_ROOT / "oracles"


def _fact(
    fact_id: str,
    text: str,
    *,
    status: str = "confirmed",
) -> RequirementFact:
    return RequirementFact(
        id=fact_id,
        source_type="prd",
        source_reference="prd_purchase.md",
        quote=text,
        subject=text,
        action="验证",
        confidence=0.95,
        status=status,
    )


def _assertion(
    assertion_id: str,
    fact_id: str,
    text: str,
    *,
    assertion_type: str = "functional",
) -> RequirementAssertion:
    return RequirementAssertion(
        id=assertion_id,
        fact_ids=[fact_id],
        assertion_text=text,
        assertion_type=assertion_type,
        risk_level="medium",
        source_references=["prd_purchase.md"],
    )


def _case(
    case_id: str,
    title: str,
    branch_type: str,
) -> CandidateTestCase:
    return CandidateTestCase(
        id=case_id,
        title=title,
        goal=title,
        expected_result=title,
        trace_references=[f"COV-{case_id}"],
        branch_type=branch_type,
    )


def _package_with_contract(
    *,
    facts: list[RequirementFact],
    assertions: list[RequirementAssertion],
    cases: list[CandidateTestCase],
    system_map: SystemMapEvid | None,
) -> AssetPackage:
    return AssetPackage(
        facts=facts,
        assertions=assertions,
        system_map=system_map,
        candidate_cases=cases,
        traceability_matrix=TraceabilityMatrix(
            rows=[
                TraceabilityRow(
                    fact_id=facts[0].id,
                    assertion_ids=[assertions[0].id] if assertions else [],
                    candidate_case_ids=[case.id for case in cases],
                    status="covered",
                )
            ]
        ),
        quality_gate_report=QualityGateReport(passed=True),
    )


def _purchase_package() -> AssetPackage:
    facts = [
        _fact("FACT-1", "任何员工都可以提交采购申请"),
        _fact("FACT-2", "采购金额高于 5000 元时由部门经理审批"),
        _fact("FACT-3", "采购金额超过 10000 元时由总监审批"),
        _fact("FACT-4", "审批通过后进入待付款，财务确认打款"),
        _fact("FACT-5", "核心状态为草稿、待审批、待付款、已完成"),
        _fact("FACT-6", "申请被驳回后返回草稿"),
    ]
    assertions = [
        _assertion("ASSERT-1", "FACT-2", "超过5000元必须由部门经理审批"),
        _assertion("ASSERT-2", "FACT-3", "超过10000元必须由总监审批"),
        _assertion(
            "ASSERT-3",
            "FACT-5",
            "草稿进入待审批，审批通过后进入待付款，最终进入已完成",
            assertion_type="state_transition",
        ),
        _assertion("ASSERT-4", "FACT-6", "驳回申请必须返回草稿"),
    ]
    cases = [
        _case("TC-1", "验证5000元边界及部门经理审批", "boundary"),
        _case("TC-2", "验证超过10000元进入总监审批", "positive"),
        _case("TC-3", "验证待付款后由财务确认打款", "state"),
        _case("TC-4", "验证驳回后恢复到草稿", "recovery"),
        _case("TC-5", "草稿到待审批再到待付款和已完成的端到端流程", "e2e"),
    ]
    system_map = SystemMapEvid(
        pages=[
            PageMap(name="采购申请创建表单", url_pattern="/purchase/new"),
            PageMap(name="审批处理详情", url_pattern="/approval/:id"),
        ],
        actions=[
            ActionMap(action_name="提交采购申请"),
            ActionMap(action_name="批准审批或驳回申请"),
        ],
        forms=[
            FormMap(
                form_name="采购申请表单",
                fields=["采购金额", "采购说明"],
                submit_action="提交采购申请",
            )
        ],
        navigations=[
            NavigationMap(
                source="采购申请草稿",
                target="待审批",
                via="提交",
            )
        ],
    )
    return _package_with_contract(
        facts=facts,
        assertions=assertions,
        cases=cases,
        system_map=system_map,
    )


def test_purchase_human_oracle_accepts_semantic_paraphrases():
    oracle = load_human_oracle(
        ORACLE_ROOT / "purchase_approval.v1.json",
        source_root=FIXTURE_ROOT,
    )

    evaluation = evaluate_test_asset_package(_purchase_package(), oracle)

    assert evaluation.passed is True
    assert evaluation.weighted_score == 1.0
    assert all(metric.passed for metric in evaluation.metrics)


def test_one_aggregated_fact_cannot_satisfy_all_atomic_expectations():
    oracle = load_human_oracle(
        ORACLE_ROOT / "purchase_approval.v1.json",
        source_root=FIXTURE_ROOT,
    )
    mega_fact = _fact(
        "FACT-MEGA",
        (
            "员工提交采购申请；超过5000部门经理审批；超过10000总监审批；"
            "审批通过进入待付款并由财务打款；草稿、待审批、待付款、已完成；"
            "驳回返回草稿。"
        ),
    )
    package = AssetPackage(facts=[mega_fact])

    evaluation = evaluate_test_asset_package(package, oracle)
    fact_metric = next(metric for metric in evaluation.metrics if metric.name == "facts")

    assert evaluation.passed is False
    assert fact_metric.score == pytest.approx(1 / 6, abs=0.0001)
    assert len(fact_metric.missing) == 5


def test_adversarial_oracle_rejects_out_of_scope_claims():
    oracle = load_human_oracle(
        ORACLE_ROOT / "adversarial_approval.v1.json",
        source_root=FIXTURE_ROOT,
    )
    facts = [
        _fact("FACT-1", "超过五千元由部门负责人审阅"),
        _fact("FACT-2", "超过10000需要更高一级审批"),
        _fact(
            "FACT-3",
            "金额阈值写成5k还是5000存在冲突",
            status="conflicted",
        ),
        _fact("FACT-BAD", "用户18岁以下不能注册"),
    ]
    assertions = [
        _assertion("ASSERT-1", "FACT-1", "超过5000由部门负责人审批"),
        _assertion("ASSERT-2", "FACT-2", "超过10000由更高一级审批"),
    ]
    cases = [
        _case("TC-1", "5000边界由部门负责人审阅", "boundary"),
        _case("TC-2", "超过10000交由更高一级审批", "positive"),
    ]
    package = _package_with_contract(
        facts=facts,
        assertions=assertions,
        cases=cases,
        system_map=None,
    )

    evaluation = evaluate_test_asset_package(package, oracle)
    fact_metric = next(metric for metric in evaluation.metrics if metric.name == "facts")

    assert evaluation.passed is False
    assert fact_metric.forbidden_matches == ["fact.out-of-scope-registration"]


def test_plan_contract_reports_missing_branch_and_traceability():
    oracle = load_human_oracle(
        ORACLE_ROOT / "purchase_approval.v1.json",
        source_root=FIXTURE_ROOT,
    )
    package = _purchase_package()
    package.candidate_cases = package.candidate_cases[:2]
    package.traceability_matrix = None

    evaluation = evaluate_test_asset_package(package, oracle)
    contract = next(
        metric for metric in evaluation.metrics
        if metric.name == "plan.contract"
    )

    assert evaluation.passed is False
    assert "candidate_case_count:2<5" in contract.failures
    assert "missing_branch_type:state" in contract.failures
    assert "missing_branch_type:recovery" in contract.failures
    assert "missing_branch_type:e2e" in contract.failures
    assert "missing_traceability_matrix" in contract.failures


def test_oracle_source_hash_mismatch_is_rejected(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("changed source", encoding="utf-8")
    oracle_data = {
        "schema_version": "human_oracle.v1",
        "fixture_id": "stale.v1",
        "source_snapshots": [
            {
                "path": "source.md",
                "sha256": "0" * 64,
            }
        ],
        "provenance": {
            "version": "1.0.0",
            "annotated_by": "test",
            "annotated_at": "2026-06-18",
            "change_reason": "test stale source detection",
        },
    }
    oracle_path = tmp_path / "oracle.json"
    oracle_path.write_text(
        json.dumps(oracle_data, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="source hash mismatch"):
        load_human_oracle(oracle_path, source_root=tmp_path)


def test_cli_outputs_machine_readable_evaluation(tmp_path, capsys):
    package_path = tmp_path / "package.json"
    package_path.write_text(
        _purchase_package().model_dump_json(indent=2),
        encoding="utf-8",
    )

    exit_code = main([
        str(package_path),
        str(ORACLE_ROOT / "purchase_approval.v1.json"),
        "--source-root",
        str(FIXTURE_ROOT),
    ])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["fixture_id"] == "purchase_approval.v1"
    assert output["passed"] is True
    assert output["weighted_score"] == 1.0
