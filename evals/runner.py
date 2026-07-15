"""Lightweight evaluation manifest validator and summarizer.

The runner intentionally evaluates the seed manifest itself, not live task
execution. It gives the refactor a stable baseline for checking whether eval
case definitions stay complete and measurable.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


SCHEMA_VERSION = "eval_case_manifest.v1"
KNOWN_TERMINAL_STATUSES = frozenset(
    {
        "failed",
        "human_review_required",
        "incomplete",
        "passed",
        "skipped",
    }
)
REQUIRED_CASE_FIELDS = (
    "id",
    "name",
    "target_url",
    "tags",
    "inputs",
    "expected_assets",
    "expected_execution",
    "report_checks",
)
REQUIRED_INPUT_FIELDS = ("prd", "swagger", "rules", "focus_areas")
REQUIRED_ASSET_FIELDS = (
    "required_assertions",
    "required_case_titles",
    "deferred_allowed",
)
REQUIRED_EXECUTION_FIELDS = (
    "allowed_terminal_statuses",
    "must_not_use_tools",
    "max_tool_failures",
)
REQUIRED_REPORT_CHECK_FIELDS = (
    "must_explain_result",
    "must_include_traceability",
)


def load_manifest(path: str | Path) -> dict[str, Any]:
    """Load a JSON eval manifest from disk."""

    manifest_path = Path(path)
    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict):
        raise ValueError("manifest root must be a JSON object")
    return manifest


def validate_manifest(manifest: dict[str, Any]) -> dict[str, list[str]]:
    """Validate the fixed eval manifest schema.

    Returns a dictionary with ``errors`` and ``warnings`` lists. Errors should
    fail the CLI; warnings describe quality issues that are useful but not
    schema-breaking.
    """

    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(manifest, dict):
        return {
            "errors": ["manifest root must be a JSON object"],
            "warnings": warnings,
        }

    schema_version = manifest.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        errors.append(
            f"schema_version must be {SCHEMA_VERSION!r}, got {schema_version!r}"
        )

    cases = manifest.get("cases")
    if not isinstance(cases, list):
        errors.append("cases must be a list")
        return {"errors": errors, "warnings": warnings}
    if not cases:
        errors.append("cases must contain at least one eval case")

    seen_ids: set[str] = set()
    for index, case in enumerate(cases):
        path = f"cases[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{path} must be an object")
            continue

        for field in REQUIRED_CASE_FIELDS:
            if field not in case:
                errors.append(f"{path}.{field} is required")

        case_id = case.get("id")
        case_label = str(case_id) if case_id else path
        if not _is_non_empty_string(case_id):
            errors.append(f"{path}.id must be a non-empty string")
        elif case_id in seen_ids:
            errors.append(f"{case_label}.id must be unique")
        elif isinstance(case_id, str):
            seen_ids.add(case_id)

        for field in ("name", "target_url"):
            if not _is_non_empty_string(case.get(field)):
                errors.append(f"{case_label}.{field} must be a non-empty string")

        _validate_string_list(
            case.get("tags"),
            f"{case_label}.tags",
            errors,
            require_non_empty=True,
        )
        if isinstance(case.get("tags"), list):
            tag_values = [tag for tag in case["tags"] if isinstance(tag, str)]
            duplicate_tags = _duplicates(tag_values)
            if duplicate_tags:
                warnings.append(
                    f"{case_label}.tags contains duplicate tags: "
                    f"{', '.join(sorted(duplicate_tags))}"
                )

        _validate_inputs(case.get("inputs"), case_label, errors)
        _validate_expected_assets(case.get("expected_assets"), case_label, errors)
        _validate_expected_execution(
            case.get("expected_execution"), case_label, errors
        )
        _validate_report_checks(case.get("report_checks"), case_label, errors)

    return {"errors": errors, "warnings": warnings}


def summarize_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build lightweight manifest metrics for the eval seed set."""

    cases = manifest.get("cases")
    if not isinstance(cases, list):
        cases = []

    tag_counts: Counter[str] = Counter()
    allowed_status_counts: Counter[str] = Counter()
    forbidden_tool_counts: Counter[str] = Counter()
    deferred_allowed_counts: Counter[str] = Counter()
    required_assertion_counts: dict[str, int] = {}
    required_case_title_counts: dict[str, int] = {}
    allowed_statuses_by_case: dict[str, list[str]] = {}
    forbidden_tools_by_case: dict[str, list[str]] = {}
    tags_by_case: dict[str, list[str]] = {}
    max_tool_failures_by_case: dict[str, int] = {}
    report_check_counts: dict[str, int] = defaultdict(int)

    total_required_assertions = 0
    total_required_case_titles = 0
    max_tool_failure_values: list[int] = []

    for index, raw_case in enumerate(cases):
        if not isinstance(raw_case, dict):
            continue
        case_id = _case_id(raw_case, index)

        tags = _string_items(raw_case.get("tags"))
        tag_counts.update(tags)
        tags_by_case[case_id] = tags

        expected_assets = _dict_value(raw_case.get("expected_assets"))
        required_assertions = _string_items(
            expected_assets.get("required_assertions")
        )
        required_case_titles = _string_items(
            expected_assets.get("required_case_titles")
        )
        total_required_assertions += len(required_assertions)
        total_required_case_titles += len(required_case_titles)
        required_assertion_counts[case_id] = len(required_assertions)
        required_case_title_counts[case_id] = len(required_case_titles)
        deferred_allowed_counts[str(bool(expected_assets.get("deferred_allowed")))] += 1

        expected_execution = _dict_value(raw_case.get("expected_execution"))
        allowed_statuses = _string_items(
            expected_execution.get("allowed_terminal_statuses")
        )
        forbidden_tools = _string_items(expected_execution.get("must_not_use_tools"))
        allowed_status_counts.update(allowed_statuses)
        forbidden_tool_counts.update(forbidden_tools)
        allowed_statuses_by_case[case_id] = allowed_statuses
        forbidden_tools_by_case[case_id] = forbidden_tools

        max_tool_failures = expected_execution.get("max_tool_failures")
        if isinstance(max_tool_failures, int) and max_tool_failures >= 0:
            max_tool_failures_by_case[case_id] = max_tool_failures
            max_tool_failure_values.append(max_tool_failures)

        report_checks = _dict_value(raw_case.get("report_checks"))
        for field in REQUIRED_REPORT_CHECK_FIELDS:
            if report_checks.get(field) is True:
                report_check_counts[field] += 1

    case_count = len([case for case in cases if isinstance(case, dict)])
    case_ids = [_case_id(case, index) for index, case in enumerate(cases) if isinstance(case, dict)]

    return {
        "cases": {
            "total": case_count,
            "ids": case_ids,
        },
        "tags": {
            "unique": sorted(tag_counts),
            "counts": dict(sorted(tag_counts.items())),
            "by_case": tags_by_case,
        },
        "required_assertions": {
            "total": total_required_assertions,
            "cases_with_required_assertions": _positive_count(
                required_assertion_counts
            ),
            "coverage_ratio": _ratio(
                _positive_count(required_assertion_counts), case_count
            ),
            "by_case": required_assertion_counts,
        },
        "required_case_titles": {
            "total": total_required_case_titles,
            "cases_with_required_case_titles": _positive_count(
                required_case_title_counts
            ),
            "coverage_ratio": _ratio(
                _positive_count(required_case_title_counts), case_count
            ),
            "by_case": required_case_title_counts,
        },
        "deferred_allowed": {
            "counts": dict(sorted(deferred_allowed_counts.items())),
        },
        "allowed_terminal_statuses": {
            "unique": sorted(allowed_status_counts),
            "counts": dict(sorted(allowed_status_counts.items())),
            "by_case": allowed_statuses_by_case,
        },
        "must_not_use_tools": {
            "unique": sorted(forbidden_tool_counts),
            "counts": dict(sorted(forbidden_tool_counts.items())),
            "cases_with_restrictions": len(
                [tools for tools in forbidden_tools_by_case.values() if tools]
            ),
            "coverage_ratio": _ratio(
                len([tools for tools in forbidden_tools_by_case.values() if tools]),
                case_count,
            ),
            "by_case": forbidden_tools_by_case,
        },
        "max_tool_failures": {
            "min": min(max_tool_failure_values) if max_tool_failure_values else None,
            "max": max(max_tool_failure_values) if max_tool_failure_values else None,
            "average": round(mean(max_tool_failure_values), 2)
            if max_tool_failure_values
            else None,
            "by_case": max_tool_failures_by_case,
        },
        "report_checks": {
            field: {
                "cases_requiring_check": report_check_counts[field],
                "coverage_ratio": _ratio(report_check_counts[field], case_count),
            }
            for field in REQUIRED_REPORT_CHECK_FIELDS
        },
    }


def build_report(
    manifest: dict[str, Any],
    manifest_path: Path,
    validation: dict[str, list[str]],
    task_evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create the JSON report payload written by the CLI."""

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_path": str(manifest_path),
        "manifest_schema_version": manifest.get("schema_version"),
        "validation": {
            "ok": not validation["errors"],
            "errors": validation["errors"],
            "warnings": validation["warnings"],
        },
        "summary": summarize_manifest(manifest),
    }
    if task_evaluation is not None:
        report["task_evaluation"] = task_evaluation
    return report


async def execute_manifest_case(manifest: dict[str, Any], case_id: str) -> int:
    """Create and run a real task from one manifest case.

    This is intentionally opt-in because it may open a browser and call LLMs.
    """

    case = _manifest_case_by_id(manifest, case_id)
    if case is None:
        raise ValueError(f"eval case not found: {case_id}")

    from core.input_normalization import normalize_task_config
    from core.task_lifecycle import TaskLifecycleService
    from database.connection import async_session, init_database
    from database.models import Task

    await init_database()
    inputs = _dict_value(case.get("inputs"))
    config = normalize_task_config({
        "prd": str(inputs.get("prd", "")),
        "swagger": str(inputs.get("swagger", "")),
        "rules": str(inputs.get("rules", "")),
        "focus_areas": str(inputs.get("focus_areas", "")),
        "execution_profile": "smoke",
    })
    async with async_session() as session:
        task = Task(
            task_name=f"Eval {case_id}: {case.get('name', '')}",
            target_url=str(case.get("target_url", "")),
            status="pending",
            config=config,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        task_id = int(task.id)

    await TaskLifecycleService().run_test_session(
        task_id,
        str(case.get("target_url", "")),
        config,
    )
    return task_id


async def evaluate_task_artifacts(
    *,
    task_id: int,
    run_id: str | None = None,
    eval_case: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score persisted task/run artifacts against eval expectations."""

    from sqlalchemy import select

    from core.runtime_tool_contract import is_runtime_tool_failure_status
    from database.connection import async_session
    from database.models import (
        CaseResultRecord,
        ExecutionRunRecord,
        Report,
        Task,
        TaskStep,
    )

    async with async_session() as session:
        task = await session.get(Task, task_id)
        if task is None:
            raise ValueError(f"task not found: {task_id}")

        if run_id:
            run = await session.get(ExecutionRunRecord, run_id)
            if run is None or run.task_id != task_id:
                raise ValueError(f"run not found for task: {run_id}")
        else:
            run_query = (
                select(ExecutionRunRecord)
                .where(ExecutionRunRecord.task_id == task_id)
                .order_by(ExecutionRunRecord.started_at.desc())
                .limit(1)
            )
            run = (await session.execute(run_query)).scalar_one_or_none()
            if run is None:
                raise ValueError(f"task has no execution run: {task_id}")

        results = list((
            await session.execute(
                select(CaseResultRecord)
                .where(CaseResultRecord.run_id == run.run_id)
                .order_by(CaseResultRecord.id)
            )
        ).scalars().all())
        steps = list((
            await session.execute(
                select(TaskStep)
                .where(TaskStep.run_id == run.run_id)
                .order_by(
                    TaskStep.test_case_id,
                    TaskStep.attempt_no,
                    TaskStep.step_index,
                )
            )
        ).scalars().all())
        report = (
            await session.execute(
                select(Report)
                .where(Report.task_id == task_id, Report.run_id == run.run_id)
                .order_by(Report.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        package = task.analysis_package or {}
        checkpoints = task.checkpoints or {}
        resume_policy = task.resume_policy or {}

    expected_assets = _dict_value(
        eval_case.get("expected_assets") if eval_case else {}
    )
    expected_execution = _dict_value(
        eval_case.get("expected_execution") if eval_case else {}
    )
    report_checks = _dict_value(
        eval_case.get("report_checks") if eval_case else {}
    )

    package_text = json.dumps(package, ensure_ascii=False)
    report_text = _read_report_text(getattr(report, "report_path", None))
    result_statuses = [row.terminal_status for row in results]
    tool_failure_steps = [
        step for step in steps
        if is_runtime_tool_failure_status(_step_signal(step, "status"))
    ]
    forbidden_tools = set(_string_items(expected_execution.get("must_not_use_tools")))
    allowed_statuses = set(
        _string_items(expected_execution.get("allowed_terminal_statuses"))
    )
    max_tool_failures = expected_execution.get("max_tool_failures")

    checks: dict[str, Any] = {
        "assets": {
            "required_assertions": _coverage_check(
                _string_items(expected_assets.get("required_assertions")),
                package_text,
            ),
            "required_case_titles": _coverage_check(
                _string_items(expected_assets.get("required_case_titles")),
                package_text,
            ),
            "has_traceability_matrix": bool(
                _dict_value(package).get("traceability_matrix")
            ),
            "has_memory_provenance": bool(
                _dict_value(_dict_value(package).get("runtime_hints")).get(
                    "memory_context_refs"
                )
            ),
        },
        "execution": {
            "denominator_preserved": (
                int((run.summary or {}).get("planned", 0))
                == len(run.candidate_case_ids or [])
                and int((run.summary or {}).get("terminal", 0)) == len(results)
            ),
            "terminal_statuses_allowed": (
                all(status in allowed_statuses for status in result_statuses)
                if allowed_statuses else True
            ),
            "forbidden_tools_absent": not any(
                step.action_type in forbidden_tools for step in steps
            ),
            "tool_failure_count": len(tool_failure_steps),
            "max_tool_failures_ok": (
                len(tool_failure_steps) <= max_tool_failures
                if isinstance(max_tool_failures, int)
                else True
            ),
        },
        "report": {
            "report_exists": bool(report and report_text),
            "must_explain_result": (
                _report_explains_results(report_text, results)
                if report_checks.get("must_explain_result") is True
                else True
            ),
            "must_include_traceability": (
                "Trace:" in report_text
                or "traceability" in package_text.lower()
                if report_checks.get("must_include_traceability") is True
                else True
            ),
            "includes_human_review_section": "Human review" in report_text,
            "includes_tool_error_summary": "Tool error summary" in report_text,
        },
        "checkpoint": {
            "has_checkpoints": bool(checkpoints),
            "latest": _dict_value(checkpoints.get("latest")),
            "has_resume_policy": bool(resume_policy),
        },
    }

    category_scores = {
        category: _score_boolean_tree(value)
        for category, value in checks.items()
    }
    overall_score = round(mean(category_scores.values()), 4) if category_scores else 0.0
    return {
        "task_id": task_id,
        "run_id": run.run_id,
        "eval_case_id": eval_case.get("id") if eval_case else None,
        "scores": {
            **category_scores,
            "overall": overall_score,
        },
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate and summarize an eval seed manifest."
    )
    parser.add_argument(
        "--manifest",
        default="evals/seed_manifest.json",
        help="Path to the eval manifest JSON file.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Path for the JSON summary report. Defaults to "
            "data/evals/eval_summary_<timestamp>.json."
        ),
    )
    parser.add_argument(
        "--task-id",
        type=int,
        default=None,
        help="Score persisted artifacts for an existing task.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Run ID to score with --task-id. Defaults to latest run.",
    )
    parser.add_argument(
        "--eval-case-id",
        default=None,
        help="Manifest case expectations to apply when scoring a task.",
    )
    parser.add_argument(
        "--execute-case-id",
        default=None,
        help=(
            "Create and execute a real task from one manifest case before "
            "scoring. This may open a browser and call LLMs."
        ),
    )
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest)
    output_path = Path(args.output) if args.output else _default_output_path()

    try:
        manifest = load_manifest(manifest_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"failed to load manifest {manifest_path}: {exc}", file=sys.stderr)
        return 2

    validation = validate_manifest(manifest)
    task_evaluation = None
    if not validation["errors"] and (args.task_id or args.execute_case_id):
        try:
            task_id = args.task_id
            if args.execute_case_id:
                task_id = asyncio.run(
                    execute_manifest_case(manifest, args.execute_case_id)
                )
            eval_case_id = args.eval_case_id or args.execute_case_id
            task_evaluation = asyncio.run(
                evaluate_task_artifacts(
                    task_id=int(task_id),
                    run_id=args.run_id,
                    eval_case=_manifest_case_by_id(manifest, eval_case_id)
                    if eval_case_id else None,
                )
            )
        except Exception as exc:
            task_evaluation = {
                "ok": False,
                "error": str(exc),
            }

    report = build_report(
        manifest,
        manifest_path,
        validation,
        task_evaluation=task_evaluation,
    )
    _write_json(output_path, report)

    print(f"wrote eval summary: {output_path}")
    print(
        "cases={case_count} errors={error_count} warnings={warning_count}".format(
            case_count=report["summary"]["cases"]["total"],
            error_count=len(validation["errors"]),
            warning_count=len(validation["warnings"]),
        )
    )
    if task_evaluation is not None:
        print(
            "task_evaluation_overall={score}".format(
                score=task_evaluation.get("scores", {}).get("overall", "n/a")
                if isinstance(task_evaluation, dict)
                else "n/a"
            )
        )

    # Dispose database connection pool to avoid CLI hanging on exit
    try:
        from database.connection import get_async_engine
        asyncio.run(get_async_engine().dispose())
    except Exception:
        pass

    if validation["errors"]:
        for error in validation["errors"]:
            print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


def _validate_inputs(value: Any, case_label: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{case_label}.inputs must be an object")
        return
    for field in REQUIRED_INPUT_FIELDS:
        if field not in value:
            errors.append(f"{case_label}.inputs.{field} is required")
        elif not isinstance(value[field], str):
            errors.append(f"{case_label}.inputs.{field} must be a string")


def _manifest_case_by_id(
    manifest: dict[str, Any],
    case_id: str | None,
) -> dict[str, Any] | None:
    if not case_id:
        return None
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        return None
    for case in cases:
        if isinstance(case, dict) and case.get("id") == case_id:
            return case
    return None


def _coverage_check(required: list[str], haystack: str) -> dict[str, Any]:
    normalized_haystack = haystack.casefold()
    found = [
        item for item in required
        if item.casefold() in normalized_haystack
    ]
    missing = [item for item in required if item not in found]
    return {
        "required": required,
        "found": found,
        "missing": missing,
        "coverage_ratio": _ratio(len(found), len(required)) if required else 1.0,
        "ok": not missing,
    }


def _step_signal(step: Any, key: str) -> str:
    value = None
    change_report = getattr(step, "change_report", None)
    tool_result = getattr(step, "tool_result", None)
    if isinstance(change_report, dict):
        value = change_report.get(key)
    if value in (None, "") and isinstance(tool_result, dict):
        value = tool_result.get(key)
    return str(value) if value not in (None, "") else ""


def _read_report_text(report_path: str | None) -> str:
    if not report_path:
        return ""
    path = Path(report_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _report_explains_results(report_text: str, results: list[Any]) -> bool:
    if not report_text:
        return False
    if not results:
        return False
    return all(
        str(getattr(result, "candidate_case_id", "")) in report_text
        and str(getattr(result, "terminal_status", "")) in report_text
        for result in results
    )


def _score_boolean_tree(value: Any) -> float:
    booleans: list[bool] = []

    def walk(node: Any) -> None:
        if isinstance(node, bool):
            booleans.append(node)
        elif isinstance(node, dict):
            for item in node.values():
                walk(item)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(value)
    if not booleans:
        return 1.0
    return round(sum(1 for item in booleans if item) / len(booleans), 4)


def _validate_expected_assets(
    value: Any, case_label: str, errors: list[str]
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{case_label}.expected_assets must be an object")
        return
    for field in REQUIRED_ASSET_FIELDS:
        if field not in value:
            errors.append(f"{case_label}.expected_assets.{field} is required")

    _validate_string_list(
        value.get("required_assertions"),
        f"{case_label}.expected_assets.required_assertions",
        errors,
        require_non_empty=True,
    )
    _validate_string_list(
        value.get("required_case_titles"),
        f"{case_label}.expected_assets.required_case_titles",
        errors,
        require_non_empty=True,
    )
    if not isinstance(value.get("deferred_allowed"), bool):
        errors.append(
            f"{case_label}.expected_assets.deferred_allowed must be a boolean"
        )


def _validate_expected_execution(
    value: Any, case_label: str, errors: list[str]
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{case_label}.expected_execution must be an object")
        return
    for field in REQUIRED_EXECUTION_FIELDS:
        if field not in value:
            errors.append(f"{case_label}.expected_execution.{field} is required")

    allowed_statuses = value.get("allowed_terminal_statuses")
    _validate_string_list(
        allowed_statuses,
        f"{case_label}.expected_execution.allowed_terminal_statuses",
        errors,
        require_non_empty=True,
    )
    if isinstance(allowed_statuses, list):
        for status in allowed_statuses:
            if isinstance(status, str) and status not in KNOWN_TERMINAL_STATUSES:
                errors.append(
                    f"{case_label}.expected_execution.allowed_terminal_statuses "
                    f"contains unknown status {status!r}"
                )

    _validate_string_list(
        value.get("must_not_use_tools"),
        f"{case_label}.expected_execution.must_not_use_tools",
        errors,
        require_non_empty=False,
    )
    max_tool_failures = value.get("max_tool_failures")
    if not isinstance(max_tool_failures, int) or max_tool_failures < 0:
        errors.append(
            f"{case_label}.expected_execution.max_tool_failures must be a "
            "non-negative integer"
        )


def _validate_report_checks(value: Any, case_label: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{case_label}.report_checks must be an object")
        return
    for field in REQUIRED_REPORT_CHECK_FIELDS:
        if field not in value:
            errors.append(f"{case_label}.report_checks.{field} is required")
        elif not isinstance(value[field], bool):
            errors.append(f"{case_label}.report_checks.{field} must be a boolean")


def _validate_string_list(
    value: Any,
    path: str,
    errors: list[str],
    *,
    require_non_empty: bool,
) -> None:
    if not isinstance(value, list):
        errors.append(f"{path} must be a list")
        return
    if require_non_empty and not value:
        errors.append(f"{path} must contain at least one item")
    for index, item in enumerate(value):
        if not _is_non_empty_string(item):
            errors.append(f"{path}[{index}] must be a non-empty string")


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if _is_non_empty_string(item)]


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _duplicates(values: list[str]) -> set[str]:
    counts = Counter(values)
    return {value for value, count in counts.items() if count > 1}


def _case_id(case: dict[str, Any], index: int) -> str:
    case_id = case.get("id")
    return case_id if isinstance(case_id, str) and case_id else f"case-{index + 1}"


def _positive_count(values: dict[str, int]) -> int:
    return len([value for value in values.values() if value > 0])


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _default_output_path() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path("data") / "evals" / f"eval_summary_{timestamp}.json"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
