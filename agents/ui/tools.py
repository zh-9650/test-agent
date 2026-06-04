"""agents/ui/tools.py — Playwright/CDP hybrid tool definitions for UI testing.

Defines @tool decorated functions that the LLM can call to interact with web pages.
Includes: click, input_text, navigate, scroll, wait, and other page interactions.

Phase 2.0C: CDP migration — 感知层和执行层都支持 CDP 后端,
使用 backendNodeId 锚定 + CDP Input.dispatchMouseEvent/Input.dispatchKeyEvent.
Playwright fallback 保留以兼容 Firefox/WebKit.
"""

from __future__ import annotations

import asyncio
import contextvars
import os
from typing import Any

from langchain_core.tools import tool

from core.cdp_client import (cdp_click, cdp_input_text, cleanup_cdp_session,
                              get_cdp_session, get_dom_fingerprint as cdp_fingerprint)
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
    cleanup_cdp_session(task_id)


def set_cdp_session(session: Any, task_id: str | None = None) -> None:
    """Phase 2.0C: Register CDP session for a task."""
    tid = task_id or _current_task_id.get()
    if tid is None:
        return
    ctx = _task_contexts.setdefault(tid, {"page": None, "element_map": {}})
    ctx["cdp_session"] = session


def get_cdp_session_ctx() -> Any | None:
    """Phase 2.0C: Get the current task's CDP session."""
    tid = _current_task_id.get()
    if tid is None:
        return None
    ctx = _task_contexts.get(tid, {})
    return ctx.get("cdp_session", None)


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
    """Phase 2.0C: CDP 优先的 DOM 指纹, 回退 JS evaluate."""
    cdp_sess = get_cdp_session_ctx()
    if cdp_sess:
        try:
            return await cdp_fingerprint(page, cdp_sess)
        except Exception:
            pass
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
    status: str | None = None,
    extracted_content: str | None = None,
    long_term_memory: str | None = None,
    candidates: list[dict[str, Any]] | None = None,
    filled_value: str | None = None,
    include_in_memory: bool = True,
    duration_ms: int = 0,
    evidence: dict[str, Any] | None = None,
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
        status: 细粒度状态 (success/failure/timeout/not_found), 默认根据 success 推断
        extracted_content: 工具提取的关键内容 (Phase 2.0D)
        long_term_memory: 给 LLM 的下一步建议 (Phase 2.0D)
        candidates: 失败时的备选元素列表 (Phase 2.0D)
        filled_value: input 实际填入值 (兼容 2.0B)
        include_in_memory: 是否进入 LLM 上下文
        duration_ms: 工具自身执行耗时
        evidence: 结构化证据
    """
    after_url = page.url
    if before_fingerprint is None:
        before_fingerprint = "0_0_0"
    after_fingerprint = await _get_dom_fingerprint(page)

    # 推断 status (Phase 2.0D)
    if status is None:
        if success:
            status = "success"
        elif error and ("timeout" in error.lower() or "超时" in error):
            status = "timeout"
        elif error and ("not found" in error.lower() or "找不到" in error or "no element" in error.lower()):
            status = "not_found"
        else:
            status = "failure"

    # 缺省 long_term_memory (Phase 2.0D)
    if long_term_memory is None and not success:
        long_term_memory = (
            f"动作 {action} 失败: {error}. "
            f"建议: 1) 检查目标元素是否可见 2) 尝试备选定位 (xpath/text/role) 3) 刷新页面后重试"
        )

    return ActionResult(
        action=action,
        target=target,
        success=success,
        error=error,
        before_url=before_url,
        after_url=after_url,
        page_changed=(before_fingerprint != after_fingerprint),
        url_changed=(before_url != after_url),
        filled_value=filled_value if filled_value is not None else "",
        status=status,
        extracted_content=extracted_content,
        long_term_memory=long_term_memory,
        candidates=candidates or [],
        include_in_memory=include_in_memory,
        duration_ms=duration_ms,
        evidence=evidence or {},
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
        return await _make_action_result(
            "navigate", url, True, page, before_url,
            extracted_content=f"已导航至 {page.url}",
        )
    except Exception as e:
        return await _make_action_result(
            "navigate", url, False, page, before_url,
            error=str(e),
            status="timeout" if "timeout" in str(e).lower() else "failure",
            long_term_memory=f"导航失败: {e}. 建议: 1) 检查 URL 是否合法 2) 检查网络 3) 尝试 page.reload()",
        )


@tool
async def click(target: str) -> dict[str, Any]:
    """点击页面上的元素。Phase 2.0C: CDP Input.dispatchMouseEvent 优先。

    Args:
        target: 元素编号（如 #3）或元素描述（如 "登录按钮"）
    """
    page = get_current_page()
    before_url = page.url
    before_fp = await _get_dom_fingerprint(page)
    cdp_sess = get_cdp_session_ctx()
    import time as _time
    _t0 = _time.time()
    try:
        locator = await _resolve_element(target, page)

        # Phase 2.0C: CDP click path — 通过坐标精准点击
        if cdp_sess:
            try:
                el_info = _get_element_info(target)
                coords = el_info.get("coords", {}) if el_info else {}
                if coords and coords.get("x") is not None and coords.get("y") is not None:
                    cx = coords["x"] + coords.get("width", 0) / 2
                    cy = coords["y"] + coords.get("height", 0) / 2
                    clicked = await cdp_click(page, cdp_sess, cx, cy)
                    if clicked:
                        await _wait_for_stable(page)
                        # Phase 2.0D: extracted_content = 元素 text (给 LLM 看点击了啥)
                        el_text = (el_info or {}).get("text", "")
                        el_label = (el_info or {}).get("label", "")
                        return await _make_action_result(
                            "click", target, True, page, before_url,
                            before_fingerprint=before_fp,
                            extracted_content=f"已点击元素 '{el_text or el_label or target}'",
                            duration_ms=int((_time.time() - _t0) * 1000),
                        )
            except Exception:
                pass

        # Fallback: Playwright locator click
        await locator.click(timeout=10000)
        await _wait_for_stable(page)
        return await _make_action_result(
            "click", target, True, page, before_url,
            before_fingerprint=before_fp,
            extracted_content=f"已点击元素 '{target}'",
            duration_ms=int((_time.time() - _t0) * 1000),
        )
    except Exception as e:
        # Phase 2.0D: 失败时构造 candidates (相似元素供 LLM 重选)
        cands = _find_similar_elements(target, page, max_n=3)
        return await _make_action_result(
            "click", target, False, page, before_url,
            before_fingerprint=before_fp,
            error=str(e),
            status="not_found" if "not found" in str(e).lower() or "timeout" in str(e).lower() else "failure",
            candidates=cands,
            duration_ms=int((_time.time() - _t0) * 1000),
        )


def _get_element_info(target: str) -> dict[str, Any] | None:
    """Phase 2.0C: 从 element_map 查找元素信息。"""
    tid = _current_task_id.get()
    ctx = _task_contexts.get(tid, {}) if tid else {}
    element_map = ctx.get("element_map", {})
    lookup_key = _normalize_target(target)
    return element_map.get(lookup_key)


def _find_similar_elements(target: str, page: Any, max_n: int = 3) -> list[dict[str, Any]]:
    """Phase 2.0D: 在 element_map 中找相似元素, 用于 click/input 失败时给 LLM 备选。

    相似度策略: text/label 包含 target 子串, 或 target 是数字时按 type 过滤
    """
    try:
        tid = _current_task_id.get()
        ctx = _task_contexts.get(tid, {}) if tid else {}
        element_map = ctx.get("element_map", {})
        target_lower = str(target).lower().strip()
        scored: list[tuple[int, dict[str, Any]]] = []
        for key, info in element_map.items():
            text = (info.get("text") or info.get("label") or "").lower()
            score = 0
            if target_lower and target_lower in text:
                score = 100 - len(text)  # 短文本优先
            elif text and target_lower and text in target_lower:
                score = 50
            elif key == target:
                score = 30
            if score > 0:
                scored.append((score, {k: info.get(k) for k in ("text", "label", "type", "role", "id") if info.get(k)}))
        scored.sort(key=lambda x: -x[0])
        return [item for _, item in scored[:max_n]]
    except Exception:
        return []


@tool
async def input_text(target: str, value: str) -> dict[str, Any]:
    """在输入框中输入文本。Phase 2.0C: CDP Input.dispatchKeyEvent 逐字输入优先。

    Args:
        target: 元素编号（如 #1）或元素描述（如 "用户名输入框"）
        value: 要输入的文本内容
    """
    page = get_current_page()
    before_url = page.url
    before_fp = await _get_dom_fingerprint(page)
    cdp_sess = get_cdp_session_ctx()
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
            if any(k in lower_target for k in ["password", "密码", "pwd", "passwd", "pass"]):
                is_password_field = True

        actual_filled = value
        if is_password_field:
            step_text = get_current_step_text()
            if not _should_auto_inject_password(get_task_config(), step_text):
                actual_filled = value
            else:
                task_config = get_task_config()
                accounts = task_config.get("accounts", [])
                matched_password = None
                
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
                    matched_password = accounts[0].get("password")
                    
                if matched_password:
                    value = matched_password
                actual_filled = value

        # Focus first via click
        await locator.click(timeout=5000)

        # Phase 2.0C: CDP keyboard input path
        cdp_used = False
        if cdp_sess and value:
            try:
                typed = await cdp_input_text(cdp_sess, value)
                if typed:
                    cdp_used = True
            except Exception:
                pass

        if not cdp_used:
            await locator.fill("", timeout=3000)
            if value:
                await locator.press_sequentially(value, delay=50)

        await _wait_for_stable(page)
        # Phase 2.0D: 脱敏 filled_value
        if is_password_field and actual_filled:
            masked = actual_filled[:2] + "****" if len(actual_filled) > 2 else "****"
        else:
            masked = actual_filled
        return await _make_action_result(
            "input_text", target, True, page, before_url,
            before_fingerprint=before_fp,
            filled_value=masked,
            extracted_content=f"已在 '{target}' 输入 '{masked}'",
        )
    except Exception as e:
        # Phase 2.0D: 失败时给候选
        cands = _find_similar_elements(target, page, max_n=3)
        return await _make_action_result(
            "input_text", target, False, page, before_url,
            before_fingerprint=before_fp,
            error=str(e),
            status="not_found" if "not found" in str(e).lower() or "timeout" in str(e).lower() else "failure",
            candidates=cands,
        )


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
        return await _make_action_result(
            "scroll", f"{direction}_{amount}", True, page, before_url,
            before_fingerprint=before_fp,
            extracted_content=f"已向 {direction} 滚动 {amount}px",
        )
    except Exception as e:
        return await _make_action_result(
            "scroll", f"{direction}_{amount}", False, page, before_url,
            before_fingerprint=before_fp, error=str(e),
        )


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
        return await _make_action_result(
            "wait", str(seconds), True, page, before_url,
            extracted_content=f"已等待 {seconds}s",
        )
    except Exception as e:
        return await _make_action_result("wait", str(seconds), False, page, before_url, error=str(e))


# Phase 2.0D: 截图-on-demand (L2_OBSERVE_SCREENSHOT 默认关, 节约 context)
_screenshot_budget: dict[str, int] = {}  # task_id -> remaining screenshots


def _consume_screenshot_quota(task_id: str | None) -> bool:
    """Check and decrement the per-task screenshot quota.

    Default budget is 2 per task (overridable via L2_SCREENSHOT_BUDGET env).
    Returns True if quota remains, False if exhausted.
    """
    if not task_id:
        return True  # no task_id = no quota (test mode)
    budget = int(os.getenv("L2_SCREENSHOT_BUDGET", "2"))
    used = _screenshot_budget.get(task_id, 0)
    if used >= budget:
        return False
    _screenshot_budget[task_id] = used + 1
    return True


def _screenshot_quota_remaining(task_id: str | None) -> int:
    if not task_id:
        return int(os.getenv("L2_SCREENSHOT_BUDGET", "2"))
    budget = int(os.getenv("L2_SCREENSHOT_BUDGET", "2"))
    return max(0, budget - _screenshot_budget.get(task_id, 0))


def reset_screenshot_budget(task_id: str) -> None:
    """Reset screenshot quota for a task (call on task end)."""
    _screenshot_budget.pop(task_id, None)


@tool
async def screenshot_on_demand(reason: str) -> dict[str, Any]:
    """当页面元素位置/状态不确定时, 主动请求截图供 LLM 视觉分析。

    Phase 2.0D 混合策略: observe_node 默认不截图 (节省 context),
    LLM 遇到需要视觉判断的场景 (例如:
    - 找不到元素, 但页面可能有视觉干扰
    - 颜色/图标差异需要确认
    - 弹窗/动画状态不确定) 时显式调用本工具。

    配额: 每个测试用例最多调用 2 次 (env L2_SCREENSHOT_BUDGET 可改)。
    截图采用 JPEG quality=70, 1280×720, 约 5-15KB base64,
    直接注入到 LLM tool_message 上下文。

    Args:
        reason: 调用截图的原因 (例如 "按钮位置不确定, 需视觉确认")
    """
    page = get_current_page()
    before_url = page.url
    task_id = get_current_task_id()
    if not _consume_screenshot_quota(task_id):
        return await _make_action_result(
            "screenshot_on_demand", reason, False, page, before_url,
            error=f"screenshot quota exhausted (used {_screenshot_budget.get(task_id, 0)}/{os.getenv('L2_SCREENSHOT_BUDGET', '2')})",
            status="failure",
            extracted_content=(
                f"截图配额已用完 ({os.getenv('L2_SCREENSHOT_BUDGET', '2')} 次/用例上限). "
                f"请基于现有 page_info 文本信息继续决策, 避免再次请求截图。"
            ),
        )
    try:
        # Phase 2.0D: 固定 1280×720 JPEG q=70 (比默认 q=60 略高, 因 on-demand 看重点)
        from core.page_semantic import take_screenshot_compressed
        screenshot_b64 = await take_screenshot_compressed(page, quality=70)
        return {
            **await _make_action_result(
                "screenshot_on_demand", reason, True, page, before_url,
                extracted_content=(
                    f"已截取屏幕供视觉分析 (原因: {reason}). "
                    f"剩余配额: {_screenshot_quota_remaining(task_id)}/{os.getenv('L2_SCREENSHOT_BUDGET', '2')}."
                ),
            ),
            "screenshot_b64": screenshot_b64,
            "screenshot_injected": True,
        }
    except Exception as e:
        return await _make_action_result(
            "screenshot_on_demand", reason, False, page, before_url,
            error=str(e),
        )


@tool
async def parallel_tool_calls(
    calls: list[dict[str, str]],
    reason: str = "",
) -> dict[str, Any]:
    """并发执行多个独立的工具调用 (Phase 2.0D 优化).

    适用场景 (LLM 应主动判断):
    - 同时填写多个独立字段 (用户名 + 密码 + 邮箱)
    - 同时点击多个独立按钮 (确认 + 取消)
    - 同时 extract 多个不同元素

    不适用 (会降级串行):
    - 任一工具是 navigate / go_back (导航会换页面)
    - 两个工具 target 重叠
    - 包含 mark_task_* (标记类必最后)
    - 包含 evaluate_js (JS 状态改变)

    配置: 默认 L2_PARALLEL_TOOLS=0 禁用 (保持串行), 设 1 启用真正的并发执行.
    当 env 禁用时, 本工具会按原顺序串行执行, 不抛错.

    Args:
        calls: list of {"name": "click", "args": {"target": "#1"}}
        reason: 调用原因 (例如 "用户名/密码/邮箱是独立字段, 可并发")
    """
    page = get_current_page()
    before_url = page.url
    if not calls:
        return await _make_action_result(
            "parallel_tool_calls", reason, False, page, before_url,
            error="empty calls list",
        )
    try:
        from core.parallel_executor import execute_parallel_calls, is_parallel_enabled
        from core.dependency import split_independent_groups

        waves = split_independent_groups(calls)
        parallel_mode = is_parallel_enabled()
        results = await execute_parallel_calls(calls)

        # 统计
        success_count = sum(1 for r in results if r.get("status") == "success")
        n_waves = len(waves)
        max_concurrency = max((len(w) for w in waves), default=0)

        return await _make_action_result(
            "parallel_tool_calls", reason, True, page, before_url,
            extracted_content=(
                f"已执行 {len(calls)} 个调用 ({n_waves} wave, 最大并发={max_concurrency}, "
                f"模式={'并发' if parallel_mode else '串行降级'}). "
                f"成功: {success_count}/{len(calls)}."
            ),
        )
    except Exception as e:
        return await _make_action_result(
            "parallel_tool_calls", reason, False, page, before_url,
            error=str(e),
        )


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
        return await _make_action_result(
            "press_key", key, True, page, before_url,
            before_fingerprint=before_fp,
            extracted_content=f"已按键 {key}",
        )
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
        return await _make_action_result(
            "hover", target, True, page, before_url,
            before_fingerprint=before_fp,
            extracted_content=f"已悬停于 '{target}'",
        )
    except Exception as e:
        cands = _find_similar_elements(target, page, max_n=3)
        return await _make_action_result(
            "hover", target, False, page, before_url,
            before_fingerprint=before_fp, error=str(e),
            status="not_found" if "timeout" in str(e).lower() else "failure",
            candidates=cands,
        )

@tool
async def go_back() -> dict[str, Any]:
    """在浏览器历史记录中后退一页。"""
    page = get_current_page()
    before_url = page.url
    before_fp = await _get_dom_fingerprint(page)
    try:
        await page.go_back(wait_until="networkidle", timeout=15000)
        await _wait_for_stable(page)
        return await _make_action_result(
            "go_back", None, True, page, before_url,
            before_fingerprint=before_fp,
            extracted_content=f"已后退至 {page.url}",
        )
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
        return await _make_action_result(
            "extract_text", target, True, page, before_url,
            extracted_content=text,  # Phase 2.0D: 核心目的就是提取文本
        )
    except Exception as e:
        cands = _find_similar_elements(target, page, max_n=3)
        return await _make_action_result(
            "extract_text", target, False, page, before_url,
            error=str(e),
            status="not_found" if "timeout" in str(e).lower() else "failure",
            candidates=cands,
        )

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
        return await _make_action_result(
            "select_dropdown", target, True, page, before_url,
            before_fingerprint=before_fp,
            extracted_content=f"已在 '{target}' 选择 '{value}'",
        )
    except Exception as e:
        cands = _find_similar_elements(target, page, max_n=3)
        return await _make_action_result(
            "select_dropdown", target, False, page, before_url,
            before_fingerprint=before_fp, error=str(e),
            status="not_found" if "timeout" in str(e).lower() else "failure",
            candidates=cands,
        )

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
        return await _make_action_result(
            "evaluate_js", script[:50], True, page, before_url,
            extracted_content=str(result),
        )
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
    "screenshot_on_demand",
    "parallel_tool_calls",
    "reset_screenshot_budget",
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
    "set_cdp_session",
    "get_cdp_session_ctx",
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
    screenshot_on_demand,
    parallel_tool_calls,
]

# Provide a map for easy invocation by name
tools_by_name = {t.name: t for t in tools}

# Backward-compat alias
ui_tools = tools
