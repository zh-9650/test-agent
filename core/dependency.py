"""core/dependency.py — Phase 2.0D: action dependency detection for parallel execution.

并行执行的核心问题: 不是所有工具都能并发. 两个 action 之间的依赖关系:
1. **目标冲突**: 两个 action 操作同一元素 (例如 click 同一个 button, 后者会被前者的 DOM 变化打乱)
2. **数据依赖**: 第二个 action 依赖第一个的输出 (例如 read 文本 + 写同一文本, 顺序很关键)
3. **页面状态依赖**: 第二个 action 要求第一个改变页面状态 (例如 wait_for_load + click)
4. **导航冲突**: navigate + 任何其他 (navigate 会换页面, 后续必然失败)

依赖图 (DAG):
- 独立子集: 可并发
- 强依赖链: 必须串行
- 并行调度: 把 actions 拓扑排序, 拆成 wave, 每个 wave 内并发执行
"""

from __future__ import annotations

from typing import Any

# 工具: 哪些类型有数据依赖 / 状态依赖
NAVIGATING_TOOLS = {"navigate", "go_back"}

# 工具: 操作同一元素必串行 (target 重复)
TARGET_BASED = {
    "click", "input_text", "select_dropdown", "hover",
    "press_key", "extract_text", "evaluate_js",
}

# 工具: 改变页面状态, 后续 action 应等待
STATE_CHANGING = {
    "navigate", "click", "input_text", "select_dropdown",
    "go_back", "press_key", "evaluate_js",
    "hover", "scroll", "wait",
}

# 工具: 可视为幂等 / 纯读取, 永远独立
READ_ONLY = {"extract_text", "screenshot_on_demand"}


def has_dependency(call_a: dict[str, Any], call_b: dict[str, Any]) -> bool:
    """判断两个 action 是否有依赖 (有则必须串行).

    Args:
        call_a: {name: str, args: dict}
        call_b: {name: str, args: dict}

    Returns:
        True if 必须串行, False if 可并发.
    """
    name_a = call_a.get("name", "")
    name_b = call_b.get("name", "")
    args_a = call_a.get("args", {}) or {}
    args_b = call_b.get("args", {}) or {}

    # 1. 任一是 navigate → 全部串行 (页面换后其他动作几乎都失效)
    if name_a in NAVIGATING_TOOLS or name_b in NAVIGATING_TOOLS:
        return True

    # 2. 同一 target 视为冲突
    if name_a in TARGET_BASED and name_b in TARGET_BASED:
        target_a = args_a.get("target", "") or ""
        target_b = args_b.get("target", "") or ""
        if target_a and target_b and target_a == target_b:
            return True

    # 3. evaluate_js 默认谨慎: 两个 eval 之间串行 (script 可能改 DOM)
    if name_a == "evaluate_js" or name_b == "evaluate_js":
        return True

    # 4. 标记类工具必须最后: 任何 mark_task_* 必串行
    if name_a.startswith("mark_task_") or name_b.startswith("mark_task_"):
        return True

    # 5. screenshot_on_demand + 状态变化工具串行 (看截图前不应改状态)
    if "screenshot_on_demand" in (name_a, name_b):
        if name_a in STATE_CHANGING or name_b in STATE_CHANGING:
            return True

    # 6. 两个 read_only 可并发
    if name_a in READ_ONLY and name_b in READ_ONLY:
        return False

    # 7. 状态变化工具互相视为有依赖 (避免 race condition)
    if name_a in STATE_CHANGING and name_b in STATE_CHANGING:
        return True

    # 默认: 独立 (可并发)
    return False


def split_independent_groups(calls: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """把 actions 拆成可并发的 wave.

    返回每 wave 一个 list of action calls. 同 wave 内可并发, 不同 wave 必须串行.

    算法: 贪心, 保持原序. 把每个新 action 试着加入当前 wave, 如果它和 wave 中任一 action 有
    依赖, 就开新 wave.

    Args:
        calls: action calls 列表 (有序)

    Returns:
        list of wave, each wave = list of action calls
    """
    if not calls:
        return []
    waves: list[list[dict[str, Any]]] = []
    current_wave: list[dict[str, Any]] = [calls[0]]
    for call in calls[1:]:
        # 试着加入 current_wave: 如果和 wave 内任一 call 有依赖, 必须新开 wave
        can_join = all(
            not has_dependency(existing, call)
            for existing in current_wave
        )
        if can_join:
            current_wave.append(call)
        else:
            waves.append(current_wave)
            current_wave = [call]
    if current_wave:
        waves.append(current_wave)
    return waves


def is_parallelizable(calls: list[dict[str, Any]]) -> bool:
    """判断一组 actions 整体是否可并行 (wave 数 == 1).

    简化版: 只看第一对. 完整版用 split_independent_groups 看 wave 数.
    """
    return len(split_independent_groups(calls)) == 1
