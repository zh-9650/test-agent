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
    # browser-use 对齐 (2026-06-05): 7 个新工具已注册
    for new_tool in ("find", "get_dropdown_options", "get_specific_elements", "switch_tab", "close_tab", "refresh", "get_page_links"):
        assert new_tool in tool_names, f"missing new tool: {new_tool}"


# ---------------------------------------------------------------------------
# browser-use 对齐 (2026-06-05): 新工具 smoke test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh(page):
    from agents.ui.tools import set_current_page, refresh
    set_current_page(page)
    await page.set_content("<html><body><h1>Test</h1></body></html>")
    result = await refresh.ainvoke({})
    assert result["success"] is True
    assert "刷新" in result.get("extracted_content", "")


@pytest.mark.asyncio
async def test_get_page_links(page):
    from agents.ui.tools import set_current_page, get_page_links
    set_current_page(page)
    await page.set_content("""
    <html><body>
        <a href="https://example.com/a">Link A</a>
        <a href="https://example.com/b">Link B</a>
        <a href="https://example.com/c" style="display:none">Hidden</a>
    </body></html>
    """)
    result = await get_page_links.ainvoke({})
    assert result["success"] is True
    assert "Link A" in result.get("extracted_content", "")
    assert "example.com/a" in result.get("extracted_content", "")


@pytest.mark.asyncio
async def test_find_returns_matches(page):
    from agents.ui.tools import set_current_page, find
    set_current_page(page)
    await page.set_content("""
    <html><body>
        <button>Login</button>
        <button>Sign Up</button>
        <input placeholder="search">
    </body></html>
    """)
    result = await find.ainvoke({"query": "Login"})
    assert result["success"] is True
    content = result.get("extracted_content", "")
    assert "Login" in content


@pytest.mark.asyncio
async def test_get_dropdown_options(page):
    from agents.ui.tools import set_current_page, get_dropdown_options
    set_current_page(page)
    await page.set_content("""
    <html><body>
        <select id="sel">
            <option value="a">Apple</option>
            <option value="b" selected>Banana</option>
            <option value="c">Cherry</option>
        </select>
    </body></html>
    """)
    # 注册 element_map: select 是 #1
    from agents.ui.tools import set_current_page, set_current_task, update_element_map
    set_current_task("test-dropdown")
    set_current_page(page)
    update_element_map([{"id": "#1", "type": "select", "xpath": "//select[1]"}])
    result = await get_dropdown_options.ainvoke({"target": "#1"})
    assert result["success"] is True, f"got error: {result.get('error')}"
    content = result.get("extracted_content", "")
    assert "Apple" in content
    assert "Banana" in content
    assert "Cherry" in content
    assert "当前选中" in content


@pytest.mark.asyncio
async def test_refresh_and_get_specific_elements(page):
    from agents.ui.tools import set_current_page, get_specific_elements
    set_current_page(page)
    await page.set_content("""
    <html><body>
        <button>Btn1</button>
        <button>Btn2</button>
        <a href="/x">Link</a>
    </body></html>
    """)
    result = await get_specific_elements.ainvoke({"roles": "button,link"})
    assert result["success"] is True
    content = result.get("extracted_content", "")
    assert "Btn1" in content
    assert "Link" in content
