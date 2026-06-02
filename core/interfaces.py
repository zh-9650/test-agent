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
# Pydantic Models — Layer 1 中间产物 (IR)
# =============================================================================

class KnowledgeItem(BaseModel):
    """带证据指针的原子知识"""
    text: str = Field(description="提取出的具体的知识点规则或描述")
    source: Literal["prd", "swagger", "changelog", "inferred"] = Field(description="知识来源")
    quote: str = Field(description="原文引用片段，必须能精准在原文定位；如果是 inferred，写明推断理由")
    confidence: float = Field(description="置信度，取值范围 0.0 - 1.0", ge=0.0, le=1.0)

class KnowledgeBase(BaseModel):
    """节点 1 输出：带可追溯指针的结构化事实库"""
    business_rules: list[KnowledgeItem] = Field(description="核心业务规则，如：金额>5000需总监审批")
    roles: list[KnowledgeItem] = Field(description="系统识别出的角色集合")
    entities: list[KnowledgeItem] = Field(description="核心业务实体，如：采购申请、订单")
    constraints: list[KnowledgeItem] = Field(description="阈值与硬性约束条件")
    raw_facts: list[KnowledgeItem] = Field(description="客观事实条目")

class UseCase(BaseModel):
    """新增脚手架：基于角色的单个用例"""
    name: str = Field(description="用例名称，如 '提交采购申请'")
    actor: str = Field(description="执行该用例的角色")
    trigger: str = Field(description="触发该用例的前置状态或条件")
    outcome: str = Field(description="执行后的业务结果或状态变化")
    related_rules: list[str] = Field(description="知识库中对应规则的精确原文引用或索引")

class UseCaseModel(BaseModel):
    """节点 1.5 输出：系统的全量用例集合"""
    use_cases: list[UseCase] = Field(description="系统所有识别到的业务用例")

class StateTransition(BaseModel):
    """状态机流转边"""
    from_state: str = Field(description="触发前的起始状态")
    action: str = Field(description="触发流转的动作")
    to_state: str = Field(description="流转后的目标状态")

class BusinessFlow(BaseModel):
    """轻量级状态机节点"""
    name: str = Field(description="流程名称，如：采购审批流")
    nodes: list[str] = Field(description="该流程涉及的所有状态枚举")
    transitions: list[StateTransition] = Field(description="状态之间的合法流转路径")

class SystemModel(BaseModel):
    """节点 2 输出：全系统骨架 (基于状态机)"""
    system_name: str = Field(default="Test System", description="系统名称")
    modules: list[str] = Field(default_factory=list, description="模块列表")
    entities: list[str] = Field(default_factory=list, description="实体列表")
    roles: list[str] = Field(default_factory=list, description="角色列表")
    flows: list[BusinessFlow] = Field(default_factory=list, description="轻量状态机业务流")

class ExplorationGoal(BaseModel):
    """节点 3 输出：探索目标"""
    goal: str = Field(description="业务级能力探索目标，如：'找到订单创建能力'")
    priority: str = Field(description="高/中/低优先级")


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
    reasoning: str = Field(description="判断理由")


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
    status: str = Field(description="passed / failed / skipped / incomplete")
    steps: list[StepResult] = Field(default_factory=list)
    summary: str = Field(default="", description="执行摘要")
    duration_seconds: float = Field(default=0.0)
    setup_results: list[StepResult] = Field(default_factory=list, description="前置条件执行步骤")


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
