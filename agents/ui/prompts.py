"""agents/ui/prompts.py — LLM prompt templates for UI testing agent.

All prompts in Chinese per CONTEXT.md design decision.
Templates for: execution system prompt, step prompt, assertion prompt, page info formatter.
"""

from __future__ import annotations

from typing import Any

from core.interfaces import TestCase


def get_execution_system_prompt(test_case: TestCase) -> str:
    """System prompt for the execution phase of a single test case."""
    return f"""你是一个专业的Web应用测试工程师AI。你正在执行一个测试用例。

## 当前测试用例
- ID: {test_case.id}
- 标题: {test_case.title}
- 描述: {test_case.description}
- 预期结果: {test_case.expected}

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