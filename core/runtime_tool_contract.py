from __future__ import annotations

"""Shared runtime browser-tool contract used by prompts and schemas."""

from collections.abc import Iterable


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
