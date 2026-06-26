"""Deterministic risk-driven selection from the candidate asset pool."""

from __future__ import annotations

from collections import Counter

from core.interfaces import CandidateTestCase, ExecutionSelection, TestAssetPackage
from core.skills.auto_executability import assess_case_auto_executability


DEFAULT_TARGETS = {"smoke": 20, "balanced": 60}


def _reasons(
    case: CandidateTestCase,
    package: TestAssetPackage,
    profile: str,
) -> list[str]:
    reasons: list[str] = []
    blueprint = package.coverage_blueprint
    core_flows = {item.id for item in blueprint.business_flows if item.is_core}
    core_modules = {item.id for item in blueprint.modules if item.is_core}
    critical_dependencies = {
        item.id for item in blueprint.dependencies if item.risk_tier in {"P0", "P1"}
    }
    if case.branch_type == "e2e" and core_flows.intersection(case.business_flow_ids):
        reasons.append("核心业务流程 E2E")
    if critical_dependencies.intersection(case.dependency_ids) and case.branch_type in {
        "positive",
        "negative",
        "exception",
        "recovery",
    }:
        reasons.append("P0/P1 模块依赖联动")
    if core_modules.intersection(case.module_ids) and case.branch_type == "positive":
        reasons.append("核心模块主路径")
    if case.priority == "high":
        reasons.append("高风险断言")
    if case.branch_type == "permission":
        reasons.append("角色授权或越权")
    if profile == "smoke" and not reasons:
        return []
    return reasons


def _selection_cap(
    profile: str,
    target_count: int,
    mandatory_count: int,
) -> int:
    if profile == "smoke":
        return min(30, max(target_count, mandatory_count))
    return max(target_count, mandatory_count)


def select_execution_cases(
    package: TestAssetPackage,
    profile: str = "balanced",
    target: int | None = None,
) -> ExecutionSelection:
    if profile not in {"smoke", "balanced", "full"}:
        raise ValueError(f"unsupported execution profile: {profile}")

    cases = sorted(package.candidate_cases, key=lambda item: item.id)
    assessments = {case.id: assess_case_auto_executability(case) for case in cases}
    auto_cases = [case for case in cases if assessments[case.id].auto_executable]
    deferred_reasons = {
        case.id: list(assessments[case.id].reasons)
        for case in cases
        if not assessments[case.id].auto_executable
    }

    if profile == "full":
        selected = auto_cases
        reasons = {case.id: ["完整自动执行"] for case in selected}
        target_count = len(auto_cases)
        mandatory_count = len(auto_cases)
    else:
        target_count = target or DEFAULT_TARGETS[profile]
        mandatory_pairs = [
            (case, _reasons(case, package, profile))
            for case in auto_cases
        ]
        selected = [case for case, why in mandatory_pairs if why]
        reasons = {case.id: why for case, why in mandatory_pairs if why}
        cap = _selection_cap(profile, target_count, len(selected))
        if len(selected) > cap:
            selected = selected[:cap]
            reasons = {case.id: reasons[case.id] for case in selected}
        mandatory_count = len(selected)

        selected_ids = {case.id for case in selected}
        remaining = [case for case in auto_cases if case.id not in selected_ids]
        branch_seen = Counter(case.branch_type for case in selected)
        module_seen = Counter(module for case in selected for module in case.module_ids)

        def score(case: CandidateTestCase) -> tuple:
            new_modules = sum(1 for module in case.module_ids if not module_seen[module])
            return (
                case.priority != "high",
                not bool(case.business_flow_ids or case.dependency_ids),
                {"low": 0, "medium": 1, "high": 2}[case.estimated_cost],
                branch_seen[case.branch_type],
                -new_modules,
                case.id,
            )

        for case in sorted(remaining, key=score):
            if len(selected) >= cap:
                break
            selected.append(case)
            reasons[case.id] = ["风险与覆盖增益补位"]
            branch_seen[case.branch_type] += 1
            module_seen.update(case.module_ids)

    reasons.update(deferred_reasons)
    selected_ids = [case.id for case in selected]
    selected_set = set(selected_ids)
    deferred_ids = [case.id for case in cases if case.id not in selected_set]
    return ExecutionSelection(
        profile=profile,
        target_count=target_count,
        mandatory_count=mandatory_count,
        selected_count=len(selected_ids),
        deferred_count=len(deferred_ids),
        selected_case_ids=selected_ids,
        deferred_case_ids=deferred_ids,
        selection_reasons=reasons,
        coverage_summary={
            "modules": sorted({item for case in selected for item in case.module_ids}),
            "business_flows": sorted({item for case in selected for item in case.business_flow_ids}),
            "dependencies": sorted({item for case in selected for item in case.dependency_ids}),
            "branches": dict(Counter(case.branch_type for case in selected)),
            "candidate_case_count": len(cases),
            "auto_executable_case_count": len(auto_cases),
            "non_auto_executable_case_count": len(deferred_reasons),
        },
    )
