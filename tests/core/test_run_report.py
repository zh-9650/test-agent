"""Run report contract tests."""

from types import SimpleNamespace

from core.interfaces import CandidateTestCase, TestAssetPackage as AssetPackageModel
from core.run_report import build_run_report


def test_report_uses_asset_package_and_authoritative_results():
    run = SimpleNamespace(
        run_id="RUN-1",
        status="completed",
        summary={
            "planned": 1,
            "passed": 1,
            "failed": 0,
            "incomplete": 0,
            "skipped": 0,
            "human_review_required": 0,
        },
    )
    result = SimpleNamespace(
        candidate_case_id="CASE-1",
        terminal_status="passed",
        summary="通过",
        failure_reason=None,
        evidence_refs=["page_url: https://example.com"],
    )
    step = SimpleNamespace(
        test_case_id="CASE-1",
        attempt_no=1,
        step_index=0,
        action_type="navigate",
        action_target="https://example.com",
        result="loaded",
    )
    package = AssetPackageModel(
        candidate_cases=[
            CandidateTestCase(
                id="CASE-1",
                title="首页标题验证",
                goal="验证首页标题",
                expected_result="显示 Example Domain",
                trace_references=["COV-1"],
            )
        ]
    )

    html = build_run_report(run, [result], [step], package)

    assert "首页标题验证" in html
    assert "验证首页标题" in html
    assert "显示 Example Domain" in html
    assert "COV-1" in html
    assert "page_url: https://example.com" in html
    assert "Passed</strong><span>1" in html
