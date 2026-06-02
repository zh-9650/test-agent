"""agents/ui/execution_graph.py — Execution subgraph for UI test execution.

Builds a LangGraph StateGraph that executes the observe→decide→execute→assert→record
loop for a single test case. This is the core AI testing loop where the LLM agent
actually tests web pages.

Flow:
    START → observe → decide → (has tool_call?) → execute → assert → record → (loop or END)
                                       ↓ no tool_call
                                     record → END (test case complete)

Safety valves: max steps per case, max consecutive failures (both configurable via env).
"""

from __future__ import annotations

import os
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from core.change_detector import detect_changes
from core.interfaces import AssertionResult, ChangeReport, StepResult, TestCase, TestState
from core.llm_client import count_tokens, get_llm_client, safe_structured_invoke
from core.page_semantic import extract_page_semantics, take_screenshot, take_screenshot_compressed

from agents.ui.prompts import _format_page_info, get_assertion_prompt, get_execution_system_prompt, get_step_prompt
from agents.ui.tools import get_current_page, set_current_task, tools_by_name, tools, update_element_map


# =============================================================================
# V2.0 A (2026-06-02) — L2 Safety Net Helpers
# =============================================================================


def _fallback_assertion(reasoning: str, parse_error: Exception) -> AssertionResult:
    """V2.0 A6 (2026-06-02): 兜底断言, 当 LLM 返回无法解析为 JSON 时调用.

    设计理由 (来自 V2.0 v2 plan §3.1):
    - 老代码: JSON 解析失败 → 返 "未能解析评估结果 (非 JSON 格式)" + status="inconclusive"
    - 老代码问题: 散在 assert_node 内联 try/except, 难测试, 难复用
    - V2.0 A6: 抽出独立函数, 单元测试可独立验证, Phase B pydantic AssertionResult 接入也走它
    - 行为: 永远返 inconclusive, 不假装"猜测"status, reasoning 包含原始文本 + 错误

    Args:
        reasoning: LLM 原始响应文本
        parse_error: 解析时抛出的异常 (ValueError/SyntaxError/...)

    Returns:
        AssertionResult(status="inconclusive", reasoning=...)
    """
    excerpt = (reasoning or "")[:200]
    return AssertionResult(
        status="inconclusive",
        reasoning=f"LLM 响应 JSON 解析失败, 走 fallback 断言 (错误: {type(parse_error).__name__}: {parse_error})。原始响应片段: {excerpt!r}",
    )


def _truncate_messages_by_token(messages: list, budget: int) -> list[RemoveMessage]:
    """V2.0 A2 (2026-06-02): 按 token 数截断 messages, 保护 L2 context 不撞 65K.

    设计依据 (Anthropic Context Engineering 2025-09 + Microsoft Compaction 2026):
    - 保留 system message (index 0) + 最近 5 条 (含最新 user/assistant)
    - 删掉中间 (老) 的消息
    - 顺序: 从最老往新删, 直到 token count <= budget
    - 安全阀: budget 默认 30000 (留 65K - 30K 给 LLM output + 安全 buffer)
    - env 可调: L2_TOKEN_BUDGET

    Args:
        messages: LangChain 消息列表
        budget: token 预算

    Returns:
        RemoveMessage 列表 (LangGraph 会从 state 移除这些 id)
    """
    if not messages:
        return []
    total = count_tokens(messages)
    if total <= budget:
        return []

    # 计算可保留的范围: 永远保留 [0] (system) + 最后 5 条
    head = messages[:1]  # system
    tail_count = 5
    tail = messages[-tail_count:] if len(messages) > tail_count else []
    middle = messages[1:-tail_count] if len(messages) > tail_count + 1 else []

    # 从 middle 最老的开始删
    to_remove: list[RemoveMessage] = []
    working_head = list(head)
    working_middle = list(middle)
    working_tail = list(tail)
    while working_middle:
        candidate = working_head + working_middle + working_tail
        if count_tokens(candidate) <= budget:
            break
        m = working_middle.pop(0)  # 删最老的
        if hasattr(m, "id") and m.id:
            to_remove.append(RemoveMessage(id=m.id))
        elif m is not None:
            # 兜底: 没 id 时按 hash 构造 (LangGraph 不会真删, 但不会崩)
            import hashlib
            fake_id = hashlib.md5(repr(m).encode()).hexdigest()
            to_remove.append(RemoveMessage(id=fake_id))
    return to_remove


# =============================================================================
# Conditional Edge Functions
# =============================================================================


def should_continue(state: dict[str, Any]) -> str:
    """After decide: does the LLM want to execute a tool, or is the test case done?

    Checks the last message for tool_calls:
    - Has tool_calls → "execute"
    - No tool_calls → "record_complete" (test case done)
    """
    messages = state.get("messages", [])
    if not messages:
        return "record_complete"

    last_message = messages[-1]
    from core.llm_client import extract_tool_calls_from_message
    if extract_tool_calls_from_message(last_message):
        return "execute"
    return "record_complete"


def should_continue_or_stop(state: dict[str, Any]) -> str:
    """After record: continue to next step, or stop?

    Three conditions to stop:
    1. current_step >= MAX_STEPS_PER_CASE (safety valve)
    2. consecutive_failures >= MAX_CONSECUTIVE_FAILURES (safety valve)
    3. No tool_call from decide (test case naturally complete)
    """
    max_steps = int(os.getenv("MAX_STEPS_PER_CASE", "15"))
    max_failures = int(os.getenv("MAX_CONSECUTIVE_FAILURES", "3"))

    # Safety valve 1: max steps
    current_step = state.get("current_step", 0)
    if current_step >= max_steps:
        return "end"

    # Safety valve 2: consecutive failures
    consecutive_failures = state.get("consecutive_failures", 0)
    if consecutive_failures >= max_failures:
        return "end"

    # Check if test case is complete (look for the last AIMessage with tool_calls)
    # In the observe-decide-execute-assert-record loop, after record we check whether
    # the decide node produced a tool_call. If yes → loop back to observe. If no → end.
    messages = state.get("messages", [])
    # Find the most recent AIMessage to check if it had tool_calls
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            from core.llm_client import extract_tool_calls_from_message
            calls = extract_tool_calls_from_message(msg)
            if calls:
                # If the tool call was a completion marker, we should stop
                for call in calls:
                    if call.get("name") in ["mark_task_complete", "mark_task_failed", "mark_task_skipped"]:
                        return "end"
                return "observe"
            else:
                return "end"
    # No AIMessage found — end
    return "end"


# =============================================================================
# Node Implementations
# =============================================================================


async def observe_node(state: dict[str, Any]) -> dict[str, Any]:
    """Extract page semantics and screenshot from the current page.

    - Calls extract_page_semantics() to get page info
    - Calls take_screenshot_compressed() for visual context (V2.0 A2: JPEG q=60)
    - Updates element map so tools can resolve #N references
    - Saves state_before for change detection after execute
    """
    try:
        task_id = state.get("task_id")
        if task_id:
            set_current_task(task_id)
        page = get_current_page()

        # Extract semantics
        page_info = await extract_page_semantics(page)
        # V2.0 A2: 截图压缩 (env L2_SCREENSHOT_COMPRESSED=1 默认开)
        compress = os.getenv("L2_SCREENSHOT_COMPRESSED", "1") != "0"
        if compress:
            screenshot = await take_screenshot_compressed(page)
        else:
            screenshot = await take_screenshot(page)

        # Update element map for tools to resolve #N references
        update_element_map(page_info.get("interactive_elements", []))

        # Take state snapshot (for change detector after execute)
        state_before = dict(page_info)  # shallow copy

        return {
            "page_info": page_info,
            "screenshot": screenshot,
            "state_before": state_before,
            "state_after": {},  # will be filled after execute
        }
    except Exception as e:
        # Never crash: return error state
        return {
            "page_info": {"url": "error", "title": "Error", "interactive_elements": [], "error_messages": [str(e)]},
            "screenshot": "",
            "state_before": {},
            "state_after": {},
        }


async def decide_node(state: dict[str, Any]) -> dict[str, Any]:
    """LLM decides the next action based on page semantics and test case steps.

    - Gets current test case from test_plan[current_index]
    - Builds system prompt + step prompt + page info
    - Calls LLM with tools bound (kimi-k2.6 for execution)
    - Returns LLM response as new message

    V2.0 A3 (2026-06-02): session_summary 注入修复
    - V1.7 漏: decide_node 每步 insert(0, SystemMessage(...)) 覆盖前一个 case 留下的 summary
    - 修复: 从 state.session_summary 读取, 拼到 system_prompt 顶部, 跨 case 续传
    """
    try:
        llm = get_llm_client("sonnet")  # kimi-k2.6 for execution
        llm_with_tools = llm.bind_tools(tools)

        # Get current test case
        test_plan = state.get("test_plan", [])
        current_index = state.get("current_index", 0)
        if current_index >= len(test_plan):
            # No more test cases — should not happen in this subgraph
            return {"messages": [AIMessage(content="所有测试用例已完成。")]}

        current_test_case = test_plan[current_index]

        # Fetch contextual memories for this specific test case (RAG)
        from core.memory_utils import retrieve_memories
        query_text = f"{current_test_case.title} {current_test_case.description} {' '.join(current_test_case.steps)}"
        task_config = dict(state.get("task_config", {}))
        target_url = task_config.get("target_url", "")
        if target_url:
            contextual_memory = await retrieve_memories(target_url, query_text)
            task_config["memory_context"] = contextual_memory

        # Build prompts
        base_system_prompt = get_execution_system_prompt(current_test_case, task_config)

        # V2.0 A3: 把 session_summary 拼到 system_prompt 顶部 (跨 case 续传)
        session_summary = state.get("session_summary", "")
        if session_summary:
            system_prompt = (
                f"<session_summary>\n{session_summary}\n</session_summary>\n\n"
                f"{base_system_prompt}"
            )
        else:
            system_prompt = base_system_prompt

        step_prompt = get_step_prompt(state.get("current_step", 0), current_test_case)

        # Build messages for LLM
        messages = list(state.get("messages", []))  # copy

        # Add/replace system message at the start
        messages.insert(0, SystemMessage(content=system_prompt))

        # Add current step info + page semantics
        page_info = state.get("page_info", {})
        page_summary = _format_page_info(page_info)
        text_content = f"{step_prompt}\n\n当前页面状态:\n{page_summary}"

        # V2.0 A2: 截图压缩 (env L2_SCREENSHOT_COMPRESSED=1 默认开, 节省 80% tokens)
        # 兼容旧行为: 传 "0" 关闭
        compress = os.getenv("L2_SCREENSHOT_COMPRESSED", "1") != "0"
        screenshot_base64 = state.get("screenshot")
        if screenshot_base64:
            # 注意: state.screenshot 已是 base64, 不再二次压缩
            # 压缩应在 observe_node 截图时就做 (后续优化点)
            content = [
                {"type": "text", "text": text_content},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_base64}"}}
            ]
        else:
            content = text_content

        messages.append(HumanMessage(content=content))

        # Call LLM
        # Robust Retry Loop for API Rate Limits (429)
        import asyncio
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = await llm_with_tools.ainvoke(messages)
                return {"messages": [response]}
            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    return {"messages": [AIMessage(content=f"LLM调用失败: {str(e)}")]}

    except Exception as e:
        # Never crash: return error as AI message
        return {"messages": [AIMessage(content=f"LLM调用失败: {str(e)}")]}


async def execute_node(state: dict[str, Any]) -> dict[str, Any]:
    """Execute the tool call from the LLM's decide response.

    - Gets the last AI message with tool_calls
    - Dispatches to the matching tool function
    - Takes post-action snapshot for change detection
    - Increments current_step
    - V2.0 A4 (2026-06-02): 工具失败计入 consecutive_failures (不再沉默)
    - V2.0 A2 (2026-06-02): 截图压缩 (默认 JPEG q=60, 节省 ~80% tokens)
    """
    messages = state.get("messages", [])
    current_step = state.get("current_step", 0)
    consecutive_failures = state.get("consecutive_failures", 0)
    task_id = state.get("task_id")
    if task_id:
        set_current_task(task_id)

    # Get the last AI message with tool calls
    last_ai_msg = None
    tool_calls = []
    from core.llm_client import extract_tool_calls_from_message
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            calls = extract_tool_calls_from_message(msg)
            if calls:
                last_ai_msg = msg
                tool_calls = calls
                break

    if not last_ai_msg or not tool_calls:
        return {}  # shouldn't happen if decide routed here

    # Execute all tools sequentially
    results = []
    tool_messages = []
    any_failure = False
    for tool_call in tool_calls:
        tool_name = tool_call.get("name", "")
        tool_args = tool_call.get("args", {})
        tool_call_id = tool_call.get("id", "")

        try:
            if tool_name in tools_by_name:
                tool_fn = tools_by_name[tool_name]
                result_text = await tool_fn.ainvoke(tool_args)
            else:
                result_text = f"未知工具: {tool_name}"
        except Exception as e:
            result_text = f"执行失败: {str(e)}"

        results.append(result_text)
        tool_messages.append(ToolMessage(content=result_text, tool_call_id=tool_call_id, name=tool_name))

        # V2.0 A4: 失败信号捕获
        if "执行失败" in result_text or "未知工具" in result_text or "拒绝执行" in result_text:
            any_failure = True
            break  # Stop executing further tools if one fails

    # V2.0 A4: 失败计数
    if any_failure:
        consecutive_failures += 1
    else:
        # 成功重置 (与 L1 assert_node 行为一致, 防止老 fail 累积)
        consecutive_failures = 0

    # Take post-action snapshot for change detection
    state_after = {}
    screenshot_after = ""
    try:
        page = get_current_page()
        state_after = await extract_page_semantics(page)
        # V2.0 A2: 截图压缩 (JPEG q=60, env 可调)
        compress = os.getenv("L2_SCREENSHOT_COMPRESSED", "1") != "0"
        if compress:
            screenshot_after = await take_screenshot_compressed(page)
        else:
            screenshot_after = await take_screenshot(page)
    except Exception:
        # If we can't get post-action state, use empty dict
        pass

    import asyncio
    await asyncio.sleep(2) # Throttle to avoid LLM rate limit (429)

    return {
        "messages": tool_messages,
        "state_after": state_after,
        "screenshot_after": screenshot_after,
        "current_step": current_step + 1,
        "_last_tool_result": "\n".join(results),
        "_last_tool_calls": tool_calls, # Pass the batch for assertion
        "consecutive_failures": consecutive_failures,
    }


async def assert_node(state: dict[str, Any]) -> dict[str, Any]:
    """Assert the action result using hierarchical layers:
    
    Layer 0: Rule-based quick judgment (skip LLM for obvious cases)
    Layer 1: Change detection (facts) — detect_changes(state_before, state_after)
    Layer 2: LLM semantic judgment — pass/fail/inconclusive based on expected result
    """
    try:
        # Layer 1: Change detection (facts)
        state_before = state.get("state_before", {})
        state_after = state.get("state_after", {})
        change_report = detect_changes(state_before, state_after)

        # Get test case context (needed for both rule-based and LLM paths)
        test_plan = state.get("test_plan", [])
        current_index = state.get("current_index", 0)
        current_test_case = test_plan[current_index] if current_index < len(test_plan) else None

        tool_calls = state.get("_last_tool_calls", [])

        expected = current_test_case.expected if current_test_case else "无预期结果"
        
        current_step_index = state.get("current_step", 1) - 1
        if current_test_case and current_step_index < len(current_test_case.steps):
            current_step_text = current_test_case.steps[current_step_index]
        else:
            current_step_text = "验证最终预期结果"

        # =================================================================
        # Layer 0: Rule-based quick judgment (Hierarchical Assertion)
        # =================================================================

        # Layer 0.5: Explicit task markers (from Testhub migration)
        for call in tool_calls:
            name = call.get("name", "")
            if name == "mark_task_complete":
                reasoning = call.get("args", {}).get("reasoning", "LLM 主动标记任务成功")
                print(f"[HierarchicalAssert] LLM Explicit Marker: pass - {reasoning}")
                return {
                    "_last_change_report": change_report,
                    "_last_assertion": AssertionResult(status="pass", reasoning=reasoning),
                    "consecutive_failures": 0,
                }
            elif name == "mark_task_failed":
                reasoning = call.get("args", {}).get("reasoning", "LLM 主动标记任务失败")
                print(f"[HierarchicalAssert] LLM Explicit Marker: fail - {reasoning}")
                return {
                    "_last_change_report": change_report,
                    "_last_assertion": AssertionResult(status="fail", reasoning=reasoning),
                    "consecutive_failures": state.get("consecutive_failures", 0) + 1,
                }
            elif name == "mark_task_skipped":
                reasoning = call.get("args", {}).get("reasoning", "LLM 主动标记任务跳过")
                print(f"[HierarchicalAssert] LLM Explicit Marker: skipped - {reasoning}")
                return {
                    "_last_change_report": change_report,
                    "_last_assertion": AssertionResult(status="pass", reasoning=reasoning),
                    "consecutive_failures": 0,
                }

        # Rule 1: JS errors or visible error messages → FAIL immediately
        if change_report.js_errors or change_report.error_messages_visible:
            details_parts = []
            if change_report.js_errors:
                details_parts.append(f"JS错误: {change_report.js_errors}")
            if change_report.error_messages_visible:
                details_parts.append(f"页面错误: {change_report.error_messages_visible}")
            details = "; ".join(details_parts)
            status = "fail"
            reasoning = f"规则断言: 检测到错误 - {details}"
            print(f"[HierarchicalAssert] Rule-based: {status} - {reasoning}")
            assertion = AssertionResult(status=status, reasoning=reasoning)
            consecutive_failures = state.get("consecutive_failures", 0) + 1
            return {
                "_last_change_report": change_report,
                "_last_assertion": assertion,
                "consecutive_failures": consecutive_failures,
            }

        # Rule 2: Network errors → FAIL immediately
        if change_report.network_errors:
            details = f"网络错误: {change_report.network_errors}"
            status = "fail"
            reasoning = f"规则断言: 网络错误 - {details}"
            print(f"[HierarchicalAssert] Rule-based: {status} - {reasoning}")
            assertion = AssertionResult(status=status, reasoning=reasoning)
            consecutive_failures = state.get("consecutive_failures", 0) + 1
            return {
                "_last_change_report": change_report,
                "_last_assertion": assertion,
                "consecutive_failures": consecutive_failures,
            }

        # Rule 3: Intermediate step with no significant changes → INCONCLUSIVE
        is_final_step = current_test_case is not None and current_step_index >= len(current_test_case.steps) - 1
        if not is_final_step:
            has_significant_changes = (
                change_report.url_changed
                or change_report.new_elements
                or change_report.gone_elements
                or change_report.modal_appeared
            )
            if not has_significant_changes:
                status = "inconclusive"
                reasoning = "规则断言: 中间步骤，页面无明显变化"
                print(f"[HierarchicalAssert] Rule-based: {status} - {reasoning}")
                assertion = AssertionResult(status=status, reasoning=reasoning)
                consecutive_failures = 0  # reset on inconclusive
                return {
                    "_last_change_report": change_report,
                    "_last_assertion": assertion,
                    "consecutive_failures": consecutive_failures,
                }

        # =================================================================
        # Layer 2: LLM semantic judgment (fallthrough — no rule fired)
        # V2.0 B2 (2026-06-02): 走 safe_structured_invoke + pydantic AssertionResult
        # 替换 V1.5 的 50 行手剥 JSON, pydantic 强类型 + 双重 fallback (structured + raw parse)
        # =================================================================

        assertion_prompt = get_assertion_prompt(
            tool_calls=tool_calls,
            change_report=change_report,
            expected=expected,
            current_step_text=current_step_text,
            page_info=state_after,
        )

        # B2: 把 screenshot_after 拼到 prompt 末尾 (multimodal)
        screenshot_after = state.get("screenshot_after")
        if screenshot_after:
            # 视觉证据优先: 拼接图像块到 HumanMessage
            content_with_image = [
                {"type": "text", "text": assertion_prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_after}"}}
            ]
            full_prompt = assertion_prompt  # safe_structured_invoke 走纯文本
            multimodal = True
        else:
            full_prompt = assertion_prompt
            multimodal = False

        # B2: 走 safe_structured_invoke + pydantic AssertionResult
        # 双轨: 1) structured_output (主) → 2) raw parse + JSON extract (fallback)
        result = await safe_structured_invoke(full_prompt, AssertionResult, model_type="sonnet")

        if result is not None and isinstance(result, AssertionResult):
            status = result.status
            final_reasoning = result.reasoning
        else:
            # B2 双 fallback 都失败 → V2.0 A6 _fallback_assertion 兜底
            print(f"[HierarchicalAssert] B2 safe_structured_invoke returned None, using _fallback_assertion")
            # 取最后一次 LLM 响应文本 (从 multimodal 切换到 raw 调用)
            try:
                llm = get_llm_client("sonnet")
                msgs = [SystemMessage(content="你是 UI 自动化测试断言专家. 输出 JSON: {status, reasoning}")]
                if multimodal:
                    msgs.append(HumanMessage(content=content_with_image))
                else:
                    msgs.append(HumanMessage(content=full_prompt))
                raw = await llm.ainvoke(msgs)
                raw_text = raw.content if hasattr(raw, "content") else str(raw)
                if isinstance(raw_text, list):
                    parts = []
                    for item in raw_text:
                        if isinstance(item, dict) and "text" in item:
                            parts.append(item["text"])
                        elif isinstance(item, str):
                            parts.append(item)
                    raw_text = "\n".join(parts)
                fallback = _fallback_assertion(raw_text if isinstance(raw_text, str) else str(raw_text), ValueError("safe_structured_invoke returned None"))
            except Exception as e2:
                fallback = _fallback_assertion(f"LLM 调用失败: {e2}", e2)
            status = fallback.status
            final_reasoning = fallback.reasoning

        # B2: 状态归一化 (pydantic 已经校验 status enum, 但万一 raw parse 走到要兜底)
        if status not in ("pass", "fail", "inconclusive"):
            status = "inconclusive"

        assertion = AssertionResult(status=status, reasoning=final_reasoning)

        # Update consecutive_failures
        consecutive_failures = state.get("consecutive_failures", 0)
        if status == "fail":
            consecutive_failures += 1
        else:
            consecutive_failures = 0  # reset on pass or inconclusive

        return {
            "_last_change_report": change_report,
            "_last_assertion": assertion,
            "consecutive_failures": consecutive_failures,
        }
    except Exception as e:
        # Never crash: return inconclusive assertion
        return {
            "_last_change_report": ChangeReport(),
            "_last_assertion": AssertionResult(status="inconclusive", reasoning=f"断言异常: {str(e)}"),
            "consecutive_failures": state.get("consecutive_failures", 0),
        }


async def record_node(state: dict[str, Any]) -> dict[str, Any]:
    """Record the step result and manage context for next step.

    Two paths reach this node:
    1. After assert (normal step) → build StepResult and collect it
    2. From decide with no tool_call (test case complete) → skip StepResult

    V2.0 A2 (2026-06-02): 上下文管理从"按条"截断改为"按 token"截断
    - 老逻辑: messages > 10 → 删中间, 撞 65K token 风险
    - 新逻辑: total tokens > L2_TOKEN_BUDGET (默认 30K) → 删中间 (保留 system + 最近 5)
    - 依据: Anthropic Context Engineering 2025-09 + Microsoft Compaction 2026
    """
    # Determine if this is a normal step (path from assert) or completion (path from decide)
    messages = list(state.get("messages", []))
    last_ai_msg = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            last_ai_msg = msg
            break

    from core.llm_client import extract_tool_calls_from_message
    calls = extract_tool_calls_from_message(last_ai_msg) if last_ai_msg else []
    has_tool_call = bool(calls)

    # Build StepResult only on normal step path (has tool_call)
    collected_steps = []
    if has_tool_call:
        if len(calls) > 1:
            action_type = "BATCH"
            action_target = "Multiple"
            action_args = {"calls": calls}
        else:
            tool_call = calls[0]
            action_type = tool_call.get("name", "")
            action_target = str(tool_call.get("args", {}).get("target", ""))
            action_args = tool_call.get("args", {})

        step_result = StepResult(
            step_index=state.get("current_step", 0) - 1,  # execute already incremented
            action_type=action_type,
            action_target=action_target,
            action_args=action_args,
            result=state.get("_last_tool_result", ""),
            screenshot_path=state.get("screenshot", ""),
            change_report=state.get("_last_change_report"),
            assertion=state.get("_last_assertion"),
            thought=last_ai_msg.content if isinstance(last_ai_msg.content, str) else str(last_ai_msg.content),
        )
        collected_steps = [step_result]

    # V2.0 A2: token-aware truncation
    budget = int(os.getenv("L2_TOKEN_BUDGET", "30000"))
    messages_to_remove = _truncate_messages_by_token(messages, budget)

    result: dict[str, Any] = {}
    if collected_steps:
        result["_collected_steps"] = collected_steps
    if messages_to_remove:
        result["messages"] = messages_to_remove

    return result


# =============================================================================
# Graph Builder
# =============================================================================


def build_execution_graph() -> StateGraph:
    """Build the execution subgraph for a single test case.

    Nodes: observe, decide, execute, assert, record
    Conditional edges:
    - decide → execute (has tool_call) or record (no tool_call = test case done)
    - record → observe (continue) or END (safety valve or test case complete)
    """
    graph = StateGraph(TestState)

    # Add nodes
    graph.add_node("observe", observe_node)
    graph.add_node("decide", decide_node)
    graph.add_node("execute", execute_node)
    graph.add_node("assert", assert_node)
    graph.add_node("record", record_node)

    # Edges
    graph.add_edge(START, "observe")
    graph.add_edge("observe", "decide")
    graph.add_conditional_edges(
        "decide",
        should_continue,
        {
            "execute": "execute",
            "record_complete": "record",  # no tool_call = test case done
        },
    )
    graph.add_edge("execute", "assert")
    graph.add_edge("assert", "record")
    graph.add_conditional_edges(
        "record",
        should_continue_or_stop,
        {
            "observe": "observe",  # continue to next step
            "end": END,             # safety valve hit or test case complete
        },
    )

    return graph.compile()