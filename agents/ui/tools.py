"""agents/ui/tools.py — Playwright tool definitions for UI testing.

Defines @tool decorated functions that the LLM can call to interact with web pages.
Includes: click, input_text, navigate, scroll, wait, and other page interactions.
"""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.tools import tool

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_current_page = None
_element_map: dict[str, dict] = {}


def set_current_page(page: Any) -> None:
    global _current_page
    _current_page = page


def get_current_page() -> Any:
    if _current_page is None:
        raise RuntimeError("No active page. Call set_current_page() first.")
    return _current_page


def update_element_map(elements: list[dict]) -> None:
    global _element_map
    _element_map = {el["id"]: el for el in elements}


# ---------------------------------------------------------------------------
# Element resolution helper
# ---------------------------------------------------------------------------

async def _resolve_element(target: str, page: Any) -> Any:
    """Resolve a target string to a Playwright Locator.

    Strategy:
    1. If target starts with #, look up in _element_map and build locator
    2. Otherwise, try text-based locators in order
    """
    if target.startswith("#") and target in _element_map:
        el_info = _element_map[target]
        # Build locator from element info
        el_type = el_info.get("type", "")
        if el_type == "input":
            input_type = el_info.get("input_type", "text")
            # Try by label, placeholder, or CSS
            label = el_info.get("label", "")
            if label:
                locator = page.get_by_label(label)
                if await locator.count() > 0:
                    return locator.first
            placeholder = el_info.get("placeholder", "")
            if placeholder:
                locator = page.get_by_placeholder(placeholder)
                if await locator.count() > 0:
                    return locator.first
        elif el_type == "button":
            text = el_info.get("text", "")
            if text:
                locator = page.get_by_role("button", name=text)
                if await locator.count() > 0:
                    return locator.first
        # ... more type-specific resolution
        # Fallback: try text content
        text = el_info.get("text", "") or el_info.get("label", "")
        if text:
            locator = page.get_by_text(text, exact=False)
            if await locator.count() > 0:
                return locator.first

    # Not an ID — try as description
    # Try get_by_role button
    locator = page.get_by_role("button", name=target)
    if await locator.count() > 0:
        return locator.first
    # Try get_by_text
    locator = page.get_by_text(target, exact=False)
    if await locator.count() > 0:
        return locator.first
    # Try placeholder
    locator = page.get_by_placeholder(target)
    if await locator.count() > 0:
        return locator.first
    # Try aria-label
    locator = page.locator(f"[aria-label='{target}']")
    if await locator.count() > 0:
        return locator.first

    raise ValueError(f"找不到元素: {target}")


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

@tool
async def navigate(url: str) -> str:
    """导航到指定 URL。

    Args:
        url: 要导航到的完整 URL

    Returns:
        操作结果描述
    """
    try:
        page = get_current_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)
        return f"已导航到 {url}"
    except Exception as e:
        return f"导航失败: {e}"


@tool
async def click(target: str) -> str:
    """点击页面上的元素。

    Args:
        target: 元素编号（如 #3）或元素描述（如 "登录按钮"）

    Returns:
        操作结果描述
    """
    try:
        page = get_current_page()
        locator = await _resolve_element(target, page)
        await locator.click(timeout=10000)
        return f"已点击 {target}"
    except Exception as e:
        return f"点击失败: {e}"


@tool
async def input_text(target: str, value: str) -> str:
    """在输入框中输入文本。

    Args:
        target: 元素编号（如 #1）或元素描述（如 "用户名输入框"）
        value: 要输入的文本内容

    Returns:
        操作结果描述
    """
    try:
        page = get_current_page()
        locator = await _resolve_element(target, page)
        await locator.fill(value, timeout=10000)
        return f"已在 {target} 输入文本"
    except Exception as e:
        return f"输入失败: {e}"


@tool
async def scroll(direction: str, amount: int = 300) -> str:
    """滚动页面。

    Args:
        direction: 滚动方向，"up" 或 "down"
        amount: 滚动像素数，默认 300

    Returns:
        操作结果描述
    """
    try:
        page = get_current_page()
        delta = amount if direction == "down" else -amount
        await page.mouse.wheel(0, delta)
        direction_str = "向下" if direction == "down" else "向上"
        return f"已{direction_str}滚动 {amount} 像素"
    except Exception as e:
        return f"滚动失败: {e}"


@tool
async def wait(seconds: float = 1.0) -> str:
    """等待指定秒数。用于等待页面加载或动画完成。

    Args:
        seconds: 等待秒数，默认 1.0

    Returns:
        操作结果描述
    """
    try:
        await asyncio.sleep(seconds)
        return f"已等待 {seconds} 秒"
    except Exception as e:
        return f"等待失败: {e}"


# ---------------------------------------------------------------------------
# Tool exports
# ---------------------------------------------------------------------------

# List of all UI tools for bind_tools()
ui_tools = [navigate, click, input_text, scroll, wait]

# Dict for dispatching tool calls to implementations
tools_by_name = {t.name: t for t in ui_tools}
