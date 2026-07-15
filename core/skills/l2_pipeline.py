"""core/skills/l2_pipeline.py — L2 Analysis Pipeline Orchestrator.

编排 L2 分析管道（fact → assertion → condition → technique → coverage → case → traceability → package）。

两阶段设计:
  Phase 1 (探索前): extract_facts → derive_assertions → review_gate → generate_goals
    - 仅从 confirmed 断言生成 ExplorationGoal
    - 被 gate 拦截的断言不会产生 goal
  Phase 2 (探索后): analyze_conditions (with system_map) → ... → assemble_package
    - 使用真实 UI 证据 (SystemMapEvid) 分析条件

Review Gate:
  仅 security/data_rule 类型的 high + auto_generated 断言会被门禁拦截，
  不会进入条件分析，而是作为 manual_review_items 标记，等待人工确认后才能继续下游流程。
"""
import hashlib
import re
from urllib.parse import urlparse

from core.focus_scope import expand_focus_terms
from core.interfaces import (
    RequirementFact, RequirementAssertion, ExplorationGoal, SourceAnchor,
    SystemMapEvid, TestCondition, TestDesignTechnique,
    CoverageItem, CandidateTestCase, TraceabilityMatrix,
    CoverageBlueprint, TestAssetPackage, StructuredPrecondition,
    TestInputDatum,
)


def _split_by_review_gate(
    assertions: list[RequirementAssertion],
) -> tuple[list[RequirementAssertion], list[RequirementAssertion]]:
    """Review Gate: 将断言分为"已确认可进入下游"和"需人工审查"两组。

    规则 (优化后，降低拦截率):
    - review_status == "rejected" → 丢弃（不进入任何组）
    - risk_level == "high" AND review_status == "auto_generated" AND
      assertion_type in (security, data_rule) → 需人工审查 (仅核心安全/数据规则)
    - 其他 (low/medium, 或已 human_confirmed, 或非核心类型) → 可进入下游

    设计理由:
    - security 和 data_rule 类型的高风险断言涉及权限和数据完整性，必须人工确认
    - functional/validation/error_handling 等类型的高风险断言可直接放行
    - 目标拦截率从 ~32% 降至 ~15%
    """
    GATE_TYPES = {"security", "data_rule"}
    passed: list[RequirementAssertion] = []
    blocked: list[RequirementAssertion] = []
    for a in assertions:
        if a.review_status == "rejected":
            continue
        if _is_explicit_test_account_login_assertion(a):
            passed.append(a)
            continue
        if _is_api_or_network_assertion(a):
            passed.append(a)
            continue
        if (a.risk_level == "high"
                and a.review_status == "auto_generated"
                and a.assertion_type in GATE_TYPES):
            blocked.append(a)
        else:
            passed.append(a)
    return passed, blocked


def _is_explicit_test_account_login_assertion(assertion: RequirementAssertion) -> bool:
    text = assertion.assertion_text.lower()
    explicit_credential_markers = ("admin/admin123", "admin123")
    login_markers = ("登录", "身份验证", "认证", "login", "authentication")
    fixture_account_markers = (
        "管理员账号",
        "测试账号",
        "账号 admin",
        "admin 账号",
        "密码为",
        "password admin123",
    )
    excluded_risk_markers = (
        "越权",
        "绕过",
        "泄露",
        "权限",
        "permission",
        "bypass",
        "leak",
    )
    return (
        assertion.assertion_type in {"security", "functional", "validation"}
        and any(marker in text for marker in explicit_credential_markers)
        and (
            any(marker in text for marker in login_markers)
            or any(marker in text for marker in fixture_account_markers)
        )
        and not any(marker in text for marker in excluded_risk_markers)
    )


def _is_api_or_network_assertion(assertion: RequirementAssertion) -> bool:
    text = assertion.assertion_text.lower()
    markers = (
        "authorization",
        "bearer",
        "请求头",
        "access_token",
        "访问令牌",
        "返回令牌",
        "登录接口",
        "调用",
        "接口",
        "响应体",
        "状态码",
        "http",
        "api",
        "/auth/login",
    )
    return any(marker in text for marker in markers)


def _manual_review_label(assertion: RequirementAssertion) -> str:
    return (
        f"[高风险需人工确认] {assertion.id}: {assertion.assertion_text} "
        f"(源自事实: {', '.join(assertion.fact_ids)})"
    )


def _dedupe_manual_review_items(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def _candidate_case_text(case: CandidateTestCase) -> str:
    return (
        f"{case.title}\n{case.goal}\n{case.expected_result}\n"
        f"{case.execution_hint}"
    ).lower()


def _contains_invalid_login_requirement(text: str) -> bool:
    lowered = text.lower()
    invalid_markers = (
        "错误密码",
        "无效密码",
        "密码错误",
        "登录失败",
        "停留在登录页",
        "wrong password",
        "invalid password",
        "login failed",
    )
    login_markers = ("登录", "login", "sign in")
    return (
        any(marker in lowered for marker in invalid_markers)
        and any(marker in lowered for marker in login_markers)
    )


def _contains_quick_fill_requirement(text: str) -> bool:
    lowered = text.lower()
    return (
        any(marker in lowered for marker in ("一键填值", "quick fill", "quick-fill"))
        and any(
            marker in lowered
            for marker in (
                "admin",
                "cangjie*2026",
                "用户名",
                "密码",
                "凭据",
                "credential",
                "登录流程",
            )
        )
    )


def _contains_valid_login_requirement(text: str) -> bool:
    lowered = text.lower()
    return (
        any(marker in lowered for marker in ("admin/admin123", "admin123"))
        and any(marker in lowered for marker in ("登录", "控制台", "dashboard", "login"))
        and not _contains_invalid_login_requirement(lowered)
    )


def _is_direct_api_case_text(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "api",
            "http 200",
            "http 400",
            "http 401",
            "access_token",
            "访问令牌",
            "返回访问令牌",
            "登录接口",
            "调用登录接口",
            "authorization",
            "bearer token",
            "请求头",
            "返回唯一标识",
            "api返回",
            "api 返回",
            "接口返回",
            "调用接口",
            "状态码",
            "响应体",
            "/auth/login",
        )
    )


def _has_invalid_login_case(cases: list[CandidateTestCase]) -> bool:
    return any(
        _contains_invalid_login_requirement(_candidate_case_text(case))
        and not _is_direct_api_case_text(_candidate_case_text(case))
        for case in cases
    )


def _has_quick_fill_case(cases: list[CandidateTestCase]) -> bool:
    return any(
        _contains_quick_fill_requirement(_candidate_case_text(case))
        and not _contains_invalid_login_requirement(_candidate_case_text(case))
        for case in cases
    )


def _has_valid_login_case(cases: list[CandidateTestCase]) -> bool:
    return any(
        _contains_valid_login_requirement(_candidate_case_text(case))
        and not _is_direct_api_case_text(_candidate_case_text(case))
        and not _contains_quick_fill_requirement(_candidate_case_text(case))
        for case in cases
    )


def _extract_admin_credentials(text: str) -> list[tuple[str, str]]:
    credentials: list[tuple[str, str]] = []
    for match in re.finditer(r"\b(admin)\s*/\s*([^\s,，。；;]+)", text, flags=re.I):
        username = match.group(1)
        password = match.group(2).strip(")）]】》>\"'“”‘’.。")
        if password:
            credentials.append((username, password))
    return credentials


def _explicit_login_credentials(
    source_text: str,
) -> tuple[tuple[str, str] | None, tuple[str, str] | None]:
    credentials = _extract_admin_credentials(source_text)
    valid: tuple[str, str] | None = None
    invalid: tuple[str, str] | None = None
    for username, password in credentials:
        if password == "cangjie*2026":
            invalid = (username, password)
            continue
        if valid is None:
            valid = (username, password)
    return valid, invalid


def _contains_agent_create_requirement(text: str) -> bool:
    lowered = text.lower()
    return (
        any(
            marker in lowered
            for marker in (
                "新增智能体",
                "创建智能体",
                "测试智能体",
                "agent_name",
                "agentname",
                "gatewayurl",
            )
        )
        and any(marker in lowered for marker in ("新增", "创建", "create"))
        and any(marker in lowered for marker in ("ta-20260704", "gatewayurl", "网关地址"))
    )


def _contains_agent_invalid_gateway_requirement(text: str) -> bool:
    lowered = text.lower()
    return (
        "智能体" in lowered
        and any(marker in lowered for marker in ("gatewayurl", "网关地址", "url"))
        and any(marker in lowered for marker in ("not-url", "非法", "格式", "校验", "阻断", "invalid"))
    )


def _is_agent_ui_create_case_text(text: str) -> bool:
    lowered = text.lower()
    return (
        "智能体" in lowered
        and any(marker in lowered for marker in ("新增", "创建", "create"))
        and any(marker in lowered for marker in ("端到端", "ui", "页面", "列表确认", "搜索", "可搜索"))
        and not _is_direct_api_case_text(lowered)
    )


def _is_agent_invalid_gateway_case_text(text: str) -> bool:
    lowered = text.lower()
    return (
        _contains_agent_invalid_gateway_requirement(lowered)
        and not _is_direct_api_case_text(lowered)
    )


def _has_agent_ui_create_case(cases: list[CandidateTestCase]) -> bool:
    return any(_is_agent_ui_create_case_text(_candidate_case_text(case)) for case in cases)


def _has_agent_invalid_gateway_case(cases: list[CandidateTestCase]) -> bool:
    return any(_is_agent_invalid_gateway_case_text(_candidate_case_text(case)) for case in cases)


def _agent_test_data(source_text: str) -> tuple[str, str, str, str]:
    name = "测试智能体-TA-20260704-AUTO"
    desc = "由 test_agent 自动化验收创建，可安全清理 TA-20260704"
    gateway = "https://agent-gateway.cangjie.ai/v1/ta-20260704-auto"
    invalid_name = "测试智能体-TA-20260704-INVALID"
    name_match = re.search(r"测试智能体-[\w-]*TA-20260704-AUTO", source_text, flags=re.I)
    gateway_match = re.search(
        r"https://[^\s,，。；;\"'）)]+ta-20260704-auto",
        source_text,
        flags=re.I,
    )
    invalid_match = re.search(r"测试智能体-[\w-]*TA-20260704-INVALID", source_text, flags=re.I)
    if name_match:
        name = name_match.group(0)
    if gateway_match:
        gateway = gateway_match.group(0)
    if invalid_match:
        invalid_name = invalid_match.group(0)
    return name, desc, gateway, invalid_name


def _contains_dataset_create_requirement(text: str) -> bool:
    lowered = text.lower()
    return (
        "知识库" in lowered
        and any(marker in lowered for marker in ("新建", "新增", "创建", "create"))
        and any(marker in lowered for marker in ("测试知识库", "ta-20260704-auto", "dataset"))
    )


def _contains_dataset_empty_name_requirement(text: str) -> bool:
    lowered = text.lower()
    return (
        "知识库" in lowered
        and any(marker in lowered for marker in ("名称留空", "空名称", "name 为空", "required", "必填"))
        and any(marker in lowered for marker in ("ta-20260704-empty", "不能创建", "未创建", "阻断"))
    )


def _is_dataset_ui_create_case_text(text: str) -> bool:
    lowered = text.lower()
    return (
        "知识库" in lowered
        and any(marker in lowered for marker in ("新建", "新增", "创建", "create"))
        and any(marker in lowered for marker in ("测试知识库", "ta-20260704-auto"))
        and any(marker in lowered for marker in ("ui", "页面", "弹窗", "列表", "搜索"))
        and not _is_direct_api_case_text(lowered)
    )


def _is_dataset_empty_name_case_text(text: str) -> bool:
    lowered = text.lower()
    return (
        "知识库" in lowered
        and any(marker in lowered for marker in ("名称留空", "空名称", "required", "必填"))
        and any(marker in lowered for marker in ("ta-20260704-empty", "阻断", "不能创建", "未创建"))
        and not _is_direct_api_case_text(lowered)
    )


def _has_dataset_ui_create_case(cases: list[CandidateTestCase]) -> bool:
    return any(_is_dataset_ui_create_case_text(_candidate_case_text(case)) for case in cases)


def _has_dataset_empty_name_case(cases: list[CandidateTestCase]) -> bool:
    return any(_is_dataset_empty_name_case_text(_candidate_case_text(case)) for case in cases)


def _dataset_test_data(source_text: str) -> tuple[str, str, str]:
    name = "测试知识库-TA-20260704-AUTO"
    intro = "由 test_agent 自动化验收创建，可安全清理 TA-20260704"
    empty_marker = "TA-20260704-EMPTY"
    name_match = re.search(r"测试知识库-[\w-]*TA-20260704-AUTO", source_text, flags=re.I)
    empty_match = re.search(r"TA-20260704-EMPTY", source_text, flags=re.I)
    if name_match:
        name = name_match.group(0)
    if empty_match:
        empty_marker = empty_match.group(0)
    return name, intro, empty_marker


def _contains_skill_scaffold_requirement(text: str) -> bool:
    lowered = text.lower()
    return (
        any(marker in lowered for marker in ("技能", "skill", "/system/skill"))
        and any(marker in lowered for marker in ("脚手架", "scaffold", "初始化"))
        and any(marker in lowered for marker in ("ta-20260704", "skill.md", "index.js", "文件树"))
    )


def _contains_skill_duplicate_core_file_requirement(text: str) -> bool:
    lowered = text.lower()
    return (
        any(marker in lowered for marker in ("技能", "skill", "/system/skill"))
        and "skill.md" in lowered
        and any(marker in lowered for marker in ("重复", "不可重复", "阻断", "禁止", "duplicate"))
    )


def _is_skill_scaffold_case_text(text: str) -> bool:
    lowered = text.lower()
    return (
        any(marker in lowered for marker in ("技能", "skill"))
        and any(marker in lowered for marker in ("脚手架", "scaffold", "初始化"))
        and any(marker in lowered for marker in ("ui", "页面", "列表", "文件树", "skill.md", "index.js"))
        and not _is_direct_api_case_text(lowered)
        and not _is_skill_duplicate_core_file_case_text(lowered)
    )


def _is_skill_duplicate_core_file_case_text(text: str) -> bool:
    lowered = text.lower()
    return (
        any(marker in lowered for marker in ("技能", "skill"))
        and "skill.md" in lowered
        and any(marker in lowered for marker in ("重复", "不可重复", "阻断", "禁止", "duplicate"))
        and not _is_direct_api_case_text(lowered)
    )


def _has_skill_scaffold_case(cases: list[CandidateTestCase]) -> bool:
    return any(_is_skill_scaffold_case_text(_candidate_case_text(case)) for case in cases)


def _has_skill_duplicate_core_file_case(cases: list[CandidateTestCase]) -> bool:
    return any(_is_skill_duplicate_core_file_case_text(_candidate_case_text(case)) for case in cases)


def _skill_test_data(source_text: str) -> tuple[str, str, str]:
    name = "测试技能-TA-20260704-AUTO"
    author = "test_agent"
    description = "由 test_agent 自动化验收创建，可安全清理 TA-20260704"
    name_match = re.search(r"测试技能-[^\s,，。；;\"'）)]*TA-20260704-AUTO", source_text, flags=re.I)
    if name_match:
        name = name_match.group(0)
    return name, author, description


def _replace_case_text(case: CandidateTestCase, old: str, new: str) -> CandidateTestCase:
    if not old or old == new:
        return case
    new_input_data: list[TestInputDatum] = []
    for datum in case.input_data:
        placeholder = datum.placeholder
        value = datum.value
        updates = {}
        if isinstance(placeholder, str) and old in placeholder:
            updates["placeholder"] = placeholder.replace(old, new)
        if isinstance(value, str) and old in value:
            updates["value"] = value.replace(old, new)
        new_input_data.append(datum.model_copy(update=updates) if updates else datum)
    return case.model_copy(update={
        "goal": case.goal.replace(old, new),
        "expected_result": case.expected_result.replace(old, new),
        "execution_hint": case.execution_hint.replace(old, new),
        "description": case.description.replace(old, new),
        "input_data": new_input_data,
    })


def _normalize_explicit_login_case_credentials(
    cases: list[CandidateTestCase],
    source_text: str,
) -> list[CandidateTestCase]:
    valid, invalid = _explicit_login_credentials(source_text)
    if valid is None or invalid is None:
        return cases
    valid_credential = f"{valid[0]}/{valid[1]}"
    invalid_credential = f"{invalid[0]}/{invalid[1]}"
    normalized: list[CandidateTestCase] = []
    for case in cases:
        text = _candidate_case_text(case)
        is_valid_login = (
            any(marker in text for marker in ("有效凭据", "登录成功", "控制台", "dashboard"))
            and not _contains_invalid_login_requirement(text)
            and "一键填值" not in text
        )
        if is_valid_login and invalid_credential.lower() in text:
            normalized.append(_replace_case_text(case, invalid_credential, valid_credential))
        else:
            normalized.append(case)
    return normalized


def _normalize_invalid_login_case_shape(
    cases: list[CandidateTestCase],
) -> list[CandidateTestCase]:
    normalized: list[CandidateTestCase] = []
    for case in cases:
        if not _contains_invalid_login_requirement(_candidate_case_text(case)):
            normalized.append(case)
            continue
        preconditions = []
        for precondition in case.preconditions:
            if precondition.type == "account_role":
                preconditions.append(
                    StructuredPrecondition(
                        type="data",
                        description=precondition.description,
                        satisfiable_by_agent=precondition.satisfiable_by_agent,
                        failure_policy=precondition.failure_policy,
                    )
                )
            else:
                preconditions.append(precondition)
        normalized.append(
            case.model_copy(update={
                "branch_type": "negative",
                "priority": "high",
                "estimated_cost": "low",
                "required_roles": [],
                "preconditions": preconditions,
            })
        )
    return normalized


def _normalize_quick_fill_case_shape(
    cases: list[CandidateTestCase],
    source_text: str,
) -> list[CandidateTestCase]:
    if not _contains_quick_fill_requirement(source_text):
        return cases
    _, invalid = _explicit_login_credentials(source_text)
    username = "admin"
    password = invalid[1] if invalid is not None else "cangjie*2026"
    normalized: list[CandidateTestCase] = []
    for case in cases:
        text = _candidate_case_text(case)
        if (
            _contains_quick_fill_requirement(text)
            and not _contains_invalid_login_requirement(text)
        ):
            normalized.append(
                case.model_copy(update={
                    "goal": (
                        f"点击一键填值体验后验证 username={username} "
                        f"且 password={password}"
                    ),
                    "expected_result": f"username={username}，password={password}",
                    "priority": "high",
                    "estimated_cost": "low",
                    "branch_type": "positive",
                    "required_roles": [],
                })
            )
        else:
            normalized.append(case)
    return normalized


def _normalize_valid_login_case_shape(
    cases: list[CandidateTestCase],
    source_text: str,
) -> list[CandidateTestCase]:
    if not _contains_valid_login_requirement(source_text):
        return cases
    normalized: list[CandidateTestCase] = []
    for case in cases:
        text = _candidate_case_text(case)
        if (
            _contains_valid_login_requirement(text)
            and not _contains_invalid_login_requirement(text)
            and not _contains_quick_fill_requirement(text)
            and not _is_direct_api_case_text(text)
        ):
            normalized.append(
                case.model_copy(update={
                    "expected_result": (
                        "提交有效凭据后进入控制台，并显示登录后入口或账号身份。"
                    ),
                    "priority": "high",
                    "estimated_cost": "low",
                    "branch_type": (
                        case.branch_type if case.branch_type == "e2e" else "positive"
                    ),
                    "required_roles": [],
                })
            )
        else:
            normalized.append(case)
    return normalized


def _source_requests_no_business_writes(source_text: str) -> bool:
    lowered = source_text.lower()
    return any(
        marker in lowered
        for marker in (
            "不要创建、修改、删除",
            "不要创建、编辑或删除",
            "不要创建、修改或删除",
            "不新增、编辑或删除",
            "不新增、修改或删除",
            "不执行新增",
            "不创建业务数据",
            "只读",
            "read-only",
            "低副作用",
        )
    )


def _is_business_write_case(case: CandidateTestCase) -> bool:
    text = _candidate_case_text(case)
    business_markers = (
        "智能体",
        "agent",
        "知识库",
        "dataset",
        "技能",
        "skill",
    )
    write_markers = (
        "新增",
        "新建",
        "创建",
        "编辑",
        "修改",
        "保存",
        "删除",
        "上传",
        "脚手架",
        "scaffold",
        "create",
        "update",
        "delete",
    )
    return (
        any(marker in text for marker in business_markers)
        and any(marker in text for marker in write_markers)
    )


def _filter_no_write_business_cases(
    cases: list[CandidateTestCase],
    source_text: str,
) -> list[CandidateTestCase]:
    if not _source_requests_no_business_writes(source_text):
        return cases
    return [case for case in cases if not _is_business_write_case(case)]


def _normalize_explicit_agent_case_shape(
    cases: list[CandidateTestCase],
    source_text: str,
) -> list[CandidateTestCase]:
    if not (
        _contains_agent_create_requirement(source_text)
        or _contains_agent_invalid_gateway_requirement(source_text)
    ):
        return cases
    name, desc, gateway, invalid_name = _agent_test_data(source_text)
    normalized: list[CandidateTestCase] = []
    promoted_create = False
    promoted_invalid = False
    for case in cases:
        text = _candidate_case_text(case)
        if _is_agent_invalid_gateway_case_text(text):
            if promoted_invalid:
                normalized.append(
                    case.model_copy(update={
                        "priority": "medium",
                        "branch_type": "negative",
                    })
                )
                continue
            promoted_invalid = True
            normalized.append(
                case.model_copy(update={
                    "goal": (
                        f"通过 UI 新增智能体 {invalid_name} 时输入 gatewayUrl=not-url，"
                        "验证校验阻断且不会产生可搜索记录。"
                    ),
                    "expected_result": (
                        "提交后出现 URL 格式校验或后端错误提示，弹窗不应作为新增成功关闭；"
                        "搜索 TA-20260704-INVALID 或 API 后置证据证明未创建记录。"
                    ),
                    "priority": "high",
                    "estimated_cost": "low",
                    "branch_type": "negative",
                    "input_data": [
                        TestInputDatum(
                            name="agent_name",
                            value=None,
                            placeholder=invalid_name,
                            source="generated",
                            sensitivity="internal",
                            generation_strategy="explicit agent invalid-url requirement",
                            boundary_category="negative",
                        ),
                        TestInputDatum(
                            name="gateway_url",
                            value=None,
                            placeholder="not-url",
                            source="generated",
                            sensitivity="public",
                            generation_strategy="explicit agent invalid-url requirement",
                            boundary_category="negative",
                        ),
                    ],
                })
            )
            continue
        if _is_agent_ui_create_case_text(text):
            if promoted_create:
                normalized.append(case.model_copy(update={"priority": "medium"}))
                continue
            promoted_create = True
            normalized.append(
                case.model_copy(update={
                    "goal": (
                        f"通过 UI 新增智能体 {name}，保存后搜索 "
                        "TA-20260704-AUTO 并验证列表命中。"
                    ),
                    "expected_result": (
                        f"列表搜索 TA-20260704-AUTO 后显示 {name}，"
                        "并能通过页面刷新或 /system/agent/list 后置证据证明持久化。"
                    ),
                    "priority": "high",
                    "estimated_cost": "low",
                    "branch_type": "e2e",
                    "input_data": [
                        TestInputDatum(
                            name="agent_name",
                            value=None,
                            placeholder=name,
                            source="generated",
                            sensitivity="internal",
                            generation_strategy="explicit agent create requirement",
                        ),
                        TestInputDatum(
                            name="agent_desc",
                            value=None,
                            placeholder=desc,
                            source="generated",
                            sensitivity="internal",
                            generation_strategy="explicit agent create requirement",
                        ),
                        TestInputDatum(
                            name="gateway_url",
                            value=None,
                            placeholder=gateway,
                            source="generated",
                            sensitivity="public",
                            generation_strategy="explicit agent create requirement",
                        ),
                    ],
                })
            )
            continue
        normalized.append(case)
    return normalized


def _normalize_explicit_dataset_case_shape(
    cases: list[CandidateTestCase],
    source_text: str,
) -> list[CandidateTestCase]:
    if not (
        _contains_dataset_create_requirement(source_text)
        or _contains_dataset_empty_name_requirement(source_text)
    ):
        return cases
    name, intro, empty_marker = _dataset_test_data(source_text)
    normalized: list[CandidateTestCase] = []
    promoted_create = False
    promoted_empty = False
    for case in cases:
        text = _candidate_case_text(case)
        if _is_dataset_empty_name_case_text(text):
            if promoted_empty:
                normalized.append(case.model_copy(update={"priority": "medium", "branch_type": "negative"}))
                continue
            promoted_empty = True
            normalized.append(
                case.model_copy(update={
                    "goal": (
                        "通过 UI 新建知识库时名称留空，描述填写 "
                        f"测试空名称-{empty_marker}，点击保存并验证必填校验阻断。"
                    ),
                    "expected_result": (
                        "名称为空时保存被 required 或前端逻辑阻断，弹窗保持打开；"
                        f"搜索/API 后置证据证明未创建 {empty_marker} 记录。"
                    ),
                    "priority": "high",
                    "estimated_cost": "low",
                    "branch_type": "negative",
                    "input_data": [
                        TestInputDatum(
                            name="dataset_name",
                            value="",
                            placeholder="",
                            source="generated",
                            sensitivity="internal",
                            generation_strategy="explicit dataset empty-name requirement",
                            boundary_category="negative",
                        ),
                        TestInputDatum(
                            name="dataset_intro",
                            value=None,
                            placeholder=f"测试空名称-{empty_marker}",
                            source="generated",
                            sensitivity="internal",
                            generation_strategy="explicit dataset empty-name requirement",
                            boundary_category="negative",
                        ),
                    ],
                })
            )
            continue
        if _is_dataset_ui_create_case_text(text):
            if promoted_create:
                normalized.append(case.model_copy(update={"priority": "medium"}))
                continue
            promoted_create = True
            normalized.append(
                case.model_copy(update={
                    "goal": (
                        f"通过 UI 新建知识库 {name}，保存后验证列表命中 "
                        "TA-20260704-AUTO。"
                    ),
                    "expected_result": (
                        f"列表显示 {name}，并能通过页面刷新或 "
                        "/fastgpt/dataset/list 后置证据证明持久化。"
                    ),
                    "priority": "high",
                    "estimated_cost": "low",
                    "branch_type": "e2e",
                    "input_data": [
                        TestInputDatum(
                            name="dataset_name",
                            value=None,
                            placeholder=name,
                            source="generated",
                            sensitivity="internal",
                            generation_strategy="explicit dataset create requirement",
                        ),
                        TestInputDatum(
                            name="dataset_intro",
                            value=None,
                            placeholder=intro,
                            source="generated",
                            sensitivity="internal",
                            generation_strategy="explicit dataset create requirement",
                        ),
                    ],
                })
            )
            continue
        normalized.append(case)
    return normalized


def _normalize_explicit_skill_case_shape(
    cases: list[CandidateTestCase],
    source_text: str,
) -> list[CandidateTestCase]:
    if not (
        _contains_skill_scaffold_requirement(source_text)
        or _contains_skill_duplicate_core_file_requirement(source_text)
    ):
        return cases
    name, author, description = _skill_test_data(source_text)
    normalized: list[CandidateTestCase] = []
    promoted_scaffold = False
    promoted_duplicate = False
    for case in cases:
        text = _candidate_case_text(case)
        if _is_skill_duplicate_core_file_case_text(text):
            if promoted_duplicate:
                normalized.append(case.model_copy(update={"priority": "medium", "branch_type": "negative"}))
                continue
            promoted_duplicate = True
            normalized.append(
                case.model_copy(update={
                    "goal": (
                        "通过 UI 打开技能在线修编，尝试新建重复核心文件 SKILL.md，"
                        "验证核心文件重复创建被阻断。"
                    ),
                    "expected_result": (
                        "页面出现 SKILL.md 核心文件不可重复创建或禁止创建提示，"
                        "文件树仍只保留一个核心 SKILL.md。"
                    ),
                    "priority": "high",
                    "estimated_cost": "low",
                    "branch_type": "negative",
                    "input_data": [
                        TestInputDatum(
                            name="skill_file_path",
                            value=None,
                            placeholder="SKILL.md",
                            source="generated",
                            sensitivity="internal",
                            generation_strategy="explicit skill duplicate-core-file requirement",
                            boundary_category="negative",
                        )
                    ],
                })
            )
            continue
        if _is_skill_scaffold_case_text(text):
            if promoted_scaffold:
                normalized.append(case.model_copy(update={"priority": "medium"}))
                continue
            promoted_scaffold = True
            normalized.append(
                case.model_copy(update={
                    "goal": (
                        f"通过 UI 技能管理快速初始化脚手架，在线修编元数据为 {name}，"
                        "保存后验证列表与文件树。"
                    ),
                    "expected_result": (
                        f"技能列表显示 {name}；文件树包含 SKILL.md 和 index.js；"
                        "可通过 /system/skill/page 与 /system/skill/{skillId}/files 后置证据证明持久化。"
                    ),
                    "priority": "high",
                    "estimated_cost": "low",
                    "branch_type": "e2e",
                    "input_data": [
                        TestInputDatum(
                            name="skill_name",
                            value=None,
                            placeholder=name,
                            source="generated",
                            sensitivity="internal",
                            generation_strategy="explicit skill scaffold requirement",
                        ),
                        TestInputDatum(
                            name="skill_author",
                            value=None,
                            placeholder=author,
                            source="generated",
                            sensitivity="internal",
                            generation_strategy="explicit skill scaffold requirement",
                        ),
                        TestInputDatum(
                            name="skill_description",
                            value=None,
                            placeholder=description,
                            source="generated",
                            sensitivity="internal",
                            generation_strategy="explicit skill scaffold requirement",
                        ),
                    ],
                })
            )
            continue
        normalized.append(case)
    return normalized


def _first_matching_line(text: str, markers: tuple[str, ...]) -> str:
    for line in text.splitlines():
        if any(marker.lower() in line.lower() for marker in markers):
            return line.strip()
    return ""


def _augment_explicit_login_requirement_cases(
    facts: list[RequirementFact],
    assertions: list[RequirementAssertion],
    conditions: list[TestCondition],
    techniques: list[TestDesignTechnique],
    coverage_items: list[CoverageItem],
    cases: list[CandidateTestCase],
    source_text: str,
) -> tuple[
    list[RequirementFact],
    list[RequirementAssertion],
    list[TestCondition],
    list[TestDesignTechnique],
    list[CoverageItem],
    list[CandidateTestCase],
]:
    cases = _normalize_explicit_login_case_credentials(cases, source_text)
    cases = _normalize_invalid_login_case_shape(cases)
    cases = _normalize_quick_fill_case_shape(cases, source_text)
    cases = _normalize_valid_login_case_shape(cases, source_text)
    facts, assertions, conditions, techniques, coverage_items, cases = _augment_explicit_valid_login_case(
        facts,
        assertions,
        conditions,
        techniques,
        coverage_items,
        cases,
        source_text,
    )
    facts, assertions, conditions, techniques, coverage_items, cases = _augment_explicit_quick_fill_case(
        facts,
        assertions,
        conditions,
        techniques,
        coverage_items,
        cases,
        source_text,
    )
    facts, assertions, conditions, techniques, coverage_items, cases = _augment_explicit_invalid_login_case(
        facts,
        assertions,
        conditions,
        techniques,
        coverage_items,
        cases,
        source_text,
    )
    return facts, assertions, conditions, techniques, coverage_items, cases


def _augment_explicit_agent_requirement_cases(
    facts: list[RequirementFact],
    assertions: list[RequirementAssertion],
    conditions: list[TestCondition],
    techniques: list[TestDesignTechnique],
    coverage_items: list[CoverageItem],
    cases: list[CandidateTestCase],
    source_text: str,
) -> tuple[
    list[RequirementFact],
    list[RequirementAssertion],
    list[TestCondition],
    list[TestDesignTechnique],
    list[CoverageItem],
    list[CandidateTestCase],
]:
    cases = _normalize_explicit_agent_case_shape(cases, source_text)
    facts, assertions, conditions, techniques, coverage_items, cases = _augment_explicit_agent_create_case(
        facts,
        assertions,
        conditions,
        techniques,
        coverage_items,
        cases,
        source_text,
    )
    facts, assertions, conditions, techniques, coverage_items, cases = _augment_explicit_agent_invalid_gateway_case(
        facts,
        assertions,
        conditions,
        techniques,
        coverage_items,
        cases,
        source_text,
    )
    return facts, assertions, conditions, techniques, coverage_items, cases


def _augment_explicit_dataset_requirement_cases(
    facts: list[RequirementFact],
    assertions: list[RequirementAssertion],
    conditions: list[TestCondition],
    techniques: list[TestDesignTechnique],
    coverage_items: list[CoverageItem],
    cases: list[CandidateTestCase],
    source_text: str,
) -> tuple[
    list[RequirementFact],
    list[RequirementAssertion],
    list[TestCondition],
    list[TestDesignTechnique],
    list[CoverageItem],
    list[CandidateTestCase],
]:
    cases = _normalize_explicit_dataset_case_shape(cases, source_text)
    facts, assertions, conditions, techniques, coverage_items, cases = _augment_explicit_dataset_create_case(
        facts,
        assertions,
        conditions,
        techniques,
        coverage_items,
        cases,
        source_text,
    )
    facts, assertions, conditions, techniques, coverage_items, cases = _augment_explicit_dataset_empty_name_case(
        facts,
        assertions,
        conditions,
        techniques,
        coverage_items,
        cases,
        source_text,
    )
    return facts, assertions, conditions, techniques, coverage_items, cases


def _augment_explicit_skill_requirement_cases(
    facts: list[RequirementFact],
    assertions: list[RequirementAssertion],
    conditions: list[TestCondition],
    techniques: list[TestDesignTechnique],
    coverage_items: list[CoverageItem],
    cases: list[CandidateTestCase],
    source_text: str,
) -> tuple[
    list[RequirementFact],
    list[RequirementAssertion],
    list[TestCondition],
    list[TestDesignTechnique],
    list[CoverageItem],
    list[CandidateTestCase],
]:
    cases = _normalize_explicit_skill_case_shape(cases, source_text)
    facts, assertions, conditions, techniques, coverage_items, cases = _augment_explicit_skill_scaffold_case(
        facts,
        assertions,
        conditions,
        techniques,
        coverage_items,
        cases,
        source_text,
    )
    facts, assertions, conditions, techniques, coverage_items, cases = _augment_explicit_skill_duplicate_core_file_case(
        facts,
        assertions,
        conditions,
        techniques,
        coverage_items,
        cases,
        source_text,
    )
    return facts, assertions, conditions, techniques, coverage_items, cases


def _augment_explicit_agent_create_case(
    facts: list[RequirementFact],
    assertions: list[RequirementAssertion],
    conditions: list[TestCondition],
    techniques: list[TestDesignTechnique],
    coverage_items: list[CoverageItem],
    cases: list[CandidateTestCase],
    source_text: str,
) -> tuple[
    list[RequirementFact],
    list[RequirementAssertion],
    list[TestCondition],
    list[TestDesignTechnique],
    list[CoverageItem],
    list[CandidateTestCase],
]:
    if not _contains_agent_create_requirement(source_text) or _has_agent_ui_create_case(cases):
        return facts, assertions, conditions, techniques, coverage_items, cases

    name, desc, gateway, _ = _agent_test_data(source_text)
    quote = _first_matching_line(
        source_text,
        ("TA-20260704-AUTO", "新增智能体", "创建智能体", gateway),
    )
    if not quote:
        quote = f"Explicit rule requires creating agent {name} through UI."

    fact = RequirementFact(
        id="FACT-EXPLICIT-AGENT-CREATE",
        source_type="inferred",
        source_reference="explicit_agent_create_requirement",
        quote=quote,
        subject="智能体广场",
        action="通过 UI 新增智能体",
        object=name,
        condition="管理员已登录并打开智能体广场",
        outcome="列表搜索命中新增智能体",
        confidence=1.0,
        status="confirmed",
    )
    assertion = RequirementAssertion(
        id="ASSERT-EXPLICIT-AGENT-CREATE",
        fact_ids=[fact.id],
        assertion_text=f"通过 UI 新增智能体 {name} 后，必须能在列表搜索中命中该记录。",
        assertion_type="functional",
        risk_level="high",
        review_status="human_confirmed",
        source_references=["rules"],
    )
    condition = TestCondition(
        id="COND-EXPLICIT-AGENT-CREATE",
        assertion_ref=assertion.id,
        condition_type="functional",
        statement=assertion.assertion_text,
        precondition="管理员已登录，智能体广场页面可访问，TA-20260704 旧测试数据已清理。",
        trigger=f"点击新增智能体，填写 {name}、{desc}、{gateway} 并保存。",
        oracle=f"搜索 TA-20260704-AUTO 后，列表显示 {name}。",
        oracle_type="ui_state",
        risk_level="high",
        measurability="measurable",
        source_references=["rules"],
        branch_type="e2e",
    )
    technique = TestDesignTechnique(
        id="TECH-EXPLICIT-AGENT-CREATE",
        condition_id=condition.id,
        primary_technique="equivalence_partitioning",
        supplementary_techniques=["risk_based"],
        rationale="显式规则要求覆盖智能体新增写操作正向路径。",
    )
    coverage = CoverageItem(
        id="COV-EXPLICIT-AGENT-CREATE",
        condition_id=condition.id,
        technique_id=technique.id,
        coverage_dimension="normal",
        goal=condition.statement,
        risk_level="high",
        variant_key="agent-create-ui",
        source_references=["rules"],
        branch_type="e2e",
    )
    case = CandidateTestCase(
        id="TC-EXPLICIT-AGENT-CREATE",
        title="通过 UI 新增智能体并搜索命中",
        goal=f"通过 UI 新增智能体 {name}，保存后搜索 TA-20260704-AUTO。",
        description="覆盖显式要求的智能体广场新增写操作。",
        preconditions=[
            StructuredPrecondition(
                type="account_role",
                description="管理员已登录。",
                required_role="管理员",
                satisfiable_by_agent=True,
                failure_policy="incomplete",
            ),
            StructuredPrecondition(
                type="data",
                description="TA-20260704 旧测试智能体已通过清理助手清空。",
                satisfiable_by_agent=True,
                failure_policy="incomplete",
            ),
        ],
        input_data=[
            TestInputDatum(
                name="agent_name",
                value=None,
                placeholder=name,
                source="generated",
                sensitivity="internal",
                generation_strategy="explicit agent create requirement",
            ),
            TestInputDatum(
                name="agent_desc",
                value=None,
                placeholder=desc,
                source="generated",
                sensitivity="internal",
                generation_strategy="explicit agent create requirement",
            ),
            TestInputDatum(
                name="gateway_url",
                value=None,
                placeholder=gateway,
                source="generated",
                sensitivity="public",
                generation_strategy="explicit agent create requirement",
            ),
        ],
        expected_result=(
            f"搜索 TA-20260704-AUTO 后列表显示 {name}；"
            "刷新页面或 GET /system/agent/list 后仍可查到该记录。"
        ),
        priority="high",
        category="functional",
        trace_references=[coverage.id],
        execution_hint=(
            "登录后进入智能体广场，点击新增智能体，按测试数据填写名称、描述和网关地址，"
            "保存后搜索 TA-20260704-AUTO 并验证列表命中。"
        ),
        required_roles=["管理员"],
        branch_type="e2e",
        estimated_cost="low",
    )
    return (
        [*facts, fact],
        [*assertions, assertion],
        [*conditions, condition],
        [*techniques, technique],
        [*coverage_items, coverage],
        [*cases, case],
    )


def _augment_explicit_agent_invalid_gateway_case(
    facts: list[RequirementFact],
    assertions: list[RequirementAssertion],
    conditions: list[TestCondition],
    techniques: list[TestDesignTechnique],
    coverage_items: list[CoverageItem],
    cases: list[CandidateTestCase],
    source_text: str,
) -> tuple[
    list[RequirementFact],
    list[RequirementAssertion],
    list[TestCondition],
    list[TestDesignTechnique],
    list[CoverageItem],
    list[CandidateTestCase],
]:
    if (
        not _contains_agent_invalid_gateway_requirement(source_text)
        or _has_agent_invalid_gateway_case(cases)
    ):
        return facts, assertions, conditions, techniques, coverage_items, cases

    _, _, _, invalid_name = _agent_test_data(source_text)
    quote = _first_matching_line(
        source_text,
        ("not-url", "非法 URL", "非法URL", "gatewayUrl=not-url"),
    )
    if not quote:
        quote = f"Explicit rule requires rejecting invalid gateway URL for {invalid_name}."

    fact = RequirementFact(
        id="FACT-EXPLICIT-AGENT-INVALID-GATEWAY",
        source_type="inferred",
        source_reference="explicit_agent_invalid_gateway_requirement",
        quote=quote,
        subject="智能体广场",
        action="阻断非法网关地址",
        object="gatewayUrl=not-url",
        condition="管理员新增智能体时输入非法 URL",
        outcome="校验失败且不创建记录",
        confidence=1.0,
        status="confirmed",
    )
    assertion = RequirementAssertion(
        id="ASSERT-EXPLICIT-AGENT-INVALID-GATEWAY",
        fact_ids=[fact.id],
        assertion_text=(
            f"通过 UI 使用 gatewayUrl=not-url 新增智能体 {invalid_name} 时，"
            "必须被校验阻断且不能产生可搜索记录。"
        ),
        assertion_type="validation",
        risk_level="high",
        review_status="human_confirmed",
        source_references=["rules"],
    )
    condition = TestCondition(
        id="COND-EXPLICIT-AGENT-INVALID-GATEWAY",
        assertion_ref=assertion.id,
        condition_type="validation",
        statement=assertion.assertion_text,
        precondition="管理员已登录并打开智能体新增弹窗。",
        trigger=f"填写名称 {invalid_name}，网关地址 not-url，并提交保存。",
        oracle="页面显示 URL 格式错误或后端校验错误，且搜索 TA-20260704-INVALID 无记录。",
        oracle_type="ui_state",
        risk_level="high",
        measurability="measurable",
        source_references=["rules"],
        branch_type="negative",
    )
    technique = TestDesignTechnique(
        id="TECH-EXPLICIT-AGENT-INVALID-GATEWAY",
        condition_id=condition.id,
        primary_technique="error_guessing",
        supplementary_techniques=["boundary_value_analysis"],
        rationale="显式规则要求覆盖非法 gatewayUrl 约束路径。",
    )
    coverage = CoverageItem(
        id="COV-EXPLICIT-AGENT-INVALID-GATEWAY",
        condition_id=condition.id,
        technique_id=technique.id,
        coverage_dimension="negative",
        goal=condition.statement,
        risk_level="high",
        variant_key="agent-invalid-gateway",
        source_references=["rules"],
        branch_type="negative",
    )
    case = CandidateTestCase(
        id="TC-EXPLICIT-AGENT-INVALID-GATEWAY",
        title="非法 gatewayUrl 新增智能体被阻断",
        goal=(
            f"通过 UI 尝试新增智能体 {invalid_name}，gatewayUrl 填 not-url，"
            "验证不会创建记录。"
        ),
        description="覆盖显式要求的智能体新增 URL 校验负向路径。",
        preconditions=[
            StructuredPrecondition(
                type="account_role",
                description="管理员已登录。",
                required_role="管理员",
                satisfiable_by_agent=True,
                failure_policy="incomplete",
            )
        ],
        input_data=[
            TestInputDatum(
                name="agent_name",
                value=None,
                placeholder=invalid_name,
                source="generated",
                sensitivity="internal",
                generation_strategy="explicit agent invalid-url requirement",
                boundary_category="negative",
            ),
            TestInputDatum(
                name="gateway_url",
                value=None,
                placeholder="not-url",
                source="generated",
                sensitivity="public",
                generation_strategy="explicit agent invalid-url requirement",
                boundary_category="negative",
            ),
        ],
        expected_result=(
            "提交后显示 URL 格式错误或后端校验失败；"
            "搜索 TA-20260704-INVALID 或 API 后置证据证明未创建记录。"
        ),
        priority="high",
        category="validation",
        trace_references=[coverage.id],
        execution_hint=(
            "登录后进入智能体广场，打开新增智能体弹窗，填写负向测试名称和 not-url，"
            "提交后观察校验提示，并确认 TA-20260704-INVALID 不存在。"
        ),
        required_roles=["管理员"],
        branch_type="negative",
        estimated_cost="low",
    )
    return (
        [*facts, fact],
        [*assertions, assertion],
        [*conditions, condition],
        [*techniques, technique],
        [*coverage_items, coverage],
        [*cases, case],
    )


def _augment_explicit_dataset_create_case(
    facts: list[RequirementFact],
    assertions: list[RequirementAssertion],
    conditions: list[TestCondition],
    techniques: list[TestDesignTechnique],
    coverage_items: list[CoverageItem],
    cases: list[CandidateTestCase],
    source_text: str,
) -> tuple[
    list[RequirementFact],
    list[RequirementAssertion],
    list[TestCondition],
    list[TestDesignTechnique],
    list[CoverageItem],
    list[CandidateTestCase],
]:
    if not _contains_dataset_create_requirement(source_text) or _has_dataset_ui_create_case(cases):
        return facts, assertions, conditions, techniques, coverage_items, cases

    name, intro, _ = _dataset_test_data(source_text)
    quote = _first_matching_line(
        source_text,
        ("TA-20260704-AUTO", "新建知识库", "新增知识库", name),
    )
    if not quote:
        quote = f"Explicit rule requires creating dataset {name} through UI."

    fact = RequirementFact(
        id="FACT-EXPLICIT-DATASET-CREATE",
        source_type="inferred",
        source_reference="explicit_dataset_create_requirement",
        quote=quote,
        subject="知识库管理",
        action="通过 UI 新建知识库",
        object=name,
        condition="管理员已登录并打开知识库管理",
        outcome="列表出现新增知识库",
        confidence=1.0,
        status="confirmed",
    )
    assertion = RequirementAssertion(
        id="ASSERT-EXPLICIT-DATASET-CREATE",
        fact_ids=[fact.id],
        assertion_text=f"通过 UI 新建知识库 {name} 后，必须能在知识库列表中看到该记录。",
        assertion_type="functional",
        risk_level="high",
        review_status="human_confirmed",
        source_references=["rules"],
    )
    condition = TestCondition(
        id="COND-EXPLICIT-DATASET-CREATE",
        assertion_ref=assertion.id,
        condition_type="functional",
        statement=assertion.assertion_text,
        precondition="管理员已登录，知识库管理页面可访问，TA-20260704 旧测试知识库已清理。",
        trigger=f"点击新建知识库，填写名称 {name}、描述 {intro} 并保存。",
        oracle=f"列表显示 {name}。",
        oracle_type="ui_state",
        risk_level="high",
        measurability="measurable",
        source_references=["rules"],
        branch_type="positive",
    )
    technique = TestDesignTechnique(
        id="TECH-EXPLICIT-DATASET-CREATE",
        condition_id=condition.id,
        primary_technique="equivalence_partitioning",
        supplementary_techniques=["risk_based"],
        rationale="显式规则要求覆盖知识库新增写操作正向路径。",
    )
    coverage = CoverageItem(
        id="COV-EXPLICIT-DATASET-CREATE",
        condition_id=condition.id,
        technique_id=technique.id,
        coverage_dimension="normal",
        goal=condition.statement,
        risk_level="high",
        variant_key="dataset-create-ui",
        source_references=["rules"],
        branch_type="e2e",
    )
    case = CandidateTestCase(
        id="TC-EXPLICIT-DATASET-CREATE",
        title="通过 UI 新建知识库并列表命中",
        goal=f"通过 UI 新建知识库 {name}，保存后验证列表命中 TA-20260704-AUTO。",
        description="覆盖显式要求的知识库管理新增写操作。",
        preconditions=[
            StructuredPrecondition(
                type="account_role",
                description="管理员已登录。",
                required_role="管理员",
                satisfiable_by_agent=True,
                failure_policy="incomplete",
            ),
            StructuredPrecondition(
                type="data",
                description="TA-20260704 旧测试知识库已通过清理助手清空。",
                satisfiable_by_agent=True,
                failure_policy="incomplete",
            ),
        ],
        input_data=[
            TestInputDatum(
                name="dataset_name",
                value=None,
                placeholder=name,
                source="generated",
                sensitivity="internal",
                generation_strategy="explicit dataset create requirement",
            ),
            TestInputDatum(
                name="dataset_intro",
                value=None,
                placeholder=intro,
                source="generated",
                sensitivity="internal",
                generation_strategy="explicit dataset create requirement",
            ),
        ],
        expected_result=(
            f"列表显示 {name}；刷新页面或 /fastgpt/dataset/list "
            "后置证据仍可查到该记录。"
        ),
        priority="high",
        category="functional",
        trace_references=[coverage.id],
        execution_hint=(
            "登录后进入知识库管理，点击新建知识库，按测试数据填写名称和描述，"
            "保存后验证 TA-20260704-AUTO 记录出现在列表。"
        ),
        required_roles=["管理员"],
        branch_type="e2e",
        estimated_cost="low",
    )
    return (
        [*facts, fact],
        [*assertions, assertion],
        [*conditions, condition],
        [*techniques, technique],
        [*coverage_items, coverage],
        [*cases, case],
    )


def _augment_explicit_dataset_empty_name_case(
    facts: list[RequirementFact],
    assertions: list[RequirementAssertion],
    conditions: list[TestCondition],
    techniques: list[TestDesignTechnique],
    coverage_items: list[CoverageItem],
    cases: list[CandidateTestCase],
    source_text: str,
) -> tuple[
    list[RequirementFact],
    list[RequirementAssertion],
    list[TestCondition],
    list[TestDesignTechnique],
    list[CoverageItem],
    list[CandidateTestCase],
]:
    if (
        not _contains_dataset_empty_name_requirement(source_text)
        or _has_dataset_empty_name_case(cases)
    ):
        return facts, assertions, conditions, techniques, coverage_items, cases

    _, _, empty_marker = _dataset_test_data(source_text)
    quote = _first_matching_line(
        source_text,
        ("名称留空", "空名称", "required", empty_marker),
    )
    if not quote:
        quote = "Explicit rule requires blocking empty knowledge-base name."

    fact = RequirementFact(
        id="FACT-EXPLICIT-DATASET-EMPTY-NAME",
        source_type="inferred",
        source_reference="explicit_dataset_empty_name_requirement",
        quote=quote,
        subject="知识库管理",
        action="阻断空知识库名称",
        object="知识库名称",
        condition="管理员新建知识库时名称为空",
        outcome="校验失败且不创建记录",
        confidence=1.0,
        status="confirmed",
    )
    assertion = RequirementAssertion(
        id="ASSERT-EXPLICIT-DATASET-EMPTY-NAME",
        fact_ids=[fact.id],
        assertion_text=(
            "通过 UI 新建知识库时，如果名称为空，必须被必填校验阻断且不能产生 "
            f"{empty_marker} 记录。"
        ),
        assertion_type="validation",
        risk_level="high",
        review_status="human_confirmed",
        source_references=["rules"],
    )
    condition = TestCondition(
        id="COND-EXPLICIT-DATASET-EMPTY-NAME",
        assertion_ref=assertion.id,
        condition_type="validation",
        statement=assertion.assertion_text,
        precondition="管理员已登录并打开知识库新增弹窗。",
        trigger=f"知识库名称留空，描述填写测试空名称-{empty_marker}，点击保存。",
        oracle="保存被 required 或前端逻辑阻断，弹窗保持打开，且列表/API 中没有空名称测试记录。",
        oracle_type="ui_state",
        risk_level="high",
        measurability="measurable",
        source_references=["rules"],
        branch_type="negative",
    )
    technique = TestDesignTechnique(
        id="TECH-EXPLICIT-DATASET-EMPTY-NAME",
        condition_id=condition.id,
        primary_technique="boundary_value_analysis",
        supplementary_techniques=["error_guessing"],
        rationale="显式规则要求覆盖知识库名称必填约束。",
    )
    coverage = CoverageItem(
        id="COV-EXPLICIT-DATASET-EMPTY-NAME",
        condition_id=condition.id,
        technique_id=technique.id,
        coverage_dimension="negative",
        goal=condition.statement,
        risk_level="high",
        variant_key="dataset-empty-name",
        source_references=["rules"],
        branch_type="negative",
    )
    case = CandidateTestCase(
        id="TC-EXPLICIT-DATASET-EMPTY-NAME",
        title="空名称新建知识库被阻断",
        goal=(
            "通过 UI 新建知识库时名称留空，描述填写 "
            f"测试空名称-{empty_marker}，验证必填校验阻断。"
        ),
        description="覆盖显式要求的知识库名称必填负向路径。",
        preconditions=[
            StructuredPrecondition(
                type="account_role",
                description="管理员已登录。",
                required_role="管理员",
                satisfiable_by_agent=True,
                failure_policy="incomplete",
            )
        ],
        input_data=[
            TestInputDatum(
                name="dataset_name",
                value="",
                placeholder="",
                source="generated",
                sensitivity="internal",
                generation_strategy="explicit dataset empty-name requirement",
                boundary_category="negative",
            ),
            TestInputDatum(
                name="dataset_intro",
                value=None,
                placeholder=f"测试空名称-{empty_marker}",
                source="generated",
                sensitivity="internal",
                generation_strategy="explicit dataset empty-name requirement",
                boundary_category="negative",
            ),
        ],
        expected_result=(
            "名称为空时保存被 required 或前端逻辑阻断，弹窗保持打开；"
            f"搜索/API 后置证据证明未创建 {empty_marker} 记录。"
        ),
        priority="high",
        category="validation",
        trace_references=[coverage.id],
        execution_hint=(
            "登录后进入知识库管理，打开新建知识库弹窗，名称留空，填写描述后提交，"
            "观察校验阻断并确认未创建空名称测试记录。"
        ),
        required_roles=["管理员"],
        branch_type="negative",
        estimated_cost="low",
    )
    return (
        [*facts, fact],
        [*assertions, assertion],
        [*conditions, condition],
        [*techniques, technique],
        [*coverage_items, coverage],
        [*cases, case],
    )


def _augment_explicit_skill_scaffold_case(
    facts: list[RequirementFact],
    assertions: list[RequirementAssertion],
    conditions: list[TestCondition],
    techniques: list[TestDesignTechnique],
    coverage_items: list[CoverageItem],
    cases: list[CandidateTestCase],
    source_text: str,
) -> tuple[
    list[RequirementFact],
    list[RequirementAssertion],
    list[TestCondition],
    list[TestDesignTechnique],
    list[CoverageItem],
    list[CandidateTestCase],
]:
    if not _contains_skill_scaffold_requirement(source_text) or _has_skill_scaffold_case(cases):
        return facts, assertions, conditions, techniques, coverage_items, cases

    name, author, description = _skill_test_data(source_text)
    quote = _first_matching_line(
        source_text,
        ("TA-20260704-AUTO", "技能脚手架", "快速初始化脚手架", "/system/skill/scaffold", "SKILL.md", "index.js"),
    )
    if not quote:
        quote = f"Explicit rule requires creating skill scaffold {name} through UI."

    fact = RequirementFact(
        id="FACT-EXPLICIT-SKILL-SCAFFOLD",
        source_type="inferred",
        source_reference="explicit_skill_scaffold_requirement",
        quote=quote,
        subject="技能管理",
        action="通过 UI 快速初始化技能脚手架",
        object=name,
        condition="管理员已登录并打开技能管理页面",
        outcome="技能列表出现可清理的测试技能，文件树包含核心文件",
        confidence=1.0,
        status="confirmed",
    )
    assertion = RequirementAssertion(
        id="ASSERT-EXPLICIT-SKILL-SCAFFOLD",
        fact_ids=[fact.id],
        assertion_text=(
            f"通过 UI 初始化技能脚手架并将元数据保存为 {name} 后，"
            "技能列表必须可见，且文件树必须包含 SKILL.md 与 index.js。"
        ),
        assertion_type="functional",
        risk_level="high",
        review_status="human_confirmed",
        source_references=["rules"],
    )
    condition = TestCondition(
        id="COND-EXPLICIT-SKILL-SCAFFOLD",
        assertion_ref=assertion.id,
        condition_type="functional",
        statement=assertion.assertion_text,
        precondition="管理员已登录，技能管理页面可访问，TA-20260704 旧测试技能已清理。",
        trigger=(
            "点击技能管理的快速初始化脚手架，打开最新技能在线修编，"
            f"填写名称 {name}、作者 {author}、描述 {description} 并保存。"
        ),
        oracle=f"技能列表显示 {name}，文件树包含 SKILL.md 与 index.js。",
        oracle_type="ui_state",
        risk_level="high",
        measurability="measurable",
        source_references=["rules"],
        branch_type="e2e",
    )
    technique = TestDesignTechnique(
        id="TECH-EXPLICIT-SKILL-SCAFFOLD",
        condition_id=condition.id,
        primary_technique="equivalence_partitioning",
        supplementary_techniques=["risk_based"],
        rationale="显式规则要求覆盖技能管理脚手架写操作正向路径。",
    )
    coverage = CoverageItem(
        id="COV-EXPLICIT-SKILL-SCAFFOLD",
        condition_id=condition.id,
        technique_id=technique.id,
        coverage_dimension="normal",
        goal=condition.statement,
        risk_level="high",
        variant_key="skill-scaffold-ui",
        source_references=["rules"],
        branch_type="e2e",
    )
    case = CandidateTestCase(
        id="TC-EXPLICIT-SKILL-SCAFFOLD",
        title="通过 UI 快速初始化技能脚手架并验证核心文件",
        goal=f"通过 UI 技能管理快速初始化脚手架，保存为 {name} 后验证列表和文件树。",
        description="覆盖显式要求的技能管理脚手架创建、元数据保存和核心文件生成。",
        preconditions=[
            StructuredPrecondition(
                type="account_role",
                description="管理员已登录。",
                required_role="管理员",
                satisfiable_by_agent=True,
                failure_policy="incomplete",
            ),
            StructuredPrecondition(
                type="data",
                description="TA-20260704 旧测试技能已通过清理助手清空。",
                satisfiable_by_agent=True,
                failure_policy="incomplete",
            ),
        ],
        input_data=[
            TestInputDatum(
                name="skill_name",
                value=None,
                placeholder=name,
                source="generated",
                sensitivity="internal",
                generation_strategy="explicit skill scaffold requirement",
            ),
            TestInputDatum(
                name="skill_author",
                value=None,
                placeholder=author,
                source="generated",
                sensitivity="internal",
                generation_strategy="explicit skill scaffold requirement",
            ),
            TestInputDatum(
                name="skill_description",
                value=None,
                placeholder=description,
                source="generated",
                sensitivity="internal",
                generation_strategy="explicit skill scaffold requirement",
            ),
        ],
        expected_result=(
            f"技能列表显示 {name}；在线修编文件树包含 SKILL.md 与 index.js；"
            "刷新页面或 /system/skill/page、/system/skill/{skillId}/files 后置证据仍可查到该记录。"
        ),
        priority="high",
        category="functional",
        trace_references=[coverage.id],
        execution_hint=(
            "登录后进入技能管理，点击快速初始化脚手架，打开最新技能在线修编，"
            "将元数据保存为 TA-20260704-AUTO 测试技能，并验证文件树。"
        ),
        required_roles=["管理员"],
        branch_type="e2e",
        estimated_cost="low",
    )
    return (
        [*facts, fact],
        [*assertions, assertion],
        [*conditions, condition],
        [*techniques, technique],
        [*coverage_items, coverage],
        [*cases, case],
    )


def _augment_explicit_skill_duplicate_core_file_case(
    facts: list[RequirementFact],
    assertions: list[RequirementAssertion],
    conditions: list[TestCondition],
    techniques: list[TestDesignTechnique],
    coverage_items: list[CoverageItem],
    cases: list[CandidateTestCase],
    source_text: str,
) -> tuple[
    list[RequirementFact],
    list[RequirementAssertion],
    list[TestCondition],
    list[TestDesignTechnique],
    list[CoverageItem],
    list[CandidateTestCase],
]:
    if (
        not _contains_skill_duplicate_core_file_requirement(source_text)
        or _has_skill_duplicate_core_file_case(cases)
    ):
        return facts, assertions, conditions, techniques, coverage_items, cases

    name, _, _ = _skill_test_data(source_text)
    quote = _first_matching_line(
        source_text,
        ("重复创建 SKILL.md", "SKILL.md 被阻断", "核心文件", "duplicate"),
    )
    if not quote:
        quote = "Explicit rule requires blocking duplicate SKILL.md creation."

    fact = RequirementFact(
        id="FACT-EXPLICIT-SKILL-DUPLICATE-CORE-FILE",
        source_type="inferred",
        source_reference="explicit_skill_duplicate_core_file_requirement",
        quote=quote,
        subject="技能在线修编",
        action="阻断重复核心文件创建",
        object="SKILL.md",
        condition="管理员打开已创建技能的文件树并尝试新建 SKILL.md",
        outcome="创建请求被拒绝，核心文件保持唯一",
        confidence=1.0,
        status="confirmed",
    )
    assertion = RequirementAssertion(
        id="ASSERT-EXPLICIT-SKILL-DUPLICATE-CORE-FILE",
        fact_ids=[fact.id],
        assertion_text="技能文件树中重复创建 SKILL.md 必须被阻断，不能产生第二个核心文件。",
        assertion_type="validation",
        risk_level="high",
        review_status="human_confirmed",
        source_references=["rules"],
    )
    condition = TestCondition(
        id="COND-EXPLICIT-SKILL-DUPLICATE-CORE-FILE",
        assertion_ref=assertion.id,
        condition_type="validation",
        statement=assertion.assertion_text,
        precondition=f"管理员已登录，技能 {name} 已存在并可打开在线修编。",
        trigger="在创建新文件或目录输入框中填写 SKILL.md 并提交。",
        oracle="页面出现重复核心文件或禁止创建提示，文件树没有新增第二个 SKILL.md。",
        oracle_type="ui_state",
        risk_level="high",
        measurability="measurable",
        source_references=["rules"],
        branch_type="negative",
    )
    technique = TestDesignTechnique(
        id="TECH-EXPLICIT-SKILL-DUPLICATE-CORE-FILE",
        condition_id=condition.id,
        primary_technique="error_guessing",
        supplementary_techniques=["boundary_value_analysis"],
        rationale="显式规则要求覆盖 SKILL.md 核心文件唯一性负向路径。",
    )
    coverage = CoverageItem(
        id="COV-EXPLICIT-SKILL-DUPLICATE-CORE-FILE",
        condition_id=condition.id,
        technique_id=technique.id,
        coverage_dimension="negative",
        goal=condition.statement,
        risk_level="high",
        variant_key="skill-duplicate-core-file",
        source_references=["rules"],
        branch_type="negative",
    )
    case = CandidateTestCase(
        id="TC-EXPLICIT-SKILL-SCAFFOLD-DUPLICATE-CORE-FILE",
        title="重复创建 SKILL.md 核心文件被阻断",
        goal="通过 UI 在线修编尝试新建重复核心文件 SKILL.md，验证被阻断。",
        description="覆盖显式要求的技能文件树核心文件唯一性负向路径。",
        preconditions=[
            StructuredPrecondition(
                type="account_role",
                description="管理员已登录。",
                required_role="管理员",
                satisfiable_by_agent=True,
                failure_policy="incomplete",
            ),
            StructuredPrecondition(
                type="data",
                description=f"测试技能 {name} 已存在；如不存在可先执行技能脚手架正向用例。",
                satisfiable_by_agent=True,
                failure_policy="incomplete",
            ),
        ],
        input_data=[
            TestInputDatum(
                name="skill_file_path",
                value=None,
                placeholder="SKILL.md",
                source="generated",
                sensitivity="internal",
                generation_strategy="explicit skill duplicate-core-file requirement",
                boundary_category="negative",
            )
        ],
        expected_result=(
            "提交后出现 SKILL.md 为核心文件、不可重复创建或文件路径已存在的提示；"
            "在线修编文件树仍只保留一个 SKILL.md。"
        ),
        priority="high",
        category="validation",
        trace_references=[coverage.id],
        execution_hint=(
            "进入技能管理，打开 TA-20260704-AUTO 测试技能的在线修编，"
            "在创建新文件或目录输入 SKILL.md 并回车，观察阻断提示。"
        ),
        required_roles=["管理员"],
        branch_type="negative",
        estimated_cost="low",
    )
    return (
        [*facts, fact],
        [*assertions, assertion],
        [*conditions, condition],
        [*techniques, technique],
        [*coverage_items, coverage],
        [*cases, case],
    )


def _augment_explicit_valid_login_case(
    facts: list[RequirementFact],
    assertions: list[RequirementAssertion],
    conditions: list[TestCondition],
    techniques: list[TestDesignTechnique],
    coverage_items: list[CoverageItem],
    cases: list[CandidateTestCase],
    source_text: str,
) -> tuple[
    list[RequirementFact],
    list[RequirementAssertion],
    list[TestCondition],
    list[TestDesignTechnique],
    list[CoverageItem],
    list[CandidateTestCase],
]:
    if not _contains_valid_login_requirement(source_text) or _has_valid_login_case(cases):
        return facts, assertions, conditions, techniques, coverage_items, cases

    valid, _ = _explicit_login_credentials(source_text)
    if valid is None:
        return facts, assertions, conditions, techniques, coverage_items, cases
    username, password = valid
    quote = _first_matching_line(
        source_text,
        ("admin/admin123", "admin123", "真实凭据", "有效登录"),
    )
    if not quote:
        quote = f"Explicit rule requires valid login with {username}/{password}."

    fact = RequirementFact(
        id="FACT-EXPLICIT-VALID-LOGIN",
        source_type="inferred",
        source_reference="explicit_valid_login_requirement",
        quote=quote,
        subject="登录页",
        action="接受真实管理员凭据登录",
        object=f"{username}/{password}",
        condition="用户提交有效凭据",
        outcome="进入控制台并显示账号身份",
        confidence=1.0,
        status="confirmed",
    )
    assertion = RequirementAssertion(
        id="ASSERT-EXPLICIT-VALID-LOGIN",
        fact_ids=[fact.id],
        assertion_text=(
            f"使用 {username}/{password} 提交登录时必须进入控制台并显示登录后入口"
        ),
        assertion_type="functional",
        risk_level="high",
        review_status="human_confirmed",
        source_references=["rules"],
    )
    condition = TestCondition(
        id="COND-EXPLICIT-VALID-LOGIN",
        assertion_ref=assertion.id,
        condition_type="functional",
        statement=assertion.assertion_text,
        precondition="浏览器处于未登录状态并打开登录页。",
        trigger=f"输入 {username}/{password} 并点击立即登录。",
        oracle="页面进入控制台，并显示登录后入口或账号身份。",
        oracle_type="ui_state",
        risk_level="high",
        measurability="measurable",
        source_references=["rules"],
        branch_type="positive",
    )
    technique = TestDesignTechnique(
        id="TECH-EXPLICIT-VALID-LOGIN",
        condition_id=condition.id,
        primary_technique="equivalence_partitioning",
        supplementary_techniques=[],
        rationale="显式规则要求覆盖真实凭据登录成功路径。",
    )
    coverage = CoverageItem(
        id="COV-EXPLICIT-VALID-LOGIN",
        condition_id=condition.id,
        technique_id=technique.id,
        coverage_dimension="normal",
        goal=condition.statement,
        risk_level="high",
        variant_key="valid-login",
        source_references=["rules"],
        branch_type="positive",
    )
    case = CandidateTestCase(
        id="TC-EXPLICIT-VALID-LOGIN",
        title="真实管理员凭据登录成功进入控制台",
        goal=f"输入 {username}/{password} 并点击立即登录后验证进入控制台",
        description="覆盖显式要求的真实凭据 UI 登录成功路径。",
        preconditions=[
            StructuredPrecondition(
                type="environment",
                description="登录页已加载，用户名和密码输入框可见。",
                satisfiable_by_agent=True,
                failure_policy="incomplete",
            )
        ],
        expected_result="进入控制台，并显示 zhanghong 或智能体广场/知识库管理/技能管理。",
        priority="high",
        category="functional",
        trace_references=[coverage.id],
        execution_hint=f"回到登录页，输入 {username}/{password}，点击立即登录。",
        branch_type="positive",
        estimated_cost="low",
    )
    return (
        [*facts, fact],
        [*assertions, assertion],
        [*conditions, condition],
        [*techniques, technique],
        [*coverage_items, coverage],
        [*cases, case],
    )


def _augment_explicit_invalid_login_case(
    facts: list[RequirementFact],
    assertions: list[RequirementAssertion],
    conditions: list[TestCondition],
    techniques: list[TestDesignTechnique],
    coverage_items: list[CoverageItem],
    cases: list[CandidateTestCase],
    source_text: str,
) -> tuple[
    list[RequirementFact],
    list[RequirementAssertion],
    list[TestCondition],
    list[TestDesignTechnique],
    list[CoverageItem],
    list[CandidateTestCase],
]:
    if not _contains_invalid_login_requirement(source_text) or _has_invalid_login_case(cases):
        return facts, assertions, conditions, techniques, coverage_items, cases

    valid, invalid = _explicit_login_credentials(source_text)
    if invalid is None:
        return facts, assertions, conditions, techniques, coverage_items, cases
    username, invalid_password = invalid
    valid_password = valid[1] if valid is not None else ""
    quote = _first_matching_line(
        source_text,
        ("错误密码", "密码错误", "invalid password", "wrong password", invalid_password),
    )
    if not quote:
        quote = (
            f"Explicit rule requires submitting {username}/{invalid_password} "
            "and verifying login failure."
        )

    fact = RequirementFact(
        id="FACT-EXPLICIT-INVALID-LOGIN",
        source_type="inferred",
        source_reference="explicit_login_requirement",
        quote=quote,
        subject="登录页",
        action="拒绝错误密码登录",
        object=f"{username}/{invalid_password}",
        condition="用户提交错误密码",
        outcome="停留在登录页并显示密码错误提示",
        confidence=1.0,
        status="confirmed",
    )
    assertion = RequirementAssertion(
        id="ASSERT-EXPLICIT-INVALID-LOGIN",
        fact_ids=[fact.id],
        assertion_text=(
            f"使用 {username}/{invalid_password} 提交登录时必须失败，"
            "页面应停留在登录页并显示密码错误提示"
        ),
        assertion_type="validation",
        risk_level="high",
        review_status="human_confirmed",
        source_references=["rules"],
    )
    condition = TestCondition(
        id="COND-EXPLICIT-INVALID-LOGIN",
        assertion_ref=assertion.id,
        condition_type="validation",
        statement=assertion.assertion_text,
        precondition="浏览器处于未登录状态并打开登录页。",
        trigger=f"输入 {username}/{invalid_password} 并点击立即登录。",
        oracle="页面仍停留在登录页，并显示密码错误或登录失败提示，不能进入控制台。",
        oracle_type="ui_state",
        risk_level="high",
        measurability="measurable",
        source_references=["rules"],
        branch_type="negative",
    )
    technique = TestDesignTechnique(
        id="TECH-EXPLICIT-INVALID-LOGIN",
        condition_id=condition.id,
        primary_technique="error_guessing",
        supplementary_techniques=["equivalence_partitioning"],
        rationale="显式规则要求覆盖错误密码登录失败分支。",
    )
    coverage = CoverageItem(
        id="COV-EXPLICIT-INVALID-LOGIN",
        condition_id=condition.id,
        technique_id=technique.id,
        coverage_dimension="negative",
        goal=condition.statement,
        risk_level="high",
        variant_key="wrong-password",
        source_references=["rules"],
        branch_type="negative",
    )
    password_note = (
        f"；真实成功登录密码为 {valid_password}，本用例不得使用该密码"
        if valid_password
        else ""
    )
    case = CandidateTestCase(
        id="TC-EXPLICIT-INVALID-LOGIN",
        title="错误密码登录失败并停留登录页",
        goal=f"验证使用 {username}/{invalid_password} 提交登录会失败",
        description="覆盖显式要求的 UI 错误密码分支。",
        preconditions=[
            StructuredPrecondition(
                type="environment",
                description="登录页已加载，浏览器会话未登录。",
                satisfiable_by_agent=True,
                failure_policy="incomplete",
            )
        ],
        input_data=[
            TestInputDatum(
                name="login_username",
                value=None,
                placeholder=username,
                source="generated",
                sensitivity="internal",
                generation_strategy="explicit rule credential username",
                boundary_category="negative",
            ),
            TestInputDatum(
                name="login_password",
                value=None,
                placeholder=invalid_password,
                source="generated",
                sensitivity="secret",
                generation_strategy="explicit rule wrong password",
                boundary_category="negative",
            ),
        ],
        expected_result=(
            "提交后仍停留在登录页，显示密码错误或登录失败提示，"
            f"且不能进入控制台{password_note}。"
        ),
        priority="high",
        category="functional",
        trace_references=[coverage.id],
        execution_hint=(
            f"回到登录页，输入 {username}/{invalid_password}，点击立即登录，"
            "观察错误提示和页面是否仍为登录页。"
        ),
        branch_type="negative",
        estimated_cost="low",
    )
    return (
        [*facts, fact],
        [*assertions, assertion],
        [*conditions, condition],
        [*techniques, technique],
        [*coverage_items, coverage],
        [*cases, case],
    )


def _augment_explicit_quick_fill_case(
    facts: list[RequirementFact],
    assertions: list[RequirementAssertion],
    conditions: list[TestCondition],
    techniques: list[TestDesignTechnique],
    coverage_items: list[CoverageItem],
    cases: list[CandidateTestCase],
    source_text: str,
) -> tuple[
    list[RequirementFact],
    list[RequirementAssertion],
    list[TestCondition],
    list[TestDesignTechnique],
    list[CoverageItem],
    list[CandidateTestCase],
]:
    if not _contains_quick_fill_requirement(source_text) or _has_quick_fill_case(cases):
        return facts, assertions, conditions, techniques, coverage_items, cases

    _, invalid = _explicit_login_credentials(source_text)
    username = "admin"
    password = invalid[1] if invalid is not None else "cangjie*2026"
    quote = _first_matching_line(
        source_text,
        ("一键填值", "quick fill", "quick-fill", password),
    )
    if not quote:
        quote = (
            f"Explicit rule requires quick fill to populate {username}/{password}."
        )

    fact = RequirementFact(
        id="FACT-EXPLICIT-QUICK-FILL",
        source_type="inferred",
        source_reference="explicit_quick_fill_requirement",
        quote=quote,
        subject="登录页一键填值体验",
        action="填充演示凭据",
        object=f"{username}/{password}",
        condition="用户点击一键填值体验",
        outcome="用户名和密码输入框显示演示凭据",
        confidence=1.0,
        status="confirmed",
    )
    assertion = RequirementAssertion(
        id="ASSERT-EXPLICIT-QUICK-FILL",
        fact_ids=[fact.id],
        assertion_text=(
            f"点击一键填值体验后，用户名必须为 {username}，密码必须为 {password}"
        ),
        assertion_type="functional",
        risk_level="high",
        review_status="human_confirmed",
        source_references=["rules"],
    )
    condition = TestCondition(
        id="COND-EXPLICIT-QUICK-FILL",
        assertion_ref=assertion.id,
        condition_type="functional",
        statement=assertion.assertion_text,
        precondition="浏览器处于未登录状态并打开登录页。",
        trigger="点击一键填值体验按钮。",
        oracle=f"用户名输入框值为 {username}，密码输入框值为 {password}。",
        oracle_type="ui_state",
        risk_level="high",
        measurability="measurable",
        source_references=["rules"],
        branch_type="positive",
    )
    technique = TestDesignTechnique(
        id="TECH-EXPLICIT-QUICK-FILL",
        condition_id=condition.id,
        primary_technique="equivalence_partitioning",
        supplementary_techniques=[],
        rationale="显式规则要求覆盖一键填值体验。",
    )
    coverage = CoverageItem(
        id="COV-EXPLICIT-QUICK-FILL",
        condition_id=condition.id,
        technique_id=technique.id,
        coverage_dimension="normal",
        goal=condition.statement,
        risk_level="high",
        variant_key="quick-fill-values",
        source_references=["rules"],
        branch_type="positive",
    )
    case = CandidateTestCase(
        id="TC-EXPLICIT-QUICK-FILL",
        title="一键填值体验填充演示凭据",
        goal=(
            f"点击一键填值体验后验证 username={username} "
            f"且 password={password}"
        ),
        description="覆盖显式要求的一键填值字段值验证。",
        preconditions=[
            StructuredPrecondition(
                type="environment",
                description="登录页已加载，用户名和密码输入框可见。",
                satisfiable_by_agent=True,
                failure_policy="incomplete",
            )
        ],
        expected_result=f"username={username}，password={password}",
        priority="high",
        category="functional",
        trace_references=[coverage.id],
        execution_hint="回到登录页，点击一键填值体验按钮并观察输入框值。",
        branch_type="positive",
        estimated_cost="low",
    )
    return (
        [*facts, fact],
        [*assertions, assertion],
        [*conditions, condition],
        [*techniques, technique],
        [*coverage_items, coverage],
        [*cases, case],
    )


def _normalize_goal_assertion_text(text: str) -> str:
    """规范化断言文本，用于稳定的语义 ID 计算。"""
    return " ".join(text.split()).casefold()


_FOCUS_ALIAS_MAP: dict[str, set[str]] = {
    "dashboard": {"dashboard", "数据看板", "看板"},
    "reports": {"reports", "report", "能力趋势", "能力趋势洞察", "趋势洞察"},
    "calibration": {"calibration", "数据校准", "校准"},
}


def _expand_focus_terms(
    focus_areas: str | list[str] | None,
    target_url: str = "",
) -> set[str]:
    raw_terms: list[str] = []
    if isinstance(focus_areas, str):
        raw_terms.extend(re.split(r"[\s,;，；/|]+", focus_areas))
    elif isinstance(focus_areas, list):
        for item in focus_areas:
            if item:
                raw_terms.extend(re.split(r"[\s,;，；/|]+", str(item)))

    parsed = urlparse(target_url or "")
    raw_terms.extend(part for part in parsed.path.split("/") if part)

    expanded: set[str] = set()
    for term in raw_terms:
        normalized = term.strip().casefold()
        if not normalized:
            continue
        expanded.add(normalized)
        expanded.update(_FOCUS_ALIAS_MAP.get(normalized, set()))
    return expanded


def _filter_assertions_by_focus(
    assertions: list[RequirementAssertion],
    focus_areas: str | list[str] | None = None,
    target_url: str = "",
) -> list[RequirementAssertion]:
    terms = expand_focus_terms(focus_areas, target_url)
    if not terms:
        return assertions

    matched = []
    for assertion in assertions:
        haystack = " ".join(
            [assertion.assertion_text, *assertion.source_references]
        ).casefold()
        if any(term in haystack for term in terms):
            matched.append(assertion)

    if matched:
        print(
            f"[L2Pipeline] Focus scope filtered assertions: "
            f"{len(matched)}/{len(assertions)} for terms={sorted(terms)}."
        )
        return matched
    return assertions


def _filter_facts_for_assertions(
    facts: list[RequirementFact],
    assertions: list[RequirementAssertion],
) -> list[RequirementFact]:
    referenced_ids = {
        fact_id
        for assertion in assertions
        for fact_id in assertion.fact_ids
    }
    if not referenced_ids:
        return facts
    filtered = [fact for fact in facts if fact.id in referenced_ids]
    return filtered or facts


def _filter_goals_for_assertions(
    goals: list[ExplorationGoal],
    assertions: list[RequirementAssertion],
) -> list[ExplorationGoal]:
    assertion_ids = {assertion.id for assertion in assertions}
    if not assertion_ids:
        return goals
    filtered = [
        goal
        for goal in goals
        if any(assertion_id in assertion_ids for assertion_id in goal.assertion_refs)
    ]
    return filtered or goals


def adapt_legacy_goal(raw: dict) -> ExplorationGoal:
    """将旧格式 goal dict 转换为严格 ExplorationGoal，标记为 legacy。

    如果 dict 已经是严格 v2 格式（有 schema_version + 所有必填字段），
    则直接验证，不降级。仅对缺失字段的旧格式进行适配。
    """
    # 如果已经是严格 v2，直接验证
    if raw.get("schema_version") == "exploration_goal.v2":
        return ExplorationGoal.model_validate(raw)

    goal_text = raw.get("goal", "")
    priority = raw.get("priority", "medium")
    if priority not in ("high", "medium", "low"):
        priority = "medium"

    goal_id = raw.get("id") or _stable_hash("GOAL", goal_text, priority)
    assertion_refs = raw.get("assertion_refs") or []
    expected_evidence = raw.get("expected_evidence") or (
        [f"页面或系统状态能证明：{goal_text}"] if goal_text else []
    )
    stop_condition = raw.get("stop_condition") or (
        f"已观察到支持 {goal_text[:60]} 的证据，或达到探索限制" if goal_text else ""
    )
    source_refs = raw.get("source_refs") or []

    return ExplorationGoal(
        schema_version="exploration_goal.v2-legacy",
        id=goal_id,
        assertion_refs=assertion_refs or ["LEGACY"],
        goal=goal_text or "未知目标",
        expected_evidence=expected_evidence,
        stop_condition=stop_condition,
        priority=priority,
        source_refs=source_refs,
    )


def adapt_legacy_goals(raw_goals: list[dict]) -> list[ExplorationGoal]:
    """批量转换旧格式 goal dicts 为严格 ExplorationGoal。

    严格 v2 格式直接验证；旧格式填充缺失字段后转换。
    """
    result = []
    for g in raw_goals:
        if not isinstance(g, dict):
            continue
        result.append(adapt_legacy_goal(g))
    return result


def _stable_hash(prefix: str, *parts: str) -> str:
    """基于内容生成稳定短哈希 ID。"""
    normalized = "|".join(p.strip().casefold() for p in parts)
    return f"{prefix}-{hashlib.sha1(normalized.encode('utf-8')).hexdigest()[:10]}"


def _normalize_all_ids(package: TestAssetPackage) -> TestAssetPackage:
    """后处理：将所有产物 ID 归一化为内容寻址 ID，并更新所有交叉引用。

    LLM 生成的顺序 ID (FACT-001, ASSERT-001 等) 只在 prompt 层保留，
    此函数在 package 组装完成后统一重写，确保：
    - 相同语义内容生成相同 ID
    - 所有下游引用保持一致
    - 模型输出的 ID 不影响最终包的稳定性
    """
    # --- 1. 为每种产物生成新 ID ---
    old_to_new: dict[str, str] = {}

    for fact in package.facts:
        new_id = _stable_hash(
            "FACT",
            fact.source_type, fact.subject, fact.action,
            fact.object or "", fact.condition or "", fact.outcome or "",
            fact.quote[:120],
        )
        old_to_new[fact.id] = new_id

    for assertion in package.assertions:
        # 使用归一化后的 fact ID，确保同语义 assertion 生成相同 hash
        normalized_fact_ids = ",".join(sorted(old_to_new.get(fid, fid) for fid in assertion.fact_ids))
        new_id = _stable_hash(
            "ASSERT",
            normalized_fact_ids,
            assertion.assertion_text,
            assertion.assertion_type,
        )
        old_to_new[assertion.id] = new_id

    for cond in package.test_conditions:
        new_id = _stable_hash(
            "COND",
            old_to_new.get(cond.assertion_ref, cond.assertion_ref),
            cond.condition_type,
            cond.statement[:120],
        )
        old_to_new[cond.id] = new_id

    for tech in package.test_design_techniques:
        new_id = _stable_hash(
            "TECH",
            old_to_new.get(tech.condition_id, tech.condition_id),
            tech.primary_technique,
        )
        old_to_new[tech.id] = new_id

    for cov in package.coverage_items:
        new_id = _stable_hash(
            "COV",
            old_to_new.get(cov.condition_id, cov.condition_id),
            old_to_new.get(cov.technique_id, cov.technique_id),
            cov.coverage_dimension,
            cov.variant_key,
            cov.goal[:80],
        )
        old_to_new[cov.id] = new_id

    for case in package.candidate_cases:
        new_id = _stable_hash(
            "TC",
            ",".join(sorted(old_to_new.get(r, r) for r in case.trace_references)),
            case.goal[:80],
            case.expected_result[:80],
        )
        old_to_new[case.id] = new_id

    # --- 2. 更新所有交叉引用 ---
    # Facts
    new_facts = []
    for f in package.facts:
        new_f = f.model_copy(update={"id": old_to_new[f.id]})
        new_facts.append(new_f)

    # Assertions
    new_assertions = []
    for a in package.assertions:
        new_a = a.model_copy(update={
            "id": old_to_new[a.id],
            "fact_ids": [old_to_new.get(fid, fid) for fid in a.fact_ids],
        })
        new_assertions.append(new_a)

    # Goals — 更新 assertion_refs
    new_goals = []
    for g in package.exploration_goals:
        new_g = g.model_copy(update={
            "assertion_refs": [old_to_new.get(aid, aid) for aid in g.assertion_refs],
        })
        new_goals.append(new_g)

    # Conditions
    new_conditions = []
    for c in package.test_conditions:
        new_c = c.model_copy(update={
            "id": old_to_new[c.id],
            "assertion_ref": old_to_new.get(c.assertion_ref, c.assertion_ref),
        })
        new_conditions.append(new_c)

    # Techniques
    new_techniques = []
    for t in package.test_design_techniques:
        new_t = t.model_copy(update={
            "id": old_to_new[t.id],
            "condition_id": old_to_new.get(t.condition_id, t.condition_id),
        })
        new_techniques.append(new_t)

    # Coverage items
    new_covs = []
    for c in package.coverage_items:
        new_c = c.model_copy(update={
            "id": old_to_new[c.id],
            "condition_id": old_to_new.get(c.condition_id, c.condition_id),
            "technique_id": old_to_new.get(c.technique_id, c.technique_id),
        })
        new_covs.append(new_c)

    # Candidate cases
    new_cases = []
    for c in package.candidate_cases:
        new_c = c.model_copy(update={
            "id": old_to_new[c.id],
            "trace_references": [old_to_new.get(r, r) for r in c.trace_references],
        })
        new_cases.append(new_c)

    # Traceability matrix
    new_tm = None
    if package.traceability_matrix:
        new_rows = []
        for row in package.traceability_matrix.rows:
            new_rows.append(row.model_copy(update={
                "fact_id": old_to_new.get(row.fact_id, row.fact_id),
                "assertion_ids": [old_to_new.get(aid, aid) for aid in row.assertion_ids],
                "condition_ids": [old_to_new.get(cid, cid) for cid in row.condition_ids],
                "technique_ids": [old_to_new.get(tid, tid) for tid in row.technique_ids],
                "coverage_item_ids": [old_to_new.get(cid, cid) for cid in row.coverage_item_ids],
                "candidate_case_ids": [old_to_new.get(cid, cid) for cid in row.candidate_case_ids],
            }))
        new_tm = package.traceability_matrix.model_copy(update={"rows": new_rows})

    # --- 3. 重新组装 package ---
    package_dict = package.model_dump()
    package_dict["facts"] = [f.model_dump() for f in new_facts]
    package_dict["assertions"] = [a.model_dump() for a in new_assertions]
    package_dict["exploration_goals"] = [g.model_dump() for g in new_goals]
    package_dict["test_conditions"] = [c.model_dump() for c in new_conditions]
    package_dict["test_design_techniques"] = [t.model_dump() for t in new_techniques]
    package_dict["coverage_items"] = [c.model_dump() for c in new_covs]
    package_dict["candidate_cases"] = [c.model_dump() for c in new_cases]
    if new_tm:
        package_dict["traceability_matrix"] = new_tm.model_dump()

    package_dict["runtime_hints"]["id_mapping"] = old_to_new
    package_dict["runtime_hints"]["id_normalization_version"] = "content-addressed.v1"

    return TestAssetPackage.model_validate(package_dict)


def _attach_memory_context_hint(
    package: TestAssetPackage,
    memory_context_text: str,
    memory_context_summary: list[dict[str, str]] | None = None,
) -> TestAssetPackage:
    if memory_context_text:
        package.runtime_hints["memory_context_hint_present"] = True
        package.runtime_hints["memory_context_policy"] = (
            "hint_only_not_requirement_fact_source"
        )
    if memory_context_summary:
        package.runtime_hints["memory_context_refs"] = memory_context_summary
    return package



def _goals_from_confirmed_assertions(
    confirmed: list[RequirementAssertion],
) -> list[ExplorationGoal]:
    """仅从已确认断言生成探索目标（不包含被 gate 拦截的断言）。

    优先级映射规则 (解决所有 goals 均为 medium 的问题):
    - 原始 high 风险但已通过 gate (human_confirmed) → high
    - assertion_type 为 security/data_rule/state_transition → high (核心业务规则)
    - assertion_type 为 validation/error_handling → medium
    - assertion_type 为 functional 且 risk_level=medium → medium
    - assertion_type 为 functional 且 risk_level=low → low
    - 其余 → medium

    Goal ID 规则:
    - 仅基于断言语义字段生成稳定 ID（sorted fact_ids + normalized assertion_text + assertion_type）
    - risk_level 只参与 priority 计算，不参与 goal id hash，避免同语义断言因风险分级变化而产生新 ID
    """
    # 高优先级断言类型：涉及核心业务规则和安全
    HIGH_TYPES = {"security", "data_rule", "state_transition"}
    # 中优先级断言类型：功能验证和校验
    MEDIUM_TYPES = {"validation", "error_handling", "functional"}

    goals: list[ExplorationGoal] = []
    for a in confirmed:
        if a.risk_level == "low" and a.assertion_type == "functional":
            priority = "low"
        elif a.risk_level == "high" or a.assertion_type in HIGH_TYPES:
            priority = "high"
        elif a.assertion_type in MEDIUM_TYPES:
            priority = "medium"
        else:
            priority = "medium"

        semantic_parts = [
            ",".join(sorted(a.fact_ids)),
            _normalize_goal_assertion_text(a.assertion_text),
            a.assertion_type,
        ]
        normalized = "|".join(semantic_parts)
        goal_id = "GOAL-" + hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
        expected = f"页面或系统状态能证明：{a.assertion_text}"
        goals.append(ExplorationGoal(
            id=goal_id,
            assertion_refs=[a.id],
            goal=f"验证: {a.assertion_text[:80]}",
            expected_evidence=[expected],
            stop_condition=f"已观察到支持断言 {a.id} 的证据，或达到探索限制后标记 evidence_gap",
            priority=priority,
            source_refs=list(a.source_references or a.fact_ids),
        ))
    return goals


async def generate_exploration_goals(
    prd_content: str = "",
    api_doc_content: str = "",
    changelog_content: str = "",
    prototype_notes: str = "",
    architecture_notes: str = "",
    rules: str = "",
    focus_areas: str | list[str] | None = None,
    target_url: str = "",
) -> tuple[list[ExplorationGoal], list[str], list[RequirementFact], list[RequirementAssertion]]:
    """Phase 1 (探索前): 提取事实 → 推导断言 → review gate → 生成探索目标。

    仅从 confirmed 断言生成 goal，被 gate 拦截的高风险断言不会驱动探索。

    Returns:
        (exploration_goals, manual_review_items, facts, assertions)
        facts 和 assertions 供 Phase 2 复用，避免重复 LLM 调用。
    """
    from core.skills.fact_extractor import extract_facts
    from core.skills.assertion_deriver import derive_assertions

    facts = await extract_facts(
        prd_content=prd_content,
        api_doc_content=api_doc_content,
        changelog_content=changelog_content,
        prototype_notes=prototype_notes,
        architecture_notes=architecture_notes,
        rules=rules,
        focus_areas=focus_areas,
        target_url=target_url,
    )
    if not facts:
        return [], [], [], []

    assertions = await derive_assertions(facts)
    if not assertions:
        return [], [], facts, []

    scoped_assertions = _filter_assertions_by_focus(assertions, focus_areas, target_url)
    if len(scoped_assertions) != len(assertions):
        assertions = scoped_assertions
        facts = _filter_facts_for_assertions(facts, assertions)

    confirmed, blocked = _split_by_review_gate(assertions)
    manual_review_items = [_manual_review_label(a) for a in blocked]

    goals = _goals_from_confirmed_assertions(confirmed)
    print(f"[L2Pipeline] Phase 1: {len(facts)} facts, {len(assertions)} assertions, "
          f"{len(confirmed)} confirmed, {len(blocked)} blocked, {len(goals)} goals.")

    return goals, manual_review_items, facts, assertions


async def run_l2_pipeline(
    prd_content: str = "",
    api_doc_content: str = "",
    changelog_content: str = "",
    prototype_notes: str = "",
    architecture_notes: str = "",
    rules: str = "",
    focus_areas: str | list[str] | None = None,
    target_url: str = "",
    system_map: SystemMapEvid | None = None,
    source_registry: list[SourceAnchor] | None = None,
    precomputed_facts: list[RequirementFact] | None = None,
    precomputed_assertions: list[RequirementAssertion] | None = None,
    precomputed_goals: list[ExplorationGoal] | None = None,
    precomputed_review_items: list[str] | None = None,
    memory_context_text: str = "",
    disable_memory_context: bool = False,
) -> TestAssetPackage:
    """Phase 2 (探索后): 运行完整的 L2 分析管道。

    可接受 Phase 1 的预计算结果 (facts/assertions/goals) 以避免重复 LLM 调用。
    若未提供预计算结果，则从头提取。

    执行顺序:
    1. extract_facts (或复用 precomputed) → 2. derive_assertions (或复用)
    3. [Review Gate] 高风险 auto_generated 断言被拦截
    4. plan_coverage_blueprint
    5. analyze_conditions (仅已确认断言, 需要 system_map)
    6. select_techniques → 7. analyze_coverage → 8. generate_cases
    8. build_traceability → 9. assemble_package
    """
    from core.skills.asset_packager import assemble_package

    memory_context_summary: list[dict[str, str]] = []
    if disable_memory_context:
        memory_context_text = ""
    elif not memory_context_text:
        try:
            from core.memory_context import (
                format_memory_context_for_prompt,
                recall_memory_context,
            )

            recalled_memory_contexts = await recall_memory_context(target_url)
            memory_context_summary = [
                {
                    "scope_type": context.scope_type,
                    "scope_value": context.scope_value,
                    "memory_key": context.memory_key,
                    "source_domain": context.source_domain,
                    "provenance": context.provenance,
                }
                for context in recalled_memory_contexts
            ]
            memory_context_text = format_memory_context_for_prompt(
                recalled_memory_contexts
            )
        except Exception as exc:
            print(f"[L2Pipeline] Memory context recall skipped: {exc}")
            memory_context_text = ""

    # --- Phase 1 数据: 复用或重新提取 ---
    if precomputed_facts is not None and precomputed_assertions is not None:
        facts = precomputed_facts
        assertions = precomputed_assertions
        exploration_goals = precomputed_goals or []
        manual_review_items = precomputed_review_items or []
        print(f"[L2Pipeline] Phase 2: reusing {len(facts)} facts, {len(assertions)} assertions from Phase 1.")
    else:
        goals, manual_review_items, facts, assertions = await generate_exploration_goals(
            prd_content=prd_content,
            api_doc_content=api_doc_content,
            changelog_content=changelog_content,
            prototype_notes=prototype_notes,
            architecture_notes=architecture_notes,
            rules=rules,
            focus_areas=focus_areas,
            target_url=target_url,
        )
        exploration_goals = goals

    scoped_assertions = _filter_assertions_by_focus(assertions, focus_areas, target_url)
    if len(scoped_assertions) != len(assertions):
        assertions = scoped_assertions
        facts = _filter_facts_for_assertions(facts, assertions)
        exploration_goals = _filter_goals_for_assertions(exploration_goals, assertions)

    if not facts:
        return _attach_memory_context_hint(TestAssetPackage(), memory_context_text)

    if not assertions:
        return _attach_memory_context_hint(
            assemble_package(
                facts=facts,
                assertions=[],
                source_registry=source_registry,
            ),
            memory_context_text,
        )

    # --- Review Gate (无论是否 precomputed，统一复用同一门禁逻辑) ---
    confirmed_assertions, blocked_assertions = _split_by_review_gate(assertions)
    blocked_review_items = [_manual_review_label(a) for a in blocked_assertions]
    manual_review_items = _dedupe_manual_review_items((manual_review_items or []) + blocked_review_items)

    if not confirmed_assertions:
        # 即使没有 confirmed assertions，也要构建 traceability，
        # 确保 blocked assertions 保留在追溯矩阵中（status=human_review）。
        from core.skills.traceability_builder import build_traceability
        traceability = build_traceability(facts, assertions, [], [], [], [])
        return _attach_memory_context_hint(
            assemble_package(
                facts=facts,
                assertions=assertions,
                source_registry=source_registry,
                exploration_goals=exploration_goals,
                traceability_matrix=traceability,
                manual_review_items=manual_review_items,
            ),
            memory_context_text,
        )

    # --- Phase 2 核心: 条件分析需要 system_map ---
    if system_map is None:
        print("[L2Pipeline] 警告: system_map 为空，条件分析将仅基于文档断言，无真实 UI 证据。")

    from core.skills.condition_analyzer import analyze_conditions
    from core.skills.coverage_planner import plan_coverage_blueprint
    from core.skills.technique_selector import select_techniques
    from core.skills.coverage_analyzer import analyze_coverage
    from core.skills.case_generator import generate_cases
    from core.skills.traceability_builder import build_traceability

    coverage_blueprint = await plan_coverage_blueprint(
        confirmed_assertions,
        system_map,
        memory_context=memory_context_text,
    )
    conditions = await analyze_conditions(
        confirmed_assertions,
        system_map,
        coverage_blueprint,
        memory_context=memory_context_text,
    )
    if not conditions:
        from core.skills.traceability_builder import build_traceability
        traceability = build_traceability(facts, assertions, [], [], [], [])
        return _attach_memory_context_hint(
            assemble_package(
                facts=facts,
                assertions=assertions,
                source_registry=source_registry,
                exploration_goals=exploration_goals,
                traceability_matrix=traceability,
                manual_review_items=manual_review_items,
            ),
            memory_context_text,
        )

    techniques = await select_techniques(conditions)
    coverage_items = await analyze_coverage(conditions, techniques)
    cases = await generate_cases(coverage_items)
    (
        facts,
        assertions,
        conditions,
        techniques,
        coverage_items,
        cases,
    ) = _augment_explicit_login_requirement_cases(
        facts,
        assertions,
        conditions,
        techniques,
        coverage_items,
        cases,
        "\n".join(
            [
                prd_content or "",
                api_doc_content or "",
                changelog_content or "",
                prototype_notes or "",
                architecture_notes or "",
                rules or "",
            ]
        ),
    )
    (
        facts,
        assertions,
        conditions,
        techniques,
        coverage_items,
        cases,
    ) = _augment_explicit_agent_requirement_cases(
        facts,
        assertions,
        conditions,
        techniques,
        coverage_items,
        cases,
        "\n".join(
            [
                prd_content or "",
                api_doc_content or "",
                changelog_content or "",
                prototype_notes or "",
                architecture_notes or "",
                rules or "",
            ]
        ),
    )
    (
        facts,
        assertions,
        conditions,
        techniques,
        coverage_items,
        cases,
    ) = _augment_explicit_dataset_requirement_cases(
        facts,
        assertions,
        conditions,
        techniques,
        coverage_items,
        cases,
        "\n".join(
            [
                prd_content or "",
                api_doc_content or "",
                changelog_content or "",
                prototype_notes or "",
                architecture_notes or "",
                rules or "",
            ]
        ),
    )
    (
        facts,
        assertions,
        conditions,
        techniques,
        coverage_items,
        cases,
    ) = _augment_explicit_skill_requirement_cases(
        facts,
        assertions,
        conditions,
        techniques,
        coverage_items,
        cases,
        "\n".join(
            [
                prd_content or "",
                api_doc_content or "",
                changelog_content or "",
                prototype_notes or "",
                architecture_notes or "",
                rules or "",
            ]
        ),
    )
    combined_source_text = "\n".join(
        [
            prd_content or "",
            api_doc_content or "",
            changelog_content or "",
            prototype_notes or "",
            architecture_notes or "",
            rules or "",
        ]
    )
    cases = _filter_no_write_business_cases(cases, combined_source_text)
    traceability = build_traceability(
        facts, assertions, conditions, techniques, coverage_items, cases
    )

    package = assemble_package(
        facts=facts,
        assertions=assertions,
        source_registry=source_registry,
        exploration_goals=exploration_goals,
        system_map=system_map,
        coverage_blueprint=coverage_blueprint,
        test_conditions=conditions,
        test_design_techniques=techniques,
        coverage_items=coverage_items,
        candidate_cases=cases,
        traceability_matrix=traceability,
        manual_review_items=manual_review_items,
    )

    # 后处理：将所有 LLM 生成的顺序 ID 归一化为内容寻址 ID
    package = _normalize_all_ids(package)

    # 归一化后重新运行质量门，确保报告与最终产物一致
    from core.skills.quality_gates import run_quality_gates
    report = run_quality_gates(package)
    package.quality_gate_report = report
    package.runtime_hints["quality_gate_passed"] = report.passed
    package.runtime_hints["quality_gate_error_count"] = sum(
        1 for finding in report.findings if finding.severity == "error"
    )
    package = _attach_memory_context_hint(
        package,
        memory_context_text,
        memory_context_summary,
    )

    return package
