"""Deterministic evaluation against versioned human-oracle fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from core.interfaces import TestAssetPackage


class SourceSnapshot(BaseModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class OracleProvenance(BaseModel):
    version: str
    annotated_by: str
    annotated_at: date
    change_reason: str
    affected_metrics: list[str] = Field(default_factory=list)


class SemanticExpectation(BaseModel):
    id: str
    required_term_groups: list[list[str]] = Field(default_factory=list)
    field_values: dict[str, list[str]] = Field(default_factory=dict)
    critical: bool = True

    @model_validator(mode="after")
    def validate_match_contract(self) -> "SemanticExpectation":
        if not self.required_term_groups and not self.field_values:
            raise ValueError(
                "semantic expectation requires terms or field constraints"
            )
        if any(not group for group in self.required_term_groups):
            raise ValueError("semantic expectation term groups cannot be empty")
        if any(not values for values in self.field_values.values()):
            raise ValueError("semantic expectation field values cannot be empty")
        return self


class ArtifactOracle(BaseModel):
    required: list[SemanticExpectation] = Field(default_factory=list)
    forbidden: list[SemanticExpectation] = Field(default_factory=list)
    minimum_score: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_unique_expectation_ids(self) -> "ArtifactOracle":
        expectation_ids = [
            expectation.id
            for expectation in [*self.required, *self.forbidden]
        ]
        if len(expectation_ids) != len(set(expectation_ids)):
            raise ValueError("artifact oracle expectation IDs must be unique")
        return self


class ExplorationOracle(BaseModel):
    pages: ArtifactOracle = Field(default_factory=ArtifactOracle)
    actions: ArtifactOracle = Field(default_factory=ArtifactOracle)
    forms: ArtifactOracle = Field(default_factory=ArtifactOracle)
    navigations: ArtifactOracle = Field(default_factory=ArtifactOracle)
    require_system_map: bool = False


class PlanOracle(BaseModel):
    candidate_cases: ArtifactOracle = Field(default_factory=ArtifactOracle)
    required_branch_types: list[
        Literal[
            "positive",
            "negative",
            "boundary",
            "permission",
            "state",
            "exception",
            "recovery",
            "e2e",
        ]
    ] = Field(default_factory=list)
    minimum_candidate_cases: int = Field(default=0, ge=0)
    require_traceability: bool = True
    require_quality_gate_pass: bool = True


class HumanOracleFixture(BaseModel):
    schema_version: Literal["human_oracle.v1"] = "human_oracle.v1"
    fixture_id: str
    source_snapshots: list[SourceSnapshot]
    provenance: OracleProvenance
    facts: ArtifactOracle = Field(default_factory=ArtifactOracle)
    assertions: ArtifactOracle = Field(default_factory=ArtifactOracle)
    exploration: ExplorationOracle = Field(default_factory=ExplorationOracle)
    plan: PlanOracle = Field(default_factory=PlanOracle)

    @model_validator(mode="after")
    def validate_unique_source_paths(self) -> "HumanOracleFixture":
        source_paths = [
            snapshot.path
            for snapshot in self.source_snapshots
        ]
        if len(source_paths) != len(set(source_paths)):
            raise ValueError("human oracle source paths must be unique")
        return self


class OracleMetric(BaseModel):
    name: str
    passed: bool
    score: float
    matched: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    forbidden_matches: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)


class HumanOracleEvaluation(BaseModel):
    fixture_id: str
    passed: bool
    weighted_score: float
    metrics: list[OracleMetric]


def load_human_oracle(
    path: str | Path,
    *,
    source_root: str | Path | None = None,
) -> HumanOracleFixture:
    oracle_path = Path(path)
    fixture = HumanOracleFixture.model_validate(
        json.loads(oracle_path.read_text(encoding="utf-8"))
    )
    root = Path(source_root) if source_root is not None else oracle_path.parent.parent
    _verify_source_snapshots(fixture, root)
    return fixture


def evaluate_test_asset_package(
    package: TestAssetPackage,
    oracle: HumanOracleFixture,
) -> HumanOracleEvaluation:
    metrics = [
        _evaluate_artifacts("facts", package.facts, oracle.facts),
        _evaluate_artifacts("assertions", package.assertions, oracle.assertions),
    ]

    system_map = package.system_map
    metrics.extend([
        _evaluate_artifacts(
            "exploration.pages",
            system_map.pages if system_map else [],
            oracle.exploration.pages,
        ),
        _evaluate_artifacts(
            "exploration.actions",
            system_map.actions if system_map else [],
            oracle.exploration.actions,
        ),
        _evaluate_artifacts(
            "exploration.forms",
            system_map.forms if system_map else [],
            oracle.exploration.forms,
        ),
        _evaluate_artifacts(
            "exploration.navigations",
            system_map.navigations if system_map else [],
            oracle.exploration.navigations,
        ),
        _evaluate_artifacts(
            "plan.candidate_cases",
            package.candidate_cases,
            oracle.plan.candidate_cases,
        ),
        _evaluate_plan_contract(package, oracle),
    ])

    active_metrics = [
        metric
        for metric in metrics
        if (
            metric.matched
            or metric.missing
            or metric.forbidden_matches
            or metric.failures
            or metric.name == "plan.contract"
        )
    ]
    weighted_score = (
        sum(metric.score for metric in active_metrics) / len(active_metrics)
        if active_metrics
        else 1.0
    )
    return HumanOracleEvaluation(
        fixture_id=oracle.fixture_id,
        passed=all(metric.passed for metric in metrics),
        weighted_score=round(weighted_score, 4),
        metrics=metrics,
    )


def _verify_source_snapshots(
    oracle: HumanOracleFixture,
    source_root: Path,
) -> None:
    resolved_root = source_root.resolve()
    for snapshot in oracle.source_snapshots:
        source_path = (resolved_root / snapshot.path).resolve()
        try:
            source_path.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(
                f"Oracle source path escapes fixture root: {snapshot.path}"
            ) from exc
        if not source_path.is_file():
            raise ValueError(f"Oracle source file is missing: {snapshot.path}")
        digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        if digest != snapshot.sha256:
            raise ValueError(
                f"Oracle source hash mismatch for {snapshot.path}: "
                f"expected {snapshot.sha256}, got {digest}"
            )


def _evaluate_artifacts(
    name: str,
    artifacts: list[Any],
    oracle: ArtifactOracle,
) -> OracleMetric:
    artifact_dicts = [_as_dict(artifact) for artifact in artifacts]
    texts = [_flatten_text(artifact) for artifact in artifact_dicts]
    matched = _maximum_expectation_matching(
        oracle.required,
        artifact_dicts,
        texts,
    )
    matched_ids = sorted(matched)
    missing_ids = sorted(
        expectation.id
        for expectation in oracle.required
        if expectation.id not in matched
    )
    critical_missing = sorted(
        expectation.id
        for expectation in oracle.required
        if expectation.critical and expectation.id not in matched
    )
    forbidden_matches = sorted(
        expectation.id
        for expectation in oracle.forbidden
        if any(
            _matches_expectation(expectation, artifact, text)
            for artifact, text in zip(artifact_dicts, texts)
        )
    )
    score = (
        len(matched_ids) / len(oracle.required)
        if oracle.required
        else 1.0
    )
    passed = (
        score >= oracle.minimum_score
        and not critical_missing
        and not forbidden_matches
    )
    return OracleMetric(
        name=name,
        passed=passed,
        score=round(score, 4),
        matched=matched_ids,
        missing=missing_ids,
        forbidden_matches=forbidden_matches,
    )


def _maximum_expectation_matching(
    expectations: list[SemanticExpectation],
    artifacts: list[dict[str, Any]],
    texts: list[str],
) -> set[str]:
    candidates: dict[str, list[int]] = {}
    for expectation in expectations:
        candidates[expectation.id] = [
            index
            for index, (artifact, text) in enumerate(zip(artifacts, texts))
            if _matches_expectation(expectation, artifact, text)
        ]

    artifact_owner: dict[int, str] = {}

    def assign(expectation_id: str, seen: set[int]) -> bool:
        for artifact_index in candidates[expectation_id]:
            if artifact_index in seen:
                continue
            seen.add(artifact_index)
            owner = artifact_owner.get(artifact_index)
            if owner is None or assign(owner, seen):
                artifact_owner[artifact_index] = expectation_id
                return True
        return False

    ordered_ids = sorted(candidates, key=lambda item: (len(candidates[item]), item))
    matched: set[str] = set()
    for expectation_id in ordered_ids:
        if assign(expectation_id, set()):
            matched.add(expectation_id)
    return matched


def _matches_expectation(
    expectation: SemanticExpectation,
    artifact: dict[str, Any],
    text: str,
) -> bool:
    for alternatives in expectation.required_term_groups:
        if not alternatives:
            continue
        if not any(_normalize_text(term) in text for term in alternatives):
            return False
    for field_name, accepted_values in expectation.field_values.items():
        actual_value = artifact.get(field_name)
        normalized_actual = _normalize_text(str(actual_value or ""))
        if normalized_actual not in {
            _normalize_text(value)
            for value in accepted_values
        }:
            return False
    return True


def _evaluate_plan_contract(
    package: TestAssetPackage,
    oracle: HumanOracleFixture,
) -> OracleMetric:
    failures: list[str] = []
    cases = package.candidate_cases
    if len(cases) < oracle.plan.minimum_candidate_cases:
        failures.append(
            "candidate_case_count:"
            f"{len(cases)}<{oracle.plan.minimum_candidate_cases}"
        )

    present_branch_types = {case.branch_type for case in cases}
    for branch_type in oracle.plan.required_branch_types:
        if branch_type not in present_branch_types:
            failures.append(f"missing_branch_type:{branch_type}")

    if oracle.exploration.require_system_map and package.system_map is None:
        failures.append("missing_system_map")

    if oracle.plan.require_traceability:
        if package.traceability_matrix is None:
            failures.append("missing_traceability_matrix")
        else:
            case_ids = {case.id for case in cases}
            traced_case_ids = {
                case_id
                for row in package.traceability_matrix.rows
                for case_id in row.candidate_case_ids
            }
            missing_case_ids = sorted(case_ids - traced_case_ids)
            if missing_case_ids:
                failures.append(
                    "untraced_cases:" + ",".join(missing_case_ids)
                )

    if oracle.plan.require_quality_gate_pass:
        if package.quality_gate_report is None:
            failures.append("missing_quality_gate_report")
        elif not package.quality_gate_report.passed:
            failures.append("quality_gate_failed")

    return OracleMetric(
        name="plan.contract",
        passed=not failures,
        score=1.0 if not failures else 0.0,
        failures=failures,
    )


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    return {"value": value}


def _flatten_text(value: Any) -> str:
    parts: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for nested in item.values():
                visit(nested)
        elif isinstance(item, (list, tuple, set)):
            for nested in item:
                visit(nested)
        elif item is not None:
            parts.append(str(item))

    visit(value)
    return _normalize_text(" ".join(parts))


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a TestAssetPackage JSON against a human oracle."
    )
    parser.add_argument("package", type=Path)
    parser.add_argument("oracle", type=Path)
    parser.add_argument("--source-root", type=Path, default=None)
    args = parser.parse_args(argv)

    package = TestAssetPackage.model_validate_json(
        args.package.read_text(encoding="utf-8")
    )
    oracle = load_human_oracle(
        args.oracle,
        source_root=args.source_root,
    )
    evaluation = evaluate_test_asset_package(package, oracle)
    print(json.dumps(
        evaluation.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
    ))
    return 0 if evaluation.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
