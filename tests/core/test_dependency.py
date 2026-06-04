"""Tests for core/dependency.py — action dependency detection."""
from core.dependency import has_dependency, split_independent_groups, is_parallelizable


def test_no_args_no_dep():
    """两个 click 不同 target 视为有依赖 (state-changing pair 走 fail-safe 串行)"""
    # 设计选择: state-changing 工具互相视为有依赖, 避免 race
    # click+click 串行, 不是真的依赖但保守处理
    assert has_dependency(
        {"name": "click", "args": {"target": "#1"}},
        {"name": "click", "args": {"target": "#2"}},
    ) is True


def test_same_target_creates_dep():
    assert has_dependency(
        {"name": "click", "args": {"target": "#1"}},
        {"name": "click", "args": {"target": "#1"}},
    ) is True


def test_navigate_always_creates_dep():
    assert has_dependency(
        {"name": "navigate", "args": {"url": "x"}},
        {"name": "click", "args": {"target": "#1"}},
    ) is True
    assert has_dependency(
        {"name": "click", "args": {"target": "#1"}},
        {"name": "navigate", "args": {"url": "x"}},
    ) is True


def test_evaluate_js_always_creates_dep():
    assert has_dependency(
        {"name": "evaluate_js", "args": {"script": "1"}},
        {"name": "click", "args": {"target": "#1"}},
    ) is True


def test_mark_task_always_serial():
    assert has_dependency(
        {"name": "click", "args": {"target": "#1"}},
        {"name": "mark_task_complete", "args": {"reasoning": "done"}},
    ) is True


def test_read_only_independent():
    # 2 个 read_only 视为独立
    assert has_dependency(
        {"name": "extract_text", "args": {"target": "#1"}},
        {"name": "extract_text", "args": {"target": "#2"}},
    ) is False


def test_screenshot_with_state_change_serial():
    assert has_dependency(
        {"name": "screenshot_on_demand", "args": {"reason": "x"}},
        {"name": "click", "args": {"target": "#1"}},
    ) is True


def test_two_state_changing_serial():
    """两个状态变化工具之间视为有依赖 (避免 race)"""
    assert has_dependency(
        {"name": "click", "args": {"target": "#1"}},
        {"name": "input_text", "args": {"target": "#2", "value": "x"}},
    ) is True


def test_independent_different_targets_parallel():
    """state-changing 工具互相视为有依赖 (保守)"""
    assert has_dependency(
        {"name": "click", "args": {"target": "#1"}},
        {"name": "input_text", "args": {"target": "#2", "value": "x"}},
    ) is True


def test_split_independent_groups_empty():
    assert split_independent_groups([]) == []


def test_split_single():
    waves = split_independent_groups([{"name": "click", "args": {"target": "#1"}}])
    assert len(waves) == 1
    assert len(waves[0]) == 1


def test_split_two_independent():
    # 2 个 read_only 独立
    calls = [
        {"name": "extract_text", "args": {"target": "#1"}},
        {"name": "extract_text", "args": {"target": "#2"}},
    ]
    waves = split_independent_groups(calls)
    assert len(waves) == 1
    assert len(waves[0]) == 2


def test_split_two_dependent():
    calls = [
        {"name": "click", "args": {"target": "#1"}},
        {"name": "click", "args": {"target": "#1"}},
    ]
    waves = split_independent_groups(calls)
    assert len(waves) == 2
    assert all(len(w) == 1 for w in waves)


def test_split_mixed():
    calls = [
        {"name": "extract_text", "args": {"target": "#1"}},
        {"name": "extract_text", "args": {"target": "#2"}},  # 同 wave (read_only)
        {"name": "click", "args": {"target": "#3"}},  # 与 read_only 独立 → 同 wave
        {"name": "click", "args": {"target": "#4"}},  # state-changing pair → 新 wave
    ]
    waves = split_independent_groups(calls)
    # 期望: wave 1 = [extract, extract, click #3], wave 2 = [click #4]
    assert len(waves) == 2
    assert len(waves[0]) == 3
    assert len(waves[1]) == 1


def test_is_parallelizable_true():
    assert is_parallelizable([
        {"name": "extract_text", "args": {"target": "#1"}},
        {"name": "extract_text", "args": {"target": "#2"}},
    ]) is True


def test_is_parallelizable_false():
    assert is_parallelizable([
        {"name": "click", "args": {"target": "#1"}},
        {"name": "click", "args": {"target": "#2"}},
    ]) is False  # state-changing pair 串行


def test_state_change_vs_read_only_independent():
    """state-changing 工具 vs read_only 工具视为独立 (默认路径 False)"""
    assert has_dependency(
        {"name": "click", "args": {"target": "#1"}},
        {"name": "extract_text", "args": {"target": "#2"}},
    ) is False
