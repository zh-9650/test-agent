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

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from core.change_detector import detect_changes
from core.interfaces import AssertionResult, ChangeReport, StepResult, TestCase, TestState
from core.llm_client import get_llm_client
from core.page_semantic import extract_page_semantics, take_screenshot

from agents.ui.prompts import _format_page_info, get_assertion_prompt, get_execution_system_prompt, get_step_prompt
from agents.ui.tools import get_current_page, tools_by_name, ui_tools, update_element_map


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
            if extract_tool_calls_from_message(msg):
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
        llm_with_tools = llm.bind_tools(ui_tools)

        # Get current test case
        test_plan = state.get("test_plan", [])
        current_index = state.get("current_index", 0)
        if current_index >= len(test_plan):
            # No more test cases — should not happen in this subgraph
            return {"messages": [AIMessage(content="所有测试用例已完成。")]}

        current_test_case = test_plan[current_index]

        # Build prompts
        system_prompt = get_execution_system_prompt(current_test_case, state.get("task_config"))
        step_prompt = get_step_prompt(state.get("current_step", 0), current_test_case)

        # Build messages for LLM
        messages = list(state.get("messages", []))  # copy

        # Add/replace system message at the start
        messages.insert(0, SystemMessage(content=system_prompt))

        # Add current step info + page semantics
        page_info = state.get("page_info", {})
        page_summary = _format_page_info(page_info)
        messages.append(HumanMessage(content=f"{step_prompt}\n\n当前页面状态:\n{page_summary}"))

        # Call LLM
        response = await llm_with_tools.ainvoke(messages)

        return {
            "messages": [response],  # add_messages reducer appends
        }
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

    tool_call = tool_calls[0]  # Phase 1: one tool call per step
    tool_name = tool_call["name"]
    tool_args = tool_call["args"]

    # Execute the tool
    result_text = ""
    try:
        if tool_name in tools_by_name:
            tool_fn = tools_by_name[tool_name]
            result_text = await tool_fn.ainvoke(tool_args)
        else:
            result_text = f"未知工具: {tool_name}"
    except Exception as e:
        result_text = f"执行失败: {str(e)}"

    # Take post-action snapshot for change detection
    state_after = {}
    try:
        page = get_current_page()
        state_after = await extract_page_semantics(page)
    except Exception:
        # If we can't get post-action state, use empty dict
        state_after = {}

    return {
        "state_after": state_after,
        "current_step": current_step + 1,
        "_last_tool_result": result_text,
    }


async def assert_node(state: dict[str, Any]) -> dict[str, Any]:
    """Assert the action result using dual-layer: change detector + LLM judgment.

    Layer 1: Change detection (facts) — detect_changes(state_before, state_after)
    Layer 2: LLM semantic judgment — pass/fail/inconclusive based on expected result
    """
    try:
        # Layer 1: Change detection (facts)
        state_before = state.get("state_before", {})
        state_after = state.get("state_after", {})
        change_report = detect_changes(state_before, state_after)

        # Layer 2: LLM semantic judgment
        llm = get_llm_client("sonnet")

        test_plan = state.get("test_plan", [])
        current_index = state.get("current_index", 0)
        current_test_case = test_plan[current_index] if current_index < len(test_plan) else None

        # Find the tool_call from the last AIMessage
        messages = state.get("messages", [])
        # Find the tool_call from the last AIMessage
        messages = state.get("messages", [])
        tool_call = None
        from core.llm_client import extract_tool_calls_from_message
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                calls = extract_tool_calls_from_message(msg)
                if calls:
                    tool_call = calls[0]
                    break

        expected = current_test_case.expected if current_test_case else "无预期结果"

        assertion_prompt = get_assertion_prompt(
            tool_call=tool_call,
            change_report=change_report,
            expected=expected,
        )

        response = await llm.ainvoke([HumanMessage(content=assertion_prompt)])

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

        import re
        upper_reasoning = reasoning.upper()
        
        # Find the last occurrence of PASS/FAIL/INCONCLUSIVE:
        matches = list(re.finditer(r'(PASS|FAIL|INCONCLUSIVE)\s*:\s*(.*)', upper_reasoning))
        if matches:
            last_match = matches[-1]
            status_str = last_match.group(1)
            
            # Extract the actual Chinese/English reason from the original text
            # by matching the same offset
            start_idx = last_match.start(2)
            short_reasoning = reasoning[start_idx:].strip()
            
            if status_str == "PASS":
                status = "pass"
            elif status_str == "FAIL":
                status = "fail"
            else:
                status = "inconclusive"
                
            reasoning = short_reasoning
        else:
            # Fallback
            if "PASS" in upper_reasoning or "通过" in reasoning:
                status = "pass"
            elif "FAIL" in upper_reasoning or "失败" in reasoning:
                status = "fail"
            else:
                status = "inconclusive"

        assertion = AssertionResult(status=status, reasoning=reasoning)

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
        tool_call = calls[0]
        step_result = StepResult(
            step_index=state.get("current_step", 0) - 1,  # execute already incremented
            action_type=tool_call.get("name", ""),
            action_target=str(tool_call.get("args", {}).get("target", "")),
            action_args=tool_call.get("args", {}),
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