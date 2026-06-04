"""Tests for Phase 2.0D screenshot_on_demand tool — quota + b64 injection."""
import os
import pytest

from agents.ui.tools import (
    set_current_task, cleanup_task_context, get_current_task_id,
    _consume_screenshot_quota, _screenshot_quota_remaining,
    reset_screenshot_budget, _screenshot_budget,
)
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def _clean():
    _screenshot_budget.clear()
    yield
    _screenshot_budget.clear()


def test_consume_quota_default_2():
    assert _consume_screenshot_quota("task-1") is True  # 1
    assert _consume_screenshot_quota("task-1") is True  # 2
    assert _consume_screenshot_quota("task-1") is False  # 3rd blocked


def test_quota_remaining():
    assert _screenshot_quota_remaining("task-1") == 2
    _consume_screenshot_quota("task-1")
    assert _screenshot_quota_remaining("task-1") == 1
    _consume_screenshot_quota("task-1")
    assert _screenshot_quota_remaining("task-1") == 0


def test_quota_custom_budget(monkeypatch):
    monkeypatch.setenv("L2_SCREENSHOT_BUDGET", "5")
    for _ in range(5):
        assert _consume_screenshot_quota("task-1") is True
    assert _consume_screenshot_quota("task-1") is False


def test_quota_isolated_per_task():
    assert _consume_screenshot_quota("task-A") is True
    assert _consume_screenshot_quota("task-A") is True
    assert _consume_screenshot_quota("task-A") is False
    # task-B 不受 task-A 影响
    assert _consume_screenshot_quota("task-B") is True


def test_no_task_id_no_quota():
    # 没有 task_id 时, 始终允许 (test mode)
    assert _consume_screenshot_quota(None) is True
    assert _consume_screenshot_quota(None) is True
    assert _consume_screenshot_quota(None) is True


def test_reset_screenshot_budget():
    _consume_screenshot_quota("task-1")
    _consume_screenshot_quota("task-1")
    assert _consume_screenshot_quota("task-1") is False
    reset_screenshot_budget("task-1")
    assert _consume_screenshot_quota("task-1") is True


@pytest.mark.asyncio
async def test_screenshot_on_demand_returns_b64():
    """验证 screenshot_on_demand 成功时返回 screenshot_b64 字段"""
    set_current_task("task-screenshot-1")
    try:
        from agents.ui.tools import screenshot_on_demand, set_current_page

        # Mock page
        fake_page = MagicMock()
        fake_page.url = "https://example.com"
        set_current_page(fake_page, "task-screenshot-1")

        # Mock take_screenshot_compressed
        fake_b64 = "iVBORw0KGgoAAAANSUhEUg=="
        with patch("core.page_semantic.take_screenshot_compressed", new=AsyncMock(return_value=fake_b64)):
            # 替换 _make_action_result 链路: 直接调 .ainvoke (LangChain tool)
            result = await screenshot_on_demand.ainvoke({"reason": "button unclear"})

        # ActionResult 字段
        assert result["action"] == "screenshot_on_demand"
        assert result["status"] == "success"
        assert "screenshot_b64" in result
        assert result["screenshot_b64"] == fake_b64
        assert result["screenshot_injected"] is True
        # 配额扣减
        assert _screenshot_budget.get("task-screenshot-1") == 1
    finally:
        cleanup_task_context("task-screenshot-1")
        reset_screenshot_budget("task-screenshot-1")


@pytest.mark.asyncio
async def test_screenshot_on_demand_quota_exhausted():
    """配额用完时返回 failure, 不调用 take_screenshot"""
    set_current_task("task-screenshot-2")
    try:
        from agents.ui.tools import screenshot_on_demand, set_current_page

        # Mock page
        fake_page = MagicMock()
        fake_page.url = "https://example.com"
        set_current_page(fake_page, "task-screenshot-2")

        # 预先用完配额
        _consume_screenshot_quota("task-screenshot-2")
        _consume_screenshot_quota("task-screenshot-2")

        with patch("core.page_semantic.take_screenshot_compressed", new=AsyncMock()) as mock_shot:
            result = await screenshot_on_demand.ainvoke({"reason": "another"})

        assert result["action"] == "screenshot_on_demand"
        assert result["status"] == "failure"
        assert "screenshot_b64" not in result
        assert "quota exhausted" in result["error"].lower()
        # 配额耗尽时不应触发截图
        mock_shot.assert_not_called()
    finally:
        cleanup_task_context("task-screenshot-2")
        reset_screenshot_budget("task-screenshot-2")
