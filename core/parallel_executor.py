"""core/parallel_executor.py — Phase 2.0D: parallel action execution.

负责调度一组 actions 按依赖图拆 wave, 每个 wave 内并发执行 (asyncio.gather).
依赖检测委托给 core.dependency.split_independent_groups.

默认禁用 (env L2_PARALLEL_TOOLS=0), 需 LLM 显式调用 parallel_tool_calls
且 env L2_PARALLEL_TOOLS=1 时才真正并发. 默认走串行 (行为不变).

设计原则 (来自 Day 7 用户约定):
- 默认禁用, 不破坏现有 LLM 单 tool_call 行为
- LLM 必须显式表达"同时填多个独立字段"等意图, 我们才并行
- 任何依赖冲突 → 降级串行 (fail-safe)
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from core.dependency import split_independent_groups, has_dependency


def is_parallel_enabled() -> bool:
    """env gate: L2_PARALLEL_TOOLS=1 启用, 默认 0."""
    return os.getenv("L2_PARALLEL_TOOLS", "0") == "1"


async def execute_parallel_calls(
    calls: list[dict[str, Any]],
    *,
    executor: Any = None,
) -> list[dict[str, Any]]:
    """Execute a list of action calls in parallel waves.

    Args:
        calls: list of {name: str, args: dict}
        executor: async callable (call_dict) -> result_dict
                   若 None, 使用 tools_by_name[name].ainvoke (LangChain tool)

    Returns:
        list of result dicts (按输入顺序, 同一个 wave 内按 gather 返回顺序)

    Behavior:
        - Default: 串行 (each call awaited sequentially)
        - 当 env L2_PARALLEL_TOOLS=1: 按依赖图拆 wave, 每 wave 内 asyncio.gather
        - 任何 wave 内 has_dependency 冲突 → 降级为串行
    """
    if not calls:
        return []

    if executor is None:
        from agents.ui.tools import tools_by_name
        async def executor(call: dict) -> dict:
            tool = tools_by_name.get(call["name"])
            if tool is None:
                return {
                    "action": call["name"],
                    "status": "failure",
                    "error": f"Unknown tool: {call['name']}",
                }
            return await tool.ainvoke(call.get("args", {}))

    # 串行 fallback (默认)
    if not is_parallel_enabled():
        results: list[dict[str, Any]] = []
        for call in calls:
            try:
                result = await executor(call)
                results.append(result)
            except Exception as e:
                results.append({
                    "action": call.get("name", "?"),
                    "status": "failure",
                    "error": str(e),
                })
        return results

    # 并行路径
    waves = split_independent_groups(calls)
    all_results: list[dict[str, Any]] = []
    for wave in waves:
        if len(wave) == 1:
            # 单个不需要 gather
            try:
                result = await executor(wave[0])
                all_results.append(result)
            except Exception as e:
                all_results.append({
                    "action": wave[0].get("name", "?"),
                    "status": "failure",
                    "error": str(e),
                })
        else:
            # 并发 wave: gather 包裹
            coros = [executor(call) for call in wave]
            gathered = await asyncio.gather(*coros, return_exceptions=True)
            for call, res in zip(wave, gathered):
                if isinstance(res, Exception):
                    all_results.append({
                        "action": call.get("name", "?"),
                        "status": "failure",
                        "error": str(res),
                    })
                else:
                    all_results.append(res)
    return all_results
