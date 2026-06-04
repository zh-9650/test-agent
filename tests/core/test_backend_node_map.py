"""Tests for core/backend_node_map.py — Phase 2.0D persistence layer."""
import pytest
from core import backend_node_map


@pytest.fixture(autouse=True)
def _clean():
    """每个测试前清空 map"""
    backend_node_map.clear_all()
    yield
    backend_node_map.clear_all()


def test_store_and_lookup_basic():
    backend_node_map.store("task-1", "#3", 12345, frame_id="frame-1",
                           attrs={"tag": "button", "text": "Submit"},
                           current_step=0)
    entry = backend_node_map.lookup("task-1", "#3", current_step=5)
    assert entry is not None
    assert entry["backend_node_id"] == 12345
    assert entry["frame_id"] == "frame-1"
    assert entry["attrs"]["tag"] == "button"
    assert entry["last_seen_step"] == 5  # touched


def test_lookup_missing_task_returns_none():
    assert backend_node_map.lookup("nonexistent", "#3", current_step=0) is None


def test_lookup_missing_element_returns_none():
    backend_node_map.store("task-1", "#1", 100, current_step=0)
    assert backend_node_map.lookup("task-1", "#999", current_step=0) is None


def test_store_rejects_empty():
    backend_node_map.store("", "#3", 100, current_step=0)
    backend_node_map.store("task-1", "", 100, current_step=0)
    backend_node_map.store("task-1", "#3", 0, current_step=0)  # 0 = invalid
    assert backend_node_map.get_all("task-1") == {}


def test_store_updates_existing():
    backend_node_map.store("task-1", "#1", 100, current_step=0)
    backend_node_map.store("task-1", "#1", 200, current_step=5)
    entry = backend_node_map.lookup("task-1", "#1", current_step=6)
    assert entry["backend_node_id"] == 200


def test_pruning_by_age():
    """超过 MAX_AGE_STEPS 的 entry 应该在 lookup 时被剪掉"""
    # Default MAX_AGE_STEPS = 20
    backend_node_map.store("task-1", "#1", 100, current_step=0)
    # 22 步之后, #1 应该被剪掉
    entry = backend_node_map.lookup("task-1", "#1", current_step=22)
    assert entry is None


def test_pruning_keeps_fresh():
    backend_node_map.store("task-1", "#1", 100, current_step=0)
    # 10 步之后, #1 应该还在
    entry = backend_node_map.lookup("task-1", "#1", current_step=10)
    assert entry is not None
    assert entry["backend_node_id"] == 100


def test_clear_specific_task():
    backend_node_map.store("task-1", "#1", 100, current_step=0)
    backend_node_map.store("task-2", "#1", 200, current_step=0)
    backend_node_map.clear("task-1")
    assert backend_node_map.lookup("task-1", "#1", current_step=0) is None
    assert backend_node_map.lookup("task-2", "#1", current_step=0) is not None


def test_stats():
    backend_node_map.store("task-1", "#1", 100, current_step=0)
    backend_node_map.store("task-1", "#2", 200, current_step=0)
    backend_node_map.store("task-2", "#1", 300, current_step=0)
    s = backend_node_map.stats()
    assert s["tasks"] == 2
    assert s["total_entries"] == 3
    assert s["per_task"] == {"task-1": 2, "task-2": 1}


def test_get_all_returns_snapshot():
    backend_node_map.store("task-1", "#1", 100, current_step=0)
    snap = backend_node_map.get_all("task-1")
    assert "#1" in snap
    assert snap["#1"]["backend_node_id"] == 100
    # Modifying snapshot should not affect map
    snap["#1"]["backend_node_id"] = 999
    entry = backend_node_map.lookup("task-1", "#1", current_step=0)
    assert entry["backend_node_id"] == 100


def test_multiple_tasks_isolation():
    backend_node_map.store("task-1", "#1", 100, current_step=0)
    backend_node_map.store("task-2", "#1", 200, current_step=0)
    e1 = backend_node_map.lookup("task-1", "#1", current_step=0)
    e2 = backend_node_map.lookup("task-2", "#1", current_step=0)
    assert e1["backend_node_id"] == 100
    assert e2["backend_node_id"] == 200


def test_hard_cap_max_entries():
    """超过 MAX_ENTRIES_PER_TASK 时, 最老的 entry 被裁掉 (pruning 是惰性的)"""
    # MAX_ENTRIES_PER_TASK = 500
    for i in range(510):
        backend_node_map.store("task-1", f"#{i}", i, current_step=i)
    # Pruning 在 lookup 时触发, 调一次 lookup 触发裁剪
    backend_node_map.lookup("task-1", "#509", current_step=509)
    all_entries = backend_node_map.get_all("task-1")
    assert len(all_entries) <= 500
    # 最新的应该还在
    last = backend_node_map.lookup("task-1", "#509", current_step=509)
    assert last is not None
