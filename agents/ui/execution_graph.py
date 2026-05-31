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
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from core.change_detector import detect_changes
from core.interfaces import AssertionResult, ChangeReport, StepResult, TestCase, TestState
from core.llm_client import get_llm_client
from core.page_semantic import extract_page_semantics, take_screenshot

from agents.ui.prompts import _format_page_info, get_assertion_prompt, get_execution_system_prompt, get_step_prompt
from agents.ui.tools import get_current_page, set_current_task, tools_by_name, tools, update_element_map


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
    - Calls take_screenshot() for visual context
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
        system_prompt = get_execution_system_prompt(current_test_case, task_config)
        step_prompt = get_step_prompt(state.get("current_step", 0), current_test_case)

        # Build messages for LLM
        messages = list(state.get("messages", []))  # copy

        # Add/replace system message at the start
        messages.insert(0, SystemMessage(content=system_prompt))

        # Add current step info + page semantics
        page_info = state.get("page_info", {})
        page_summary = _format_page_info(page_info)
        text_content = f"{step_prompt}\n\n当前页面状态:\n{page_summary}"
        
        screenshot_base64 = state.get("screenshot")
        if screenshot_base64:
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
    """
    messages = state.get("messages", [])
    current_step = state.get("current_step", 0)
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
        
        if "执行失败" in result_text or "未知工具" in result_text:
            break # Stop executing further tools if one fails

    # Take post-action snapshot for change detection
    state_after = {}
    screenshot_after = ""
    try:
        page = get_current_page()
        state_after = await extract_page_semantics(page)
        from core.page_semantic import take_screenshot
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
        # =================================================================

        llm = get_llm_client("sonnet")

        assertion_prompt = get_assertion_prompt(
            tool_calls=tool_calls,
            change_report=change_report,
            expected=expected,
            current_step_text=current_step_text,
            page_info=state_after,
        )

        screenshot_after = state.get("screenshot_after")
        if screenshot_after:
            content = [
                {"type": "text", "text": assertion_prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_after}"}}
            ]
        else:
            content = assertion_prompt

        # Robust Retry Loop for API Rate Limits (429)
        import asyncio
        max_retries = 3
        response = None
        sys_prompt = "You are a QA testing assistant. Evaluate the test result and return status/reasoning as JSON."
        for attempt in range(max_retries):
            try:
                response = await llm.ainvoke([
                    SystemMessage(content=sys_prompt),
                    HumanMessage(content=content)
                ])
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise e

        # Parse assertion result from LLM response
        reasoning = response.content if hasattr(response, "content") else str(response)
        if isinstance(reasoning, list):
            text_parts = []
            for item in reasoning:
                if isinstance(item, str):
                    text_parts.append(item)
                elif isinstance(item, dict):
                    if item.get("type") == "thinking":
                        text_parts.append(item.get("thinking", ""))
                    elif item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                    elif "text" in item:
                        text_parts.append(item["text"])
            reasoning = "\n".join(text_parts).strip()
        elif not isinstance(reasoning, str):
            reasoning = str(reasoning)

        import json
        import re
        
        status = "inconclusive"
        final_reasoning = reasoning
        
        # Try to extract json block if wrapped in markdown
        thinking_str = ""
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', reasoning, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
            thinking_str = reasoning[:json_match.start()].strip()
        else:
            # Fallback: extract the first {...} block
            fallback_match = re.search(r'(\{.*?\})', reasoning, re.DOTALL)
            json_str = fallback_match.group(1) if fallback_match else reasoning
            thinking_str = reasoning[:fallback_match.start()].strip() if fallback_match else ""
        
        try:
            import ast
            try:
                parsed = json.loads(json_str.strip())
            except json.JSONDecodeError:
                parsed = ast.literal_eval(json_str.strip())
                
            if isinstance(parsed, dict):
                status_str = parsed.get("status", "").upper()
                if status_str in ["PASS", "FAIL", "INCONCLUSIVE"]:
                    status = status_str.lower()
                final_reasoning = parsed.get("reasoning", str(parsed))
                if thinking_str:
                    final_reasoning = f"{thinking_str}\n\n结论: {final_reasoning}"
        except Exception as e:
            print(f"[HierarchicalAssert] LLM JSON parse failed: {e}. Raw: {reasoning}")
            status = "inconclusive"
            final_reasoning = "未能解析评估结果 (非 JSON 格式)"

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

    Also does context management: trim messages if > 10 to keep context manageable.
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

    # Context management: trim messages if conversation grows too long
    messages_to_remove = []
    if len(messages) > 10:
        middle_messages = messages[1:-10]
        for m in middle_messages:
            if hasattr(m, "id") and m.id:
                messages_to_remove.append(m)

    result: dict[str, Any] = {}
    if collected_steps:
        result["_collected_steps"] = collected_steps
    if messages_to_remove:
        result["messages"] = [RemoveMessage(id=m.id) for m in messages_to_remove]

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