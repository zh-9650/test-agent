"""Deterministic risk-driven selection from the candidate asset pool."""

from __future__ import annotations

from collections import Counter

from core.interfaces import CandidateTestCase, ExecutionSelection, TestAssetPackage
from core.skills.auto_executability import assess_case_auto_executability


DEFAULT_TARGETS = {"smoke": 20, "balanced": 60}


def _case_text(case: CandidateTestCase) -> str:
    parts = [
        case.title,
        case.goal,
        case.description,
        case.expected_result,
        case.execution_hint,
        case.category,
        case.branch_type,
    ]
    for item in case.input_data:
        parts.extend([
            item.name,
            item.value or "",
            item.placeholder or "",
            item.source,
            item.generation_strategy,
            item.boundary_category,
        ])
    return "\n".join(str(part or "") for part in parts).lower()


def _smoke_intent_bucket(case: CandidateTestCase) -> str:
    text = _case_text(case)
    if any(marker in text for marker in ("一键填值", "quick fill", "quick-fill")):
        return "login.quick_fill"
    if any(
        marker in text
        for marker in (
            "错误密码",
            "无效密码",
            "密码错误",
            "拒绝登录",
            "wrong password",
            "invalid password",
            "invalid credential",
            "cangjie*2026",
        )
    ) and any(marker in text for marker in ("登录", "login", "sign in")):
        return "login.invalid_password"
    has_gateway = any(
        marker in text for marker in ("gatewayurl", "gateway", "网关", "url")
    )
    has_invalid_signal = any(
        marker in text
        for marker in ("not-url", "非法", "无效", "格式", "校验", "阻断", "invalid")
    )
    invalid_gateway = (
        has_gateway
        and (
            has_invalid_signal
            or case.branch_type in {"negative", "boundary", "exception"}
        )
    )
    if invalid_gateway:
        return "gateway.invalid"

    agent_markers = ("智能体", "agent")
    if any(marker in text for marker in agent_markers):
        if any(marker in text for marker in ("新增", "创建", "create", "ta-20260704-auto")):
            return "agent.create"
    if "知识库" in text and any(
        marker in text for marker in ("新建", "新增", "创建", "create")
    ):
        if any(marker in text for marker in ("名称留空", "空名称", "required", "必填")):
            return "dataset.empty_name"
        if any(marker in text for marker in ("测试知识库", "ta-20260704-auto")):
            return "dataset.create"
    if any(marker in text for marker in ("技能", "skill")):
        if "skill.md" in text and any(
            marker in text for marker in ("重复", "不可重复", "阻断", "禁止", "duplicate")
        ):
            return "skill.duplicate_core_file"
        stable_skill_scaffold_markers = (
            "ta-20260704-auto" in text
            and "skill.md" in text
            and "index.js" in text
        )
        if stable_skill_scaffold_markers or (
            any(marker in text for marker in ("脚手架", "scaffold", "初始化"))
            and any(marker in text for marker in ("ta-20260704-auto", "skill.md", "index.js"))
        ):
            return "skill.scaffold"
    if any(marker in text for marker in ("登录", "login", "sign in")) and any(
        marker in text
        for marker in ("成功", "控制台", "dashboard", "admin/admin123", "zhanghong")
    ):
        return "login.success"
    return ""


def _smoke_specificity_score(case: CandidateTestCase) -> int:
    text = _case_text(case)
    score = 0
    if case.priority == "high":
        score += 4
    if case.estimated_cost == "low":
        score += 3
    elif case.estimated_cost == "medium":
        score += 1
    score += min(len(case.input_data), 4) * 3
    if "ta-20260704" in text:
        score += 8
    if "not-url" in text:
        score += 6
    if "skill.md" in text:
        score += 5
    if "index.js" in text:
        score += 2
    if "通过 ui" in text or "ui " in text:
        score += 3
    if "搜索" in text:
        score += 2
    if "explicit" in text or "显式" in text:
        score += 2
    if "admin/admin123" in text:
        score += 6
    if "cangjie*2026" in text:
        score += 5
    if "username=admin" in text or "用户名" in text:
        score += 2
    if "password=" in text or "密码" in text:
        score += 2
    if "zhanghong" in text:
        score += 4
    if "页面呈现与覆盖目标一致" in text:
        score -= 4
    return score


def _dedupe_smoke_mandatory_pairs(
    pairs: list[tuple[CandidateTestCase, list[str]]],
) -> tuple[list[tuple[CandidateTestCase, list[str]]], dict[str, list[str]]]:
    passthrough: list[tuple[int, CandidateTestCase, list[str]]] = []
    bucketed: dict[str, list[tuple[int, CandidateTestCase, list[str]]]] = {}
    for index, (case, why) in enumerate(pairs):
        bucket = _smoke_intent_bucket(case)
        if not bucket:
            passthrough.append((index, case, why))
            continue
        bucketed.setdefault(bucket, []).append((index, case, why))

    duplicate_reasons: dict[str, list[str]] = {}
    kept = list(passthrough)
    for items in bucketed.values():
        best_index, best_case, best_why = sorted(
            items,
            key=lambda item: (
                -_smoke_specificity_score(item[1]),
                item[0],
                item[1].id,
            ),
        )[0]
        kept.append((best_index, best_case, best_why))
        for _, case, _ in items:
            if case.id == best_case.id:
                continue
            duplicate_reasons[case.id] = [
                f"smoke 同类执行意图已由 {best_case.id} 覆盖"
            ]

    kept.sort(key=lambda item: item[0])
    return [(case, why) for _, case, why in kept], duplicate_reasons


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
    if case.priority == "high" and (
        profile != "smoke" or bool(_smoke_intent_bucket(case))
    ):
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
        mandatory_pairs = [(case, why) for case, why in mandatory_pairs if why]
        duplicate_reasons: dict[str, list[str]] = {}
        if profile == "smoke":
            mandatory_pairs, duplicate_reasons = _dedupe_smoke_mandatory_pairs(
                mandatory_pairs
            )
        selected = [case for case, _ in mandatory_pairs]
        reasons = {case.id: why for case, why in mandatory_pairs}
        reasons.update(duplicate_reasons)
        cap = _selection_cap(profile, target_count, len(selected))
        if len(selected) > cap:
            selected = selected[:cap]
            reasons = {case.id: reasons[case.id] for case in selected}
            reasons.update(duplicate_reasons)
        mandatory_count = len(selected)

        selected_ids = {case.id for case in selected}
        duplicate_ids = set(duplicate_reasons)
        remaining = [
            case
            for case in auto_cases
            if case.id not in selected_ids and case.id not in duplicate_ids
        ]
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
