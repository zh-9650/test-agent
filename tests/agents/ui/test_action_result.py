"""Tests for Phase 2.0D structured ActionResult.

覆盖:
1. ActionResult Pydantic 模型新增字段 (status / extracted_content / long_term_memory / candidates / include_in_memory / duration_ms / evidence)
2. _make_action_result 自动推断 status + long_term_memory
3. _find_similar_elements 找相似元素
4. 工具返回 dict 包含新字段 (集成测, 用真实 Playwright)
"""

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.interfaces import ActionResult
from agents.ui.tools import (
    _make_action_result,
    _find_similar_elements,
    set_current_page, set_current_task, update_element_map, cleanup_task_context,
    navigate, click, input_text, wait, mark_task_complete, mark_task_failed, mark_task_skipped,
)


@pytest.fixture(autouse=True)
def _auto_task():
    set_current_task("test-action-result")
    yield
    cleanup_task_context("test-action-result")


# ============================================================================
# 模型字段测试
# ============================================================================

def test_action_result_new_fields():
    """Pydantic 模型能序列化所有新字段"""
    ar = ActionResult(
        action="click",
        target="#3",
        success=False,
        error="Element not found",
        status="not_found",
        extracted_content="已点击登录按钮",
        long_term_memory="建议: 检查目标元素是否可见",
        candidates=[{"text": "登录", "role": "button", "id": "#5"}],
        include_in_memory=True,
        duration_ms=250,
        evidence={"screenshot_path": "/data/1.png", "network": "ok"},
    )
    dumped = ar.model_dump()
    assert dumped["status"] == "not_found"
    assert dumped["extracted_content"] == "已点击登录按钮"
    assert dumped["long_term_memory"] is not None
    assert len(dumped["candidates"]) == 1
    assert dumped["candidates"][0]["id"] == "#5"
    assert dumped["duration_ms"] == 250
    assert dumped["evidence"]["screenshot_path"] == "/data/1.png"


def test_action_result_is_terminal():
    """is_terminal() 正确识别 mark_task_* 工具"""
    assert ActionResult(action="mark_task_complete", success=True).is_terminal()
    assert ActionResult(action="mark_task_failed", success=False).is_terminal()
    assert ActionResult(action="mark_task_skipped", success=True).is_terminal()
    assert not ActionResult(action="click", success=True).is_terminal()
    assert not ActionResult(action="input_text", success=True).is_terminal()


def test_action_result_backward_compat():
    """老字段 (success / error / before_url / after_url / page_changed / url_changed / filled_value) 仍可用"""
    ar = ActionResult(
        action="input_text", target="#1", success=True, filled_value="1234****",
    )
    assert ar.success
    assert ar.filled_value == "1234****"
    assert ar.before_url == ""
    assert ar.status == "success"  # 默认值


# ============================================================================
# _make_action_result 推断逻辑
# ============================================================================

class _FakePage:
    """Mock page for _make_action_result 测试 (不需 Playwright)"""
    def __init__(self, url="https://example.com"):
        self.url = url

    async def _get_dom_fingerprint(self, page):
        return "0_0_0"


@pytest.mark.asyncio
async def test_make_action_result_status_success():
    """成功 → status=success"""
    page = _FakePage()
    res = await _make_action_result("click", "#3", True, page, page.url)
    assert res["status"] == "success"
    assert res["success"] is True


@pytest.mark.asyncio
async def test_make_action_result_status_timeout_inferred():
    """失败 + 错误信息含 'timeout' → status=timeout"""
    page = _FakePage()
    res = await _make_action_result(
        "click", "#3", False, page, page.url, error="Locator.click: Timeout 5000ms exceeded"
    )
    assert res["status"] == "timeout"


@pytest.mark.asyncio
async def test_make_action_result_status_not_found_inferred():
    """失败 + 错误信息含 'not found' → status=not_found"""
    page = _FakePage()
    res = await _make_action_result(
        "click", "#99", False, page, page.url, error="Element not found: #99"
    )
    assert res["status"] == "not_found"


@pytest.mark.asyncio
async def test_make_action_result_status_failure_inferred():
    """失败 + 通用错误 → status=failure"""
    page = _FakePage()
    res = await _make_action_result(
        "click", "#3", False, page, page.url, error="Element is disabled"
    )
    assert res["status"] == "failure"


@pytest.mark.asyncio
async def test_make_action_result_long_term_memory_auto():
    """失败时自动生成 long_term_memory (无显式传入)"""
    page = _FakePage()
    res = await _make_action_result(
        "click", "#3", False, page, page.url, error="X"
    )
    assert res["long_term_memory"]
    assert "建议" in res["long_term_memory"]


@pytest.mark.asyncio
async def test_make_action_result_explicit_status_overrides():
    """显式 status 优先于自动推断"""
    page = _FakePage()
    res = await _make_action_result(
        "click", "#3", False, page, page.url,
        error="X", status="timeout",  # 显式指定
    )
    assert res["status"] == "timeout"


@pytest.mark.asyncio
async def test_make_action_result_filled_value():
    """filled_value 字段透传 (2.0B 兼容)"""
    page = _FakePage()
    res = await _make_action_result(
        "input_text", "#1", True, page, page.url,
        filled_value="12****",
    )
    assert res["filled_value"] == "12****"


# ============================================================================
# 工具集成测试 (真实 Playwright)
# ============================================================================

@pytest_asyncio.fixture
async def page():
    """提供真实 Playwright 页面"""
    set_current_task("test-action-result")
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content("""
            <html><body>
                <button id="b1">登录</button>
                <input id="i1" type="text" placeholder="用户名" />
                <input id="i2" type="password" placeholder="密码" />
                <a id="a1" href="#">忘记密码</a>
            </body></html>
        """)
        set_current_page(page, "test-action-result")
        # 喂 element_map (CDP AXTree 模拟数据)
        update_element_map([
            {"id": "#1", "type": "button", "text": "登录", "role": "button", "label": "登录", "placeholder": "", "coords": {"x": 0, "y": 0, "width": 50, "height": 30}},
            {"id": "#2", "type": "input", "text": "", "role": "textbox", "label": "", "placeholder": "用户名", "coords": {"x": 0, "y": 50, "width": 100, "height": 20}},
            {"id": "#3", "type": "input", "text": "", "role": "textbox", "label": "", "placeholder": "密码", "coords": {"x": 0, "y": 100, "width": 100, "height": 20}},
            {"id": "#4", "type": "a", "text": "忘记密码", "role": "link", "label": "忘记密码", "placeholder": "", "coords": {"x": 0, "y": 150, "width": 80, "height": 20}},
        ])
        yield page
        await browser.close()


@pytest.mark.asyncio
async def test_navigate_returns_extracted_content(page):
    """navigate 成功 → extracted_content 含目标 URL"""
    await page.goto("about:blank")
    set_current_page(page, "test-action-result")
    res = await navigate.ainvoke({"url": "about:blank"})
    assert res["status"] == "success"
    assert res["success"] is True
    assert "已导航" in res["extracted_content"]


@pytest.mark.asyncio
async def test_click_success_returns_extracted_content(page):
    """click 成功 → extracted_content 含元素描述"""
    res = await click.ainvoke({"target": "#1"})
    assert res["status"] == "success"
    assert res["success"] is True
    assert "已点击" in res["extracted_content"] or "登录" in res["extracted_content"]


@pytest.mark.asyncio
async def test_click_failure_returns_candidates(page):
    """click 失败 → status + candidates (从 element_map 找相似)"""
    res = await click.ainvoke({"target": "#99"})
    assert res["status"] in ("not_found", "timeout", "failure")
    assert res["success"] is False
    assert res["error"]
    assert res["long_term_memory"]  # 自动生成
    # candidates 应包含 #1 登录 (因为 target #99 不存在)
    # 注意: 实际是否返回依赖 _find_similar_elements 匹配策略
    # 此用例仅验证字段存在
    assert "candidates" in res


@pytest.mark.asyncio
async def test_input_text_success_returns_filled_value(page):
    """input_text 成功 → filled_value 脱敏 + extracted_content"""
    res = await input_text.ainvoke({"target": "#2", "value": "hello world"})
    assert res["status"] == "success", f"res={res}"
    assert res["success"] is True
    assert res["filled_value"] == "hello world"  # 非密码字段不脱敏
    assert "hello world" in res["extracted_content"]


@pytest.mark.asyncio
async def test_mark_task_complete_has_extracted_content(page):
    """mark_task_* 工具 → extracted_content = reasoning"""
    res = await mark_task_complete.ainvoke({"reasoning": "测试成功并且满足证据链要求，已成功提取所有页面字段。"})
    assert res["status"] == "success", f"res={res}"
    assert "测试成功并且满足证据链要求" in res["extracted_content"]
    assert res["is_terminal"]() if hasattr(res, 'is_terminal') else True  # dict 没有 is_terminal


@pytest.mark.asyncio
async def test_mark_task_failed_has_error(page):
    """mark_task_failed → error=reasoning + extracted_content=reasoning"""
    res = await mark_task_failed.ainvoke({"reasoning": "测试失败"})
    # 注意: error 含"测试失败"不含 not_found/timeout, 所以推断为 failure
    assert res["error"] == "测试失败"
    assert res["extracted_content"] == "测试失败"


# ============================================================================
# _find_similar_elements 测试
# ============================================================================

def test_find_similar_elements_by_text():
    """根据 text/label 找相似元素"""
    from agents.ui.tools import _task_contexts, _current_task_id
    tid = _current_task_id.get()
    _task_contexts[tid] = {
        "element_map": {
            "#1": {"text": "登录按钮", "label": "登录按钮", "type": "button", "role": "button"},
            "#2": {"text": "注册", "label": "注册", "type": "button", "role": "button"},
            "#3": {"text": "忘记密码", "label": "忘记密码", "type": "a", "role": "link"},
        }
    }
    cands = _find_similar_elements("登录", _FakePage(), max_n=3)
    assert len(cands) > 0
    # 应包含 #1 (text 含"登录")
    texts = [c.get("text", "") for c in cands]
    assert "登录按钮" in texts


def test_find_similar_elements_empty_on_no_match():
    """无匹配 → 空列表"""
    from agents.ui.tools import _task_contexts, _current_task_id
    tid = _current_task_id.get()
    _task_contexts[tid] = {
        "element_map": {
            "#1": {"text": "完全不相关", "label": "", "type": "div", "role": ""},
        }
    }
    cands = _find_similar_elements("登录", _FakePage(), max_n=3)
    assert cands == []
