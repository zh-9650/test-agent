from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


DEPTH_ORDER = {"D0": 0, "D1": 1, "D2": 2, "D3": 3, "D4": 4}
EVIDENCE_FIELDS = (
    "evidence_ui",
    "evidence_backend",
    "evidence_artifact",
    "evidence_cleanup",
)


@dataclass
class CaseFinding:
    case_id: str
    severity: str
    code: str
    message: str


@dataclass
class ReleaseReadinessReport:
    run_dir: str
    release_status: str
    total_cases: int
    pass_cases: int
    no_go_cases: list[str]
    findings: list[CaseFinding]


def _read_matrix(run_dir: Path) -> list[dict[str, str]]:
    matrix_path = run_dir / "coverage-matrix.csv"
    if not matrix_path.exists():
        raise FileNotFoundError(f"missing coverage matrix: {matrix_path}")
    with matrix_path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _depth_value(value: str) -> int | None:
    return DEPTH_ORDER.get((value or "").strip().upper())


def _split_evidence_refs(values: Iterable[str]) -> list[str]:
    refs: list[str] = []
    for value in values:
        for part in (value or "").split(";"):
            ref = part.strip()
            if ref.startswith(("evidence/", "quality/", "setup/")):
                refs.append(ref)
    return refs


def _existing_refs(run_dir: Path, refs: Iterable[str]) -> list[Path]:
    existing: list[Path] = []
    for ref in refs:
        path = run_dir / ref
        if path.exists():
            existing.append(path)
    return existing


def _has_case_prefixed_evidence(run_dir: Path, case_id: str) -> bool:
    evidence_dir = run_dir / "evidence"
    if not evidence_dir.exists():
        return False
    return any(path.is_file() for path in evidence_dir.glob(f"{case_id}*"))


def evaluate_run(run_dir: str | Path) -> ReleaseReadinessReport:
    root = Path(run_dir)
    rows = _read_matrix(root)
    findings: list[CaseFinding] = []
    no_go_cases: list[str] = []
    pass_cases = 0

    if not rows:
        findings.append(
            CaseFinding(
                case_id="__matrix__",
                severity="error",
                code="empty_matrix",
                message="coverage-matrix.csv contains no cases",
            )
        )

    seen_ids: set[str] = set()
    for row in rows:
        case_id = (row.get("case_id") or "").strip()
        status = (row.get("status") or "").strip().lower()
        required_depth = _depth_value(row.get("required_depth", ""))
        achieved_depth = _depth_value(row.get("achieved_depth", ""))

        if not case_id:
            findings.append(
                CaseFinding(
                    case_id="__matrix__",
                    severity="error",
                    code="missing_case_id",
                    message="matrix row is missing case_id",
                )
            )
            continue

        if case_id in seen_ids:
            findings.append(
                CaseFinding(
                    case_id=case_id,
                    severity="error",
                    code="duplicate_case_id",
                    message=f"duplicate case_id {case_id}",
                )
            )
        seen_ids.add(case_id)

        refs = _split_evidence_refs(row.get(field, "") for field in EVIDENCE_FIELDS)
        existing_refs = _existing_refs(root, refs)
        if status in {"pass", "partial", "blocked"} and not existing_refs:
            findings.append(
                CaseFinding(
                    case_id=case_id,
                    severity="error",
                    code="missing_evidence_ref",
                    message="status needs at least one existing evidence/setup/quality reference",
                )
            )
        if status in {"pass", "partial"} and not _has_case_prefixed_evidence(
            root, case_id
        ):
            findings.append(
                CaseFinding(
                    case_id=case_id,
                    severity="error",
                    code="missing_case_prefixed_evidence",
                    message=f"no evidence file starts with {case_id}",
                )
            )

        if status == "pass":
            pass_cases += 1
            if required_depth is None or achieved_depth is None:
                findings.append(
                    CaseFinding(
                        case_id=case_id,
                        severity="error",
                        code="invalid_depth",
                        message="pass case has invalid required_depth or achieved_depth",
                    )
                )
                no_go_cases.append(case_id)
            elif achieved_depth < required_depth:
                findings.append(
                    CaseFinding(
                        case_id=case_id,
                        severity="error",
                        code="depth_below_floor",
                        message=(
                            f"achieved_depth={row.get('achieved_depth')} is below "
                            f"required_depth={row.get('required_depth')}"
                        ),
                    )
                )
                no_go_cases.append(case_id)
        else:
            no_go_cases.append(case_id)
            blocker = (row.get("blocker") or "").strip()
            message = f"case status is {status or 'missing'}"
            if blocker:
                message = f"{message}: {blocker}"
            findings.append(
                CaseFinding(
                    case_id=case_id,
                    severity="release-blocker",
                    code="case_not_passed",
                    message=message,
                )
            )

    blocking_findings = [
        finding
        for finding in findings
        if finding.severity in {"error", "release-blocker"}
    ]
    release_status = "go" if not no_go_cases and not blocking_findings else "no-go"
    return ReleaseReadinessReport(
        run_dir=str(root),
        release_status=release_status,
        total_cases=len(rows),
        pass_cases=pass_cases,
        no_go_cases=sorted(set(no_go_cases)),
        findings=findings,
    )


def _report_to_json(report: ReleaseReadinessReport) -> str:
    payload = asdict(report)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a test run's release readiness from coverage matrix evidence."
    )
    parser.add_argument("run_dir", help="Path to the test run directory.")
    parser.add_argument(
        "--expect-status",
        choices=("go", "no-go"),
        help="Exit successfully only when the computed release status matches.",
    )
    parser.add_argument(
        "--json-output",
        help="Optional path to write the structured readiness report.",
    )
    args = parser.parse_args(argv)

    try:
        report = evaluate_run(args.run_dir)
    except Exception as exc:
        print(f"RELEASE READINESS VALIDATION FAILED: {exc}", file=sys.stderr)
        return 2

    output = _report_to_json(report)
    print(output)
    if args.json_output:
        Path(args.json_output).write_text(output + "\n", encoding="utf-8")

    if args.expect_status and report.release_status != args.expect_status:
        print(
            f"Expected release_status={args.expect_status}, "
            f"got {report.release_status}",
            file=sys.stderr,
        )
        return 1
    if args.expect_status:
        return 0
    return 0 if report.release_status == "go" else 1


if __name__ == "__main__":
    raise SystemExit(main())
