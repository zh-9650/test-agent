"""core/context_manager.py — Phase 2.0D LLM 语义压缩

对标 browser-use MessageManager:
- 触发条件: 步数 + tokens 双阈值 (browser-use 默认 25 步 + 10K 字符)
- 压缩方式: 用轻量 LLM (deepseek-v4-flash) 总结老旧历史, 保留关键信息
- 保留失败动作: 永远不擦除"做过什么没用"的证据 (Manus 经验)
- 保留: System Message + 最近 N 步 + 1 条压缩摘要

回退策略: 压缩失败时降级为物理截断 (system + 最后 5 条)
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage

from core.llm_client import get_llm_client


# ============================================================================
# 配置 (env 可调)
# ============================================================================

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# 触发压缩的步数阈值 (browser-use compact_every_n_steps)
COMPACT_EVERY_N_STEPS = _env_int("L2_COMPACT_EVERY_N_STEPS", 25)

# 触发压缩的 token 阈值 (browser-use trigger_token_count)
COMPACT_TRIGGER_TOKENS = _env_int("L2_COMPACT_TRIGGER_TOKENS", 30000)

# 保留最近几步不压缩 (browser-use keep_last_items)
COMPACT_KEEP_LAST = _env_int("L2_COMPACT_KEEP_LAST", 6)

# 压缩摘要最大字符数 (browser-use summary_max_chars)
COMPACT_SUMMARY_MAX_CHARS = _env_int("L2_COMPACT_SUMMARY_MAX_CHARS", 2000)

# 压缩总开关 (0 = 禁用, 走物理截断)
COMPACTION_ENABLED = os.getenv("L2_COMPACTION", "1") != "0"


# ============================================================================
# 压缩 Prompt (中文, 强调保留关键信息)
# ============================================================================

_COMPACT_PROMPT = """你是一个测试执行历史的压缩助手。请将以下执行步骤总结为一段简短的摘要。

【必须保留的信息】
1. 已完成的步骤和对应的页面变化
2. 失败的尝试 (尤其是工具错误: timeout / not_found / 其他异常), 这些是避免重复错误的关键
3. 当前测试进度 (已完成 X/N 步, 当前在第几步)
4. 关键页面状态 (登录态、表单填写值、URL)
5. 当前目标和预期结果

【可以省略】
- 重复的中间观察 (相同页面被多次 observe)
- 成功但无副作用的导航/wait
- 已通过但不再需要回看的步骤细节

【输出格式】
一段 200-500 字的中文摘要, 用分点列出关键信息。开头注明"已压缩 N 步"。

【待压缩历史】
{history_text}

【输出摘要】
"""


# ============================================================================
# 公开 API
# ============================================================================

def should_compact(state: dict[str, Any]) -> bool:
    """判断是否需要压缩。

    Args:
        state: LangGraph state, 需含 messages / current_step

    Returns:
        bool: True 表示需要压缩
    """
    if not COMPACTION_ENABLED:
        return False
    messages = state.get("messages", [])
    if not messages:
        return False
    current_step = state.get("current_step", 0)
    if current_step < COMPACT_EVERY_N_STEPS:
        return False
    # token 阈值检查
    try:
        from core.llm_client import count_tokens
        total_tokens = count_tokens(messages)
        if total_tokens is None:
            total_tokens = 0
    except Exception:
        # 估算失败时按字符粗算 (4 字符 ≈ 1 token)
        total_tokens = sum(len(str(m.content)) for m in messages) // 4
    return total_tokens > COMPACT_TRIGGER_TOKENS


def _messages_to_text(messages: list[BaseMessage]) -> str:
    """把消息列表转为可读的文本格式, 方便 LLM 摘要。"""
    lines: list[str] = []
    for i, msg in enumerate(messages):
        msg_type = msg.__class__.__name__
        content = msg.content if isinstance(msg.content, str) else str(msg.content)[:500]
        # 截断过长的 content
        if len(content) > 800:
            content = content[:800] + "..."
        tool_call_id = getattr(msg, "tool_call_id", "")
        extra = f" [tool_call_id={tool_call_id}]" if tool_call_id else ""
        lines.append(f"[{i}] {msg_type}{extra}: {content}")
    return "\n".join(lines)


async def _invoke_compact_llm(history_text: str) -> str | None:
    """调用 LLM 压缩历史。失败返回 None (调用方降级到物理截断)。"""
    try:
        client = get_llm_client("haiku")  # 用轻量模型 (deepseek-v4-flash)
        prompt = _COMPACT_PROMPT.format(history_text=history_text)
        response = await client.ainvoke(prompt)
        content = response.content if isinstance(response.content, str) else str(response.content)
        if not content or not content.strip():
            return None
        # 截断过长摘要
        if len(content) > COMPACT_SUMMARY_MAX_CHARS:
            content = content[:COMPACT_SUMMARY_MAX_CHARS] + "\n[摘要截断]"
        return content.strip()
    except Exception as e:
        # 压缩失败 (LLM 调用异常) — 返回 None 让调用方降级
        import sys
        print(f"[context_manager] LLM compression failed: {e}", file=sys.stderr)
        return None


def _truncate_physically(messages: list[BaseMessage]) -> list[RemoveMessage]:
    """物理截断: 保留 system + 最后 5 条, 删除中间。

    压缩失败时的回退方案。
    """
    if len(messages) <= 6:
        return []
    tail_count = 5
    middle = messages[1:-tail_count]
    to_remove: list[RemoveMessage] = []
    for m in middle:
        if hasattr(m, "id") and m.id:
            to_remove.append(RemoveMessage(id=m.id))
        else:
            import hashlib
            fake_id = hashlib.md5(repr(m).encode()).hexdigest()
            to_remove.append(RemoveMessage(id=fake_id))
    return to_remove


async def compact_history(
    state: dict[str, Any],
    *,
    summary: str | None = None,
) -> tuple[list[RemoveMessage], str | None]:
    """压缩 state 中的 messages。

    策略:
    1. 保留 system message (head) + 最后 COMPACT_KEEP_LAST 步
    2. 中间部分用 LLM 总结为 1 条 SystemMessage, 插入到 head 后
    3. 删除被压缩的原始消息 (返回 RemoveMessage 列表)
    4. 失败时降级为物理截断 (保留 system + 最后 5 条)

    Args:
        state: LangGraph state
        summary: 可选, 外部预生成的摘要 (用于测试). 传 None 则调用 LLM.

    Returns:
        (RemoveMessages, compaction_summary):
          - RemoveMessages: 应从 state 中删除的消息 ID 列表
          - compaction_summary: LLM 生成的摘要 (用于注入下一轮 decide prompt)
    """
    messages = list(state.get("messages", []))
    if len(messages) <= COMPACT_KEEP_LAST + 1:
        return [], None

    # 1. 找 system message (head)
    head = messages[:1]  # 假设第一条是 system
    tail = messages[-COMPACT_KEEP_LAST:]
    middle = messages[1:-COMPACT_KEEP_LAST]

    if not middle:
        return [], None

    # 2. 生成摘要 (外部传入 or LLM 调用)
    if summary is None:
        history_text = _messages_to_text(middle)
        summary = await _invoke_compact_llm(history_text)

    if summary is None:
        # 降级: 物理截断
        return _truncate_physically(messages), None

    # 3. 构造 RemoveMessage 列表
    to_remove: list[RemoveMessage] = []
    for m in middle:
        if hasattr(m, "id") and m.id:
            to_remove.append(RemoveMessage(id=m.id))
        else:
            import hashlib
            fake_id = hashlib.md5(repr(m).encode()).hexdigest()
            to_remove.append(RemoveMessage(id=fake_id))

    return to_remove, summary


def build_compact_summary_message(summary: str) -> SystemMessage:
    """构造压缩摘要 SystemMessage (用于插入到 messages 列表)。

    标签: [COMPACTED SUMMARY] + 摘要内容
    """
    return SystemMessage(content=f"[COMPACTED SUMMARY - 已压缩 {COMPACT_EVERY_N_STEPS}+ 步历史]\n{summary}")


# ============================================================================
# 同步 API (供测试用, 避免每次 await)
# ============================================================================

def compact_history_sync(state: dict[str, Any], summary: str | None = None) -> list[RemoveMessage]:
    """同步版本的 compress, 不调用 LLM, 仅用预生成 summary 生成 RemoveMessage 列表。

    便于测试。也用于 caller 已经知道摘要的场景。
    """
    messages = list(state.get("messages", []))
    if len(messages) <= COMPACT_KEEP_LAST + 1:
        return []
    middle = messages[1:-COMPACT_KEEP_LAST]
    to_remove: list[RemoveMessage] = []
    for m in middle:
        if hasattr(m, "id") and m.id:
            to_remove.append(RemoveMessage(id=m.id))
        else:
            import hashlib
            fake_id = hashlib.md5(repr(m).encode()).hexdigest()
            to_remove.append(RemoveMessage(id=fake_id))
    return to_remove
