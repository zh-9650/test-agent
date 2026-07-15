from __future__ import annotations

"""Shared runtime browser-tool contract used by prompts and schemas."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field


RUNTIME_ACTION_TOOLS: tuple[str, ...] = (
    "click",
    "navigate",
    "scroll",
    "input_text",
    "select_option",
    "wait",
    "mark_task_complete",
    "mark_task_failed",
)

RuntimePhase = Literal["exploration", "execution"]
RuntimePermissionLevel = Literal["L0", "L1", "L2", "L3"]
RuntimeToolStatus = Literal[
    "success",
    "blocked",
    "failed",
    "timeout",
    "not_found",
    "noop",
    "completion_rejected",
]

RUNTIME_TOOL_FAILURE_STATUSES: tuple[RuntimeToolStatus, ...] = (
    "blocked",
    "failed",
    "timeout",
    "not_found",
    "completion_rejected",
)


@dataclass(frozen=True)
class ToolErrorTaxon:
    category: str
    label: str
    description: str
    severity: Literal["info", "warning", "error"]
    remediation: str = ""


_UNKNOWN_TOOL_ERROR_TAXON = ToolErrorTaxon(
    category="unknown",
    label="未分类错误",
    description="尚未归入标准 taxonomy 的工具错误码。",
    severity="warning",
    remediation="查看对应步骤的工具参数、页面状态和运行时日志后再归类。",
)

TOOL_ERROR_TAXONOMY: dict[str, ToolErrorTaxon] = {
    "policy": ToolErrorTaxon(
        category="policy",
        label="策略拦截",
        description="动作被运行时安全策略或工具准入规则阻止。",
        severity="warning",
        remediation="检查动作是否跨域、是否使用泛化选择器，或是否需要先进入人工审查。",
    ),
    "selector": ToolErrorTaxon(
        category="selector",
        label="元素定位",
        description="页面元素定位失败、歧义或无法满足唯一性要求。",
        severity="error",
        remediation="优先改用语义编号、可访问名称或更具体的唯一选择器。",
    ),
    "tool": ToolErrorTaxon(
        category="tool",
        label="工具执行",
        description="浏览器工具调用本身失败、超时或未产生有效操作。",
        severity="error",
        remediation="查看页面是否仍在加载、控件是否可交互，并减少无效 wait/scroll。",
    ),
    "case": ToolErrorTaxon(
        category="case",
        label="用例执行",
        description="用例尝试级别的超时、异常或恢复失败。",
        severity="error",
        remediation="缩小用例目标、补充前置条件或通过人工审查恢复后重试。",
    ),
    "decision": ToolErrorTaxon(
        category="decision",
        label="动作决策",
        description="模型输出的下一步动作缺失、为空或不符合工具合同。",
        severity="warning",
        remediation="检查提示上下文是否缺少页面语义、失败反馈或可用工具说明。",
    ),
    "runtime": ToolErrorTaxon(
        category="runtime",
        label="运行时兜底",
        description="运行时记录的兜底错误，通常需要结合步骤上下文排查。",
        severity="error",
        remediation="查看异常堆栈、浏览器 trace 和 task checkpoint 确认失败边界。",
    ),
}

TOOL_ERROR_CODE_TAXONOMY: dict[str, ToolErrorTaxon] = {
    "policy.action_not_mapping": ToolErrorTaxon(
        category="policy",
        label="动作格式错误",
        description="模型返回的动作不是 JSON object。",
        severity="warning",
        remediation="要求模型只返回单个 BrowserAction JSON 对象。",
    ),
    "policy.missing_tool": ToolErrorTaxon(
        category="policy",
        label="缺少工具名",
        description="动作缺少 tool 字段。",
        severity="warning",
        remediation="补充 tool 字段，并限制在当前阶段允许的工具集合内。",
    ),
    "policy.unsupported_tool": ToolErrorTaxon(
        category="policy",
        label="不支持的工具",
        description="动作请求了生产合同之外的工具。",
        severity="warning",
        remediation="改用 click、navigate、scroll、input_text、select_option、wait 或终态工具。",
    ),
    "policy.args_not_mapping": ToolErrorTaxon(
        category="policy",
        label="参数格式错误",
        description="工具 args 不是 JSON object。",
        severity="warning",
        remediation="将工具参数改成对象结构，例如 {\"selector\":\"#1\"}。",
    ),
    "policy.missing_navigation_url": ToolErrorTaxon(
        category="policy",
        label="缺少导航地址",
        description="navigate 动作缺少 url。",
        severity="warning",
        remediation="提供站内相对地址或同源绝对地址。",
    ),
    "policy.forbidden_navigation_target": ToolErrorTaxon(
        category="policy",
        label="禁止的导航目标",
        description="导航目标属于浏览器内部、文件或源码协议。",
        severity="warning",
        remediation="只导航到被测系统同源页面。",
    ),
    "policy.cross_origin_navigation_blocked": ToolErrorTaxon(
        category="policy",
        label="跨域导航被阻止",
        description="navigate 目标与任务目标 URL 不同源。",
        severity="warning",
        remediation="改用同源路径；如确需跨系统操作，应先进入人工审查。",
    ),
    "policy.missing_selector": ToolErrorTaxon(
        category="policy",
        label="缺少选择器",
        description="需要定位元素的动作缺少 selector。",
        severity="warning",
        remediation="从页面语义中的交互元素选择一个具体编号或唯一选择器。",
    ),
    "policy.generic_container_selector_blocked": ToolErrorTaxon(
        category="policy",
        label="泛化选择器被阻止",
        description="动作试图操作 body、html 或 document 这类容器。",
        severity="warning",
        remediation="定位到具体按钮、链接、输入框或 select 控件。",
    ),
    "policy.browser_chrome_selector_blocked": ToolErrorTaxon(
        category="policy",
        label="浏览器 UI 选择器被阻止",
        description="动作疑似指向 devtools 或浏览器 chrome UI。",
        severity="warning",
        remediation="只操作被测页面 DOM 中的业务元素。",
    ),
    "policy.missing_input_text": ToolErrorTaxon(
        category="policy",
        label="缺少输入文本",
        description="input_text 动作缺少 text。",
        severity="warning",
        remediation="为输入动作提供非敏感的测试文本，真实 secret 不写入长期记录。",
    ),
    "selector.not_found": ToolErrorTaxon(
        category="selector",
        label="元素未找到",
        description="选择器没有匹配到可操作元素。",
        severity="error",
        remediation="重新观察页面，改用当前页面语义编号、文本或角色定位。",
    ),
    "selector.ambiguous": ToolErrorTaxon(
        category="selector",
        label="元素定位歧义",
        description="选择器匹配多个元素，无法唯一执行。",
        severity="error",
        remediation="增加可访问名称、父级范围或使用更具体的语义编号。",
    ),
    "tool.timeout": ToolErrorTaxon(
        category="tool",
        label="工具超时",
        description="浏览器动作在限制时间内未完成。",
        severity="error",
        remediation="确认页面加载状态，减少等待链路，必要时把该用例交给人工审查。",
    ),
    "tool.exception": ToolErrorTaxon(
        category="tool",
        label="工具异常",
        description="工具调用抛出未细分异常。",
        severity="error",
        remediation="结合 message、trace 和页面状态细分异常并补充专用错误码。",
    ),
    "tool.missing_select_option_value": ToolErrorTaxon(
        category="tool",
        label="select 选项缺失",
        description="select_option 没有提供 value、label 或 text。",
        severity="error",
        remediation="从页面 select 选项中选择明确的 value 或 label。",
    ),
    "tool.noop": ToolErrorTaxon(
        category="tool",
        label="工具无操作",
        description="工具请求没有产生有效动作。",
        severity="warning",
        remediation="检查工具名和参数是否与当前页面状态匹配。",
    ),
    "case.attempt_timeout": ToolErrorTaxon(
        category="case",
        label="用例尝试超时",
        description="单次 case attempt 超过配置时间。",
        severity="error",
        remediation="缩短目标路径、补充前置条件，或提高该 case 的人工接管优先级。",
    ),
    "case.execution_error": ToolErrorTaxon(
        category="case",
        label="用例执行异常",
        description="case attempt 发生运行时异常。",
        severity="error",
        remediation="查看步骤历史和异常信息，修复 runtime 或 case 输入后恢复运行。",
    ),
    "decision.invalid_or_empty_action": ToolErrorTaxon(
        category="decision",
        label="无效动作决策",
        description="模型没有返回可执行动作。",
        severity="warning",
        remediation="增加页面观察摘要、失败反馈或更明确的下一步约束。",
    ),
}

TOOL_PERMISSION_LEVELS: dict[str, RuntimePermissionLevel] = {
    "click": "L1",
    "navigate": "L1",
    "scroll": "L1",
    "input_text": "L1",
    "select_option": "L1",
    "wait": "L1",
    "mark_task_complete": "L1",
    "mark_task_failed": "L1",
}

EXPLORATION_ACTION_TOOLS: tuple[str, ...] = (
    "click",
    "navigate",
    "scroll",
    "select_option",
    "wait",
    "mark_task_complete",
    "mark_task_failed",
)

EXECUTION_ACTION_TOOLS: tuple[str, ...] = (
    "click",
    "navigate",
    "scroll",
    "input_text",
    "select_option",
    "wait",
    "mark_task_failed",
)

TOOL_ARGUMENT_EXAMPLES: dict[str, str] = {
    "click": '{"tool":"click","args":{"selector":"#1"}}',
    "navigate": '{"tool":"navigate","args":{"url":"/dashboard"}}',
    "scroll": '{"tool":"scroll","args":{"direction":"down"}}',
    "input_text": '{"tool":"input_text","args":{"selector":"#1","text":"文本"}}',
    "select_option": '{"tool":"select_option","args":{"selector":"#1","value":"all"}}',
    "wait": '{"tool":"wait","args":{"ms":1000}}',
    "mark_task_complete": '{"tool":"mark_task_complete","args":{"summary":"已找到证据"}}',
    "mark_task_failed": '{"tool":"mark_task_failed","args":{"reason":"无法继续"}}',
}


class RuntimeToolResult(BaseModel):
    """Structured result contract for production runtime tool calls."""

    tool: str
    phase: RuntimePhase
    permission_level: RuntimePermissionLevel = "L1"
    status: RuntimeToolStatus
    error_code: str = ""
    message: str = ""
    llm_feedback: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    normalized_args: dict[str, Any] = Field(default_factory=dict)
    before_url: str = ""
    after_url: str = ""
    url_changed: bool = False
    page_changed: bool = False
    changed_signals: dict[str, Any] = Field(default_factory=dict)
    selector_resolution: dict[str, Any] = Field(default_factory=dict)
    policy_decision: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int = 0
    evidence: dict[str, Any] = Field(default_factory=dict)
    hitl_required: bool = False
    hitl_reason: str = ""

    def feedback_text(self) -> str:
        return self.llm_feedback or self.message

    def normalized_action(self) -> dict[str, Any]:
        return {"tool": self.tool, "args": dict(self.normalized_args)}

    def is_success(self) -> bool:
        return self.status == "success"

    def is_failure(self) -> bool:
        return is_runtime_tool_failure_status(self.status)


def is_runtime_tool_failure_status(status: str) -> bool:
    return status in RUNTIME_TOOL_FAILURE_STATUSES


def tool_error_taxon_for_code(error_code: str) -> ToolErrorTaxon:
    code = str(error_code or "").strip()
    if not code:
        return _UNKNOWN_TOOL_ERROR_TAXON
    exact = TOOL_ERROR_CODE_TAXONOMY.get(code)
    if exact is not None:
        return exact
    prefix = code.split(".", 1)[0]
    return TOOL_ERROR_TAXONOMY.get(prefix, _UNKNOWN_TOOL_ERROR_TAXON)


def permission_level_for_tool(tool: str) -> RuntimePermissionLevel:
    return TOOL_PERMISSION_LEVELS.get(tool, "L3")


def normalize_args_for_storage(args: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(args, Mapping):
        return {}
    return dict(args)


def format_tool_list(tools: Iterable[str]) -> str:
    return "、".join(tools)


def format_tool_prompt_line(tools: Iterable[str]) -> str:
    return f"可用 tool：{format_tool_list(tools)}。"


def format_tool_example(tool: str = "click") -> str:
    return f"格式：{TOOL_ARGUMENT_EXAMPLES[tool]}"


def validate_tool_subset(tools: Iterable[str]) -> None:
    unknown = [tool for tool in tools if tool not in RUNTIME_ACTION_TOOLS]
    if unknown:
        raise ValueError(f"unknown runtime tools: {', '.join(unknown)}")
