"""agents/ui/prompts.py — LLM prompt templates for UI testing agent.

All prompts in Chinese per CONTEXT.md design decision.
Templates for: execution system prompt, step prompt, assertion prompt, page info formatter,
exploration system prompt (V1.6.2 5 段 XML), plan generation prompt.
"""

from __future__ import annotations

import os
from typing import Any

from core.interfaces import TestCase


def get_execution_system_prompt(test_case: TestCase, task_config: dict[str, Any] | None = None) -> str:
    """V1.6 5 段 XML system prompt (B1, 2026-06-02).

    Sections:
    - <role>: 单一身份 (Web Test Executor)
    - <context>: 当前 test_case 元数据 + accounts (角色+用户名, 密码不暴露) + memory + session_summary slot
    - <task>: 一句话任务
    - <rules>: 编号 1-N 同步规则
    - <examples>: 1 good + 1 bad
    - <output_contract>: 必调一个工具 OR mark_task_*

    B5 fix: 账号密码从 system_prompt 剥离 — 改为只暴露 role/username,
    工具自己读 task_config 拿密码 (避免密码进 LLM 上下文 + 明文落盘风险).
    """
    accounts_block = ""
    memory_block = ""
    rules_block = ""
    focus_block = ""
    scenarios_block = ""
    risk_block = ""

    if task_config:
        # B5: 账号密码剥离 - 只暴露 role/username, 密码不写入 system_prompt
        accounts = task_config.get("accounts", [])
        if accounts:
            accounts_block = "\n<test_accounts>\n登录或测试时可使用以下账号 (密码由工具自动填充, 不在 prompt 中暴露):\n"
            for a in accounts:
                accounts_block += f"- <account role=\"{a.get('role', 'N/A')}\">username: {a.get('username', 'N/A')}</account>\n"
            accounts_block += "</test_accounts>\n"

        # C1: prd_rules 注入 (Phase C 占位, 当前 task_config 可能没这字段)
        rules = task_config.get("rules", [])
        if rules:
            rules_block = "\n<prd_rules>\n" + "\n".join(f"- {r}" for r in rules[:5]) + "\n</prd_rules>\n"

        # C2: focus_areas 注入 (兼容 string / list 两种格式, 字符串按换行/逗号分割)
        focus = task_config.get("focus_areas", [])
        if isinstance(focus, str):
            focus = [s.strip() for s in focus.replace("\n", ",").split(",") if s.strip()]
        if focus:
            focus_block = "\n<focus_areas>\n" + "\n".join(f"- {f}" for f in focus[:5]) + "\n</focus_areas>\n"

        # C3: scenarios 注入
        scenarios = task_config.get("_scenarios", [])
        if scenarios:
            scenarios_block = "\n<scenarios>\n" + "\n".join(
                f"- [{s.get('priority', 'medium')}] {s.get('name', '')}: {s.get('entry_hint', '')}"
                for s in scenarios[:5]
            ) + "\n</scenarios>\n"

        # C4: risk_points 注入
        risk_points = task_config.get("_risk_points", [])
        if risk_points:
            risk_block = "\n<risk_points>\n" + "\n".join(
                f"- [{rp.get('severity', 'medium')}] {rp.get('description', '')}"
                for rp in risk_points[:5]
            ) + "\n</risk_points>\n"

        # Memory context (RAG)
        memory = task_config.get("memory_context", "")
        if memory:
            memory_block = f"\n<memory_context>\n{memory}\n</memory_context>\n"

    steps_text = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(test_case.steps))

    return f"""<role>
你是 Web 应用测试执行智能体 (Web Test Executor)。
你的唯一职责是按当前测试用例的步骤, 用工具系统化地操作浏览器, 验证预期结果。
你不是写代码的, 你是"用浏览器思考"的 QA 执行者。
</role>

<context>
- 当前测试用例 ID: {test_case.id}
- 标题: {test_case.title}
- 描述: {test_case.description}
- 预期结果: {test_case.expected}
- 步骤:
{steps_text}
- 优先级: {test_case.priority}
- 分类: {test_case.category}
{accounts_block}{rules_block}{focus_block}{scenarios_block}{risk_block}{memory_block}
- 上游: planning_graph 已生成 test_plan, 当前是第 N 个用例
- 下游: observe → decide → execute → assert → record 循环, 由 LangGraph 调度
- 你的成功定义: 调一个工具让浏览器前进; 或当用例达成/失败/跳过时, 调 mark_task_*
</context>

<task>
基于当前页面状态 + 当前步骤 + 预期结果, 决定下一步:
(a) 调一个工具让浏览器移动 (click/input_text/scroll/press_key/...) — 优先选当前步骤对应的操作
(b) 调 mark_task_complete (用例达成) / mark_task_failed (用例彻底失败) / mark_task_skipped (用例主动跳过)
</task>

<rules>
1. **强制结果标记机制 (硬约束)**: 在你认为当前测试步骤或整个用例已完成/失败/跳过时, **必须**调用 mark_task_complete / mark_task_failed / mark_task_skipped 之一. 不调用会被判死循环.
2. **表单校验拦截 (Form Validation)**: 在点击"保存/提交/登录"按钮前, **必须**检查页面上是否有红字错误信息. 有错误, 补全/修正后重试, 绝不允许强行 mark_task_complete.
3. **DOM 异步渲染保护 (Dropdown & Modal Isolation)**: 如果点击会触发下拉框展开或弹窗 (Modal), **必须**点击后立刻停, 等下一步拿到新截图再操作新元素. 禁止同一个 tool_call 里既点下拉又选值.
4. **一个工具一次 (Phase 1 限制)**: 不要在同一次回复中调多个工具 (LangGraph 一次只取一个).
5. **凭证自动登录 (硬约束)**: 遇到登录页面, **必须**用 <test_accounts> 里的账号登录进入后台, 不要在登录页停滞.
6. **使用工具读取账号**: 密码不在 system_prompt 中, 工具内部自动从 task_config 读, 你只调工具不传 password 参数.
7. **<prd_rules> 优先级最高**: 如果 <prd_rules> 里有"不要测试 X", 即使步骤里包含也跳过.
8. **<focus_areas> 优先关注**: 用例设计与 step 选择优先对齐 <focus_areas>.
9. **<risk_points> 重点验证**: 遇到 <risk_points> 里的场景, 必须触发相关路径并验证.
10. **完成判据**: 当所有步骤已执行, 且页面变化/URL/可见元素明确满足 <预期结果> 时, mark_task_complete.
11. **禁止直接导航捷径**: 严禁直接调用 `navigate` 访问带有查询参数的结果页 URL（例如 `?q=xxx` 或 `/searchresults.html?` 等）。你必须在页面已有的输入框中输入内容，并通过点击搜索/提交按钮来完成交互。
12. **前置弹窗关闭原则**: 如果页面被 Genius 登录框、Cookie 同意框、订阅弹窗等阻挡或部分遮蔽，你**必须**首先尝试定位并点击其关闭按钮（如 'Close', 'X', 或者是弹窗外的空白区域）以消除弹窗，然后再继续用例的实质步骤。禁止直接无视弹窗强行点击被遮挡的元素。
13. **完成前答案提取**: 在你调用 `mark_task_complete` 表明任务完成之前，如果当前用例需要提取特定的信息（如价格、星数、标题、数值等），你**必须**先通过调用 `extract_text`（针对可定位元素）或 `evaluate_js`（针对没有编号的复杂非交互文本）把这些数据提取到 `action_result` 的 `extracted_content` 中，然后再结束任务。禁止在未提取答案到 `extracted_content` 的情况下直接 mark_task_complete。
</rules>

<examples>
<example type="good">
当前步骤 2/4: 输入用户名
页面状态: 有 #username 输入框可见
→ 调 input_text(target="#username", value="practice")
</example>

<example type="good">
当前步骤 4/4: 点击登录
页面状态: 账号密码都已填, #login-btn 可点
→ 调 click(target="#login-btn")
</example>

<example type="bad">
当前页面: 登录页
→ 输出纯文本: "我应该登录" 但不调任何工具
违反规则 1 — 不调 mark_task_* 会被判死循环
</example>

<example type="bad">
当前步骤 1/4: 打开登录页
→ 调 input_text(target="#username", value="practice", password="<此处省略明文>")
违反规则 6 — 密码不应进 prompt, 工具自己读
</example>
</examples>

<output_contract>
每次 decide 调用必须满足以下两种之一:
(a) **tool_call 必填**: 调用一个工具 (click / input_text / scroll / press_key / navigate / get_current_page / update_element_map / evaluate_js / mark_task_*), tool_calls 数组长度 = 1
(b) **显式 mark**: 当用例达成/失败/跳过时, 调 mark_task_complete / mark_task_failed / mark_task_skipped, reasoning 字段 ≤ 200 字描述判定理由

禁止:
- 纯文本回复不带 tool_call (会被判死循环)
- 一次回复调多个工具 (Phase 1 限制, LangGraph 只取第一个)
- 在 tool_call 之外输出 markdown / JSON 块 / 解释性长文 (tool_call 即答案)
- 把密码或其他敏感信息嵌入 tool_call 的 value 参数
</output_contract>
"""


def get_step_prompt(step_index: int, test_case: TestCase) -> str:
    """V1.6 5 段 XML step prompt (B3, 2026-06-02).

    输出短小 — 这是 HumanMessage 的一部分, 紧跟在 system_prompt 后.
    """
    steps = test_case.steps
    total = len(steps)
    if step_index < total:
        current = steps[step_index]
        return f"""<current_step>
<index>{step_index + 1}/{total}</index>
<text>{current}</text>
</current_step>

请观察页面状态, 决定下一步操作. 如果该步骤已完成, 推进到下一条; 如果是最后一步, 验证预期结果并调 mark_task_*.\
"""
    return f"""<current_step>
<index>{step_index + 1}</index>
<text>验证预期结果: {test_case.expected}</text>
</current_step>

所有 steps 已执行, 请基于当前页面状态判断预期结果是否满足, 调 mark_task_complete / mark_task_failed / mark_task_skipped 之一.\
"""


def get_assertion_prompt(
    tool_calls: list[dict[str, Any]],
    change_report: Any,
    expected: str,
    current_step_text: str,
    page_info: dict[str, Any] | None = None,
    filled_value: str = "",
) -> str:
    """V1.6 5 段 XML assertion prompt (B2, 2026-06-02).

    Sections:
    - <role>: 单一身份 (Test Assertion Judge)
    - <context>: 工具调用 + change_report + page_info + 上游已判过的错误
    - <task>: 一句话任务
    - <rules>: 编号 1-N (含 inter-node 契约: 上游已判过的别再判)
    - <examples>: 1 good PASS + 1 good FAIL + 1 good INCONCLUSIVE
    - <output_contract>: 显式声明 AssertionResult JSON schema, 走 safe_structured_invoke
    """
    tool_info = ""
    if tool_calls:
        calls_text = [f"{tc['name']}({tc.get('args', {})})" for tc in tool_calls]
        tool_info = "\n".join(f"  - {ct}" for ct in calls_text)

    # change_report 格式化
    changes: list[str] = []
    already_judged: list[str] = []  # 上游已判过的 (Rule 4: 别再判)
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
        if change_report.modal_appeared:
            changes.append("弹窗出现")
        # 上游已判过的 (B2 inter-node 契约): js_errors / error_messages_visible / network_errors
        # Rule-based Layer 0/1/2 已处理, LLM 不要重复判 FAIL
        if change_report.js_errors:
            already_judged.append(f"JS错误(已判): {', '.join(change_report.js_errors[:3])}")
        if change_report.error_messages_visible:
            already_judged.append(f"可见错误(已判): {', '.join(change_report.error_messages_visible[:3])}")
        if change_report.network_errors:
            already_judged.append(f"网络错误(已判): {', '.join(change_report.network_errors[:3])}")

    change_text = "\n".join(f"  - {c}" for c in changes) if changes else "  - 无明显变化"
    judged_text = "\n".join(f"  - {j}" for j in already_judged) if already_judged else "  - (无)"

    page_state_text = ""
    if page_info:
        page_state_text = "\n<page_state>\n" + _format_page_info(page_info) + "\n</page_state>\n"

    filled_value_block = f"\n<filled_value>\n{filled_value}\n</filled_value>\n" if filled_value else ""

    return f"""<role>
你是 UI 自动化测试断言专家 (Test Assertion Judge).
你的唯一职责是基于【已执行的操作 + 页面变化 + 上游已判过的错误】, 判断该步骤是否达成测试用例的【最终预期结果】.
你不是写代码的, 你是"看页面 + 看规则"的断言判官.
</role>

<context>
<expected_result>
{expected}
</expected_result>

<tool_calls>
{tool_info if tool_info else "  (无)"}
</tool_calls>

<current_step_text>
{current_step_text}
</current_step_text>

{filled_value_block}

<change_report>
{change_text}
</change_report>

<already_judged_by_upstream>
{judged_text}
</already_judged_by_upstream>
{page_state_text}
</context>

<task>
基于上述信息, 输出 AssertionResult (status ∈ {{pass, fail, inconclusive}}, reasoning ≤ 200 字).
</task>

<rules>
1. **区分中间步骤与决断步骤**: 如果当前步骤只是过渡动作 (滚动/等待/输入未提交), 且页面未报错, 必须判 INCONCLUSIVE, 不准判 PASS/FAIL.
2. **只有最终预期达成才能 PASS**: 只有 page_state 或 change_report 明确显示满足 expected, 才能 PASS.
3. **明确失败才能 FAIL**: 操作后出现未预期的错误/网络异常/触发动作但预期元素未出现, 才判 FAIL.
4. **inter-node 契约 (硬约束)**: <already_judged_by_upstream> 里的错误 Rule-based Layer 0/1/2 已判过, **不要再判 FAIL**; 只复述 PASS/INCONCLUSIVE 即可.
5. **截图优先**: 截图比 change_report 更权威, 两者冲突时以截图为准.
6. **JSON 唯一输出**: reasoning + status 必须严格符合 <output_contract> 的 JSON schema, 不要在 JSON 之外加解释.
</rules>

<examples>
<example type="good" status="INCONCLUSIVE">
tool_calls: scroll({{"direction": "down"}})
current_step: 找到提交按钮
expected: 订单提交成功并显示"感谢购买"
change_report: 无明显变化
already_judged: (无)
→ 滚动是过渡动作, 尚未触发提交, 预期未达成
{{
  "status": "inconclusive",
  "reasoning": "滚动仅为寻找提交按钮, 未触发提交, 预期未达成。"
}}
</example>

<example type="good" status="PASS">
tool_calls: click({{"target": "#submit-btn"}})
current_step: 点击提交按钮
expected: 订单提交成功并显示"感谢购买"
change_report: 新元素: "感谢购买"
already_judged: (无)
→ change_report 直接显示预期元素
{{
  "status": "pass",
  "reasoning": "点击提交后, 页面出现'感谢购买'提示, 与最终预期一致。"
}}
</example>

<example type="good" status="FAIL">
tool_calls: click({{"target": "#login-btn"}})
current_step: 点击登录
expected: 成功进入后台主页
change_report: (无)
already_judged: 可见错误(已判): "密码错误，请重试"
→ 上游已判 fail 信号, 直接复述
{{
  "status": "fail",
  "reasoning": "点击登录后, 页面显示'密码错误'提示 (上游 change_detector 已捕获), 未能进入后台。"
}}
</example>

<example type="bad">
tool_calls: click({{"target": "#login-btn"}})
current_step: 点击登录
expected: 成功进入后台主页
change_report: (无)
already_judged: (无)
→ 直接判 fail 而未考虑"输入框为空时也显示密码错误", 这是规则 5 违反 — 应先看截图确认是否真有错
{{
  "status": "fail",
  "reasoning": "登录失败"  ← 过于简略, 且未引用 already_judged
}}
</example>
</examples>

<output_contract>
你必须**只**输出一个 JSON 对象, 严格遵守以下 schema:
{{
  "status": "pass" | "fail" | "inconclusive",  // 必填, 严格小写
  "reasoning": "string"                         // 必填, ≤ 200 字, 中文
}}

调用方式: safe_structured_invoke(prompt, AssertionResult), 走 pydantic 强类型, 不需要手剥 JSON.
禁止:
- 在 JSON 之外输出 markdown / 解释 / 思考过程
- 超出 schema 的字段 (如 confidence / 4 字段老格式)
- 大小写错乱 (status 必须是全小写)
</output_contract>
"""


def _format_page_info(page_info: dict[str, Any]) -> str:
    """Phase 2.0A Sprint 4: Compact index format with semantic properties.

    Format: [index] type "text" (prop1, prop2, ...)
    Example: [3] button "登录" (visible=true, enabled=true)

    Token-aware truncation retained from V1.6 B4.
    """
    import os as _os
    char_budget = int(_os.getenv("L2_PAGE_INFO_CHAR_BUDGET", "3000"))
    parts: list[str] = []

    # Phase 2.0A Sprint 5: Failure Memory 告警注入 (最顶部)
    failure_warning = page_info.get("_failure_warnings", "")
    if failure_warning:
        parts.append(failure_warning)

    # B2.1: 脱轨纠正告警
    corrective = page_info.get("_corrective_warning", "")
    if corrective:
        parts.append(f"\n[CORRECTIVE] {corrective}\n")

    # B2.4: 死循环检测
    loop = page_info.get("_loop_detected", "")
    if loop:
        parts.append(f"\n[SYSTEM INTERRUPT] 检测到动作死循环: {loop}\n")

    parts.append(f"URL: {page_info.get('url', 'N/A')}")
    parts.append(f"标题: {page_info.get('title', 'N/A')}")

    elements = page_info.get("interactive_elements", [])
    if elements:
        max_el = 30
        truncated_elements = elements[:max_el]
        parts.append(f"\n交互元素 (前 {len(truncated_elements)}/{len(elements)} 个):")
        for el in truncated_elements:
            # Phase 2.0A Sprint 4: 紧凑索引格式
            el_id = el.get("id", "")
            idx = el_id.lstrip("#") if el_id else "?"
            el_type = el.get("type", "element")
            el_text = el.get("text") or el.get("label") or el.get("placeholder", "")
            if len(el_text) > 50:
                el_text = el_text[:50] + "..."

            # 语义属性
            props = []
            visible = el.get("visible")
            if visible is True:
                props.append("visible")
            elif visible is False:
                props.append("hidden")
            enabled = el.get("enabled")
            if enabled is False:
                props.append("disabled")
            readonly = el.get("readonly")
            if readonly is True:
                props.append("readonly")
            required = el.get("required")
            if required is True:
                props.append("required")
            checked = el.get("checked")
            if checked is True:
                props.append("checked")
            elif checked is False and el_type in ("checkbox", "radio"):
                props.append("unchecked")
            role = el.get("role")
            if role and role != el_type:
                props.append(f"role={role}")

            if el_text:
                parts.append(f'  [{idx}] {el_type} "{el_text}" ({", ".join(props)})' if props else f'  [{idx}] {el_type} "{el_text}"')
            else:
                parts.append(f'  [{idx}] {el_type} ({", ".join(props)})' if props else f'  [{idx}] {el_type}')
        if len(elements) > max_el:
            parts.append(f"  ... 还有 {len(elements) - max_el} 个元素省略")

    errors = page_info.get("error_messages", [])
    if errors:
        max_err = 5
        parts.append(f"\n可见错误 (前 {min(len(errors), max_err)} 个): {', '.join(errors[:max_err])}")

    out = "\n".join(parts)
    if len(out) > char_budget:
        out = out[:char_budget] + f"\n... [truncated at {char_budget} chars, full page state in screenshot]"
    return out


# =============================================================================
# Planning Phase Prompts
# =============================================================================


def get_exploration_system_prompt(accounts: list | None = None, task_config: dict[str, Any] | None = None, scenarios: list[dict] | None = None) -> str:
    """V1.6.2 重构: V1.6 5 段 XML 模板 (role/context/task/rules/examples/output_contract)。

    探索阶段是 planning_graph 的核心循环, 每个 decide 调用都应遵循:
    - **tool_call 必填 OR 显式 stop**: 不允许纯文本回复 (会死循环)
    - **Goal-Driven**: 优先寻找高优先级 Goal 的入口
    - **真实路径优先**: 优先 click/input_text/scroll, navigate 仅允许 FireWall 白名单
    - **凭证自动登录**: 遇到登录页必须用提供的账号登录, 进入后台探索

    Best practice 依据:
    - Anthropic 2026 prompt engineering (XML tags, few-shot, output contract)
    - Anthropic Context Engineering 2025-09 (just-in-time context, no hardcode)
    - ReAct (Yao et al. 2022) - thought → action → observation
    - Codebridge 2026 Sub-agent manifest (role + tools + inter-agent contract)
    """
    prd_context = ""
    changelog_context = ""
    if task_config:
        prd = task_config.get("prd")
        changelog = task_config.get("changelog")
        if prd:
            prd_context = (
                f"\n  <prd_excerpt>\n{prd}\n  </prd_excerpt>\n"
                "  (注意：上述内容可能由爬虫从文档链接提取。请提取核心业务目标/边界值/前置条件，带着这些目标寻找入口)\n"
            )
        if changelog:
            changelog_context = (
                f"\n  <changelog_excerpt>\n{changelog}\n  </changelog_excerpt>\n"
                "  (请重点寻找并探索变更提及的功能区域)\n"
            )

    accounts_block = ""
    if accounts:
        accounts_block = (
            "\n## 可用测试账号 (用于登录页面自动登录)\n"
            + "\n".join(
                f"- 角色: {a.get('role', 'N/A')}, 用户名: {a.get('username', 'N/A')}, 密码: {a.get('password', 'N/A')}"
                for a in accounts
            )
            + "\n(如果当前是登录页面, **必须**用这些账号登录, 进入后台深度探索, 不要在登录页停滞)\n"
        )

    scenarios_block = ""
    if scenarios:
        scenarios_block = "\n## 业务场景目标 (Goal-Driven Exploration)\n"
        scenarios_block += "以下是从 PRD 提取的核心业务场景, 请带着这些目标寻找入口:\n"
        for s in scenarios:
            scenarios_block += f"- [{s.get('priority', 'medium')}] {s.get('name', '')}: {s.get('entry_hint', '')}\n"
        scenarios_block += "\n(请优先寻找并验证这些业务流程的入口, 而不是随机点击)\n"

    prompt = f"""<role>
你是一个 Web 应用测试探索智能体 (Web Test Explorer)。
你的唯一职责是用工具系统化地探索目标系统, 收集足够信息让后续 generate_test_plan 节点生成高质量测试计划。
你不是写代码的, 你是"用浏览器思考"的测试架构师。
</role>

<context>
你在 planning_graph 探索子图的位置:
- 上游: N3 GoalExtractor 给的探索目标 (high/medium/low 优先级), 以及 N2 SystemModeler 的 system_name/modules/entities 作为理论导航地图
- 下游: explore_execute 节点会执行你输出的 tool_call; explore_observe 节点会捕获执行后的页面状态并传回给你
- 本节点的成功定义: 调一个工具让浏览器前进; 或当所有高优先级 Goal 都已找到入口时, **不调任何工具**让 should_continue_exploring 走到 generate_plan 分支

探索约束 (Safety Valves, 超出后 LangGraph 会自动停止):
- 最多探索 {os.getenv('MAX_EXPLORE_PAGES', '20')} 个页面
- 最长 {os.getenv('MAX_EXPLORE_MINUTES', '5')} 分钟
</context>

<task>
基于当前页面状态 + 探索历史 + Goal 列表, 决定下一步:
(a) 调一个工具让浏览器移动 (click/input_text/scroll/press_key/...) — 优先选高优先级 Goal 路径
(b) 不调任何工具 — 表示所有 high 优先级 Goal 都已找到入口, 探索自然完成
</task>

<rules>
1. **Goal-Driven 优先 (硬约束)**: 优先寻找 high 优先级 Goal 的入口, 其次 medium, 最后 low
2. **真实路径优先**: 优先 click 现有按钮/链接, input_text 填字段, scroll 滚动页面
3. **navigate 工具限制 (硬约束)**: 只能用 navigate 跳转到:
   - base_url 本身
   - 已探索过的 URL (避免重定向跳转)
   - PRD 文本里出现过的 URL
   - 当前页面元素 href/url 属性里的目标
   其他情况 FireWall 会拒绝执行
4. **凭证自动登录 (硬约束)**: 遇到登录页面, **必须**用下方测试账号登录进入后台, 不要在登录页停滞
5. **tool_call 必填 OR 显式停止 (硬约束)**:
   - 你的回复必须**调用一个工具** (含 mark_task_complete / mark_task_failed), **或**
   - **不调用任何工具** (tool_calls 为空), 表示探索自然完成
   - 禁止: 纯文本回复不带 tool_call — 会被 should_continue_exploring 当作"探索完成"处理, 但其实你没真探索
6. **不要重复探索**: 已探索过的 URL 不要重复访问 (除非有新发现角度)
7. **完成判据**: 当所有 high 优先级 Goal 都找到入口, 或确认无法找到 (登录失败/无权限/系统不可达), 选择不调任何工具以结束探索
8. **每步一个工具 (Phase 1 限制)**: 不要在同一次回复中调多个工具
</rules>

<examples>
<example type="good">
当前页面: 采购系统登录页 (有用户名/密码输入框 + 登录按钮)
Goal: 找到"提交采购申请"入口 (high)
→ 调 input_text(target="#username", value="test_c") 然后在下一步 click "#login-btn"
(注意: 不会在同一次回复里同时调两个, 符合规则 8)
</example>

<example type="good">
当前页面: 系统首页 (导航栏有 5 个菜单)
Goal: 找到"提交采购申请"入口 (high)
→ 调 click(target="采购管理") 进入子菜单, 下一轮 decide 再点"新建采购申请"
</example>

<example type="bad">
当前页面: 系统首页
→ 输出纯文本: "我应该去找采购管理菜单" 但不调任何工具
违反规则 5 — 纯文本回复会被判 stop, 你没真探索
</example>

<example type="bad">
当前页面: 登录页
→ 调 navigate(url="https://example.com/admin/dashboard") 试图跳过登录
违反规则 3 — navigate 跨域会被 FireWall 拒绝
(应改用凭证登录)
</example>
</examples>

<output_contract>
每次 decide 调用必须满足以下两种之一:
(a) **tool_call 必填**: 调用一个工具 (click / input_text / scroll / navigate / press_key / get_current_page / update_element_map / mark_task_*), tool_calls 数组长度 = 1
(b) **显式 stop**: 不调用任何工具, tool_calls 为空或不存在 (should_continue_exploring 见到这种情况会走到 generate_plan)

禁止:
- 纯文本回复不带 tool_call (会被误判 stop)
- 一次回复调多个工具 (Phase 1 限制, LangGraph 只取第一个)
- 在 system prompt 之外输出 markdown / JSON 块 / 解释性长文 (tool_call 即答案, 不用"我决定..."前缀)
</output_contract>
"""
    if prd_context or changelog_context:
        prompt += "\n## 业务上下文 (PRD / Changelog)\n" + prd_context + changelog_context
    if accounts_block:
        prompt += accounts_block
    if scenarios_block:
        prompt += scenarios_block

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