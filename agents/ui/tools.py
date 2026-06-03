"""agents/ui/tools.py — Playwright tool definitions for UI testing.

Defines @tool decorated functions that the LLM can call to interact with web pages.
Includes: click, input_text, navigate, scroll, wait, and other page interactions.

Phase 2.0A improvements:
- All tools return ActionResult dict (Sprint 2)
- wait_for_stable() built into each tool (Sprint 3)
- DOM fingerprint for page_changed detection (Sprint 2)
"""

from __future__ import annotations

import asyncio
import contextvars
from typing import Any

from langchain_core.tools import tool

from core.interfaces import ActionResult

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


def set_task_config(config: dict[str, Any], task_id: str | None = None) -> None:
    """Set the current task's config registry."""
    tid = task_id or _current_task_id.get()
    if tid is None:
        raise RuntimeError("No active task. Call set_current_task() first.")
    ctx = _task_contexts.setdefault(tid, {"page": None, "element_map": {}})
    ctx["task_config"] = config


def get_task_config() -> dict[str, Any]:
    """Get the current task's config registry."""
    tid = _current_task_id.get()
    if tid is None:
        return {}
    ctx = _task_contexts.get(tid, {})
    return ctx.get("task_config", {})


def set_current_step_text(step_text: str, task_id: str | None = None) -> None:
    """B1.4: Register the current step text into task context."""
    tid = task_id or _current_task_id.get()
    if tid is None:
        return
    ctx = _task_contexts.setdefault(tid, {"page": None, "element_map": {}})
    ctx["current_step_text"] = step_text


def get_current_step_text() -> str:
    """B1.4: Get the current step text from task context."""
    tid = _current_task_id.get()
    if tid is None:
        return ""
    ctx = _task_contexts.get(tid, {})
    return ctx.get("current_step_text", "")


def update_element_map(elements: list[dict]) -> None:
    tid = _current_task_id.get()
    if tid is None:
        raise RuntimeError("No active task. Call set_current_task() first.")
    ctx = _task_contexts.setdefault(tid, {"page": None, "element_map": {}})
    ctx["element_map"] = {el["id"]: el for el in elements}


def get_element_map() -> dict[str, dict]:
    """Return the current task's element map (read-only snapshot)."""
    tid = _current_task_id.get()
    if tid is None:
        return {}
    ctx = _task_contexts.get(tid, {})
    return dict(ctx.get("element_map", {}))


# ---------------------------------------------------------------------------
# Phase 2.0A Sprint 2+3: DOM fingerprint + wait_for_stable + ActionResult helper
# ---------------------------------------------------------------------------


async def _get_dom_fingerprint(page: Any) -> str:
    """计算当前页面的 DOM 三维指纹：elCount_htmlLen_textLen。"""
    try:
        return await page.evaluate("""() => {
            const elCount = document.querySelectorAll('*').length;
            const htmlLen = document.documentElement.outerHTML.length;
            const textLen = document.body?.innerText?.length ?? 0;
            return `${elCount}_${htmlLen}_${textLen}`;
        }""")
    except Exception:
        return "0_0_0"


async def _wait_for_stable(page: Any, timeout: int = 5000, poll_interval: int = 250) -> None:
    """等待 DOM 稳定：networkidle 兜底 + DOM 指纹轮询 + 物理缓冲。

    不新增 LangGraph 节点，直接在工具函数内部调用。
    企业系统有 WebSocket/SSE 时 networkidle 永不触发，靠 DOM 指纹轮询稳定。
    """
    try:
        await page.wait_for_load_state("networkidle", timeout=2000)
    except Exception:
        pass
    for _ in range(timeout // poll_interval):
        before = await _get_dom_fingerprint(page)
        await asyncio.sleep(poll_interval / 1000)
        after = await _get_dom_fingerprint(page)
        if before == after:
            await asyncio.sleep(0.5)
            return


async def _make_action_result(
    action: str,
    target: str | int | None,
    success: bool,
    page: Any,
    before_url: str,
    before_fingerprint: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """构造 ActionResult dict。

    Args:
        action: 动作名称
        target: 动作目标
        success: 是否成功
        page: Playwright page 对象
        before_url: 动作执行前 URL
        before_fingerprint: 动作执行前的 DOM 指纹 (None 时自动计算)
        error: 错误信息
    """
    after_url = page.url
    if before_fingerprint is None:
        before_fingerprint = "0_0_0"
    after_fingerprint = await _get_dom_fingerprint(page)
    return ActionResult(
        action=action,
        target=target,
        success=success,
        error=error,
        before_url=before_url,
        after_url=after_url,
        page_changed=(before_fingerprint != after_fingerprint),
        url_changed=(before_url != after_url),
    ).model_dump()


# ---------------------------------------------------------------------------
# Element resolution helper
# ---------------------------------------------------------------------------


def _normalize_target(target: Any) -> str:
    """自适应归一化元素引用：纯数字、[N]、[ N ]、整数 → #N。

    根因 1 (元素引用匹配脱锚): LLM 可能输出 933 / [933] / [ 933 ] / 整数 933,
    统一映射为 #933 供 element_map 查找。
    """
    raw = str(target).strip() if not isinstance(target, (int, float)) else str(int(target))
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if inner.isdigit():
            return f"#{inner}"
        return inner
    if raw.isdigit():
        return f"#{raw}"
    return raw


async def _resolve_element(target: str, page: Any) -> Any:
    """Resolve a target string to a Playwright Locator.

    Strategy:
    1. Normalize target. If target is digit or [digit] or starts with #, look up in element_map
    2. If found, try xpath or other specific fallback attributes
    3. Otherwise, try text-based locators in order
    """
    tid = _current_task_id.get()
    ctx = _task_contexts.get(tid, {}) if tid else {}
    element_map = ctx.get("element_map", {})

    # Normalize target key — 自适应归一化 (根因 1)
    lookup_key = _normalize_target(target)

    # B3.2: Locator 总调用计数
    try:
        tc = get_task_config()
        if "_locator_stats" not in tc:
            tc["_locator_stats"] = {"total": 0, "failed": 0}
        tc["_locator_stats"]["total"] = tc["_locator_stats"].get("total", 0) + 1
    except Exception:
        pass

    if lookup_key in element_map:
        el_info = element_map[lookup_key]
        
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

        # Fallback: try text content
        text = el_info.get("text", "") or el_info.get("label", "")
        if text:
            locator = page.get_by_text(text, exact=False)
            if await locator.count() > 0:
                return locator.first

    # Not an ID — try as description (使用 str 安全转换, 防止整数 target 崩溃)
    safe_target = str(target)
    # Try get_by_role button
    locator = page.get_by_role("button", name=safe_target)
    if await locator.count() > 0:
        return locator.first
    # Try get_by_text
    locator = page.get_by_text(safe_target, exact=False)
    if await locator.count() > 0:
        return locator.first
    # Try placeholder
    locator = page.get_by_placeholder(safe_target)
    if await locator.count() > 0:
        return locator.first
    # Try aria-label
    locator = page.locator(f"[aria-label='{safe_target}']")
    if await locator.count() > 0:
        return locator.first

    # B3.2: Locator 失败统计 — 在 task_config 累加
    try:
        tc = get_task_config()
        if "_locator_stats" not in tc:
            tc["_locator_stats"] = {"total": 0, "failed": 0}
        tc["_locator_stats"]["total"] = tc["_locator_stats"].get("total", 0) + 1
        tc["_locator_stats"]["failed"] = tc["_locator_stats"].get("failed", 0) + 1
    except Exception:
        pass

    raise ValueError(f"找不到元素: {safe_target}")


# ---------------------------------------------------------------------------
# B1.1: Password injection intent check
# ---------------------------------------------------------------------------


def _should_auto_inject_password(task_config: dict[str, Any], step_text: str) -> bool:
    """B1.1: 校验当前步骤语义是否确实需要输入密码。

    如果 step_text 含有"密码/password/pass"等关键词 → 允许注入。
    如果 step_text 含有"用户名/账号/username/user/account/登录名" → 拒绝注入（可能填错框）。
    无 step context 时保守放行。

    Returns:
        True 允许自动注入密码, False 不允许
    """
    if not step_text:
        return True
    lower = step_text.lower()
    if any(k in lower for k in ["密码", "password", "输入密码", "填密码", "pass"]):
        return True
    if any(k in lower for k in ["用户名", "账号", "username", "user", "account", "登录名", "邮箱", "email"]):
        return False
    return True


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------

@tool
async def navigate(url: str) -> dict[str, Any]:
    """导航到指定 URL。

    Args:
        url: 要导航到的完整 URL
    """
    page = get_current_page()
    before_url = page.url
    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await _wait_for_stable(page)
        return await _make_action_result("navigate", url, True, page, before_url)
    except Exception as e:
        return await _make_action_result("navigate", url, False, page, before_url, error=str(e))


@tool
async def click(target: str) -> dict[str, Any]:
    """点击页面上的元素。

    Args:
        target: 元素编号（如 #3）或元素描述（如 "登录按钮"）
    """
    page = get_current_page()
    before_url = page.url
    before_fp = await _get_dom_fingerprint(page)
    try:
        locator = await _resolve_element(target, page)
        await locator.click(timeout=10000)
        await _wait_for_stable(page)
        return await _make_action_result("click", target, True, page, before_url, before_fingerprint=before_fp)
    except Exception as e:
        return await _make_action_result("click", target, False, page, before_url, before_fingerprint=before_fp, error=str(e))


@tool
async def input_text(target: str, value: str) -> dict[str, Any]:
    """在输入框中输入文本。使用 press_sequentially() 逐字输入以触发前端完整事件校验。

    Args:
        target: 元素编号（如 #1）或元素描述（如 "用户名输入框"）
        value: 要输入的文本内容
    """
    page = get_current_page()
    before_url = page.url
    before_fp = await _get_dom_fingerprint(page)
    try:
        locator = await _resolve_element(target, page)
        
        # Check if this input field is a password field (根因 2)
        is_password_field = False
        try:
            input_type = await locator.get_attribute("type")
            if input_type == "password":
                is_password_field = True
        except Exception:
            pass

        if not is_password_field:
            lower_target = str(target).lower()
            # 扩大匹配范围: password / 密码 / pwd / passwd / pass
            if any(k in lower_target for k in ["password", "密码", "pwd", "passwd", "pass"]):
                is_password_field = True

        if is_password_field:
            # B1.1: 注入前校验步骤语义
            step_text = get_current_step_text()
            if not _should_auto_inject_password(get_task_config(), step_text):
                # 步骤语义不匹配: 不注入密码，按原值填入，并记录警告
                actual_filled = value
            else:
                # Let's search config accounts for matching username filled on the page
                task_config = get_task_config()
                accounts = task_config.get("accounts", [])
                matched_password = None
                
                # Find filled username value on the page
                username_val = ""
                try:
                    inputs = await page.query_selector_all("input")
                    for ip in inputs:
                        ip_type = await ip.get_attribute("type") or "text"
                        if ip_type in ["text", "email", "number", "tel"]:
                            val = await ip.input_value()
                            if val:
                                name = (await ip.get_attribute("name") or "").lower()
                                id_attr = (await ip.get_attribute("id") or "").lower()
                                placeholder = (await ip.get_attribute("placeholder") or "").lower()
                                if any(k in name or k in id_attr or k in placeholder for k in ["user", "name", "email", "phone", "account", "账号", "用户名"]):
                                    username_val = val
                                    break
                    
                    # Fallback: first non-empty input value that is not password/button
                    if not username_val:
                        for ip in inputs:
                            ip_type = await ip.get_attribute("type") or "text"
                            if ip_type not in ["password", "submit", "button", "checkbox", "radio"]:
                                val = await ip.input_value()
                                if val:
                                    username_val = val
                                    break
                except Exception:
                    pass
                
                if username_val:
                    for a in accounts:
                        if a.get("username") == username_val:
                            matched_password = a.get("password")
                            break
                
                if not matched_password and accounts:
                    # Check if any input value matches username
                    try:
                        all_vals = []
                        inputs = await page.query_selector_all("input")
                        for ip in inputs:
                            val = await ip.input_value()
                            if val:
                                all_vals.append(val.strip())
                        for a in accounts:
                            u = a.get("username")
                            if u and u.strip() in all_vals:
                                matched_password = a.get("password")
                                break
                    except Exception:
                        pass
                
                if not matched_password and accounts:
                    # Last resort fallback: first account's password
                    matched_password = accounts[0].get("password")
                    
                if matched_password:
                    value = matched_password
                actual_filled = value
        else:
            actual_filled = value

        await locator.click(timeout=5000)  # 先聚焦
        await locator.fill("", timeout=3000)  # 清空
        if value:
            await locator.press_sequentially(value, delay=50)
        await _wait_for_stable(page)
        result = await _make_action_result("input_text", target, True, page, before_url, before_fingerprint=before_fp)
        # B1.3: 记录实际填入值（密码脱敏）
        if is_password_field and actual_filled:
            masked = actual_filled[:2] + "****" if len(actual_filled) > 2 else "****"
            result["filled_value"] = masked
        else:
            result["filled_value"] = actual_filled
        return result
    except Exception as e:
        return await _make_action_result("input_text", target, False, page, before_url, before_fingerprint=before_fp, error=str(e))


@tool
async def scroll(direction: str, amount: int = 300) -> dict[str, Any]:
    """滚动页面。

    Args:
        direction: 滚动方向，"up" 或 "down"
        amount: 滚动像素数，默认 300
    """
    page = get_current_page()
    before_url = page.url
    before_fp = await _get_dom_fingerprint(page)
    try:
        delta = amount if direction == "down" else -amount
        await page.mouse.wheel(0, delta)
        await _wait_for_stable(page)
        return await _make_action_result("scroll", f"{direction}_{amount}", True, page, before_url, before_fingerprint=before_fp)
    except Exception as e:
        return await _make_action_result("scroll", f"{direction}_{amount}", False, page, before_url, before_fingerprint=before_fp, error=str(e))


@tool
async def wait(seconds: float = 1.0) -> dict[str, Any]:
    """等待指定秒数。用于等待页面加载或动画完成。

    Args:
        seconds: 等待秒数，默认 1.0
    """
    page = get_current_page()
    before_url = page.url
    try:
        await asyncio.sleep(seconds)
        await _wait_for_stable(page) if seconds < 3 else None
        return await _make_action_result("wait", str(seconds), True, page, before_url)
    except Exception as e:
        return await _make_action_result("wait", str(seconds), False, page, before_url, error=str(e))

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
async def press_key(key: str) -> dict[str, Any]:
    """按下键盘按键。例如 'Enter', 'Escape', 'Tab' 等。

    Args:
        key: 要按下的按键名称
    """
    page = get_current_page()
    before_url = page.url
    before_fp = await _get_dom_fingerprint(page)
    try:
        await page.keyboard.press(key)
        await _wait_for_stable(page)
        return await _make_action_result("press_key", key, True, page, before_url, before_fingerprint=before_fp)
    except Exception as e:
        return await _make_action_result("press_key", key, False, page, before_url, before_fingerprint=before_fp, error=str(e))

@tool
async def hover(target: str) -> dict[str, Any]:
    """悬停在页面上的元素上。适用于触发下拉菜单或提示框。

    Args:
        target: 元素编号（如 #3）或元素描述
    """
    page = get_current_page()
    before_url = page.url
    before_fp = await _get_dom_fingerprint(page)
    try:
        locator = await _resolve_element(target, page)
        await locator.hover(timeout=10000)
        await _wait_for_stable(page)
        return await _make_action_result("hover", target, True, page, before_url, before_fingerprint=before_fp)
    except Exception as e:
        return await _make_action_result("hover", target, False, page, before_url, before_fingerprint=before_fp, error=str(e))

@tool
async def go_back() -> dict[str, Any]:
    """在浏览器历史记录中后退一页。"""
    page = get_current_page()
    before_url = page.url
    before_fp = await _get_dom_fingerprint(page)
    try:
        await page.go_back(wait_until="networkidle", timeout=15000)
        await _wait_for_stable(page)
        return await _make_action_result("go_back", None, True, page, before_url, before_fingerprint=before_fp)
    except Exception as e:
        return await _make_action_result("go_back", None, False, page, before_url, before_fingerprint=before_fp, error=str(e))

@tool
async def extract_text(target: str) -> dict[str, Any]:
    """提取页面元素的文本内容。

    Args:
        target: 元素编号（如 #3）或元素描述
    """
    page = get_current_page()
    before_url = page.url
    try:
        locator = await _resolve_element(target, page)
        text = await locator.inner_text(timeout=5000)
        result = await _make_action_result("extract_text", target, True, page, before_url)
        result["extracted_content"] = text
        return result
    except Exception as e:
        return await _make_action_result("extract_text", target, False, page, before_url, error=str(e))

@tool
async def select_dropdown(target: str, value: str) -> dict[str, Any]:
    """从下拉菜单(select)中选择选项。

    Args:
        target: 元素编号（如 #3）或元素描述
        value: 要选择的选项的文本、value或label
    """
    page = get_current_page()
    before_url = page.url
    before_fp = await _get_dom_fingerprint(page)
    try:
        locator = await _resolve_element(target, page)
        await locator.select_option(value, timeout=10000)
        await _wait_for_stable(page)
        return await _make_action_result("select_dropdown", target, True, page, before_url, before_fingerprint=before_fp)
    except Exception as e:
        return await _make_action_result("select_dropdown", target, False, page, before_url, before_fingerprint=before_fp, error=str(e))

@tool
async def evaluate_js(script: str) -> dict[str, Any]:
    """在当前页面中执行一段 JavaScript 代码。

    Args:
        script: 要执行的 JavaScript 代码
    """
    blacklist = ("page.goto", "page.evaluate", "window.location", "location.href", "fetch(")
    lower = script.lower()
    for keyword in blacklist:
        if keyword in lower:
            page = get_current_page()
            return await _make_action_result(
                "evaluate_js", script[:50], False, page, page.url,
                error=f"拒绝执行: 脚本包含被禁关键字 {keyword!r}"
            )

    page = get_current_page()
    before_url = page.url
    try:
        wrapped_script = script
        if "return " in script and not script.strip().startswith("(") and not script.strip().startswith("function"):
            wrapped_script = f"(() => {{\n{script}\n}})()"
        result = await page.evaluate(wrapped_script)
        res = await _make_action_result("evaluate_js", script[:50], True, page, before_url)
        res["extracted_content"] = str(result)
        return res
    except Exception as e:
        return await _make_action_result("evaluate_js", script[:50], False, page, before_url, error=str(e))


@tool
async def mark_task_complete(reasoning: str) -> dict[str, Any]:
    """标记当前任务已成功完成，并结束执行。

    Args:
        reasoning: 任务成功的理由或发现，请尽量详细说明
    """
    page = get_current_page()
    return {
        **await _make_action_result("mark_task_complete", None, True, page, page.url),
        "display_text": f"任务标记为已成功: {reasoning}",
        "extracted_content": reasoning,
    }


@tool
async def mark_task_failed(reasoning: str) -> dict[str, Any]:
    """标记当前任务执行失败，无法继续，并结束执行。

    Args:
        reasoning: 任务失败的具体原因（如：找不到目标元素，页面报错等）
    """
    page = get_current_page()
    return {
        **await _make_action_result("mark_task_failed", None, False, page, page.url, error=reasoning),
        "display_text": f"任务标记为已失败: {reasoning}",
        "extracted_content": reasoning,
    }


@tool
async def mark_task_skipped(reasoning: str) -> dict[str, Any]:
    """标记当前任务被跳过（如前置条件已满足无需执行），并结束执行。

    Args:
        reasoning: 跳过任务的具体原因
    """
    page = get_current_page()
    return {
        **await _make_action_result("mark_task_skipped", None, True, page, page.url),
        "display_text": f"任务标记为已跳过: {reasoning}",
        "extracted_content": reasoning,
    }


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
    "set_task_config",
    "get_task_config",
    "get_element_map",
    "update_element_map",
    "set_current_task",
    "get_current_task_id",
    "cleanup_task_context",
    "set_current_step_text",
    "get_current_step_text",
    "_should_auto_inject_password",
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

# Backward-compat alias
ui_tools = tools
