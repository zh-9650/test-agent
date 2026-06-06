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


# ---------------------------------------------------------------------------
# mark_task_complete strict completion protocol
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_task_complete_success_single_target(page):
    """Single-target expected, normal-length reasoning, no extracted_fields → accept."""
    from agents.ui.tools import set_current_page, set_current_expected, mark_task_complete
    set_current_page(page)
    set_current_expected("登录成功并跳转到 dashboard 页面")
    await page.set_content("<html><head><title>Dashboard</title></head><body><h1>Welcome</h1></body></html>")
    result = await mark_task_complete.ainvoke({
        "reasoning": "已成功跳转到 Dashboard 页面, h1 显示 Welcome, 登录流程完整执行",
    })
    assert result["success"] is True
    assert result["status"] == "success"
    assert "Dashboard" in result.get("extracted_content", "")


@pytest.mark.asyncio
async def test_mark_task_complete_rejects_short_reasoning(page):
    """reasoning < 20 chars → rejected."""
    from agents.ui.tools import set_current_page, set_current_expected, mark_task_complete
    set_current_page(page)
    set_current_expected("登录成功")
    await page.set_content("<html><body>ok</body></html>")
    result = await mark_task_complete.ainvoke({
        "reasoning": "完成",  # too short
    })
    assert result["success"] is False
    assert result["status"] == "completion_rejected"
    assert "reasoning 过短" in result.get("extracted_content", "")


@pytest.mark.asyncio
async def test_mark_task_complete_rejects_multi_target_missing_fields(page):
    """expected contains '和' → extracted_fields required and must have ≥2 keys."""
    from agents.ui.tools import set_current_page, set_current_expected, mark_task_complete
    set_current_page(page)
    set_current_expected("报告头条新闻的 title 和 score 两个字段")
    await page.set_content("<html><body><h1>HN</h1></body></html>")

    # Case A: no extracted_fields at all
    result = await mark_task_complete.ainvoke({
        "reasoning": "已经看到了页面上的两个字段, 任务可以标记完成。",
    })
    assert result["success"] is False
    assert result["status"] == "completion_rejected"
    assert "多目标" in result.get("extracted_content", "")

    # Case B: extracted_fields has only 1 key
    result2 = await mark_task_complete.ainvoke({
        "reasoning": "已经看到了页面上的两个字段, 任务可以标记完成。",
        "extracted_fields": {"title": "Show HN: foo"},
    })
    assert result2["success"] is False
    assert result2["status"] == "completion_rejected"


@pytest.mark.asyncio
async def test_mark_task_complete_accepts_multi_target_with_fields(page):
    """expected contains '和' + extracted_fields has ≥2 keys → accept."""
    from agents.ui.tools import set_current_page, set_current_expected, mark_task_complete
    set_current_page(page)
    set_current_expected("报告头条新闻的 title 和 score 两个字段")
    await page.set_content("<html><head><title>HN</title></head><body><h1>News</h1></body></html>")
    result = await mark_task_complete.ainvoke({
        "reasoning": "已抓取 title='Show HN: foo' 和 score='1234', 两字段都已写入 extracted_fields",
        "extracted_fields": {"title": "Show HN: foo", "score": "1234"},
        "evidence_url": page.url,
    })
    assert result["success"] is True
    assert result["status"] == "success"
    content = result.get("extracted_content", "")
    assert "extracted_fields" in content
    assert "title" in content
    assert "score" in content


@pytest.mark.asyncio
async def test_mark_task_complete_evidence_url_mismatch_warns_not_rejects(page):
    """evidence_url mismatch → soft warn, still accept."""
    from agents.ui.tools import set_current_page, set_current_expected, mark_task_complete
    set_current_page(page)
    set_current_expected("访问到目标页面")
    await page.set_content("<html><body>at real page</body></html>")
    result = await mark_task_complete.ainvoke({
        "reasoning": "已完成访问, 看到了目标页面的内容标题, 任务达成",
        "evidence_url": "https://wrong-url.example.com/",
    })
    assert result["success"] is True
    assert result["status"] == "success"
    assert "wrong-url" in result.get("extracted_content", "")
    assert "evidence_url" in result.get("extracted_content", "")
    assert "不一致" in result.get("extracted_content", "")


# ---------------------------------------------------------------------------
# New Alignment Tests (2026-06-05)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_element_re_anchoring_on_mismatch(page):
    """Verify that _resolve_element successfully performs semantic re-anchoring on mismatch."""
    from agents.ui.tools import set_current_page, update_element_map, click
    set_current_page(page)
    await page.set_content("""
    <html><body>
        <button id="new-btn">提交表单</button>
    </body></html>
    """)
    update_element_map([
        {"id": "#1", "type": "button", "text": "提交", "xpath": "//button[@id='btn-old']", "coords": {"x": 100, "y": 100, "width": 50, "height": 20}},
    ])

    result = await click.ainvoke({"target": "#1"})
    assert result["success"] is True
    assert "提交表单" in result["extracted_content"]


@pytest.mark.asyncio
async def test_aria_label_and_title_fallback_in_page_semantic(page):
    """Verify buttons/links extract aria-label or title if text is empty."""
    from core.page_semantic import extract_page_semantics
    from agents.ui.tools import set_current_page
    set_current_page(page)
    await page.set_content("""
    <html><body>
        <button aria-label="Icon Button"></button>
        <a href="/about" title="Tooltip Link"></a>
    </body></html>
    """)
    result = await extract_page_semantics(page)
    elements = result["interactive_elements"]
    assert len(elements) == 2
    assert elements[0]["text"] == "Icon Button"
    assert elements[1]["text"] == "Tooltip Link"


@pytest.mark.asyncio
async def test_page_bottom_viewport_detection(page):
    """Verify viewport detection determines when the page is scrolled to bottom."""
    from core.page_semantic import extract_page_semantics
    from agents.ui.tools import set_current_page
    set_current_page(page)
    await page.set_content("""
    <html><body style="height: 1000px; margin: 0; padding: 0;">
        <div style="height: 800px;">Spacing</div>
        <div id="bottom">Bottom</div>
    </body></html>
    """)
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    result = await extract_page_semantics(page)
    assert result["viewport"]["is_bottom"] is True
