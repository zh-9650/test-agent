"""Tests for core/parallel_executor.py — parallel action execution."""
import asyncio
import os
import pytest
from unittest.mock import AsyncMock, patch


def make_call(name, **args):
    return {"name": name, "args": args}


@pytest.mark.asyncio
async def test_default_serial(monkeypatch):
    """默认 L2_PARALLEL_TOOLS=0 → 串行执行"""
    from core.parallel_executor import execute_parallel_calls, is_parallel_enabled

    assert is_parallel_enabled() is False

    call_log: list[str] = []
    async def executor(call):
        call_log.append(call["name"])
        return {"action": call["name"], "status": "success"}

    calls = [make_call("a"), make_call("b"), make_call("c")]
    results = await execute_parallel_calls(calls, executor=executor)
    assert len(results) == 3
    assert call_log == ["a", "b", "c"]  # 串行顺序


@pytest.mark.asyncio
async def test_parallel_enabled(monkeypatch):
    """L2_PARALLEL_TOOLS=1 启用时, 独立 actions 真并发"""
    monkeypatch.setenv("L2_PARALLEL_TOOLS", "1")
    from core.parallel_executor import execute_parallel_calls, is_parallel_enabled

    assert is_parallel_enabled() is True

    async def executor(call):
        return {"action": call["name"], "status": "success"}

    # 2 个 read_only 视为独立
    calls = [
        make_call("extract_text", target="#1"),
        make_call("extract_text", target="#2"),
    ]
    results = await execute_parallel_calls(calls, executor=executor)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_parallel_with_deps_splits_waves(monkeypatch):
    """有依赖时拆 wave, 每 wave 内并发"""
    monkeypatch.setenv("L2_PARALLEL_TOOLS", "1")
    from core.parallel_executor import execute_parallel_calls

    async def executor(call):
        return {"action": call["name"], "status": "success"}

    # click#1 + click#1 (同 target) → 2 waves
    calls = [
        make_call("click", target="#1"),
        make_call("click", target="#1"),
    ]
    results = await execute_parallel_calls(calls, executor=executor)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_executor_exception_caught_serial():
    """executor 抛错时, 不应中断整个流程"""
    from core.parallel_executor import execute_parallel_calls

    async def executor(call):
        if call["name"] == "boom":
            raise RuntimeError("intentional")
        return {"action": call["name"], "status": "success"}

    calls = [make_call("a"), make_call("boom"), make_call("c")]
    results = await execute_parallel_calls(calls, executor=executor)
    assert len(results) == 3
    assert results[0]["status"] == "success"
    assert results[1]["status"] == "failure"
    assert "intentional" in results[1]["error"]
    assert results[2]["status"] == "success"


@pytest.mark.asyncio
async def test_empty_calls():
    from core.parallel_executor import execute_parallel_calls
    assert await execute_parallel_calls([]) == []


@pytest.mark.asyncio
async def test_unknown_tool_in_serial():
    """tools_by_name 找不到 tool 时, executor 返回 failure (不抛错)"""
    from core.parallel_executor import execute_parallel_calls
    calls = [make_call("nonexistent_tool")]
    results = await execute_parallel_calls(calls)
    assert len(results) == 1
    assert results[0]["status"] == "failure"
    assert "Unknown tool" in results[0]["error"]


@pytest.mark.asyncio
async def test_parallel_unknown_tool_concurrent(monkeypatch):
    """并发模式下, unknown tool 不抛错, 返回 failure"""
    monkeypatch.setenv("L2_PARALLEL_TOOLS", "1")
    from core.parallel_executor import execute_parallel_calls
    calls = [make_call("nonexistent_tool")]
    results = await execute_parallel_calls(calls)
    assert results[0]["status"] == "failure"
