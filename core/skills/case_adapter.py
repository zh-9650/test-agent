"""core/skills/case_adapter.py — CandidateTestCase → RuntimeExecutableCase 无损适配。

M2 设计原则:
- RuntimeExecutableCase 只做协议适配，不生成固定步骤
- 不改写 goal / expected_result
- 不重新分配 ID
- 不生成第二套权威测试意图
"""

from core.interfaces import (
    CandidateTestCase,
    RuntimeExecutableCase,
    StructuredPrecondition,
)


def adapt_single_case(case: CandidateTestCase) -> RuntimeExecutableCase:
    """将单个 CandidateTestCase 无损适配为 RuntimeExecutableCase。

    严格保持 ID、goal、expected_result、execution_hint 不变。
    preconditions 从自然语言 list[str] 转换为 StructuredPrecondition，
    但不会丢失原始信息。
    """
    structured_preconditions = _adapt_preconditions(case.preconditions)

    return RuntimeExecutableCase(
        id=case.id,
        objective=case.goal,
        expected=case.expected_result,
        hints=case.execution_hint,
        preconditions=structured_preconditions,
        trace_references=case.trace_references,
        priority=case.priority,
        required_roles=getattr(case, "required_roles", []),
    )


def adapt_executable_cases(
    candidate_cases: list[CandidateTestCase],
) -> list[RuntimeExecutableCase]:
    """批量无损适配 CandidateTestCase → RuntimeExecutableCase。

    不做任何过滤或排序，保持原始顺序。
    """
    return [adapt_single_case(case) for case in candidate_cases]


def _adapt_preconditions(preconditions: list[str]) -> list[StructuredPrecondition]:
    """将自然语言前置条件列表转换为结构化前置条件。

    解析规则:
    - 包含 "登录" / "login" / "账号" → account_role 类型
    - 包含 "数据" / "记录" / "已存在" → data 类型
    - 包含 "环境" / "网络" / "服务" → environment 类型
    - 其他 → business_state 类型

    无法确定类型时，默认 business_state + failure_policy=incomplete。
    """
    structured = []
    for raw in preconditions:
        if not raw or not raw.strip():
            continue

        raw_lower = raw.strip().lower()

        # account_role 类型检测
        if any(kw in raw_lower for kw in ("登录", "login", "账号", "角色", "权限", "role")):
            required_role = _extract_role(raw)
            structured.append(StructuredPrecondition(
                type="account_role",
                description=raw.strip(),
                required_role=required_role,
                satisfiable_by_agent=True,
                failure_policy="incomplete",
            ))
        # data 类型检测
        elif any(kw in raw_lower for kw in ("数据", "记录", "已存在", "已创建", "预置")):
            structured.append(StructuredPrecondition(
                type="data",
                description=raw.strip(),
                satisfiable_by_agent=False,
                failure_policy="skipped",
            ))
        # environment 类型检测
        elif any(kw in raw_lower for kw in ("环境", "网络", "服务", "数据库", "server")):
            structured.append(StructuredPrecondition(
                type="environment",
                description=raw.strip(),
                satisfiable_by_agent=False,
                failure_policy="skipped",
            ))
        # 默认: business_state
        else:
            structured.append(StructuredPrecondition(
                type="business_state",
                description=raw.strip(),
                satisfiable_by_agent=True,
                failure_policy="incomplete",
            ))

    return structured


def _extract_role(text: str) -> str | None:
    """尝试从文本中提取角色名称。"""
    text_lower = text.lower()
    # 常见角色关键词映射（顺序重要：先检查更具体的匹配）
    role_keywords = [
        ("超级管理员", "super_admin"),
        ("super_admin", "super_admin"),
        ("管理员", "admin"),
        ("admin", "admin"),
        ("普通用户", "user"),
        ("用户", "user"),
        ("user", "user"),
        ("访客", "guest"),
        ("guest", "guest"),
        ("审核员", "reviewer"),
        ("reviewer", "reviewer"),
    ]
    for keyword, role in role_keywords:
        if keyword in text_lower:
            return role
    return None
