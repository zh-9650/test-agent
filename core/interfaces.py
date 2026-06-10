"""
core/interfaces.py — AI Native Testing Platform 接口定义

本文件定义所有 Pydantic model、LangGraph state schema 和 core 模块的函数签名。
其他模块（agents/、api/、frontend/）依赖此文件中的类型定义。

规则：
- 只有 Pydantic model 定义和函数签名（函数体为 pass 或 ...）
- core-dev 后续填充实现时不能改签名
- 所有 model 和函数的 docstring 是给队友看的，要写清楚

依赖：pydantic, langgraph, langchain_core, langchain_anthropic
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AnyMessage
from langchain_core.tools import tool
from langgraph.graph import MessagesState
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


from typing import Literal

# =============================================================================
# Pydantic Models — ExplorationGoal (供 planning_graph 消费)
# =============================================================================

class ExplorationGoal(BaseModel):
    """严格探索目标。

    核心 L1/L1.5 链路要求所有字段完整。旧数据只能在读取边界通过
    adapter 显式降级，不能在核心模型内部静默生成空字符串。
    """
    schema_version: str = Field(default="exploration_goal.v2", description="Schema 版本")
    id: str = Field(min_length=1, description="稳定 Goal ID，如 GOAL-abc12345")
    assertion_refs: list[str] = Field(min_length=1, description="来源断言 ID 列表")
    goal: str = Field(min_length=1, description="要探索的业务证据目标")
    expected_evidence: list[str] = Field(min_length=1, description="期望在真实系统中观察到的证据")
    stop_condition: str = Field(min_length=1, description="达到何种证据即可停止探索")
    priority: Literal["high", "medium", "low"] = Field(description="探索优先级")
    source_refs: list[str] = Field(default_factory=list, description="来源 fact/source 引用")


# =============================================================================
# Pydantic Models — L2 分析管道 (RequirementFact → TestAssetPackage)
# =============================================================================

class SourceAnchor(BaseModel):
    """可审计来源锚点，用于 groundedness 和 Source Registry。"""
    schema_version: str = Field(default="source_anchor.v1", description="Schema 版本")
    source_id: str = Field(description="来源 ID，如 SRC-001")
    source_type: Literal["prd", "swagger", "changelog", "prototype", "architecture", "rule", "inferred"] = Field(description="来源类型")
    content_hash: str = Field(description="来源内容 hash")
    path_or_url: str = Field(default="", description="来源路径或 URL")
    section: str | None = Field(default=None, description="章节、页码或段落")
    start_offset: int | None = Field(default=None, description="quote 在来源内容中的起始 offset")
    end_offset: int | None = Field(default=None, description="quote 在来源内容中的结束 offset")
    quote: str = Field(default="", description="原文引用")
    quote_hash: str = Field(default="", description="quote hash")
    is_derived: bool = Field(default=False, description="是否由 legacy source_reference 自动派生")


class RequirementFact(BaseModel):
    """原子化、可追溯的陈述，从 PRD/Swagger/规则集/原型/架构文档/变更日志提取。

    对应 ai-development-guide.md §3.1。
    """
    id: str = Field(description="稳定 ID，如 FACT-001")
    source_type: Literal["prd", "swagger", "changelog", "prototype", "architecture", "rule", "inferred"] = Field(description="来源类型")
    source_reference: str = Field(description="来源引用（文件名、章节、URL 等）")
    quote: str = Field(description="原文引用，必须能精准在原文定位；inferred 时写明推断理由")
    subject: str = Field(description="规范化主体")
    action: str = Field(description="规范化动作")
    object: str = Field(default="", description="规范化客体")
    condition: str | None = Field(default=None, description="条件/前置")
    outcome: str | None = Field(default=None, description="结果/后置")
    confidence: float = Field(description="置信度 0.0-1.0", ge=0.0, le=1.0)
    status: Literal["draft", "confirmed", "conflicted", "superseded"] = Field(default="draft", description="事实状态")
    conflict_references: list[str] = Field(default_factory=list, description="冲突事实 ID 列表")


class RequirementAssertion(BaseModel):
    """从需求事实推导的可验证陈述。

    对应 ai-development-guide.md §3.2。
    """
    id: str = Field(description="稳定 ID，如 ASSERT-001")
    fact_ids: list[str] = Field(min_length=1, description="关联的事实 ID 列表（至少 1 条）")
    assertion_text: str = Field(description="断言文本，描述系统必须验证的内容")
    assertion_type: Literal["functional", "validation", "security", "performance", "compatibility", "data_rule", "state_transition", "error_handling"] = Field(description="断言类型")
    risk_level: Literal["high", "medium", "low"] = Field(description="风险等级")
    review_status: Literal["auto_generated", "human_confirmed", "rejected"] = Field(default="auto_generated", description="审查状态")
    source_references: list[str] = Field(default_factory=list, description="来源引用")


class PageMap(BaseModel):
    """系统地图 — 页面维度"""
    name: str = Field(description="页面名称")
    url_pattern: str = Field(default="", description="URL 模式")
    title: str = Field(default="", description="页面标题")
    elements: list[str] = Field(default_factory=list, description="页面元素摘要")
    discovered_actions: list[str] = Field(default_factory=list, description="该页面发现的可执行动作")


class ActionMap(BaseModel):
    """系统地图 — 动作维度"""
    action_name: str = Field(description="动作名称")
    trigger: str = Field(default="", description="触发方式")
    target_page: str = Field(default="", description="目标页面")
    preconditions: list[str] = Field(default_factory=list, description="前置条件")


class FormMap(BaseModel):
    """系统地图 — 表单维度"""
    form_name: str = Field(description="表单名称")
    page: str = Field(default="", description="所在页面")
    fields: list[str] = Field(default_factory=list, description="字段列表")
    submit_action: str = Field(default="", description="提交动作名称")


class NavigationMap(BaseModel):
    """系统地图 — 导航维度"""
    source: str = Field(description="来源页面")
    target: str = Field(description="目标页面")
    via: str = Field(default="", description="导航方式（点击/跳转/菜单）")
    action: str = Field(default="", description="触发动作")


class SystemMapEvid(BaseModel):
    """Live 探索产生的系统证据模型。

    对应 ai-development-guide.md §3.4。
    注意：与 core/skills/system_mapper.py 的 SystemMap 不同，
    本模型是完整的 L1 合同版本，包含四个子结构。
    """
    pages: list[PageMap] = Field(default_factory=list)
    actions: list[ActionMap] = Field(default_factory=list)
    forms: list[FormMap] = Field(default_factory=list)
    navigations: list[NavigationMap] = Field(default_factory=list)


class TestCondition(BaseModel):
    """回答"需要验证什么"的条件。

    对应 ai-development-guide.md §3.5。
    """
    id: str = Field(description="稳定 ID，如 COND-001")
    assertion_ref: str = Field(description="关联断言 ID")
    condition_type: Literal["functional", "validation", "boundary", "permission", "state_transition", "error_handling", "data_rule", "risk_case"] = Field(description="条件类型")
    statement: str = Field(description="条件陈述")
    precondition: str = Field(default="", description="前置条件")
    trigger: str = Field(default="", description="触发条件")
    oracle: str = Field(default="", description="预期结果（oracle）")
    oracle_type: Literal["ui_state", "api_response", "database", "business_rule", "network", "document", "human_review"] = Field(description="oracle 类型")
    risk_level: Literal["high", "medium", "low"] = Field(default="medium", description="风险等级")
    measurability: Literal["measurable", "partially_measurable", "human_review"] = Field(default="measurable", description="可测量性")
    source_references: list[str] = Field(default_factory=list, description="来源引用")


class TestDesignTechnique(BaseModel):
    """覆盖条件所选的设计方法。

    对应 ai-development-guide.md §3.6。
    """
    id: str = Field(description="稳定 ID，如 TECH-COND-001")
    condition_id: str = Field(description="关联条件 ID")
    primary_technique: Literal["equivalence_partitioning", "boundary_value_analysis", "decision_table", "state_transition", "pairwise", "error_guessing", "exploratory", "risk_based"] = Field(description="主要设计技术")
    supplementary_techniques: list[str] = Field(default_factory=list, description="补充技术")
    rationale: str = Field(default="", description="选择理由")


class CoverageItem(BaseModel):
    """从条件和技术创建的覆盖义务。

    对应 ai-development-guide.md §3.7。
    """
    id: str = Field(description="稳定 ID，如 COV-001")
    condition_id: str = Field(description="关联条件 ID")
    technique_id: str = Field(description="关联技术 ID")
    coverage_dimension: Literal["normal", "boundary", "negative", "permission", "state", "exception", "recovery", "compatibility", "security"] = Field(description="覆盖维度")
    goal: str = Field(description="覆盖目标描述")
    risk_level: Literal["high", "medium", "low"] = Field(default="medium", description="风险等级")


class CandidateTestCase(BaseModel):
    """从覆盖项实例化的候选测试用例。

    对应 ai-development-guide.md §3.8 + 设计文档 §5.5。
    """
    schema_version: str = Field(
        default="candidate_test_case.v1",
        description="Schema 版本，支持 legacy adapter 校验",
    )
    id: str = Field(description="稳定 ID，如 TC-CAND-001")
    title: str = Field(description="用例标题")
    goal: str = Field(description="测试目标")
    description: str = Field(default="", description="用例描述")
    preconditions: list[str] = Field(default_factory=list, description="前置条件")
    input_data: dict[str, str] = Field(default_factory=dict, description="输入数据")
    expected_result: str = Field(default="", description="预期结果")
    priority: Literal["high", "medium", "low"] = Field(default="medium", description="优先级")
    category: str = Field(default="functional", description="类别")
    trace_references: list[str] = Field(min_length=1, description="可追溯引用（覆盖项 ID 列表，至少 1 条）")
    execution_hint: str = Field(default="", description="执行提示（轻量级、发现友好的建议）")
    required_roles: list[str] = Field(default_factory=list, description="所需账号角色列表")


class TraceabilityRow(BaseModel):
    """追溯矩阵的每一行。"""
    fact_id: str = Field(description="事实 ID")
    assertion_ids: list[str] = Field(default_factory=list, description="关联的断言 ID 列表（一个事实可能对应多个断言）")
    condition_ids: list[str] = Field(default_factory=list, description="条件 ID 列表")
    technique_ids: list[str] = Field(default_factory=list, description="技术 ID 列表")
    coverage_item_ids: list[str] = Field(default_factory=list, description="覆盖项 ID 列表")
    candidate_case_ids: list[str] = Field(default_factory=list, description="候选用例 ID 列表")
    status: Literal["covered", "partial", "gap", "conflict", "human_review"] = Field(default="gap", description="覆盖状态")
    notes: str = Field(default="", description="备注")


class TraceabilityMatrix(BaseModel):
    """从源事实到候选用例的可审查映射。

    对应 ai-development-guide.md §3.9。
    """
    rows: list[TraceabilityRow] = Field(default_factory=list)


class QualityGateFinding(BaseModel):
    """确定性质量门发现。"""
    code: str = Field(description="机器可读问题代码")
    severity: Literal["error", "warning"] = Field(default="error", description="严重程度")
    message: str = Field(description="可读说明")
    artifact_type: str = Field(default="", description="产物类型")
    artifact_id: str = Field(default="", description="产物 ID")


class QualityGateReport(BaseModel):
    """确定性质量门报告。"""
    schema_version: str = Field(default="quality_gate_report.v1", description="Schema 版本")
    passed: bool = Field(description="是否通过所有 error 级质量门")
    findings: list[QualityGateFinding] = Field(default_factory=list)


class TestAssetPackage(BaseModel):
    """L1/L1.5/L2 的最终交付对象。

    对应 ai-development-guide.md §3.10。
    """
    facts: list[RequirementFact] = Field(default_factory=list)
    assertions: list[RequirementAssertion] = Field(default_factory=list)
    source_registry: list[SourceAnchor] = Field(default_factory=list)
    exploration_goals: list[ExplorationGoal] = Field(default_factory=list)
    exploration_evidence: dict[str, Any] = Field(default_factory=dict)
    system_map: SystemMapEvid | None = Field(default=None)
    test_conditions: list[TestCondition] = Field(default_factory=list)
    test_design_techniques: list[TestDesignTechnique] = Field(default_factory=list)
    coverage_items: list[CoverageItem] = Field(default_factory=list)
    candidate_cases: list[CandidateTestCase] = Field(default_factory=list)
    traceability_matrix: TraceabilityMatrix | None = Field(default=None)
    quality_gate_report: QualityGateReport | None = Field(default=None)
    ambiguities: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    manual_review_items: list[str] = Field(default_factory=list)
    runtime_hints: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# M2: Runtime explore/execute 拆分 — 目标驱动执行模型
# =============================================================================


class GoalResult(BaseModel):
    """每个探索目标的可计算结果。

    探索阶段每个 StrictExplorationGoal 必须产出一个 GoalResult，
    用于判断是否可以进入设计/执行阶段。
    """
    schema_version: str = Field(default="goal_result.v1", description="Schema 版本")
    goal_id: str = Field(description="对应的 ExplorationGoal.id")
    status: Literal["found", "not_found", "blocked", "insufficient"] = Field(
        description="探索结果状态"
    )
    evidence_refs: list[str] = Field(default_factory=list, description="支持证据引用")
    stop_reason: str = Field(default="", description="停止原因说明")
    observed_at: str = Field(default="", description="观察时间 ISO 格式")


class StructuredPrecondition(BaseModel):
    """结构化前置条件，替代自然语言 list[str]。

    账号角色必须显式声明，禁止通过 assertion 类型猜测。
    """
    type: Literal["account_role", "business_state", "environment", "data"] = Field(
        description="前置条件类型"
    )
    description: str = Field(description="前置条件描述")
    required_role: str | None = Field(default=None, description="所需角色（account_role 类型必填）")
    satisfiable_by_agent: bool = Field(default=True, description="是否可由 agent 自动满足")
    failure_policy: Literal["skipped", "incomplete", "failed", "human_review_required"] = Field(
        default="incomplete",
        description="无法满足时的失败策略"
    )


class RuntimeExecutableCase(BaseModel):
    """Runtime 无损适配的执行用例。

    只做协议适配，不生成固定步骤、不改写 goal/expected_result、
    不重新分配 ID、不生成第二套权威测试意图。
    """
    id: str = Field(description="等于 CandidateTestCase.id")
    objective: str = Field(description="等于 CandidateTestCase.goal")
    expected: str = Field(default="", description="等于 CandidateTestCase.expected_result")
    hints: str = Field(default="", description="等于 CandidateTestCase.execution_hint")
    preconditions: list[StructuredPrecondition] = Field(
        default_factory=list, description="结构化前置条件"
    )
    trace_references: list[str] = Field(default_factory=list, description="等于 CandidateTestCase.trace_references")
    priority: Literal["high", "medium", "low"] = Field(default="medium", description="等于 CandidateTestCase.priority")
    required_roles: list[str] = Field(default_factory=list, description="所需账号角色")


class TerminalAssertion(BaseModel):
    """终态判定三条件。

    只有三者均满足，case 才能 passed。
    """
    objective_satisfied: bool = Field(description="目标是否满足")
    expected_result_supported: bool = Field(description="预期结果是否被支持")
    terminal_evidence_sufficient: bool = Field(description="终态证据是否充分")
    reasoning: str = Field(default="", description="判定理由")


class ExplorationResult(BaseModel):
    """探索阶段的输出结果。

    包含系统地图证据和每个目标的探索结果。
    """
    system_map: SystemMapEvid = Field(default_factory=SystemMapEvid, description="系统地图证据")
    goal_results: list[GoalResult] = Field(default_factory=list, description="每个目标的探索结果")


class ExecutionRun(BaseModel):
    """权威运行模型。

    记录一次完整执行的所有用例结果和状态。
    """
    run_id: str = Field(description="运行 ID")
    task_id: str = Field(description="关联任务 ID")
    schema_version: str = Field(default="execution_run.v1", description="Schema 版本")
    status: Literal["running", "completed", "failed", "cancelled"] = Field(
        default="running", description="运行状态"
    )
    started_at: str = Field(default="", description="开始时间 ISO 格式")
    completed_at: str | None = Field(default=None, description="完成时间 ISO 格式")
    candidate_case_ids: list[str] = Field(default_factory=list, description="候选 case ID 列表")
    summary: dict[str, Any] = Field(default_factory=dict, description="运行摘要")


class CaseResult(BaseModel):
    """权威用例结果模型。

    一个 run_id + candidate_case_id 只能有一个 terminal CaseResult。
    retry 更新同一 CaseResult 的 attempt_count 和最终状态，不创建第二个逻辑结果。
    """
    run_id: str = Field(description="关联运行 ID")
    candidate_case_id: str = Field(description="等于 CandidateTestCase.id")
    terminal_status: Literal["passed", "failed", "skipped", "incomplete", "human_review_required"] = Field(
        description="终态结果"
    )
    attempt_count: int = Field(default=1, description="尝试次数")
    started_at: str = Field(default="", description="开始时间 ISO 格式")
    completed_at: str = Field(default="", description="完成时间 ISO 格式")
    summary: str = Field(default="", description="执行摘要")
    evidence_refs: list[str] = Field(default_factory=list, description="证据引用")
    failure_reason: str | None = Field(default=None, description="失败原因")


# =============================================================================
# Pydantic Models — 所有模块共享的数据类型
# =============================================================================


class TestCase(BaseModel):
    """测试用例。规划阶段的输出单位，执行阶段的输入单位。

    由规划子图通过 create_test_plan tool 生成。
    steps 是自然语言步骤，给执行阶段 LLM 看的任务说明书。
    """

    id: str = Field(description="用例ID，如 TC-001")
    title: str = Field(description="用例标题")
    description: str = Field(default="", description="用例详细描述")
    preconditions: list[str] = Field(
        default_factory=list,
        description="前置条件引用列表，如 ['login_as_admin']，对应 setups 的 key",
    )
    steps: list[str] = Field(description="自然语言步骤列表")
    expected: str = Field(description="预期结果描述")
    priority: str = Field(default="medium", description="优先级: high / medium / low")
    category: str = Field(default="functional", description="类别: functional / security / boundary")


class Setup(BaseModel):
    """前置条件/Setup。规划阶段识别的共享前置操作。

    执行阶段用 observe→decide→execute 循环执行 setup，
    就像执行一个迷你测试用例。不写死任何 login 函数。
    """

    id: str = Field(description="Setup ID，如 login_as_admin")
    description: str = Field(description="Setup 描述，给 LLM 看的任务说明")


class ActionResult(BaseModel):
    """Phase 2.0A Sprint 2: 标准化动作执行结果。

    所有工具函数统一返回此模型，包含执行前后的状态对比。
    Phase 2.0D (P0): 扩展为结构化结果, 支撑 LLM 语义判断。
    """

    action: str = Field(description="动作名称: click / input_text / navigate / scroll / ...")
    target: str | int | None = Field(default=None, description="动作目标 (元素索引或描述)")
    success: bool = Field(description="动作是否成功执行")
    error: str | None = Field(default=None, description="错误信息，成功时为 None")
    before_url: str = Field(default="", description="动作执行前的 URL")
    after_url: str = Field(default="", description="动作执行后的 URL")
    page_changed: bool = Field(default=False, description="DOM 指纹发生了变化")
    url_changed: bool = Field(default=False, description="URL 发生了变化")
    filled_value: str = Field(default="", description="B1.3: input_text 实际填入的值, 密码脱敏为前2位+****")

    # ---- Phase 2.0D: 结构化结果扩展 (对标 browser-use ActionResult) ----
    status: Literal["success", "failure", "timeout", "not_found", "inconclusive", "completion_rejected"] = Field(
        default="success",
        description="细粒度状态, 比 success bool 更有信息量。completion_rejected = mark_task_complete 的证据不足被工具自身拒绝, LLM 需补完后重试。"
    )
    extracted_content: str | None = Field(
        default=None,
        description="工具执行后提取的关键内容 (如填入值、点击后元素文本、错误提示), 给 LLM 阅读"
    )
    long_term_memory: str | None = Field(
        default=None,
        description="给 LLM 的下一步建议 (如'页面可能需要刷新'、'尝试其他定位策略')"
    )
    candidates: list[dict[str, Any]] = Field(
        default_factory=list,
        description="失败时的备选元素列表 (每个含 index/text/role/xpath), LLM 可重选"
    )
    include_in_memory: bool = Field(
        default=True,
        description="是否进入 LLM 上下文 (临时性工具如 screenshot 可设为 False)"
    )
    duration_ms: int = Field(default=0, description="工具自身执行耗时 (ms)")
    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="结构化证据 (screenshot 路径、network 状态、stack 摘要等)"
    )

    def is_terminal(self) -> bool:
        """判断是否为终态 (mark_task_* 工具)."""
        return self.action.startswith("mark_task_")


class StepResult(BaseModel):
    """单步执行结果。每一步（observe→decide→execute→assert）产生一个 StepResult。"""

    step_index: int = Field(description="步骤序号，从 0 开始")
    action_type: str = Field(default="", description="操作类型: click / input_text / navigate / scroll / wait")
    action_target: str = Field(default="", description="操作目标描述")
    action_args: dict[str, Any] = Field(default_factory=dict, description="操作参数")
    result: str = Field(default="", description="操作执行结果描述")
    screenshot_path: str = Field(default="", description="截图相对路径")
    change_report: Optional[ChangeReport] = Field(default=None, description="变化报告")
    assertion: Optional[AssertionResult] = Field(default=None, description="断言结果")
    thought: str = Field(default="", description="AI 思考过程（AIMessage.content）")
    reasoning_chain: list[str] = Field(default_factory=list, description="V2.0 C5: 跨步 AI 思考链 (decide + assert reasoning), 用于 ReportBuilder L2 卡片折叠展示")
    token_count: int = Field(default=0, description="V2.0 D1: 本步 decide_node 调用消耗的 token 数 (tiktoken 估算)")
    duration_ms: int = Field(default=0, description="V2.0 D2: 本步总耗时 (ms), observe→decide→execute→assert 累计")


class AssertionResult(BaseModel):
    """断言结果。LLM 语义判断的输出。"""

    status: str = Field(description="pass / fail / inconclusive")
    reasoning: str = Field(default="", description="判断理由 (LLM 必填, 但 B3.1 fast_assert / record 兜底时允许空)")
    # BUG-02 fix (2026-06-04 audit): default="" 防止 LLM 漏传 reasoning 触发 Pydantic ValidationError
    # 之前: reasoning 必填 → 漏传 → ValidationError → 走兜底分支 → 第二次 LLM 调用 (浪费)


ToolName = Literal[
    "navigate",
    "click",
    "input_text",
    "search",
    "scroll",
    "wait",
    "press_key",
    "hover",
    "request_human_intervention",
    "go_back",
    "extract_text",
    "select_dropdown",
    "evaluate_js",
    "mark_task_complete",
    "mark_task_failed",
    "mark_task_skipped",
    "screenshot_on_demand",
    "parallel_tool_calls",
    "find",
    "get_dropdown_options",
    "get_specific_elements",
    "switch_tab",
    "close_tab",
    "refresh",
    "get_page_links",
]


class AgentDecision(BaseModel):
    """LLM 决策结果。单步 decide 节点的结构化输出。

    action 字段使用 Literal 枚举约束, 防止 LLM 拼错工具名 (Click/clicker 等),
    一旦写错会在 pydantic 校验阶段就被 safe_structured_invoke 的 fallback 兜住。
    """

    evaluation: str = Field(description="对上一步操作和目标的评价/复盘 (Evaluation)")
    memory: str = Field(description="长期或短期记忆，记录当前任务进度和需要记住的状态 (Memory)")
    next_goal: str = Field(description="下一步的目标是什么 (Next Goal)")
    action: ToolName = Field(description="要调用的工具名称, 必须是 ToolName 中列出的工具之一")
    action_input: dict[str, Any] = Field(default_factory=dict, description="传给工具的参数，以键值对表示")


class ChangeReport(BaseModel):
    """变化报告。Change Detector 的输出——只报告事实，不做对错判断。

    由 change_detector.detect_changes(state_before, state_after) 生成。
    """

    url_changed: bool = Field(default=False)
    url_before: str = Field(default="")
    url_after: str = Field(default="")
    new_elements: list[str] = Field(default_factory=list, description="新出现的元素描述")
    gone_elements: list[str] = Field(default_factory=list, description="消失的元素描述")
    js_errors: list[str] = Field(default_factory=list, description="浏览器控制台错误")
    network_errors: list[str] = Field(default_factory=list, description="失败的网络请求")
    error_messages_visible: list[str] = Field(default_factory=list, description="页面上可见的错误/提示信息")
    modal_appeared: bool = Field(default=False)
    page_loading: bool = Field(default=False)


class TestResult(BaseModel):
    """单个测试用例的执行结果。包含该用例所有步骤的 StepResult。"""

    test_case_id: str = Field(description="对应的 TestCase.id")
    status: str = Field(
        description="passed / failed / skipped / incomplete / human_review_required"
    )
    steps: list[StepResult] = Field(default_factory=list)
    summary: str = Field(default="", description="执行摘要")
    duration_seconds: float = Field(default=0.0)
    setup_results: list[StepResult] = Field(default_factory=list, description="前置条件执行步骤")
    retry_count: int = Field(
        default=0,
        description="2026-06-04 retry policy: 0=首次成功, 1-2=重试次数, 3=用尽 (human_review_required)"
    )
    failure_context: list[dict[str, Any]] = Field(
        default_factory=list,
        description="2026-06-04 retry policy: 每次失败尝试的 context (screenshot/a11y/assertion), "
        "保留用于后续人工 review 或 AI 修复"
    )


# =============================================================================
# LangGraph State — 执行图的状态 schema
# =============================================================================


class TestState(MessagesState):
    """LangGraph 执行图的完整状态。

    设计原则（来自 CONTEXT.md）：
    - test_plan、results、setups 是结构化数据，不进 LLM 上下文窗口
    - messages 只包含当前用例的对话，用例结束后清空
    - page_info 和 screenshot 每步刷新
    - state_before/state_after 用于 Change Detector
    """

    # 规划阶段输出（结构化数据，不占上下文窗口）
    test_plan: list[TestCase]
    setups: dict[str, Setup]

    # 执行追踪
    current_index: int  # 当前执行到第几个用例
    current_step: int  # 当前用例内的步骤序号
    # 累积结果：使用 operator.add reducer，节点只返回新增的 [TestResult]，框架自动追加
    results: Annotated[list[TestResult], operator.add]
    consecutive_failures: int  # 连续失败计数

    # 页面信息（每步刷新）
    page_info: dict[str, Any]  # Page Semantic Layer 输出
    screenshot: str  # base64 编码的截图

    # 变化检测（execute 前快照 → execute 后快照）
    state_before: dict[str, Any]
    state_after: dict[str, Any]
    screenshot_after: str  # 执行操作后的 base64 截图

    # 步骤收集（record_node 每步追加，operator.add reducer 自动累加）
    _collected_steps: Annotated[list[StepResult], operator.add]

    # 每步临时数据（被下一步覆盖，不进 reducer）
    _last_tool_result: str  # execute_node 设置的工具执行结果文本
    _last_tool_calls: list[dict[str, Any]]  # V2.0-A (2026-06-02): execute_node 传给 assert_node 的工具调用列表 (供 Rule 0.5 mark_task_complete 使用)
    _last_change_report: Optional[ChangeReport]  # assert_node 设置的变化报告
    _last_assertion: Optional[AssertionResult]  # assert_node 设置的断言结果
    _last_evaluation: str  # LLM 对上一步操作和目标的评价/复盘
    _last_memory: str  # LLM 对任务进度和需要记住的状态的记忆
    _last_next_goal: str  # LLM 对下一步的目标

    # Phase 2.0A Sprint 2: 标准化动作执行结果 (execute_node 写入, assert_node 读取)
    _last_action_result: Optional[ActionResult]  # 上一步工具的结构化执行结果
    _last_action_result_text: str  # 上一步工具的可读文本 (用于 ToolMessage)

    # Phase 2.0A Sprint 5: Failure Memory 失败动作记忆
    recent_failures: list[dict[str, Any]] = Field(default_factory=list, description="滑动队列, 最大 3 条, 按 deque 淘汰")

    # B3.2: Locator 失败率统计
    _locator_stats: dict[str, int] = Field(default_factory=lambda: {"total": 0, "failed": 0}, description="locator 解析统计")

    # Phase 2.0A Sprint 6: Loop Detection 动作历史
    action_history: list[dict[str, Any]] = Field(default_factory=list, description="最近 6 步动作一级分类记录")
    need_replan: bool = Field(default=False, description="Loop Detection 触发后标记, decide_node 据此注入 [SYSTEM INTERRUPT]")

    # browser-use 对齐 (2026-06-05): agent_history 结构化历史
    # 仿 browser-use <agent_history><step_N>{Evaluation, Memory, Next Goal, Action Results}</step_N>
    # 每步由 decide_node 追加, 渲染时序列化为 XML 块
    agent_history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="结构化历史: [{step, evaluation, memory, next_goal, action, action_result, page_state_summary}, ...]"
    )

    # V2.0 D 可观测性 (2026-06-02)
    _last_token_count: int  # D1: 上一次 LLM 调用 (decide/assert) 的 token 数
    _last_node_name: str  # D2: 上一次执行的节点名 (runtime 据此发 node_event WebSocket)
    _last_node_duration_ms: int  # D2: 上一次节点耗时
    _early_warning_sent: bool  # D4: 当前 case 早警告是否已发 (限频 1/case)
    _step_token_log: Annotated[list[dict[str, Any]], operator.add]  # D3: 每步 token+duration, ReportBuilder 折线用

    # 任务元数据
    task_id: str
    task_config: dict[str, Any]  # 测试规则、账号信息、关注领域等


# =============================================================================
# Core Module Signatures — core-dev 后续填充实现
# =============================================================================


# --- LLM Client (core/llm_client.py) ---


def get_llm_client(model_type: str = "default") -> ChatAnthropic:
    """获取 LLM 客户端实例。

    通过环境变量配置：
    - ANTHROPIC_AUTH_TOKEN: API Key
    - ANTHROPIC_BASE_URL: API 地址
    - ANTHROPIC_MODEL: 主模型（qwen3.7-max）
    - ANTHROPIC_DEFAULT_HAIKU_MODEL: 轻量模型（deepseek-v4-flash）
    - ANTHROPIC_DEFAULT_SONNET_MODEL: 中等模型（kimi-k2.6）
    - ANTHROPIC_DEFAULT_OPUS_MODEL: 强力模型（glm-5.1）

    Args:
        model_type: "default" | "haiku" | "sonnet" | "opus"

    Returns:
        ChatAnthropic 实例，已配置 base_url 和 api_key
    """
    ...


def count_tokens(messages: list[AnyMessage], model: str = "") -> int:
    """估算消息列表的 token 数。用于成本监控和上下文管理。"""
    ...


# --- Page Semantic Layer (core/page_semantic.py) ---


async def extract_page_semantics(page: Any) -> dict[str, Any]:
    """从 Playwright page 提取页面语义摘要。

    使用 Playwright locator API（不用 querySelectorAll），框架无关。
    三层信息：
    - Layer 1: 交互元素（inputs, buttons, links, selects, checkboxes, tables）
    - Layer 2: 页面结构（URL, title, headings, breadcrumbs, nav, forms, modals）
    - Layer 3: 状态信息（loading, errors, validation, empty states, pagination）

    约束（来自 CONTEXT.md）：
    ① 每个可交互元素有编号（#1, #2, ...）供 LLM 精确引用
    ② 单页提取结果不超过 2000 tokens
    ③ 超过 50 个交互元素时截断

    Args:
        page: Playwright Page 对象

    Returns:
        dict 格式的页面语义摘要（PageSemanticInfo）
    """
    ...


async def take_screenshot(page: Any) -> str:
    """截取当前页面截图，返回 base64 编码字符串。

    Args:
        page: Playwright Page 对象

    Returns:
        base64 编码的截图字符串
    """
    ...


# --- Change Detector (core/change_detector.py) ---


def detect_changes(state_before: dict[str, Any], state_after: dict[str, Any]) -> ChangeReport:
    """对比操作前后的页面状态快照，生成变化报告。

    只报告事实（发生了什么），不做对错判断。
    检测项：URL 变化、元素增删、JS 报错、网络错误、弹窗、错误提示。

    Args:
        state_before: execute 前的页面状态快照
        state_after: execute 后的页面状态快照

    Returns:
        ChangeReport 实例
    """
    ...


# --- Execution Logger (core/execution_logger.py) ---


async def log_task_created(task_id: str, task_name: str, target_url: str, config: dict) -> None:
    """记录任务创建到数据库。"""
    ...


async def log_test_plan(task_id: str, test_plan: list[TestCase]) -> None:
    """记录生成的测试计划到数据库。"""
    ...


async def log_step(task_id: str, test_case_id: str, step: StepResult) -> None:
    """记录单个步骤到数据库（task_step 表）。"""
    ...


async def log_test_result(task_id: str, result: TestResult) -> None:
    """记录测试用例结果，更新 task 表的 passed_tests/failed_tests 计数。"""
    ...


async def get_task_steps(task_id: str, test_case_id: str = "") -> list[dict[str, Any]]:
    """查询任务步骤记录。不传 test_case_id 则返回所有步骤。"""
    ...


# --- Report Builder (core/report_builder.py) ---


class ReportBuilder:
    """报告生成器骨架。各 Agent 各自填充内容。"""

    def __init__(self, task_id: str) -> None:
        ...

    def add_result(self, result: TestResult) -> None:
        """添加一个测试用例的结果。"""
        ...

    def build_html(self, ai_summary: str = "") -> str:
        """生成 HTML 报告内容。

        Args:
            ai_summary: LLM 生成的测试总结文本，嵌入到报告头部。
        """
        ...

    def save(self, output_path: str, ai_summary: str = "") -> str:
        """保存报告到文件系统，返回相对路径。

        Args:
            output_path: 报告输出路径。
            ai_summary: LLM 生成的测试总结文本。
        """
        ...

    async def generate_summary(self, results: list[TestResult]) -> str:
        """用 LLM 生成测试总结（使用轻量模型 deepseek-v4-flash）。"""
        ...


# --- Planning Tool (agents/ui/planning_graph.py 中注册) ---
# 放在这里是为了类型定义的集中管理。
# graph-dev 在 planning_graph.py 中 import 此函数并注册到 bind_tools()。


@tool
def create_test_plan(
    test_cases: list[dict[str, Any]],
    setups: list[dict[str, Any]],
) -> str:
    """创建结构化测试计划。规划阶段 LLM 通过调用此 tool 输出测试计划。

    每个 test_case 必须包含:
    - id: str (如 "TC-001")
    - title: str
    - description: str
    - preconditions: list[str] (引用 setup 的 id)
    - steps: list[str] (自然语言步骤)
    - expected: str (预期结果)
    - priority: str ("high" / "medium" / "low")
    - category: str ("functional" / "security" / "boundary")

    每个 setup 必须包含:
    - id: str (如 "login_as_admin")
    - description: str

    Args:
        test_cases: 测试用例列表
        setups: 前置条件列表

    Returns:
        "已创建测试计划，共 N 个用例"
    """
    return f"已创建测试计划，共 {len(test_cases)} 个用例"
