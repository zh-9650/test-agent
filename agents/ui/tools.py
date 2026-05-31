"""agents/ui/tools.py — Playwright tool definitions for UI testing.

Defines @tool decorated functions that the LLM can call to interact with web pages.
Includes: click, input_text, navigate, scroll, wait, and other page interactions.
"""

from __future__ import annotations

import asyncio
import contextvars
from typing import Any

from langchain_core.tools import tool

# ---------------------------------------------------------------------------
# Per-task context registry (replaces module-level singletons)
# ---------------------------------------------------------------------------

# ContextVar holds the current task_id for the running coroutine/task
_current_task_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_task_id", default=None
)

# Registry mapping task_id -> {"page": <Page>, "element_map": {id: el_info}}
_task_contexts: dict[str, dict[str, Any]] = {}
_hitl_events: dict[str, asyncio.Event] = {}
_hitl_responses: dict[str, str] = {}


def set_current_task(task_id: str) -> None:
    """Set the current task_id for the running coroutine."""
    _current_task_id.set(task_id)


def get_current_task_id() -> str | None:
    """Return the current task_id for the running coroutine."""
    return _current_task_id.get()


def cleanup_task_context(task_id: str) -> None:
    """Remove all stored state for a finished task."""
    _task_contexts.pop(task_id, None)


def set_current_page(page: Any, task_id: str | None = None) -> None:
    tid = task_id or _current_task_id.get()
    if tid is None:
        raise RuntimeError("No active task. Call set_current_task() first.")
    ctx = _task_contexts.setdefault(tid, {"page": None, "element_map": {}})
    ctx["page"] = page


def get_current_page() -> Any:
    tid = _current_task_id.get()
    if tid is None:
        raise RuntimeError("No active task. Call set_current_task() first.")
    ctx = _task_contexts.get(tid)
    if ctx is None or ctx["page"] is None:
        raise RuntimeError("No active page. Call set_current_page() first.")
    return ctx["page"]


def update_element_map(elements: list[dict]) -> None:
    tid = _current_task_id.get()
    if tid is None:
        raise RuntimeError("No active task. Call set_current_task() first.")
    ctx = _task_contexts.setdefault(tid, {"page": None, "element_map": {}})
    ctx["element_map"] = {el["id"]: el for el in elements}


# ---------------------------------------------------------------------------
# Element resolution helper
# ---------------------------------------------------------------------------

async def _resolve_element(target: str, page: Any) -> Any:
    """Resolve a target string to a Playwright Locator.

    Strategy:
    1. If target starts with #, look up in _element_map and build locator
    2. Otherwise, try text-based locators in order
    """
    # Get per-task element map
    tid = _current_task_id.get()
    ctx = _task_contexts.get(tid, {}) if tid else {}
    element_map = ctx.get("element_map", {})

    if target.startswith("#") and target in element_map:
        el_info = element_map[target]
        
        # If we have an exact xpath from browser-use, use it directly!
        if "xpath" in el_info and el_info["xpath"]:
            locator = page.locator(f"xpath={el_info['xpath']}")
            if await locator.count() > 0:
                return locator.first
                
        # Build locator from element info (Fallback)
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
        elif el_type in ["button", "input"]:
            text = ""
            if el_type == "input" and el_info.get("input_type") in ["submit", "button"]:
                text = el_info.get("value", "") or el_info.get("text", "")
            else:
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

_hitl_callbacks: dict[str, Any] = {}

@tool
async def request_human_intervention(reason: str) -> str:
    """当遇到需要人工解决的复杂场景（如验证码、滑动拼图、MFA动态口令等）时调用此工具。
    系统会挂起当前执行流，并通过 UI 通知人类，等待人类解决后恢复。

    Args:
        reason: 呼叫人工的具体原因和要求。例如："请在浏览器中手动完成登录滑块验证，然后点击继续"。

    Returns:
        人工干预的结果回复。
    """
    task_id = get_current_task_id()
    if not task_id:
        return "人工干预失败: 找不到当前 task_id"

    # Create event and store in registry
    event = asyncio.Event()
    _hitl_events[task_id] = event

    # Trigger callback to notify API server
    if task_id in _hitl_callbacks:
        await _hitl_callbacks[task_id](reason)
    else:
        return "人工干预失败: 没有注册 HITL 回调"

    # Block execution until human responds
    await event.wait()

    # Clean up and return human response
    _hitl_events.pop(task_id, None)
    response = _hitl_responses.pop(task_id, "人类已处理完成")
    return response

@tool
async def press_key(key: str) -> str:
    """按下键盘按键。例如 'Enter', 'Escape', 'Tab' 等。

    Args:
        key: 要按下的按键名称

    Returns:
        操作结果描述
    """
    try:
        page = get_current_page()
        await page.keyboard.press(key)
        return f"已按下 {key} 键"
    except Exception as e:
        return f"按键失败: {e}"

@tool
async def hover(target: str) -> str:
    """悬停在页面上的元素上。适用于触发下拉菜单或提示框。

    Args:
        target: 元素编号（如 #3）或元素描述
    """
    try:
        page = get_current_page()
        locator = await _resolve_element(target, page)
        await locator.hover(timeout=10000)
        return f"已悬停在 {target} 上"
    except Exception as e:
        return f"悬停失败: {e}"

@tool
async def go_back() -> str:
    """在浏览器历史记录中后退一页。"""
    try:
        page = get_current_page()
        await page.go_back(wait_until="networkidle", timeout=15000)
        return "已后退到上一页"
    except Exception as e:
        return f"后退失败: {e}"

@tool
async def extract_text(target: str) -> str:
    """提取页面元素的文本内容。

    Args:
        target: 元素编号（如 #3）或元素描述
    """
    try:
        page = get_current_page()
        locator = await _resolve_element(target, page)
        text = await locator.inner_text(timeout=5000)
        return f"元素文本内容: {text}"
    except Exception as e:
        return f"提取文本失败: {e}"

@tool
async def select_dropdown(target: str, value: str) -> str:
    """从下拉菜单(select)中选择选项。

    Args:
        target: 元素编号（如 #3）或元素描述
        value: 要选择的选项的文本、value或label
    """
    try:
        page = get_current_page()
        locator = await _resolve_element(target, page)
        await locator.select_option(value, timeout=10000)
        return f"已在下拉菜单 {target} 中选择 {value}"
    except Exception as e:
        return f"选择下拉菜单失败: {e}"

@tool
async def evaluate_js(script: str) -> str:
    """在当前页面中执行一段 JavaScript 代码。

    Args:
        script: 要执行的 JavaScript 代码
    """
    try:
        page = get_current_page()
        
        # If the script contains a bare return (not inside a function), 
        # page.evaluate will throw a SyntaxError: Illegal return statement.
        # Wrap it in an IIFE (Immediately Invoked Function Expression) to safely evaluate it.
        wrapped_script = script
        if "return " in script and not script.strip().startswith("(") and not script.strip().startswith("function"):
            wrapped_script = f"(() => {{\n{script}\n}})()"
            
        result = await page.evaluate(wrapped_script)
        return f"JS执行结果: {result}"
    except Exception as e:
        return f"JS执行失败: {e}"


@tool
async def mark_task_complete(reasoning: str) -> str:
    """标记当前任务已成功完成，并结束执行。

    Args:
        reasoning: 任务成功的理由或发现，请尽量详细说明
    """
    return f"任务标记为已成功: {reasoning}"


@tool
async def mark_task_failed(reasoning: str) -> str:
    """标记当前任务执行失败，无法继续，并结束执行。

    Args:
        reasoning: 任务失败的具体原因（如：找不到目标元素，页面报错等）
    """
    return f"任务标记为已失败: {reasoning}"


@tool
async def mark_task_skipped(reasoning: str) -> str:
    """标记当前任务被跳过（如前置条件已满足无需执行），并结束执行。

    Args:
        reasoning: 跳过任务的具体原因
    """
    return f"任务标记为已跳过: {reasoning}"


# ---------------------------------------------------------------------------
# Tool exports
# ---------------------------------------------------------------------------

__all__ = [
    "navigate",
    "click",
    "input_text",
    "scroll",
    "wait",
    "press_key",
    "hover",
    "request_human_intervention",
    "go_back",
    "extract_text",
    "select_dropdown",
    "evaluate_js",
    "mark_task_complete",
    "mark_task_failed",
    "mark_task_skipped",
    "get_current_page",
    "set_current_page",
    "get_element_map",
    "update_element_map",
    "set_current_task",
    "get_current_task_id",
    "cleanup_task_context",
    "tools",
    "tools_by_name",
]

# Provide a list of tool objects for LLM binding
tools = [
    navigate,
    click,
    input_text,
    scroll,
    wait,
    press_key,
    hover,
    request_human_intervention,
    go_back,
    extract_text,
    select_dropdown,
    evaluate_js,
    mark_task_complete,
    mark_task_failed,
    mark_task_skipped,
]

# Provide a map for easy invocation by name
tools_by_name = {t.name: t for t in tools}

