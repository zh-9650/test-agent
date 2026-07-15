from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_release_readiness import evaluate_run, main


FIELDNAMES = [
    "case_id",
    "priority",
    "title",
    "required_depth",
    "evidence_ui",
    "evidence_backend",
    "evidence_artifact",
    "evidence_cleanup",
    "achieved_depth",
    "status",
    "blocker",
]


def _write_matrix(run_dir: Path, rows: list[dict[str, str]]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "evidence").mkdir(exist_ok=True)
    (run_dir / "quality").mkdir(exist_ok=True)
    with (run_dir / "coverage-matrix.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def test_release_readiness_is_no_go_when_any_case_is_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        (run_dir / "evidence").mkdir()
        (run_dir / "evidence" / "CJ-P0-001_login.json").write_text(
            "{}", encoding="utf-8"
        )
        (run_dir / "evidence" / "CJ-P1-005_blocker.json").write_text(
            "{}", encoding="utf-8"
        )
        _write_matrix(
            run_dir,
            [
                {
                    "case_id": "CJ-P0-001",
                    "priority": "P0",
                    "title": "login",
                    "required_depth": "D1",
                    "evidence_artifact": "evidence/CJ-P0-001_login.json",
                    "achieved_depth": "D1",
                    "status": "pass",
                    "blocker": "",
                },
                {
                    "case_id": "CJ-P1-005",
                    "priority": "P1",
                    "title": "dataset create",
                    "required_depth": "D2",
                    "evidence_artifact": "evidence/CJ-P1-005_blocker.json",
                    "achieved_depth": "D2",
                    "status": "blocked",
                    "blocker": "FastGPT dependency returned 502",
                },
            ],
        )

        report = evaluate_run(run_dir)

        assert report.release_status == "no-go"
        assert report.no_go_cases == ["CJ-P1-005"]
        assert any(f.code == "case_not_passed" for f in report.findings)
        assert main([str(run_dir), "--expect-status", "no-go"]) == 0


def test_release_readiness_is_go_when_all_cases_pass_with_depth_and_evidence() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        (run_dir / "evidence").mkdir()
        (run_dir / "evidence" / "CJ-P0-001_login.json").write_text(
            "{}", encoding="utf-8"
        )
        (run_dir / "evidence" / "CJ-P1-004_agent.json").write_text(
            "{}", encoding="utf-8"
        )
        _write_matrix(
            run_dir,
            [
                {
                    "case_id": "CJ-P0-001",
                    "priority": "P0",
                    "title": "login",
                    "required_depth": "D1",
                    "evidence_artifact": "evidence/CJ-P0-001_login.json",
                    "achieved_depth": "D1",
                    "status": "pass",
                    "blocker": "",
                },
                {
                    "case_id": "CJ-P1-004",
                    "priority": "P1",
                    "title": "agent create",
                    "required_depth": "D2",
                    "evidence_artifact": "evidence/CJ-P1-004_agent.json",
                    "achieved_depth": "D3",
                    "status": "pass",
                    "blocker": "",
                },
            ],
        )

        report = evaluate_run(run_dir)

        assert report.release_status == "go"
        assert report.no_go_cases == []
        assert main([str(run_dir), "--expect-status", "go"]) == 0


def test_pass_case_without_case_prefixed_evidence_is_no_go() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)
        (run_dir / "evidence").mkdir()
        (run_dir / "evidence" / "unrelated.json").write_text("{}", encoding="utf-8")
        _write_matrix(
            run_dir,
            [
                {
                    "case_id": "CJ-P0-001",
                    "priority": "P0",
                    "title": "login",
                    "required_depth": "D1",
                    "evidence_artifact": "evidence/unrelated.json",
                    "achieved_depth": "D1",
                    "status": "pass",
                    "blocker": "",
                },
            ],
        )

        report = evaluate_run(run_dir)

        assert report.release_status == "no-go"
        assert any(f.code == "missing_case_prefixed_evidence" for f in report.findings)


if __name__ == "__main__":
    test_release_readiness_is_no_go_when_any_case_is_blocked()
    test_release_readiness_is_go_when_all_cases_pass_with_depth_and_evidence()
    test_pass_case_without_case_prefixed_evidence_is_no_go()
    print("release readiness validator regression checks passed")
