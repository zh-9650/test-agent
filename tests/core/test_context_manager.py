"""Tests for Phase 2.0D LLM semantic compression (core/context_manager.py)."""

import pytest
import os
from unittest.mock import patch, AsyncMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage, RemoveMessage

from core import context_manager
from core.context_manager import (
    should_compact,
    compact_history,
    compact_history_sync,
    _truncate_physically,
    _messages_to_text,
    build_compact_summary_message,
    COMPACT_EVERY_N_STEPS,
    COMPACT_KEEP_LAST,
    COMPACTION_ENABLED,
)


# ============================================================================
# should_compact 测试
# ============================================================================

def test_should_compact_disabled():
    """L2_COMPACTION=0 → 永远不压缩"""
    with patch.object(context_manager, "COMPACTION_ENABLED", False):
        state = {"messages": [HumanMessage(content="x" * 50000)], "current_step": 100}
        assert should_compact(state) is False


def test_should_compact_step_below_threshold():
    """步数 < 阈值 → 不压缩"""
    state = {"messages": [HumanMessage(content="x" * 100)], "current_step": 5}
    assert should_compact(state) is False


def test_should_compact_step_above_but_tokens_below():
    """步数达标但 tokens 没超 → 不压缩"""
    state = {
        "messages": [HumanMessage(content="short")] * 5,
        "current_step": COMPACT_EVERY_N_STEPS + 5,
    }
    assert should_compact(state) is False


def test_should_compact_both_above():
    """步数 + tokens 双阈值都超 → 触发压缩"""
    big_content = "x" * 200
    state = {
        "messages": [HumanMessage(content=big_content)] * 800,
        "current_step": COMPACT_EVERY_N_STEPS + 5,
    }
    # mock count_tokens 返回 40000, 阈值 patch 到 100
    with patch("core.llm_client.count_tokens", return_value=40000), \
         patch.object(context_manager, "COMPACT_TRIGGER_TOKENS", 100):
        assert should_compact(state) is True


def test_should_compact_empty_messages():
    """空 messages → 不压缩"""
    state = {"messages": [], "current_step": 100}
    assert should_compact(state) is False


# ============================================================================
# _messages_to_text 测试
# ============================================================================

def test_messages_to_text_basic():
    """基本消息转文本"""
    msgs = [
        SystemMessage(content="你是测试助手"),
        HumanMessage(content="点击登录"),
        AIMessage(content="执行 click"),
    ]
    text = _messages_to_text(msgs)
    assert "SystemMessage" in text
    assert "HumanMessage" in text
    assert "AIMessage" in text
    assert "你是测试助手" in text
    assert "点击登录" in text


def test_messages_to_text_truncates_long_content():
    """超长 content 截断到 800 字符"""
    long_content = "x" * 2000
    msgs = [HumanMessage(content=long_content)]
    text = _messages_to_text(msgs)
    assert "xxx" in text
    assert "..." in text
    assert len(text) < 2000  # 截断生效


def test_messages_to_text_includes_tool_call_id():
    """ToolMessage 含 tool_call_id 时应展示"""
    msgs = [ToolMessage(content="result", tool_call_id="call_123", name="click")]
    text = _messages_to_text(msgs)
    assert "call_123" in text


# ============================================================================
# _truncate_physically 测试
# ============================================================================

def test_truncate_physically_keeps_head_and_tail():
    """物理截断: 保留 head + 最后 5 条"""
    msgs = [SystemMessage(content="system")] + [HumanMessage(content=f"m{i}") for i in range(20)]
    removed = _truncate_physically(msgs)
    # 总 21 条, 保留 head (1) + tail (5) = 6, 删除 21 - 6 = 15
    assert len(removed) == 15


def test_truncate_physically_short_messages():
    """消息数 < 6 → 不删除任何"""
    msgs = [SystemMessage(content="s"), HumanMessage(content="h")]
    removed = _truncate_physically(msgs)
    assert removed == []


# ============================================================================
# compact_history_sync 测试
# ============================================================================

def test_compact_history_sync_basic():
    """sync 版本: 接受 summary 参数, 返回 RemoveMessage 列表"""
    msgs = [SystemMessage(content="s")] + [HumanMessage(content=f"m{i}") for i in range(20)]
    state = {"messages": msgs}
    removed = compact_history_sync(state, summary="已登录系统")
    assert len(removed) == len(msgs) - 1 - COMPACT_KEEP_LAST


def test_compact_history_sync_no_messages_to_remove():
    """消息数 < keep_last + 1 → 返回空"""
    msgs = [SystemMessage(content="s"), HumanMessage(content="h1"), HumanMessage(content="h2")]
    state = {"messages": msgs}
    removed = compact_history_sync(state, summary="anything")
    assert removed == []


# ============================================================================
# compact_history (async) 测试
# ============================================================================

@pytest.mark.asyncio
async def test_compact_history_with_summary():
    """传入 summary 时不调用 LLM"""
    msgs = [SystemMessage(content="s")] + [HumanMessage(content=f"m{i}") for i in range(20)]
    state = {"messages": msgs}
    removed, comp_summary = await compact_history(state, summary="已压缩: 完成登录")
    assert len(removed) == len(msgs) - 1 - COMPACT_KEEP_LAST
    assert comp_summary == "已压缩: 完成登录"


@pytest.mark.asyncio
async def test_compact_history_llm_failure_fallback():
    """LLM 调用失败 → 降级物理截断"""
    msgs = [SystemMessage(content="s")] + [HumanMessage(content=f"m{i}") for i in range(20)]
    state = {"messages": msgs}

    # 模拟 LLM 失败
    with patch.object(context_manager, "_invoke_compact_llm", AsyncMock(return_value=None)):
        removed, comp_summary = await compact_history(state, summary=None)
        # 降级到物理截断: head + 5 保留
        assert len(removed) == len(msgs) - 1 - 5
        assert comp_summary is None


@pytest.mark.asyncio
async def test_compact_history_short_messages():
    """消息少 → 返回空"""
    msgs = [SystemMessage(content="s"), HumanMessage(content="h1")]
    state = {"messages": msgs}
    removed, comp_summary = await compact_history(state, summary=None)
    assert removed == []
    assert comp_summary is None


# ============================================================================
# build_compact_summary_message 测试
# ============================================================================

def test_build_compact_summary_message():
    """摘要消息含 [COMPACTED SUMMARY] 标签"""
    msg = build_compact_summary_message("已登录系统")
    assert isinstance(msg, SystemMessage)
    assert "COMPACTED SUMMARY" in msg.content
    assert "已登录系统" in msg.content
    assert str(COMPACT_EVERY_N_STEPS) in msg.content  # "已压缩 N 步"


# ============================================================================
# 集成: L2_COMPACTION=0 时回退物理截断
# ============================================================================

def test_compaction_disabled_uses_physical_truncate():
    """禁用压缩时 should_compact 永远 False"""
    with patch.object(context_manager, "COMPACTION_ENABLED", False):
        state = {"messages": [HumanMessage(content="x" * 50000)] * 50, "current_step": 100}
        assert should_compact(state) is False
