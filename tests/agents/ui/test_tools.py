"""Tests for agents/ui/tools.py (TDD)

Uses real Playwright with page.set_content() for reliable DOM-based tests.
"""

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from agents.ui.tools import (
    navigate, click, input_text, scroll, wait,
    set_current_page, set_current_task, update_element_map, ui_tools, tools_by_name
)


# V2.0 A (2026-06-02): pre-existing test bug — 测试调 set_current_page 但没调 set_current_task,
# tools.py 会抛 "No active task". 加 autouse fixture 兜底
@pytest_asyncio.fixture(autouse=True)
async def _auto_set_task():
    set_current_task("test-tools-default")
    yield
    # 清理
    from agents.ui.tools import cleanup_task_context
    cleanup_task_context("test-tools-default")


@pytest_asyncio.fixture
async def page():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        yield page
        await browser.close()


# ---------------------------------------------------------------------------
# test_navigate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_navigate(page):
    set_current_page(page)
    result = await navigate.ainvoke({"url": "data:text/html,<h1>Test</h1>"})
    assert isinstance(result, dict)
    assert result["success"] is True
    assert "data:text/html" in result["after_url"]


# ---------------------------------------------------------------------------
# test_click_button
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_click_button(page):
    set_current_page(page)
    await page.set_content("""
    <html><body>
        <button id="btn">点击我</button>
    </body></html>
    """)
    result = await click.ainvoke({"target": "点击我"})
    assert isinstance(result, dict)
    assert result["success"] is True


# ---------------------------------------------------------------------------
# test_click_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_click_by_id(page):
    set_current_page(page)
    await page.set_content("""
    <html><body>
        <button id="btn">登录按钮</button>
    </body></html>
    """)
    # Set element map to simulate page_semantic extraction
    update_element_map([
        {"id": "#1", "type": "button", "text": "登录按钮"},
    ])
    result = await click.ainvoke({"target": "#1"})
    assert isinstance(result, dict)
    assert result["success"] is True


# ---------------------------------------------------------------------------
# test_input_text
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_input_text(page):
    set_current_page(page)
    await page.set_content("""
    <html><body>
        <input type="text" id="user" placeholder="用户名">
    </body></html>
    """)
    result = await input_text.ainvoke({"target": "用户名", "value": "test_user"})
    assert isinstance(result, dict)
    assert result["success"] is True


# ---------------------------------------------------------------------------
# test_input_text_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_input_text_by_id(page):
    set_current_page(page)
    await page.set_content("""
    <html><body>
        <input type="text" id="user" placeholder="用户名">
    </body></html>
    """)
    update_element_map([
        {"id": "#1", "type": "input", "input_type": "text", "placeholder": "用户名"},
    ])
    result = await input_text.ainvoke({"target": "#1", "value": "test_user"})
    assert isinstance(result, dict)
    assert result["success"] is True


# ---------------------------------------------------------------------------
# test_scroll_down
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scroll_down(page):
    set_current_page(page)
    await page.set_content("<html><body style='height:2000px;'></body></html>")
    result = await scroll.ainvoke({"direction": "down", "amount": 300})
    assert isinstance(result, dict)
    assert result["success"] is True


# ---------------------------------------------------------------------------
# test_scroll_up
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scroll_up(page):
    set_current_page(page)
    await page.set_content("<html><body style='height:2000px;'></body></html>")
    result = await scroll.ainvoke({"direction": "up", "amount": 300})
    assert isinstance(result, dict)
    assert result["success"] is True


# ---------------------------------------------------------------------------
# test_wait
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wait(page):
    set_current_page(page)
    result = await wait.ainvoke({"seconds": 0.1})
    assert isinstance(result, dict)
    assert result["success"] is True


# ---------------------------------------------------------------------------
# test_click_missing_element
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_click_missing_element(page):
    set_current_page(page)
    await page.set_content("<html><body></body></html>")
    result = await click.ainvoke({"target": "不存在的按钮"})
    assert isinstance(result, dict)
    assert result["success"] is False
    assert "找不到" in result["error"] or "Error" in result["error"] or "element" in result["error"].lower()


# ---------------------------------------------------------------------------
# test_input_missing_element
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_input_missing_element(page):
    set_current_page(page)
    await page.set_content("<html><body></body></html>")
    result = await input_text.ainvoke({"target": "不存在的输入框", "value": "test"})
    assert isinstance(result, dict)
    assert result["success"] is False
    assert "找不到" in result["error"] or "Error" in result["error"] or "element" in result["error"].lower()


# ---------------------------------------------------------------------------
# test_tools_by_name_dict
# ---------------------------------------------------------------------------

def test_tools_by_name_dict():
    assert "navigate" in tools_by_name
    assert "click" in tools_by_name
    assert "input_text" in tools_by_name
    assert "scroll" in tools_by_name
    assert "wait" in tools_by_name


# ---------------------------------------------------------------------------
# test_ui_tools_list
# ---------------------------------------------------------------------------

def test_ui_tools_list():
    tool_names = [t.name for t in ui_tools]
    assert "navigate" in tool_names
    assert "click" in tool_names
    assert "input_text" in tool_names
    assert "scroll" in tool_names
    assert "wait" in tool_names
    # V2.0 A (2026-06-02): 数量从 5 增到 15 (press_key/hover/go_back/extract_text/select_dropdown/evaluate_js
    # + 3 个 mark_task_*). 只断言 "包含 5 个核心" + ">=10" 表示工具列表非空
    assert len(ui_tools) >= 10, f"expected >=10 tools, got {len(ui_tools)}"
