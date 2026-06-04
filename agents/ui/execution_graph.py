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

import functools
import os
import re
import time
from typing import Any, Awaitable, Callable

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from core.change_detector import detect_changes
from core.execution_logger import log_node_event
from core.interfaces import ActionResult, AssertionResult, ChangeReport, StepResult, TestCase, TestState
from core.llm_client import count_tokens, get_llm_client, safe_structured_invoke
from core.page_semantic import extract_page_semantics, take_screenshot, take_screenshot_compressed

from agents.ui.prompts import _format_page_info, get_assertion_prompt, get_execution_system_prompt, get_step_prompt
from agents.ui.tools import get_current_page, set_current_task, set_task_config, tools_by_name, tools, update_element_map


# =============================================================================
# V2.0 D (2026-06-02) — Observability: Node Instrumentation Decorator
# =============================================================================


def instrument_node(node_name: str) -> Callable[[Callable[..., Awaitable[dict]]], Callable[..., Awaitable[dict]]]:
    """V2.0 D2 (2026-06-02): 装饰 L2 节点, 自动:
    1. log_node_event("enter") + log_node_event("exit", duration_ms, token_count)
    2. 把 node_name / duration_ms 写到 state (_last_node_name, _last_node_duration_ms)
       让 runtime 据此发 WebSocket node_event
    3. 保留原函数签名, 单测可直接 await observe_node(state) 不变

    Args:
        node_name: 节点名 (observe/decide/execute/assert/record)

    Returns:
        Decorator
    """

    def decorator(func: Callable[..., Awaitable[dict]]) -> Callable[..., Awaitable[dict]]:
        @functools.wraps(func)
        async def wrapper(state: dict[str, Any]) -> dict[str, Any]:
            task_id = state.get("task_id", "")
            log_node_event(task_id, node_name, "enter", token_count=0)
            start = time.perf_counter()
            result: dict[str, Any] = {}
            try:
                result = await func(state)
                if not isinstance(result, dict):
                    result = {}
            finally:
                duration_ms = int((time.perf_counter() - start) * 1000)
                token_count = result.get("_last_token_count", 0) if isinstance(result, dict) else 0
                log_node_event(task_id, node_name, "exit", duration_ms=duration_ms, token_count=token_count)
                if isinstance(result, dict):
                    result["_last_node_name"] = node_name
                    result["_last_node_duration_ms"] = duration_ms
            return result

        return wrapper

    return decorator


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


def _fast_assert(state: dict[str, Any]) -> dict[str, Any] | None:
    """B3.1: 快速断言路径 — 中间步骤的规则级判断。

    封装 assert_node Layer 0 的快判逻辑:
    - marker tasks → 直接返回结果 (B1.2 二次确认)
    - action error → fail
    - page_changed 中间步骤 → inconclusive

    Returns:
        dict (可入 state) 或 None (需走 LLM assert)
    """
    action_result = state.get("_last_action_result")
    tool_calls = state.get("_last_tool_calls", [])
    test_plan = state.get("test_plan", [])
    current_index = state.get("current_index", 0)
    current_test_case = test_plan[current_index] if current_index < len(test_plan) else None
    current_step_index = state.get("current_step", 1) - 1

    # Marker tasks with B1.2 secondary confirmation
    for call in tool_calls:
        name = call.get("name", "")
        if name == "mark_task_complete":
            state_before = state.get("state_before", {})
            state_after = state.get("state_after", {})
            ar = state.get("_last_action_result")
            url_before = ar.before_url if ar else ""
            url_after = ar.after_url if ar else ""
            page_really_changed = (url_before != url_after)
            if not page_really_changed and (state_before or state_after):
                cr = detect_changes(state_before, state_after)
                page_really_changed = cr.url_changed or cr.new_elements or cr.gone_elements or cr.modal_appeared
            reasoning = call.get("args", {}).get("reasoning", "")
            if page_really_changed:
                return {"_last_change_report": ChangeReport(), "_last_assertion": AssertionResult(status="pass", reasoning=reasoning)}
            else:
                return {"_last_change_report": ChangeReport(), "_last_assertion": AssertionResult(status="inconclusive",
                    reasoning=f"⚠️ 标记成功但页面无实质变化 (URL: {url_before} → {url_after})")}
        if name == "mark_task_failed":
            reasoning = call.get("args", {}).get("reasoning", "")
            return {"_last_change_report": ChangeReport(), "_last_assertion": AssertionResult(status="fail", reasoning=reasoning)}
        if name == "mark_task_skipped":
            reasoning = call.get("args", {}).get("reasoning", "")
            return {"_last_change_report": ChangeReport(), "_last_assertion": AssertionResult(status="pass", reasoning=reasoning)}

    # Action error → fail (Phase 2.0D: 也检查 status, 失败/超时/未找到)
    if action_result and (action_result.error or action_result.status in ("failure", "timeout", "not_found")):
        reason = action_result.error or f"action status={action_result.status}"
        # Phase 2.0D: 注入 long_term_memory (失败教训) 到 reasoning
        if action_result.long_term_memory:
            reason = f"{reason}\n💡 后续建议: {action_result.long_term_memory}"
        return {"_last_change_report": ChangeReport(), "_last_assertion": AssertionResult(status="fail", reasoning=reason)}

    # Intermediate step with page change → inconclusive
    is_final_step = current_test_case is not None and current_step_index >= len(current_test_case.steps) - 1
    if not is_final_step:
        if action_result and (action_result.page_changed or action_result.url_changed):
            return {"_last_change_report": ChangeReport(url_changed=action_result.url_changed),
                    "_last_assertion": AssertionResult(status="inconclusive", reasoning="中间步骤, 页面已变化")}

    return None  # 需要走 LLM assert


def should_skip_assert(state: dict[str, Any]) -> str:
    """B3.1: assert 条件边 — 决定是否跳过 LLM assert_node。

    返回:
        "skip_assert" — 用 _fast_assert 快判, 直接走 record
        "assert_node" — 需要 LLM 语义判断
    """
    fast = _fast_assert(state)
    if fast is not None:
        return "skip_assert"
    if state.get("_last_action_result") and state.get("_last_tool_calls"):
        # 有工具执行结果但快判不能决定 → 走 LLM
        return "assert_node"
    return "skip_assert"


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


@instrument_node("observe")
async def observe_node(state: dict[str, Any]) -> dict[str, Any]:
    """Extract page semantics and screenshot from the current page.

    - Calls extract_page_semantics() to get page info
    - Calls take_screenshot_compressed() for visual context (V2.0 A2: JPEG q=60)
    - Updates element map so tools can resolve #N / [N] references
    - Saves state_before for change detection after execute
    - Phase 2.0A Sprint 5: 注入 Failure Memory 告警
    """
    try:
        task_id = state.get("task_id")
        if task_id:
            set_current_task(task_id)
            set_task_config(state.get("task_config", {}))
        page = get_current_page()

        # Extract semantics
        current_step = state.get("current_step", 0)
        page_info = await extract_page_semantics(page, task_id=task_id, current_step=current_step)
        # Phase 2.0D: 截图-on-demand 混合策略
        # 默认 observe 不截图 (L2_OBSERVE_SCREENSHOT=0), LLM 显式调 screenshot_on_demand 才截
        # 旧行为 L2_OBSERVE_SCREENSHOT=1 保留 (向后兼容)
        observe_screenshot = os.getenv("L2_OBSERVE_SCREENSHOT", "0") == "1"
        if observe_screenshot:
            # V2.0 A2: 截图压缩 (env L2_SCREENSHOT_COMPRESSED=1 默认开)
            compress = os.getenv("L2_SCREENSHOT_COMPRESSED", "1") != "0"
            if compress:
                screenshot = await take_screenshot_compressed(page)
            else:
                screenshot = await take_screenshot(page)
        else:
            # 不截图 — LLM 显式 screenshot_on_demand 时由工具自身注入
            screenshot = ""

        # Update element map for tools to resolve #N / [N] references
        update_element_map(page_info.get("interactive_elements", []))

        # Take state snapshot (for change detector after execute)
        state_before = dict(page_info)  # shallow copy

        # Phase 2.0A Sprint 5: Failure Memory 注入
        recent_failures = state.get("recent_failures", [])
        if recent_failures:
            warning_lines = ["⚠️ 警戒区: 以下动作最近执行失败，请勿重复尝试:"]
            for f in recent_failures[-2:]:  # 最近 2 条
                target_str = f.get("target", "?")
                error_str = f.get("error", "未知错误")
                warning_lines.append(f"  - {f.get('action', '?')} [{target_str}]: {error_str}")
            warning_lines.append("规则: 禁止对同一元素重复执行失败动作超过 2 次。\n")
            warning_text = "\n".join(warning_lines)
            # 将告警注入到 page_info 中，_format_page_info 会展示它
            current_errors = page_info.get("error_messages", [])
            page_info["_failure_warnings"] = warning_text

        # =================================================================
        # B2.1: 脱轨纠正 — 连续无变化检测
        # B2.4: Loop Detection 移至 observe
        # =================================================================
        action_history = state.get("action_history", [])
        need_replan = state.get("need_replan", False)

        if action_history and len(action_history) >= 2:
            recent = action_history[-2:]
            # B2.1: 检查最近 2 步页面是否停滞（无 URL 变化、非互斥动作）
            urls = set(a.get("url", "") for a in recent if a.get("url"))
            fps = set(a.get("fingerprint", "") for a in recent if a.get("fingerprint"))
            names = [a.get("name", "") for a in recent]
            
            write_actions = {"click", "input_text", "select_dropdown", "press_key", "navigate", "scroll", "hover", "BATCH"}
            all_recent_are_write = all(name in write_actions for name in names)
            page_stable = len(urls) <= 1 and len(fps) <= 1

            if page_stable and all_recent_are_write and not need_replan:
                # 检查是否不同的 action 但页面无变化（脱轨，不同于 AAA/ABAB 死循环）
                need_replan = True
                corrective_text = (
                    f"[CORRECTIVE] 页面已连续 {len(action_history)} 步无实质变化，"
                    f"建议回到测试步骤描述检查前置条件是否满足，或重试 navigate 刷新页面。"
                )
                page_info["_corrective_warning"] = corrective_text

            # B2.4: AAA / ABAB 检测
            if len(action_history) >= 3:
                names3 = [a.get("name", "") for a in action_history[-3:]]
                if names3[-1] == names3[-2] == names3[-3] and names3[-1] in write_actions:
                    need_replan = True
                    page_info["_loop_detected"] = f"AAA (连续 3 次相同写动作: {names3[-1]})"
            if len(action_history) >= 4:
                names4 = [a.get("name", "") for a in action_history[-4:]]
                if names4[-1] == names4[-3] and names4[-2] == names4[-4] and names4[-1] != names4[-2] and names4[-1] in write_actions and names4[-2] in write_actions:
                    need_replan = True
                    page_info["_loop_detected"] = f"ABAB (4 步交替写动作: {names4[-1]}/{names4[-2]})"

        # B2.3 + 2.0D: Context 压缩 — 双阈值 (步数 + tokens) 触发 LLM 语义压缩
        # 向后兼容: L2_COMPACTION=0 时回退到物理截断
        budget = int(os.getenv("L2_TOKEN_BUDGET", "30000"))
        messages = list(state.get("messages", []))
        messages_to_remove = []
        compaction_summary: str | None = None
        if messages:
            from core.context_manager import (
                should_compact, compact_history, build_compact_summary_message,
                COMPACTION_ENABLED,
            )
            if COMPACTION_ENABLED and should_compact({**state, "messages": messages}):
                # Phase 2.0D: LLM 语义压缩 (compact_history 内部调 1 次 LLM, 不再二次调用)
                try:
                    messages_to_remove, compaction_summary = await compact_history({**state, "messages": messages})
                except Exception as e:
                    # 任何异常 → 物理截断兜底
                    messages_to_remove, compaction_summary = [], None

            if not messages_to_remove:
                # 回退: 原物理截断逻辑 (L2_COMPACTION=0 或 LLM 失败)
                total = count_tokens(messages)
                if total > budget:
                    from langchain_core.messages import RemoveMessage
                    head = messages[:1]
                    tail_count = 5
                    tail = messages[-tail_count:] if len(messages) > tail_count else []
                    middle = messages[1:-tail_count] if len(messages) > tail_count + 1 else []
                    to_remove = []
                    working_head = list(head)
                    working_middle = list(middle)
                    working_tail = list(tail)
                    while working_middle:
                        candidate = working_head + working_middle + working_tail
                        if count_tokens(candidate) <= budget:
                            break
                        m = working_middle.pop(0)
                        if hasattr(m, "id") and m.id:
                            to_remove.append(RemoveMessage(id=m.id))
                        elif m is not None:
                            import hashlib
                            fake_id = hashlib.md5(repr(m).encode()).hexdigest()
                            to_remove.append(RemoveMessage(id=fake_id))
                    messages_to_remove = to_remove

        # LangGraph 1.x: messages 字段不能为 None, 不压缩时不要放入此 key
        ret: dict[str, Any] = {
            "page_info": page_info,
            "screenshot": screenshot,
            "state_before": state_before,
            "state_after": {},
            "action_history": action_history,
            "need_replan": need_replan,
            "_compaction_summary": compaction_summary,  # Phase 2.0D: LLM 语义压缩摘要
        }
        if messages_to_remove:
            ret["messages"] = messages_to_remove
        return ret
    except Exception as e:
        # Never crash: return error state
        return {
            "page_info": {"url": "error", "title": "Error", "interactive_elements": [], "error_messages": [str(e)]},
            "screenshot": "",
            "state_before": {},
            "state_after": {},
        }


@instrument_node("decide")
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

        # B2 fix (2026-06-04 audit): 注入 compaction_summary (上下文压缩摘要)
        # 之前: _compaction_summary 存到 state 但从未注入 messages → LLM 看不到被压缩的历史
        # 现在: 拼到 system_prompt 顶部, 跟 session_summary 一样的注入方式
        compaction_summary = state.get("_compaction_summary")
        if compaction_summary:
            system_prompt = (
                f"<compaction_summary>\n{compaction_summary}\n</compaction_summary>\n\n"
                f"{system_prompt}"
            )

        current_step = state.get("current_step", 0)
        step_prompt = get_step_prompt(current_step, current_test_case)

        # Build messages for LLM
        messages = list(state.get("messages", []))  # copy

        # B2.2: 复用/替换 SystemMessage 而非每步重建
        if messages and isinstance(messages[0], SystemMessage):
            messages[0] = SystemMessage(content=system_prompt)
        else:
            messages.insert(0, SystemMessage(content=system_prompt))

        # Add current step info + page semantics
        page_info = state.get("page_info", {})
        page_summary = _format_page_info(page_info)

        # Phase 2.0A Sprint 1: Goal Reminder 任务持久化守卫
        total_steps = len(current_test_case.steps)
        goal_reminder = (
            f"════════════════════════════════════════════════════\n"
            f"🧭 CURRENT TEST GOAL\n"
            f"   用例ID: {current_test_case.id}\n"
            f"   标题: {current_test_case.title}\n"
            f"   描述: {current_test_case.description}\n"
            f"   当前步骤: {current_step + 1}/{total_steps}\n"
            f"✅ SUCCESS CRITERIA: {current_test_case.expected}\n"
            f"════════════════════════════════════════════════════\n"
        )

        # Phase 2.0A Sprint 6: Loop Detection — [SYSTEM INTERRUPT] Micro-Replan
        replan_interrupt = ""
        if state.get("need_replan"):
            replan_interrupt = (
                f"[SYSTEM INTERRUPT] 检测到动作死循环。\n"
                f"你已经对当前页面元素重复执行了相同动作，页面无任何变化。\n"
                f"指令: 立即停止当前尝试，改用以下策略之一:\n"
                f"  (a) 换用 keyboard 导航 (Tab + Enter)\n"
                f"  (b) 检查页面上是否有弹窗/错误提示被忽略\n"
                f"  (c) 如果以上都不行 → mark_task_failed(原因: 页面无响应)\n"
                f"=========================\n"
            )

        text_content = f"{goal_reminder}{replan_interrupt}{step_prompt}\n\n当前页面状态:\n{page_summary}"

        # V2.0 A2: 截图压缩 (env L2_SCREENSHOT_COMPRESSED=1 默认开, 节省 80% tokens)
        # 兼容旧行为: 传 "0" 关闭
        compress = os.getenv("L2_SCREENSHOT_COMPRESSED", "1") != "0"
        screenshot_base64 = state.get("screenshot")
        if screenshot_base64:
            # 注意: state.screenshot 已是 base64, 不再二次压缩
            # 压缩应在 observe_node 截图时就做 (后续优化点)
            # V2.0 fix (2026-06-04): MiMo v2.5 (Anthropic-compatible) 拒绝 OpenAI image_url 格式
            # 会返回 'connection was closed in the middle of operation'. 改用 Anthropic 原生格式.
            content = [
                {"type": "text", "text": text_content},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": screenshot_base64}},
            ]
        else:
            content = text_content

        messages.append(HumanMessage(content=content))

        # V2.0 D1 (2026-06-02): 估算本次 decide 调用的 token 数
        # count_messages_token() handles multimodal content + 中文 tokenize via tiktoken
        decide_token_count = count_tokens(messages)

        # Call LLM
        # Robust Retry Loop for API Rate Limits (429)
        import asyncio
        import logging
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = await llm_with_tools.ainvoke(messages)
                if os.getenv("L2_DEBUG_LLM") == "1":
                    try:
                        import sys
                        encoding = sys.stdout.encoding or "utf-8"
                        safe_content = str(response.content).encode(encoding, errors="replace").decode(encoding)
                        print(f"  [Decide] LLM response: {safe_content}", flush=True)
                        if response.tool_calls:
                            safe_calls = str(response.tool_calls).encode(encoding, errors="replace").decode(encoding)
                            print(f"  [Decide] Tool calls: {safe_calls}", flush=True)
                    except Exception:
                        pass
                return {"messages": [response], "_last_token_count": decide_token_count}
            except Exception as e:
                logging.getLogger(__name__).error(
                    f"[decide attempt={attempt}] {type(e).__name__}: {e}", exc_info=True
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    return {"messages": [AIMessage(content=f"LLM调用失败: {str(e)}")], "_last_token_count": decide_token_count}

    except Exception as e:
        # Never crash: return error as AI message
        return {"messages": [AIMessage(content=f"LLM调用失败: {str(e)}")]}


@instrument_node("execute")
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
        set_task_config(state.get("task_config", {}))

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

    # B1.4: Register current step context for tools to read
    test_plan = state.get("test_plan", [])
    current_index = state.get("current_index", 0)
    current_step_index = state.get("current_step", 0)
    if current_index < len(test_plan):
        current_test_case = test_plan[current_index]
        steps = current_test_case.steps
        if current_step_index < len(steps):
            from agents.ui.tools import set_current_step_text
            set_current_step_text(steps[current_step_index])

    # Execute all tools sequentially
    results = []
    tool_messages = []
    any_failure = False
    last_action_result = None
    recent_failures = list(state.get("recent_failures", []))
    for tool_call in tool_calls:
        tool_name = tool_call.get("name", "")
        tool_args = tool_call.get("args", {})
        tool_call_id = tool_call.get("id", "")

        try:
            if tool_name in tools_by_name:
                tool_fn = tools_by_name[tool_name]
                raw_result = await tool_fn.ainvoke(tool_args)
                if isinstance(raw_result, dict):
                    action_result = ActionResult(**{k: v for k, v in raw_result.items() if k in ActionResult.model_fields})
                    last_action_result = action_result
                    display_text = f"{'✅' if action_result.success else '❌'} {action_result.action}"
                    if action_result.target is not None:
                        display_text += f" [{action_result.target}]"
                    if action_result.error:
                        display_text += f" - {action_result.error}"
                    elif action_result.page_changed:
                        display_text += " - 页面已变化"
                    elif action_result.url_changed:
                        display_text += " - URL 已变化"
                    else:
                        display_text += " - 执行完成"

                    # Phase 2.0A Sprint 5: Failure Memory
                    if not action_result.success:
                        recent_failures.append({
                            "action": action_result.action,
                            "target": action_result.target,
                            "error": action_result.error,
                            "url": action_result.before_url,
                        })
                        if len(recent_failures) > 3:
                            recent_failures.pop(0)
                    else:
                        # 成功时不主动清空，让 deque 自动淘汰
                        pass
                else:
                    display_text = str(raw_result)
            else:
                display_text = f"未知工具: {tool_name}"
        except Exception as e:
            display_text = f"执行失败: {str(e)}"

        results.append(display_text)
        tool_messages.append(ToolMessage(content=display_text, tool_call_id=tool_call_id, name=tool_name))

        # Phase 2.0A Sprint 2: 用结构化数据判断失败
        if last_action_result and not last_action_result.success:
            any_failure = True
            break  # Stop executing further tools if one fails
        elif "执行失败" in display_text or "未知工具" in display_text:
            any_failure = True
            break

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

    # Phase 2.0A Sprint 2: 将结构化 ActionResult 传给 assert_node
    action_result_text = "\n".join(results)

    return {
        "messages": tool_messages,
        "state_after": state_after,
        "screenshot_after": screenshot_after,
        "current_step": current_step + 1,
        "_last_tool_result": action_result_text,
        "_last_action_result": last_action_result,
        "_last_action_result_text": action_result_text,
        "_last_tool_calls": tool_calls, # Pass the batch for assertion
        "consecutive_failures": consecutive_failures,
        "recent_failures": recent_failures, # Phase 2.0A Sprint 5: 失败记忆
    }


@instrument_node("assert")
async def assert_node(state: dict[str, Any]) -> dict[str, Any]:
    """Assert the action result using hierarchical layers:

    Phase 2.0A Sprint 2: 优先复用 ActionResult.page_changed，不再单独调用 change_detector.py。

    Layer 0: Rule-based quick judgment
      - Explicit task markers (mark_task_complete/failed/skipped)
      - ActionResult 层面的快速判断
    Layer 1: Change detection (facts) — fallthrough if ActionEvidence insufficient
    Layer 2: LLM semantic judgment — pass/fail/inconclusive
    """
    try:
        # B3.1: 复用 _fast_assert 作为 Layer 0 快速路径 (双重安全)
        fast_result = _fast_assert(state)
        if fast_result is not None:
            return fast_result

        action_result: ActionResult | None = state.get("_last_action_result")
        tool_calls = state.get("_last_tool_calls", [])

        # Get test case context
        test_plan = state.get("test_plan", [])
        current_index = state.get("current_index", 0)
        current_test_case = test_plan[current_index] if current_index < len(test_plan) else None
        expected = current_test_case.expected if current_test_case else "无预期结果"

        current_step_index = state.get("current_step", 1) - 1
        if current_test_case and current_step_index < len(current_test_case.steps):
            current_step_text = current_test_case.steps[current_step_index]
        else:
            current_step_text = "验证最终预期结果"

        # =================================================================
        # Layer 0: Rule-based quick judgment
        # =================================================================

        # Layer 0.5: Explicit task markers with B1.2 secondary confirmation
        for call in tool_calls:
            name = call.get("name", "")
            if name == "mark_task_complete":
                reasoning = call.get("args", {}).get("reasoning", "LLM 主动标记任务成功")
                # B1.2: 二次确认 — 检查页面是否有实质变化
                state_before = state.get("state_before", {})
                state_after = state.get("state_after", {})
                action_result = state.get("_last_action_result")
                url_before = action_result.before_url if action_result else ""
                url_after = action_result.after_url if action_result else ""
                page_really_changed = (url_before != url_after)
                if not page_really_changed and (state_before or state_after):
                    change_report = detect_changes(state_before, state_after)
                    page_really_changed = (
                        change_report.url_changed
                        or change_report.new_elements
                        or change_report.gone_elements
                        or change_report.modal_appeared
                    )
                if page_really_changed:
                    return {
                        "_last_change_report": ChangeReport(),
                        "_last_assertion": AssertionResult(status="pass", reasoning=reasoning),
                        "consecutive_failures": 0,
                    }
                else:
                    downgrade = (
                        f"⚠️ LLM 标记任务成功但页面无实质变化 (URL: {url_before} → {url_after}), "
                        f"降级为 inconclusive 请人工确认。LLM 理由: {reasoning}"
                    )
                    return {
                        "_last_change_report": ChangeReport(url_changed=False),
                        "_last_assertion": AssertionResult(status="inconclusive", reasoning=downgrade),
                        "consecutive_failures": 0,
                    }
            elif name == "mark_task_failed":
                reasoning = call.get("args", {}).get("reasoning", "LLM 主动标记任务失败")
                return {
                    "_last_change_report": ChangeReport(),
                    "_last_assertion": AssertionResult(status="fail", reasoning=reasoning),
                    "consecutive_failures": state.get("consecutive_failures", 0) + 1,
                }
            elif name == "mark_task_skipped":
                reasoning = call.get("args", {}).get("reasoning", "LLM 主动标记任务跳过")
                return {
                    "_last_change_report": ChangeReport(),
                    "_last_assertion": AssertionResult(status="pass", reasoning=reasoning),
                    "consecutive_failures": 0,
                }

        # Layer 0.6: ActionResult-based quick judgment
        if action_result:
            if action_result.error:
                # 工具执行报错 → 大概率失败
                reason = f"动作执行报错: {action_result.error}"
                if action_result.long_term_memory:
                    reason = f"{reason} | 💡 后续建议: {action_result.long_term_memory}"
                return {
                    "_last_change_report": ChangeReport(),
                    "_last_assertion": AssertionResult(status="fail", reasoning=reason),
                    "consecutive_failures": state.get("consecutive_failures", 0) + 1,
                }

            # Phase 2.0D: status-based fast fail (无 error 也有 status 失败)
            if action_result.status in ("failure", "timeout", "not_found"):
                reason = f"动作状态={action_result.status}"
                if action_result.error:
                    reason = f"{reason} ({action_result.error})"
                if action_result.long_term_memory:
                    reason = f"{reason} | 💡 后续建议: {action_result.long_term_memory}"
                return {
                    "_last_change_report": ChangeReport(),
                    "_last_assertion": AssertionResult(status="fail", reasoning=reason),
                    "consecutive_failures": state.get("consecutive_failures", 0) + 1,
                }

            if action_result.page_changed or action_result.url_changed:
                # 页面有明确变化 → 大概率成功（中间步骤）
                if current_step_index < len(current_test_case.steps) - 1 if current_test_case else False:
                    return {
                        "_last_change_report": ChangeReport(url_changed=action_result.url_changed,
                                                             url_before=action_result.before_url,
                                                             url_after=action_result.after_url),
                        "_last_assertion": AssertionResult(status="inconclusive",
                                                           reasoning=f"页面已变化 (变: {'URL' if action_result.url_changed else 'DOM'}), 继续下一步"),
                        "consecutive_failures": 0,
                    }

        # =================================================================
        # Layer 1: Change detection (facts) — fallthrough for final step or complex cases
        # =================================================================
        state_before = state.get("state_before", {})
        state_after = state.get("state_after", {})
        change_report = detect_changes(state_before, state_after)

        # Rule 1: JS errors or visible error messages → FAIL immediately
        if change_report.js_errors or change_report.error_messages_visible:
            details_parts = []
            if change_report.js_errors:
                details_parts.append(f"JS错误: {change_report.js_errors}")
            if change_report.error_messages_visible:
                details_parts.append(f"页面错误: {change_report.error_messages_visible}")
            details = "; ".join(details_parts)
            return {
                "_last_change_report": change_report,
                "_last_assertion": AssertionResult(status="fail", reasoning=f"规则断言: 检测到错误 - {details}"),
                "consecutive_failures": state.get("consecutive_failures", 0) + 1,
            }

        # Rule 2: Network errors → FAIL immediately
        if change_report.network_errors:
            return {
                "_last_change_report": change_report,
                "_last_assertion": AssertionResult(status="fail", reasoning=f"规则断言: 网络错误 - {change_report.network_errors}"),
                "consecutive_failures": state.get("consecutive_failures", 0) + 1,
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
            if not has_significant_changes and not (action_result and (action_result.page_changed or action_result.url_changed)):
                return {
                    "_last_change_report": change_report,
                    "_last_assertion": AssertionResult(status="inconclusive", reasoning="规则断言: 中间步骤，页面无明显变化"),
                    "consecutive_failures": 0,
                }

        # =================================================================
        # Layer 2: LLM semantic judgment (fallthrough — the big hammer)
        # =================================================================

        # B1.3: 获取 filled_value 传给断言 prompt
        filled_value = action_result.filled_value if action_result else ""

        # Phase 2.0D: 把 ActionResult 的结构化字段 (extracted_content / long_term_memory) 注入 prompt
        action_context_lines: list[str] = []
        if action_result and action_result.extracted_content:
            action_context_lines.append(f"[工具输出] {action_result.extracted_content}")
        if action_result and action_result.long_term_memory and not action_result.success:
            action_context_lines.append(f"[系统建议] {action_result.long_term_memory}")
        if action_result and action_result.candidates:
            cands_text = " | ".join(
                f"{{text: {c.get('text','')[:30]}, role: {c.get('role','?')}, id: {c.get('id','?')}}}"
                for c in action_result.candidates[:3]
            )
            action_context_lines.append(f"[失败备选元素] {cands_text}")
        action_context = "\n".join(action_context_lines)

        assertion_prompt = get_assertion_prompt(
            tool_calls=tool_calls,
            change_report=change_report,
            expected=expected,
            current_step_text=current_step_text,
            page_info=state_after,
            filled_value=filled_value,
        )
        if action_context:
            assertion_prompt = f"{action_context}\n\n---\n{assertion_prompt}"

        screenshot_after = state.get("screenshot_after")
        if screenshot_after:
            content_with_image = [
                {"type": "text", "text": assertion_prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_after}"}}
            ]
            full_prompt = assertion_prompt
            multimodal = True
        else:
            full_prompt = assertion_prompt
            multimodal = False

        if multimodal:
            assert_token_count = count_tokens(
                [SystemMessage(content="你是 UI 自动化测试断言专家. 输出 JSON: {status, reasoning}"),
                 HumanMessage(content=content_with_image)]
            )
        else:
            assert_token_count = count_tokens([HumanMessage(content=full_prompt)])

        result = await safe_structured_invoke(full_prompt, AssertionResult, model_type="sonnet")

        if result is not None and isinstance(result, AssertionResult):
            status = result.status
            final_reasoning = result.reasoning
        else:
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
                    parts = [item.get("text", "") if isinstance(item, dict) else str(item) for item in raw_text]
                    raw_text = "\n".join(parts)
                fallback = _fallback_assertion(raw_text, ValueError("safe_structured_invoke returned None"))
            except Exception as e2:
                fallback = _fallback_assertion(f"LLM 调用失败: {e2}", e2)
            status = fallback.status
            final_reasoning = fallback.reasoning

        if status not in ("pass", "fail", "inconclusive"):
            status = "inconclusive"

        assertion = AssertionResult(status=status, reasoning=final_reasoning)

        consecutive_failures = state.get("consecutive_failures", 0)
        if status == "fail":
            consecutive_failures += 1
        else:
            consecutive_failures = 0

        return {
            "_last_change_report": change_report,
            "_last_assertion": assertion,
            "consecutive_failures": consecutive_failures,
            "_last_token_count": assert_token_count,
        }
    except Exception as e:
        return {
            "_last_change_report": ChangeReport(),
            "_last_assertion": AssertionResult(status="inconclusive", reasoning=f"断言异常: {str(e)}"),
            "consecutive_failures": state.get("consecutive_failures", 0),
        }


@instrument_node("record")
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
    # BUG-01 fix (2026-06-04 audit): should_skip_assert 计算了 _fast_assert 但 edge function
    # 无法写 state, "skip_assert" 路径下 _last_assertion 是上一步的 stale 值
    # 兜底: record_node 入口处如果 _last_assertion 缺失, 重新跑 _fast_assert 补救
    # 写到 state (本步 step_result 用) + 通过 result 透传 (下一步 record 也能拿到)
    _fast_recover_result: dict[str, Any] = {}
    if not state.get("_last_assertion"):
        fast_recover = _fast_assert(state)
        if fast_recover:
            for k, v in fast_recover.items():
                state[k] = v
            _fast_recover_result = fast_recover
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
        # Phase 2.0A Sprint 6: 记录动作历史用于 Loop Detection
        action_name = ""
        target_url = ""
        if len(calls) == 1:
            call = calls[0]
            action_name = call.get("name", "")
        elif len(calls) > 1:
            action_name = "BATCH"
        # 从 state 获取当前 URL 和 DOM 指纹
        page_info_for_loop = state.get("page_info", {})
        target_url = page_info_for_loop.get("url", "")
        fingerprint = ""
        try:
            page = get_current_page()
            from agents.ui.tools import _get_dom_fingerprint
            fingerprint = await _get_dom_fingerprint(page)
        except Exception:
            pass
        action_history = list(state.get("action_history", []))
        action_history.append({
            "name": action_name,
            "url": target_url,
            "fingerprint": fingerprint,
        })
        if len(action_history) > 6:
            action_history = action_history[-6:]
        need_replan = state.get("need_replan", False)
        if len(calls) > 1:
            action_type = "BATCH"
            action_target = "Multiple"
            action_args = {"calls": calls}
        else:
            tool_call = calls[0]
            action_type = tool_call.get("name", "")
            action_target = str(tool_call.get("args", {}).get("target", ""))
            action_args = tool_call.get("args", {})

        # V2.0 C5 (2026-06-02): 捕获 reasoning_chain
        # 从 decide AIMessage (last_ai_msg) 抽取 thinking 块, 从 _last_assertion 抽取 reasoning
        # 形成"决策 → 断言"的完整思考链, ReportBuilder L2 卡片折叠展示
        reasoning_chain: list[str] = []
        think_text = last_ai_msg.content if isinstance(last_ai_msg.content, str) else ""
        if not think_text and isinstance(last_ai_msg.content, list):
            # list 格式: [{"type": "thinking", "thinking": "..."}, ...]
            parts = []
            for item in last_ai_msg.content:
                if isinstance(item, dict):
                    if item.get("type") == "thinking":
                        parts.append(item.get("thinking", ""))
                    elif item.get("type") == "text":
                        parts.append(item.get("text", ""))
            think_text = "\n".join(parts).strip()
        if think_text:
            reasoning_chain.append(f"[Decide] {think_text[:300]}{'...' if len(think_text) > 300 else ''}")

        last_assertion = state.get("_last_assertion")
        if last_assertion and last_assertion.reasoning:
            reasoning_chain.append(f"[Assert] {last_assertion.reasoning[:300]}{'...' if len(last_assertion.reasoning) > 300 else ''}")

        # V2.0 D1+D2 (2026-06-02): 记录本步 token 用量 + 总耗时, ReportBuilder 折线用
        # _last_token_count 来自上一步 decide_node 调用 (decide 是 LLM 入口, 主要 token 消耗)
        # duration_ms 来自 record_node 自身 (在 @instrument_node wrapper 里, 但我们在 step result 里记一个聚合值)
        step_token_count = state.get("_last_token_count", 0)
        # 累计耗时: 累加 4 个节点 (observe→decide→execute→assert→record) 的 _last_node_duration_ms
        # 简化: 取当前 step 内最大的节点耗时作为 step duration (粗略, 4 节点串行实际接近求和)
        # 更准确做法: 用 _step_token_log 累加. 这里用 _last_node_duration_ms 作单点参考.
        step_duration_ms = state.get("_last_node_duration_ms", 0)

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
            reasoning_chain=reasoning_chain,
            token_count=step_token_count,
            duration_ms=step_duration_ms,
        )
        collected_steps = [step_result]

        # V2.0 D3 (2026-06-02): 累积到 _step_token_log (operator.add reducer 自动 append)
        # ReportBuilder 用这个画 token 折线
        step_log_entry = {
            "step_index": state.get("current_step", 0) - 1,
            "token_count": step_token_count,
            "duration_ms": step_duration_ms,
            "assertion_status": state["_last_assertion"].status if state.get("_last_assertion") else "none",
        }

    result: dict[str, Any] = {}
    if collected_steps:
        result["_collected_steps"] = collected_steps
        # 只有当 has_tool_call 时才有 step_log_entry
        result["_step_token_log"] = [step_log_entry]

    # B2.3 + B2.4: context 压缩和 loop detection 已移至 observe_node
    # record_node 只保留 action_history 追加
    if has_tool_call:
        result["action_history"] = action_history
        # need_replan 由 observe_node 管理，record 不再覆盖

    # BUG-01 fix: 把 _fast_assert 恢复值透传给下一步 record (state 已被本步消费, result 才能延续)
    if _fast_recover_result:
        result.update(_fast_recover_result)

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
    # B3.1: assert 条件边 — execute 后判断是否需要走 LLM assert
    graph.add_conditional_edges(
        "execute",
        should_skip_assert,
        {
            "assert_node": "assert",
            "skip_assert": "record",
        },
    )
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