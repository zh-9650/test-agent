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
4. 允许一次性下发多个操作组合（如先输入账号再输入密码最后点击登录），系统会按顺序依次执行

## ⚠️ 核心防呆与同步规则 (CRITICAL SYNC RULES)
1. **强制结果标记机制**：在你认为当前测试步骤或整个用例已完成时，**必须**调用 `mark_task_complete`。如果是彻底失败，调用 `mark_task_failed`。如果你不调用这三个标记工具之一，系统将认为你还在思考，导致死循环。
2. **表单校验拦截 (Form Validation)**：在点击任何“保存”、“提交”或“登录”按钮前，或在点击后页面没有跳转时：
   - **必须**检查页面上是否有红字错误信息（Validation Errors）。
   - 如果有错误信息，**绝不允许**强行标记任务成功或关闭弹窗，**必须**补全缺失的字段或修正错误后重试。
3. **DOM 异步渲染保护 (Dropdown & Modal Isolation)**：如果你的点击动作会触发一个下拉框展开，或弹出一个对话框（Modal），**必须在点击后立刻停止，等待系统传回最新的截图，在下一步再去操作新出现的元素**。绝对禁止在同一个组合操作里既点击下拉框又去选里面的值，否则会导致元素定位失败！

## 完成条件
当你确认所有测试步骤已完成，预期结果已验证，**必须调用 `mark_task_complete` 工具**。如果遇到致命错误无法进行，**必须调用 `mark_task_failed` 工具**。
"""



def get_step_prompt(step_index: int, test_case: TestCase) -> str:
    """Prompt for the current step."""
    steps = test_case.steps
    if step_index < len(steps):
        return f"当前步骤 {step_index + 1}/{len(steps)}: {steps[step_index]}"
    return f"步骤 {step_index + 1}: 验证预期结果是否满足"


def get_assertion_prompt(
    tool_calls: list[dict[str, Any]],
    change_report: Any,
    expected: str,
    current_step_text: str,
    page_info: dict[str, Any] | None = None,
) -> str:
    """Prompt for LLM semantic assertion."""
    tool_info = ""
    if tool_calls:
        calls_text = [f"{tc['name']}({tc.get('args', {})})" for tc in tool_calls]
        tool_info = f"执行的操作序列: {', '.join(calls_text)}"

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

    page_state_text = ""
    if page_info:
        page_state_text = "\n## 当前页面状态（最新全貌）\n" + _format_page_info(page_info)

    return f"""你是一个专业的 UI 自动化测试断言专家。你的任务是根据智能体刚刚执行的【具体操作】和页面的【前后变化】，判断该操作是否达成了测试用例的【最终预期结果】。

## 刚刚执行的实际操作
{tool_info}

## 当前计划的步骤描述（仅供参考，可能与实际操作有差异）
{current_step_text}

## 页面变化（与上一步的差异）
{change_text}
{page_state_text}

## 用例的最终预期结果
{expected}

## 判断策略（极其重要）
1. **区分中间步骤与决断步骤**：如果当前步骤只是一个过渡动作（如滚动页面、等待、输入文本但未提交），只要页面未报错崩溃，就不应该判定为 PASS 或 FAIL，而必须判定为 INCONCLUSIVE（不确定）。
2. **只有最终预期达成才能 PASS**：只有当页面的【当前状态】或【页面变化】已经明确显示满足了【用例的最终预期结果】时，才能输出 PASS。
3. **明确的失败**：如果操作后出现了错误提示、网络异常，或者执行了触发动作但预期元素未出现，则判定为 FAIL。

## 示例 (Few-Shot Examples)

示例 1（中间步骤，未达最终预期）：
操作: scroll({{"direction": "down"}})
当前步骤目标: 找到页面底部的提交按钮
预期结果: 订单提交成功并显示“感谢购买”
评估结果:
思考过程：当前操作是向下滚动页面，目的是寻找提交按钮。由于尚未进行实际的提交动作，也没有页面崩溃或异常，因此用例的最终预期尚未达成，但也没有失败。
{{
  "status": "INCONCLUSIVE",
  "reasoning": "滚动只是为了寻找按钮，未触发提交，最终预期尚未达成。"
}}

示例 2（决断步骤，达成最终预期）：
操作: click({{"target": "#submit-btn"}})
当前步骤目标: 点击提交按钮
预期结果: 订单提交成功并显示“感谢购买”
页面变化: 新元素出现: "感谢购买"
评估结果:
思考过程：当前操作点击了提交按钮。执行后，页面上出现了预期的“感谢购买”文本。这直接符合用例的最终预期结果，说明购买流程已成功完成。
{{
  "status": "PASS",
  "reasoning": "点击提交后，页面成功显示了预期的‘感谢购买’提示。"
}}

示例 3（决断步骤，发生明显失败）：
操作: click({{"target": "#login-btn"}})
当前步骤目标: 点击登录
预期结果: 成功进入后台主页
页面变化: 可见错误: "密码错误，请重试"
评估结果:
思考过程：当前操作是点击登录按钮。预期的结果是成功进入后台主页。但执行后页面上出现了明确的红色报错“密码错误，请重试”。这意味着操作失败，预期未达成。
{{
  "status": "FAIL",
  "reasoning": "点击登录后出现了‘密码错误’的红色提示，未能进入后台主页。"
}}
## 请判断
请在输出最终评估结果前，先简要分析页面的变化和最终预期结果之间的关系（思考过程）。
然后，你必须在输出的最后，以纯 JSON 格式输出你的评估结果，必须严格遵守以下 JSON 结构：
{{
  "status": "PASS", // 只能是 PASS, FAIL, 或 INCONCLUSIVE
  "reasoning": "简短的一句话理由，解释为什么给出这个状态"
}}
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


def get_exploration_system_prompt(accounts: list | None = None, task_config: dict[str, Any] | None = None, scenarios: list[dict] | None = None) -> str:
    """System prompt for the exploration phase — LLM explores the target system."""
    
    prd_context = ""
    if task_config:
        prd = task_config.get("prd")
        changelog = task_config.get("changelog")
        if prd:
            prd_context += f"\n## 产品需求文档/原型内容 (PRD)\n{prd}\n"
            prd_context += "(注意：上述内容可能是直接从文档链接爬取并提取的纯文本。请提取其中的核心业务目标、业务流转规则、边界值及前置条件，并带着这些目标寻找核心流程的入口进行点击探索)\n"
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
    if scenarios:
        prompt += "\n## 业务场景目标 (Goal-Driven Exploration)\n"
        prompt += "以下是从产品需求文档提取的核心业务场景，请带着这些目标进行探索：\n"
        for s in scenarios:
            prompt += f"- [{s.get('priority', 'medium')}] {s.get('name', '')}: {s.get('entry_hint', '')}\n"
        prompt += "\n请优先寻找并验证这些业务流程的入口，而不是随机点击。\n"
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


def get_plan_generation_prompt(target_url: str, explored_urls: list[str], task_config: dict[str, Any] | None = None, scenarios: list[dict] | None = None, risk_points: list[dict] | None = None) -> str:
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
            config_context += f"\n## 产品需求文档/原型提取内容 (PRD)\n{task_config['prd']}\n(注: 此内容可能由爬虫从文档链接提取。请结合探索结果，重点围绕其核心业务流、边界条件和前置状态生成覆盖测试用例。)\n"
        if task_config.get("api_doc"):
            config_context += f"\n## 接口文档提取内容\n{task_config['api_doc']}\n" + task_config.get("swagger", "") + "\n(请结合Swagger提取边界值、必填项和越权场景生成高价值测试用例)"
        if task_config.get("tech_doc"):
            config_context += "\n## 技术实现文档:\n" + task_config.get("tech_doc", "")
        if task_config.get("changelog"):
            config_context += "\n## 变更日志 (Changelog):\n" + task_config.get("changelog", "") + "\n(请确保测试计划覆盖了这些重点变更模块)"

    scenarios_context = ""
    if scenarios:
        scenarios_context = "\n## 已提取的核心业务场景 (请确保测试计划覆盖这些场景)\n"
        for s in scenarios:
            scenarios_context += f"- [{s.get('priority', 'medium')}] {s.get('id', '')}: {s.get('name', '')} (入口提示: {s.get('entry_hint', '')})\n"

    risk_points_context = ""
    if risk_points:
        risk_points_context = "\n## 探索中发现的高风险元素 (请针对这些元素生成专门的边界值/安全/异常测试用例)\n"
        for r in risk_points:
            risk_points_context += f"- 元素: {r.get('element', '')}\n"
            risk_points_context += f"  风险类型: {r.get('risk_type', '')}\n"
            if r.get('suggestions'):
                risk_points_context += f"  建议测试: {', '.join(r.get('suggestions', []))}\n"

    return f"""你需要为目标应用生成一份结构化的测试计划。

目标应用 URL: {target_url}
🚫 严禁在测试步骤中使用除上述目标 URL 之外的任何其他 URL。所有导航必须从目标 URL 出发，通过页面交互（点击链接、按钮等）完成。不要从记忆或探索记录中提取 URL 用于直接导航。

探索阶段收集到的页面路径 (最多20个):
{chr(10).join(explored_urls) if explored_urls else '无'}
{config_context}
{memory_info}
{scenarios_context}
{risk_points_context}
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