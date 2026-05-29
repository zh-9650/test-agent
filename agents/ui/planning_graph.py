"""agents/ui/planning_graph.py — Planning subgraph for UI test generation.

Builds a LangGraph subgraph that explores the target web application and generates
a structured test plan (test cases + setups) using the LLM.

Flow:
    START → explore_observe → explore_decide → (has tool_call?) → explore_execute → explore_observe (loop)
                                        ↓ no tool_call / safety valves
                                      generate_plan → END

Safety valves: max explored pages (MAX_EXPLORE_PAGES), max explore time (MAX_EXPLORE_MINUTES).
Both configurable via environment variables.
"""

from __future__ import annotations

import os
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from core.interfaces import Setup, TestCase, TestState, create_test_plan
from core.llm_client import get_llm_client
from core.page_semantic import extract_page_semantics, take_screenshot

from agents.ui.prompts import _format_page_info, get_exploration_system_prompt, get_plan_generation_prompt
from agents.ui.tools import get_current_page, tools_by_name, ui_tools, update_element_map


# =============================================================================
# Conditional Edge Function
# =============================================================================


def should_continue_exploring(state: dict[str, Any]) -> str:
    """After explore_decide: should we keep exploring or generate the plan?

    Three conditions to stop exploring:
    1. explored_urls >= MAX_EXPLORE_PAGES (safety valve)
    2. elapsed time >= MAX_EXPLORE_MINUTES (safety valve)
    3. LLM has no tool_calls (exploration naturally complete)
    """
    max_pages = int(os.getenv("MAX_EXPLORE_PAGES", "20"))
    max_minutes = int(os.getenv("MAX_EXPLORE_MINUTES", "5"))

    task_config = state.get("task_config", {})
    explored_urls = task_config.get("_explored_urls", [])
    start_time = task_config.get("_explore_start_time", time.time())

    # Safety valve 1: max pages
    if len(explored_urls) >= max_pages:
        return "generate"

    # Safety valve 2: max time
    elapsed = time.time() - start_time
    if elapsed >= max_minutes * 60:
        return "generate"

    # Check if LLM wants to stop exploring (no tool_calls)
    messages = state.get("messages", [])
    if messages:
        last_message = messages[-1]
        from core.llm_client import extract_tool_calls_from_message
        tool_calls = extract_tool_calls_from_message(last_message)
        if not tool_calls:
            return "generate"

    return "explore"


# =============================================================================
# Node Implementations
# =============================================================================


async def explore_observe_node(state: dict[str, Any]) -> dict[str, Any]:
    """Observe the current page during exploration.

    - Extracts page semantics and screenshot
    - Updates element map for tool resolution
    - Tracks explored URLs in task_config
    """
    try:
        page = get_current_page()

        # Extract semantics
        page_info = await extract_page_semantics(page)
        screenshot = await take_screenshot(page)

        # Update element map for tools to resolve #N references
        update_element_map(page_info.get("interactive_elements", []))

        # Track explored URLs in task_config (since TestState may not allow arbitrary keys)
        task_config = dict(state.get("task_config", {}))
        explored_urls = list(task_config.get("_explored_urls", []))
        current_url = page_info.get("url", "")
        if current_url and current_url not in explored_urls:
            explored_urls.append(current_url)

        task_config["_explored_urls"] = explored_urls
        # Preserve start time if already set, otherwise set it now
        if "_explore_start_time" not in task_config:
            task_config["_explore_start_time"] = time.time()

        return {
            "page_info": page_info,
            "screenshot": screenshot,
            "task_config": task_config,
        }
    except Exception as e:
        # Never crash: return error state
        task_config = dict(state.get("task_config", {}))
        explored_urls = list(task_config.get("_explored_urls", []))

        error_page_info = {
            "url": "error",
            "title": "Error",
            "interactive_elements": [],
            "error_messages": [str(e)],
        }

        return {
            "page_info": error_page_info,
            "screenshot": "",
            "task_config": task_config,
        }


async def explore_decide_node(state: dict[str, Any]) -> dict[str, Any]:
    """LLM decides next exploration action based on current page.

    - Builds system prompt + page summary + explored URLs context
    - Calls LLM with UI tools bound
    - Returns LLM response as new message
    """
    try:
        llm = get_llm_client("default")  # qwen3.7-max for planning
        exploration_tools = [t for t in ui_tools if t.name != "navigate"]
        llm_with_tools = llm.bind_tools(exploration_tools)

        task_config = state.get("task_config", {})
        explored_urls = task_config.get("_explored_urls", [])
        accounts = task_config.get("accounts", [])

        # Build prompts
        system_prompt = get_exploration_system_prompt(accounts, task_config)
        page_summary = _format_page_info(state.get("page_info", {}))

        credentials_ctx = ""
        if accounts:
            credentials_ctx = "\n### 可用的测试账号与凭据 (如果遇到登录页面，请使用这些账号进行输入并登录，以进入系统内部探索):\n" + "\n".join(
                f"- 角色: {a.get('role', 'N/A')}, 用户名: {a.get('username', 'N/A')}, 密码: {a.get('password', 'N/A')}"
                for a in accounts
            )

        human_msg = f"""已探索 {len(explored_urls)} 个页面。
已探索的URL: {chr(10).join(explored_urls[:20]) if explored_urls else '尚未探索'}
{credentials_ctx}

当前页面:
{page_summary}

请继续探索目标系统，或者如果你认为已经收集了足够的信息来生成测试计划，就不要调用任何工具。"""

        messages = list(state.get("messages", []))
        messages.insert(0, SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=human_msg))
        response = await llm_with_tools.ainvoke(messages)

        return {"messages": [response]}
    except Exception as e:
        # Never crash: return error as AI message
        return {"messages": [AIMessage(content=f"LLM调用失败: {str(e)}")]}


async def explore_execute_node(state: dict[str, Any]) -> dict[str, Any]:
    """Execute the exploration tool call from the LLM's decide response.

    - Gets the last AI message with tool_calls
    - Dispatches to the matching tool function
    - Returns empty dict (tool execution modifies the page, next observe will capture changes)
    """
    messages = state.get("messages", [])

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

    # --- Navigate Firewall ---
    tool_call_id = tool_call.get("id", "")
    if tool_name == "navigate":
        target_url = tool_args.get("url", "")
        task_config = state.get("task_config", {})
        explored = task_config.get("_explored_urls", [])
        page_info = state.get("page_info", {})
        elements = page_info.get("interactive_elements", [])
        base_url = task_config.get("target_url", "")
        prd = task_config.get("prd", "")
        
        is_safe = False
        if target_url == base_url or target_url in explored:
            is_safe = True
        elif prd and target_url in prd:
            is_safe = True
        else:
            for el in elements:
                if el.get("href") == target_url or el.get("url") == target_url:
                    is_safe = True
                    break
                    
        if not is_safe:
            return {
                "messages": [ToolMessage(
                    content="Firewall 拦截: 严禁凭空伪造跳转路径！请优先使用 click 操作页面上现有的按钮或链接。", 
                    tool_call_id=tool_call_id
                )],
            }

    # Execute the tool
    result_text = ""
    try:
        if tool_name in tools_by_name:
            tool_fn = tools_by_name[tool_name]
            result_text = await tool_fn.ainvoke(tool_args)
    except Exception as e:
        result_text = f"执行失败: {str(e)}"

    return {
        "messages": [ToolMessage(content=result_text, tool_call_id=tool_call_id, name=tool_name)],
    }


async def generate_plan_node(state: dict[str, Any]) -> dict[str, Any]:
    """Generate structured test plan using create_test_plan tool.

    - Gets LLM with create_test_plan tool bound
    - Sends exploration results + task config as prompt
    - Parses tool call to extract test cases and setups
    - Returns test_plan and setups as structured data
    """
    try:
        llm = get_llm_client("default")  # qwen3.7-max for planning
        llm_with_tool = llm.bind_tools([create_test_plan])

        task_config = state.get("task_config", {})
        explored_urls = task_config.get("_explored_urls", [])
        target_url = task_config.get("target_url", "")

        prompt = get_plan_generation_prompt(
            target_url=target_url,
            explored_urls=explored_urls,
            task_config=task_config,
        )

        response = await llm_with_tool.ainvoke([
            SystemMessage(content="你是一个专业的测试规划师。请根据探索结果生成结构化的测试计划。"),
            HumanMessage(content=prompt),
        ])

        # Parse the tool call to extract test plan
        if hasattr(response, "tool_calls") and response.tool_calls:
            tool_call = response.tool_calls[0]
            test_cases_data = tool_call["args"].get("test_cases", [])
            setups_data = tool_call["args"].get("setups", [])

            # Convert to Pydantic models
            test_plan = [TestCase(**tc) for tc in test_cases_data]
            setups = {s["id"]: Setup(**s) for s in setups_data}

            return {
                "test_plan": test_plan,
                "setups": setups,
                "messages": [response],
            }

        # No tool call — LLM produced text instead
        return {"messages": [response]}
    except Exception as e:
        # Never crash: return error as AI message
        return {"messages": [AIMessage(content=f"生成测试计划失败: {str(e)}")]}


# =============================================================================
# Graph Builder
# =============================================================================


def build_planning_graph() -> StateGraph:
    """Build the planning subgraph for test plan generation.

    Nodes: explore_observe, explore_decide, explore_execute, generate_plan
    Conditional edges:
    - explore_decide → explore_execute (has tool_call) or generate_plan (no tool_call / safety valves)
    - explore_execute → explore_observe (loop back)
    """
    graph = StateGraph(TestState)

    # Add nodes
    graph.add_node("explore_observe", explore_observe_node)
    graph.add_node("explore_decide", explore_decide_node)
    graph.add_node("explore_execute", explore_execute_node)
    graph.add_node("generate_plan", generate_plan_node)

    # Edges
    graph.add_edge(START, "explore_observe")
    graph.add_edge("explore_observe", "explore_decide")
    graph.add_conditional_edges(
        "explore_decide",
        should_continue_exploring,
        {
            "explore": "explore_execute",
            "generate": "generate_plan",
        },
    )
    graph.add_edge("explore_execute", "explore_observe")
    graph.add_edge("generate_plan", END)

    return graph.compile()