"""agents/ui/prompts.py — LLM prompt templates for UI testing agent.

All prompts in Chinese per CONTEXT.md design decision.
Templates for: execution system prompt, step prompt, assertion prompt, page info formatter.
"""

from __future__ import annotations

from typing import Any

from core.interfaces import TestCase


def get_execution_system_prompt(test_case: TestCase, task_config: dict[str, Any] | None = None) -> str:
    """System prompt for the execution phase of a single test case."""
    accounts_info = ""
    memory_info = ""
    if task_config:
        if task_config.get("accounts"):
            accounts = task_config.get("accounts", [])
            accounts_info = "\n## 测试账号\n你可以使用以下提供的测试账号进行登录或测试：\n"
            for a in accounts:
                accounts_info += f"- 角色: {a.get('role', 'N/A')}, 账号: {a.get('username', 'N/A')}, 密码: {a.get('password', 'N/A')}\n"
        
        if task_config.get("memory_context"):
            memory_info = task_config.get("memory_context", "")

    return f"""你是一个专业的Web应用测试工程师AI。你正在执行一个测试用例。

## 当前测试用例
- ID: {test_case.id}
- 标题: {test_case.title}
- 描述: {test_case.description}
- 预期结果: {test_case.expected}
{accounts_info}
{memory_info}
## 你的工作方式
1. 观察当前页面状态（页面元素、结构、状态）
2. 根据测试步骤决定下一步操作
3. 使用提供的工具与页面交互
4. 每次只执行一个操作

## 操作规则
- 通过元素编号（如 #3）或描述引用页面元素
- 每次只调用一个工具
- 当你认为测试用例已经完成（所有步骤已执行且预期结果已验证），不要调用任何工具
- 如果遇到错误，尝试用其他方式完成操作

## 完成条件
当你确认以下任一条件满足时，停止调用工具（输出文字总结即可）：
1. 所有测试步骤已完成，预期结果已验证
2. 无法继续执行（页面无法访问等）
"""


def get_step_prompt(step_index: int, test_case: TestCase) -> str:
    """Prompt for the current step."""
    steps = test_case.steps
    if step_index < len(steps):
        return f"当前步骤 {step_index + 1}/{len(steps)}: {steps[step_index]}"
    return f"步骤 {step_index + 1}: 验证预期结果是否满足"


def get_assertion_prompt(
    tool_call: dict[str, Any] | None,
    change_report: Any,
    expected: str,
) -> str:
    """Prompt for LLM semantic assertion."""
    tool_info = ""
    if tool_call:
        tool_info = f"执行的操作: {tool_call['name']}({tool_call['args']})"

    changes: list[str] = []
    if change_report:
        if change_report.url_changed:
            changes.append(
                f"URL变化: {change_report.url_before} → {change_report.url_after}"
            )
        if change_report.new_elements:
            changes.append(
                f"新元素: {', '.join(change_report.new_elements[:5])}"
            )
        if change_report.gone_elements:
            changes.append(
                f"消失元素: {', '.join(change_report.gone_elements[:5])}"
            )
        if change_report.js_errors:
            changes.append(f"JS错误: {', '.join(change_report.js_errors[:3])}")
        if change_report.error_messages_visible:
            changes.append(
                f"可见错误: {', '.join(change_report.error_messages_visible)}"
            )
        if change_report.modal_appeared:
            changes.append("弹窗出现")

    change_text = "\n".join(changes) if changes else "无明显变化"

    return f"""请判断以下操作的结果是否符合预期。

{tool_info}

## 页面变化（事实）
{change_text}

## 预期结果
{expected}

## 请判断
请回答 PASS（通过）、FAIL（失败）或 INCONCLUSIVE（不确定），并说明理由。
格式: PASS/FAIL/INCONCLUSIVE: 理由
"""


def _format_page_info(page_info: dict[str, Any]) -> str:
    """Format page_info dict into a readable string for the LLM."""
    lines = [f"URL: {page_info.get('url', 'N/A')}"]
    lines.append(f"标题: {page_info.get('title', 'N/A')}")

    elements = page_info.get("interactive_elements", [])
    if elements:
        lines.append("\n交互元素:")
        for el in elements[:30]:  # limit to 30 for context
            desc = f"  {el['id']}: {el['type']}"
            if el.get("label"):
                desc += f" - {el['label']}"
            if el.get("text"):
                desc += f" - {el['text']}"
            if el.get("placeholder"):
                desc += f" (placeholder: {el['placeholder']})"
            lines.append(desc)

    errors = page_info.get("error_messages", [])
    if errors:
        lines.append(f"\n可见错误: {', '.join(errors)}")

    return "\n".join(lines)


# =============================================================================
# Planning Phase Prompts
# =============================================================================


def get_exploration_system_prompt(accounts: list | None = None, task_config: dict[str, Any] | None = None) -> str:
    """System prompt for the exploration phase — LLM explores the target system."""
    
    prd_context = ""
    if task_config:
        prd = task_config.get("prd")
        changelog = task_config.get("changelog")
        if prd:
            prd_context += f"\n## 产品需求文档 (PRD)\n{prd}\n(请带着上述业务目标，优先寻找核心流程的入口进行点击探索)\n"
        if changelog:
            prd_context += f"\n## 本次发版变更 (Changelog)\n{changelog}\n(请重点寻找并探索变更提及的功能区域)\n"
            
    prompt = f"""你是一个专业的Web应用测试探索者。你的任务是探索目标系统，了解其结构和功能。

## 探索策略
1. 从首页开始，系统地浏览主要页面
2. 结合 PRD 和 Changelog 的业务目标，给页面上的按钮打分，优先点击核心业务链路上最重要的元素（DFS策略）
3. 记录每个页面的功能和用途
4. 尝试发现不同的用户角色和权限区域
{prd_context}
## 严格禁止
- **禁止使用 navigate 工具通过 URL 直接跳转页面**
- 只能通过点击页面上的链接、按钮等交互元素来导航到其他页面
- 这样可以确保探索过程模拟真实用户的操作路径
"""
    if accounts:
        prompt += """
## 优先后台探索规则
如果系统当前显示登录页面，请**优先使用下方提供的测试凭据进行输入和登录**，以便进入后台深度探索和摸排后台系统内部的核心业务菜单与功能结构！
"""
    prompt += """
## 停止条件
请继续探索目标系统，尽最大努力去点击不同的按钮、导航菜单，探索至少 5 个不同的页面，发现系统的所有核心功能。
如果你认为已经完全遍历了所有的核心功能页面并收集了足够的信息来生成测试计划，或者你陷入了死胡同无法继续，再选择不调用任何工具以结束探索。"""
    return prompt


def get_plan_generation_prompt(target_url: str, explored_urls: list[str], task_config: dict[str, Any] | None = None) -> str:
    """Prompt for generating the test plan.
    
    Includes target URL, explored paths, and constraints/focus areas from config.
    """
    config_context = ""
    memory_info = ""
    accounts = []
    rules = ""
    
    if task_config:
        accounts = task_config.get("accounts", [])
        rules_list = task_config.get("rules", [])
        focus_list = task_config.get("focus_areas", [])
        
        if rules_list:
            config_context += "\n测试规则与约束:\n" + "\n".join(f"- {r}" for r in rules_list)
            rules = "\n".join(rules_list)
        if focus_list:
            config_context += "\n测试重点区域:\n" + "\n".join(f"- {f}" for f in focus_list)
            
        if task_config.get("memory_context"):
            memory_info = task_config.get("memory_context", "")
            
        if task_config.get("prd"):
            config_context += "\n## 产品需求文档 (PRD):\n" + task_config.get("prd", "")
        if task_config.get("swagger"):
            config_context += "\n## 接口文档 (Swagger):\n" + task_config.get("swagger", "") + "\n(请结合Swagger提取边界值、必填项和越权场景生成高价值测试用例)"
        if task_config.get("tech_doc"):
            config_context += "\n## 技术实现文档:\n" + task_config.get("tech_doc", "")
        if task_config.get("changelog"):
            config_context += "\n## 变更日志 (Changelog):\n" + task_config.get("changelog", "") + "\n(请确保测试计划覆盖了这些重点变更模块)"

    return f"""你需要为目标应用生成一份结构化的测试计划。

目标应用 URL: {target_url}

探索阶段收集到的页面路径 (最多20个):
{chr(10).join(explored_urls) if explored_urls else '无'}
{config_context}
{memory_info}

## 任务要求测试账号
{chr(10).join(f"- 角色: {a.get('role', 'N/A')}, 用户名: {a.get('username', 'N/A')}" for a in accounts) if accounts else "无"}

## 测试规则
{rules if rules else "无特殊规则"}

## 请生成测试计划
请调用 create_test_plan 工具，包含：
1. 每个测试用例的 ID、标题、描述、步骤、预期结果
2. 共享的前置条件（如登录）
3. 优先级和分类
4. 覆盖功能测试、安全测试、边界测试"""
    return prompt