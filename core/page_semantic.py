"""core/page_semantic.py — Page Semantic Layer

Extracts a semantic summary from a Playwright page using the Locator API.
This is the "eyes" of the AI testing agent.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any

logger = logging.getLogger("antigravity.page_semantic")

def track_page_requests(page: Any) -> None:
    """Attach request/response/dialog/popup listeners to page.

    Tracks:
    - _pending_requests: set of in-flight Playwright Request objects
    - _request_log: list of (method, url, start_time) for pending, used to render URL+method
    - _closed_popups: list of popup descriptions auto-dismissed (max 20, ring buffer)
    - _popup_pages: list of new Page objects opened via window.open
    """
    if not hasattr(page, "_pending_requests"):
        page._pending_requests = set()
        page._request_log = []
        page._closed_popups = []
        page._popup_pages = []

        def on_request(request):
            if not request.url.startswith("data:"):
                page._pending_requests.add(request)
                try:
                    import time as _t
                    page._request_log.append({
                        "method": request.method,
                        "url": request.url,
                        "start": _t.time(),
                    })
                except Exception:
                    pass

        def on_request_finished(request):
            page._pending_requests.discard(request)
            try:
                if page._request_log:
                    entry = page._request_log[0]
                    if entry.get("url") == request.url:
                        page._request_log.pop(0)
            except Exception:
                pass

        def on_request_failed(request):
            page._pending_requests.discard(request)
            try:
                if page._request_log:
                    entry = page._request_log[0]
                    if entry.get("url") == request.url:
                        page._request_log.pop(0)
            except Exception:
                pass

        def on_dialog(dialog):
            try:
                page._closed_popups.append(
                    f"{dialog.type}: \"{dialog.message[:80]}\" (auto-dismissed)"
                )
                if len(page._closed_popups) > 20:
                    page._closed_popups = page._closed_popups[-20:]
                dialog.dismiss()
            except Exception:
                try:
                    dialog.dismiss()
                except Exception:
                    pass

        def on_popup(popup_page):
            try:
                page._popup_pages.append(popup_page)
                page._closed_popups.append(
                    f"window.open: {popup_page.url} (auto-tracked)"
                )
                if len(page._closed_popups) > 20:
                    page._closed_popups = page._closed_popups[-20:]
            except Exception:
                pass

        page.on("request", on_request)
        page.on("requestfinished", on_request_finished)
        page.on("requestfailed", on_request_failed)
        page.on("dialog", on_dialog)
        page.on("popup", on_popup)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def extract_page_semantics(page: Any, task_id: str | None = None,
                                current_step: int = 0) -> dict[str, Any]:
    """从 Playwright page 提取页面语义摘要。

    使用 Playwright locator API（不用 querySelectorAll），框架无关。
    三层信息：
    - Layer 1: 交互元素（inputs, buttons, links, selects, checkboxes, tables）
    - Layer 2: 页面结构（URL, title, headings, breadcrumbs, nav, forms, modals）
    - Layer 3: 状态信息（loading, errors, validation, empty states, pagination）

    约束（来自 CONTEXT.md）：
    ① 每个可交互元素有编号（#1, #2, ...）供 LLM 精确引用
    ② 单页提取结果不超过 2000 tokens
    ③ 超过 50 个交互元素时截断

    Phase 2.0D: 当 task_id 提供时, 将元素的 backendNodeId 持久化到
    BackendNodeMap, 供后续步骤直接 resolveNode 复用, 避免每次重走 AXTree。

    Args:
        page: Playwright Page 对象
        task_id: 可选, 持久化 backendNodeId 到 BackendNodeMap
        current_step: 当前步数 (用于 age-based pruning)

    Returns:
        dict 格式的页面语义摘要
    """
    result: dict[str, Any] = {
        "url": page.url,
        "title": await page.title(),
        "interactive_elements": [],
        "headings": [],
        "forms": [],
        "modals": [],
        "nav_items": [],
        "error_messages": [],
        "js_errors": [],
        "network_errors": [],
        "loading": False,
        "pagination": None,
        "tables": [],
        "truncated": False,
    }

    # Layer 2: Page structure
    result["headings"] = await _extract_headings(page)
    result["forms"] = await _extract_forms(page)
    result["modals"] = await _extract_modals(page)
    result["nav_items"] = await _extract_nav_items(page)

    # Layer 3: State information
    result["error_messages"] = await _extract_error_messages(page)
    result["loading"] = await _detect_loading(page)
    result["pagination"] = await _extract_pagination(page)

    # Viewport Info
    viewport_info = {}
    try:
        viewport_info = await page.evaluate("""() => {
            const scrollY = window.scrollY;
            const innerHeight = window.innerHeight;
            const scrollHeight = document.body.scrollHeight;
            return {
                scrollY: scrollY,
                scrollX: window.scrollX,
                innerHeight: innerHeight,
                innerWidth: window.innerWidth,
                scrollHeight: scrollHeight,
                is_bottom: scrollY + innerHeight >= scrollHeight - 5
            };
        }""")
        result["viewport"] = viewport_info
    except Exception:
        pass

    # Tabs info (multi-tab awareness)
    try:
        context = page.context
        tabs = []
        for i, p in enumerate(context.pages):
            tabs.append({
                "index": i,
                "title": await p.title(),
                "url": p.url,
                "active": (p == page),
            })
        if tabs:
            result["tabs"] = tabs
    except Exception:
        pass

    # Track and count pending requests (with URL/method for LLM context)
    try:
        track_page_requests(page)
        pending = getattr(page, "_pending_requests", set())
        request_log = getattr(page, "_request_log", [])
        result["pending_requests"] = len(pending)
        if request_log:
            import time as _t
            now = _t.time()
            enriched = []
            for entry in request_log[-8:]:
                dur_ms = int((now - entry.get("start", now)) * 1000)
                url = entry.get("url", "")
                if len(url) > 80:
                    url = url[:77] + "..."
                enriched.append(f"{entry.get('method', '?')} {url} ({dur_ms}ms)")
            result["pending_requests_detail"] = enriched
    except Exception:
        pass

    # Closed popups / dialogs (auto-dismissed events)
    try:
        closed_popups = getattr(page, "_closed_popups", [])
        if closed_popups:
            result["closed_popups"] = list(closed_popups[-10:])
    except Exception:
        pass

    # Layer 1: Interactive elements (collected last so we can truncate)
    all_interactive_elements = await _collect_interactive_elements(page)

    # Fallback truncation if still too many elements (env-overridable, default 100)
    import os as _os
    max_elements = int(_os.getenv("L2_MAX_INTERACTIVE_ELEMENTS", "100"))

    # Viewport filtering — only apply if total elements > max_elements to avoid blind spots (issue 5)
    interactive_elements = []
    if viewport_info and len(all_interactive_elements) > max_elements:
        sy = viewport_info.get("scrollY", 0)
        sx = viewport_info.get("scrollX", 0)
        ih = viewport_info.get("innerHeight", 1080)
        iw = viewport_info.get("innerWidth", 1920)

        # Generous buffers so sidebar/navigation and nearby off-screen elements remain visible
        buffer_y = 1000
        buffer_x = 500
        for el in all_interactive_elements:
            coords = el.get("coords")
            if not coords:
                interactive_elements.append(el)
                continue

            # Use top-left corner (box_x/box_y) for intersection, not center
            top = coords.get("box_y", coords.get("y", 0))
            left = coords.get("box_x", coords.get("x", 0))
            h = coords.get("height", 0)
            w = coords.get("width", 0)

            # Intersection check with buffers
            if (top + h > sy - buffer_y) and (top < sy + ih + buffer_y) and (left + w > sx - buffer_x) and (left < sx + iw + buffer_x):
                interactive_elements.append(el)
    else:
        interactive_elements = all_interactive_elements

    # Set viewport filtering hint flag
    result["_off_viewport_filter_skipped"] = (len(all_interactive_elements) > len(interactive_elements))

    if len(interactive_elements) > max_elements:
        interactive_elements = interactive_elements[:max_elements]
        result["truncated"] = True
        result["_total_interactive_count"] = len(all_interactive_elements)
    result["interactive_elements"] = interactive_elements

    # Tables are also interactive / structural
    result["tables"] = await _extract_tables(page)

    # Phase 2.0D: 持久化 backendNodeId 到 BackendNodeMap
    if task_id:
        try:
            from core import backend_node_map
            for el in interactive_elements:
                bid = el.get("backend_node_id")
                if bid:
                    backend_node_map.store(
                        task_id=task_id,
                        element_id=el.get("id", ""),
                        backend_node_id=bid,
                        frame_id=el.get("frame_id", ""),
                        attrs={
                            "tag": el.get("type", ""),
                            "text": el.get("text", "")[:50],
                            "role": el.get("role", ""),
                            "input_type": el.get("input_type", ""),
                        },
                        current_step=current_step,
                    )
        except Exception:
            # 持久化失败不应影响语义提取
            pass

    return result


async def take_screenshot(page: Any) -> str:
    """截取当前页面截图，返回 base64 编码字符串。

    Args:
        page: Playwright Page 对象

    Returns:
        base64 编码的截图字符串
    """
    screenshot_bytes = await page.screenshot(type="png")
    return base64.b64encode(screenshot_bytes).decode("utf-8")


async def take_screenshot_compressed(page: Any, quality: int | None = None) -> str:
    """V2.0 A2 (2026-06-02): 压缩截图供 LLM 上下文使用。

    设计理由:
    - 默认 PNG (1280x720) ~50-200KB, base64 编码后 ~67-267K 字符
    - 算 token (中文 1.5 char/token): 17K-67K tokens, 撞 L2 65K context 风险
    - JPEG quality=60: ~10-30KB, 2.5K-7.5K tokens (~80% 减少)
    - LLM 视觉理解对 JPEG quality>=60 几乎无损
    - 仍用 base64 编码 (与现有 image_url data: 协议兼容)

    Args:
        page: Playwright Page 对象
        quality: JPEG 质量 1-100, 默认 60 (从 env L2_SCREENSHOT_QUALITY 读取)

    Returns:
        base64 编码的 JPEG 字符串 (data URI 前缀由调用方加)
    """
    if quality is None:
        quality = int(os.getenv("L2_SCREENSHOT_QUALITY", "60"))
    quality = max(10, min(95, quality))  # clamp 到合理范围
    screenshot_bytes = await page.screenshot(type="jpeg", quality=quality)
    return base64.b64encode(screenshot_bytes).decode("utf-8")


# ---------------------------------------------------------------------------
# Layer 1 — Interactive Elements
# ---------------------------------------------------------------------------


async def _collect_interactive_elements(page: Any) -> list[dict[str, Any]]:
    """Phase 2.0C: CDP AXTree 优先, 回退 browser-use DOM service, 最差 Playwright locator."""
    # Priority 1: CDP AXTree (Phase 2.0C Sprint 1)
    try:
        from core.cdp_client import extract_elements_via_cdp, get_cdp_session
        cdp_session = await get_cdp_session(page)
        if cdp_session:
            cdp_elements = await extract_elements_via_cdp(page, cdp_session)
            if cdp_elements:
                return cdp_elements
    except Exception:
        pass

    # Priority 2: browser-use DOM service (existing)
    session = getattr(page, "_browser_session", None)
    if session:
        elements: list[dict[str, Any]] = []
        try:
            state = await session.get_browser_state_summary()
            if state.dom_state and state.dom_state.selector_map:
                for idx, node in state.dom_state.selector_map.items():
                    elements.append({
                        "id": f"#{idx}",
                        "type": node.tag_name or "element",
                        "xpath": node.xpath,
                        "text": node.get_meaningful_text_for_llm(),
                    })
            return elements
        except Exception as e:
            logger.warning(f"BrowserSession extraction failed: {e}")

    # Priority 3: Playwright locator fallback
    elements = []
    counter = 1

    # Inputs (excluding hidden, checkboxes, radios — those have dedicated extractors below)
    inputs = page.locator("input:visible:not([type='checkbox']):not([type='radio'])")
    input_count = await inputs.count()
    for i in range(input_count):
        el = inputs.nth(i)
        try:
            info = await _extract_input(page, el, counter)
            if info:
                elements.append(info)
                counter += 1
        except Exception:
            pass

    # Buttons
    buttons = page.locator("button:visible, input[type='submit']:visible, input[type='button']:visible, [role='button']:visible")
    button_count = await buttons.count()
    for i in range(button_count):
        el = buttons.nth(i)
        try:
            info = await _extract_button(el, counter)
            if info:
                elements.append(info)
                counter += 1
        except Exception:
            pass

    # Links
    links = page.locator("a:visible[href]")
    link_count = await links.count()
    for i in range(link_count):
        el = links.nth(i)
        try:
            info = await _extract_link(el, counter)
            if info:
                elements.append(info)
                counter += 1
        except Exception:
            pass

    # Selects
    selects = page.locator("select:visible")
    select_count = await selects.count()
    for i in range(select_count):
        el = selects.nth(i)
        try:
            info = await _extract_select(page, el, counter)
            if info:
                elements.append(info)
                counter += 1
        except Exception:
            pass

    # Checkboxes
    checkboxes = page.locator("input[type='checkbox']:visible")
    checkbox_count = await checkboxes.count()
    for i in range(checkbox_count):
        el = checkboxes.nth(i)
        try:
            info = await _extract_checkbox(page, el, counter)
            if info:
                elements.append(info)
                counter += 1
        except Exception:
            pass

    # Radios
    radios = page.locator("input[type='radio']:visible")
    radio_count = await radios.count()
    for i in range(radio_count):
        el = radios.nth(i)
        try:
            info = await _extract_radio(page, el, counter)
            if info:
                elements.append(info)
                counter += 1
        except Exception:
            pass

    return elements


async def _get_element_role(el: Any, el_type: str, tag: str = "") -> str:
    """Get the ARIA role for an element."""
    try:
        role = await el.get_attribute("role")
        if role:
            return role
    except Exception:
        pass
    role_map = {
        "button": "button",
        "link": "link",
        "checkbox": "checkbox",
        "radio": "radio",
        "select": "combobox",
        "input": "textbox" if tag != "submit" else "button",
    }
    return role_map.get(el_type, tag or el_type)


async def _get_element_semantics(el: Any, el_type: str, page: Any = None) -> dict[str, Any]:
    """Phase 2.0A Sprint 4: 获取元素的可见/启用/交互/只读/选中等语义状态。"""
    visible = False
    enabled = False
    readonly = False
    checked = None
    selected = False

    try:
        visible = await el.is_visible()
    except Exception:
        pass

    try:
        enabled = await el.is_enabled()
    except Exception:
        pass

    try:
        ro = await el.get_attribute("readonly")
        readonly = ro is not None
    except Exception:
        pass

    if el_type in ("checkbox", "radio"):
        try:
            checked = await el.is_checked()
        except Exception:
            pass
        if checked is None:
            try:
                aria = await el.get_attribute("aria-checked")
                if aria is not None:
                    checked = aria.lower() == "true"
            except Exception:
                pass
        if checked is None:
            checked = False
    elif el_type == "input":
        try:
            it = await el.get_attribute("type") or "text"
            if it in ("checkbox", "radio"):
                try:
                    checked = await el.is_checked()
                except Exception:
                    pass
                if checked is None:
                    checked = False
        except Exception:
            pass

    try:
        selected_attr = await el.get_attribute("selected")
        selected = selected_attr is not None
    except Exception:
        pass

    expanded = None
    required = False

    try:
        exp = await el.get_attribute("aria-expanded")
        if exp is not None:
            expanded = exp.lower() == "true"
    except Exception:
        pass

    try:
        req = await el.get_attribute("required")
        if req is not None:
            required = True
        else:
            aria_req = await el.get_attribute("aria-required")
            if aria_req is not None:
                required = aria_req.lower() == "true"
    except Exception:
        pass

    tag = ""
    try:
        tag = await el.evaluate("el => el.tagName.toLowerCase()")
    except Exception:
        pass

    role = await _get_element_role(el, el_type, tag)

    return {
        "visible": visible,
        "enabled": enabled,
        "interactable": visible and enabled,
        "readonly": readonly,
        "checked": checked,
        "selected": selected,
        "role": role,
        "expanded": expanded,
        "required": required,
    }


async def _get_bbox(el: Any) -> dict[str, Any]:
    """Shared bounding box extractor for all element types.

    Returns coords dict with:
      x, y     = center point (for CDP click)
      box_x, box_y = top-left corner (for viewport filtering)
      width, height
    """
    try:
        bbox = await el.bounding_box()
        if bbox:
            return {
                "x": round(bbox["x"] + bbox["width"] / 2),
                "y": round(bbox["y"] + bbox["height"] / 2),
                "box_x": round(bbox["x"]),
                "box_y": round(bbox["y"]),
                "width": round(bbox["width"]),
                "height": round(bbox["height"]),
            }
    except Exception:
        pass
    return {}


async def _extract_input(page: Any, el: Any, counter: int) -> dict[str, Any] | None:
    """Extract info from an input element."""
    input_type = await el.get_attribute("type") or "text"
    label = await _find_label(page, el)
    placeholder = await el.get_attribute("placeholder") or ""
    required = await el.get_attribute("required") is not None
    disabled = False
    try:
        disabled = await el.is_disabled()
    except Exception:
        pass

    value = ""
    if input_type != "password":
        try:
            value = await el.input_value()
        except Exception:
            pass
    else:
        value = "***"

    semantics = await _get_element_semantics(el, "input", page)
    coords = await _get_bbox(el)

    return {
        "id": f"#{counter}",
        "type": "input",
        "input_type": input_type,
        "label": label,
        "placeholder": placeholder,
        "required": required,
        "disabled": disabled,
        "value": value,
        "coords": coords,
        **semantics,
    }


async def _extract_button(el: Any, counter: int) -> dict[str, Any] | None:
    """Extract info from a button element."""
    text = await el.text_content() or ""
    text = text.strip()
    if not text:
        aria_label = await el.get_attribute("aria-label")
        if aria_label:
            text = aria_label.strip()
        else:
            title = await el.get_attribute("title")
            if title:
                text = title.strip()

    button_type = await el.get_attribute("type") or "button"
    disabled = False
    try:
        disabled = await el.is_disabled()
    except Exception:
        pass

    semantics = await _get_element_semantics(el, "button")
    coords = await _get_bbox(el)

    return {
        "id": f"#{counter}",
        "type": "button",
        "text": text,
        "button_type": button_type,
        "disabled": disabled,
        "coords": coords,
        **semantics,
    }


async def _extract_link(el: Any, counter: int) -> dict[str, Any] | None:
    """Extract info from a link element."""
    text = await el.text_content() or ""
    text = text.strip()
    if not text:
        aria_label = await el.get_attribute("aria-label")
        if aria_label:
            text = aria_label.strip()
        else:
            title = await el.get_attribute("title")
            if title:
                text = title.strip()

    href = await el.get_attribute("href") or ""

    semantics = await _get_element_semantics(el, "link")
    coords = await _get_bbox(el)

    return {
        "id": f"#{counter}",
        "type": "link",
        "text": text,
        "href": href,
        "coords": coords,
        **semantics,
    }


async def _extract_select(page: Any, el: Any, counter: int) -> dict[str, Any] | None:
    """Extract info from a select element."""
    label = await _find_label(page, el)
    options = await el.evaluate("""
        el => Array.from(el.options).map(o => o.text.trim())
    """)
    selected_value = ""
    try:
        selected_value = await el.evaluate("""
            el => {
                const opt = el.options[el.selectedIndex];
                return opt ? opt.text.trim() : "";
            }
        """) or ""
    except Exception:
        pass

    semantics = await _get_element_semantics(el, "select", page)
    coords = await _get_bbox(el)

    return {
        "id": f"#{counter}",
        "type": "select",
        "label": label,
        "options": options or [],
        "value": selected_value,
        "coords": coords,
        **semantics,
    }


async def _extract_checkbox(page: Any, el: Any, counter: int) -> dict[str, Any] | None:
    """Extract info from a checkbox element."""
    label = await _find_label(page, el)
    checked = False
    try:
        checked = await el.is_checked()
    except Exception:
        pass
    if not checked:
        try:
            aria = await el.get_attribute("aria-checked")
            if aria is not None:
                checked = aria.lower() == "true"
        except Exception:
            pass

    semantics = await _get_element_semantics(el, "checkbox", page)
    coords = await _get_bbox(el)

    return {
        "id": f"#{counter}",
        "type": "checkbox",
        "label": label,
        "checked": checked,
        "coords": coords,
        **semantics,
    }


async def _extract_radio(page: Any, el: Any, counter: int) -> dict[str, Any] | None:
    """Extract info from a radio button element."""
    label = await _find_label(page, el)
    checked = False
    try:
        checked = await el.is_checked()
    except Exception:
        pass
    if not checked:
        try:
            aria = await el.get_attribute("aria-checked")
            if aria is not None:
                checked = aria.lower() == "true"
        except Exception:
            pass

    semantics = await _get_element_semantics(el, "radio", page)
    coords = await _get_bbox(el)

    return {
        "id": f"#{counter}",
        "type": "radio",
        "label": label,
        "checked": checked,
        "coords": coords,
        **semantics,
    }


async def _find_label(page: Any, el: Any) -> str:
    """Find the best label for an element.

    Priority:
    1. aria-label attribute
    2. Associated <label> element (by for/id)
    3. placeholder attribute
    4. Parent text content
    5. Element tag name
    """
    # 1. aria-label
    aria_label = await el.get_attribute("aria-label")
    if aria_label:
        return aria_label

    # 2. Associated label via id/for
    el_id = await el.get_attribute("id")
    if el_id:
        label_locator = page.locator(f'label[for="{el_id}"]')
        try:
            label_text = await label_locator.text_content()
            if label_text:
                return label_text.strip()
        except Exception:
            pass

    # 3. placeholder
    placeholder = await el.get_attribute("placeholder")
    if placeholder:
        return placeholder

    # 4. Parent text content
    try:
        parent_text = await el.evaluate("""
            el => {
                const parent = el.parentElement;
                if (parent) {
                    const text = parent.textContent || '';
                    // Remove the element's own text to avoid duplication
                    const elText = el.textContent || '';
                    return text.replace(elText, '').trim();
                }
                return '';
            }
        """)
        if parent_text:
            return parent_text
    except Exception:
        pass

    # 5. Fall back to tag name
    try:
        tag_name = await el.evaluate("el => el.tagName.toLowerCase()")
        if tag_name:
            return tag_name
    except Exception:
        pass

    return ""


# ---------------------------------------------------------------------------
# Layer 2 — Page Structure
# ---------------------------------------------------------------------------


async def _extract_headings(page: Any) -> list[str]:
    """Extract h1, h2, h3 text content."""
    headings = page.locator("h1, h2, h3")
    count = await headings.count()
    result: list[str] = []
    for i in range(count):
        try:
            text = await headings.nth(i).text_content()
            if text and text.strip():
                result.append(text.strip())
        except Exception:
            pass
    return result


async def _extract_forms(page: Any) -> list[dict[str, Any]]:
    """Extract form elements."""
    forms = page.locator("form")
    count = await forms.count()
    result: list[dict[str, Any]] = []
    for i in range(count):
        el = forms.nth(i)
        try:
            form_id = await el.get_attribute("id") or ""
            action = await el.get_attribute("action") or ""
            method = await el.get_attribute("method") or "GET"
            result.append({
                "id": form_id,
                "action": action,
                "method": method.upper(),
            })
        except Exception:
            pass
    return result


async def _extract_modals(page: Any) -> list[dict[str, Any]]:
    """Extract modal/dialog elements."""
    modals_selectors = [
        "dialog:visible",
        "[role='dialog']:visible",
        ".modal:visible",
        ".ant-modal-wrap:visible",
        ".el-dialog__wrapper:visible",
        ".modal-overlay:visible",
    ]
    result: list[dict[str, Any]] = []
    for selector in modals_selectors:
        locator = page.locator(selector)
        count = await locator.count()
        for i in range(count):
            try:
                text = await locator.nth(i).text_content() or ""
                result.append({
                    "text": text.strip()[:200],  # Truncate long text
                })
            except Exception:
                pass
    return result


async def _extract_nav_items(page: Any) -> list[str]:
    """Extract navigation items."""
    navs = page.locator("nav a:visible, [role='navigation'] a:visible")
    count = await navs.count()
    result: list[str] = []
    for i in range(count):
        try:
            text = await navs.nth(i).text_content()
            if text and text.strip():
                result.append(text.strip())
        except Exception:
            pass
    return result


async def _extract_tables(page: Any) -> list[dict[str, Any]]:
    """Extract table information."""
    tables = page.locator("table:visible")
    count = await tables.count()
    result: list[dict[str, Any]] = []
    for i in range(count):
        el = tables.nth(i)
        try:
            table_id = await el.get_attribute("id") or ""
            # Count headers and rows
            headers = await el.locator("th").count()
            rows = await el.locator("tr").count()

            # Extract header text
            header_texts: list[str] = []
            header_els = el.locator("th")
            h_count = await header_els.count()
            for j in range(h_count):
                try:
                    text = await header_els.nth(j).text_content()
                    if text:
                        header_texts.append(text.strip())
                except Exception:
                    pass

            result.append({
                "id": table_id,
                "headers": header_texts if header_texts else [],
                "rows": rows - 1 if headers > 0 else rows,  # Exclude header row
            })
        except Exception:
            pass
    return result


# ---------------------------------------------------------------------------
# Layer 3 — State Information
# ---------------------------------------------------------------------------


async def _extract_error_messages(page: Any) -> list[str]:
    """Extract visible error/warning messages.

    V2.0-A (2026-06-02): 排除 .alert-success / .flash.success / .toast-success 等
    成功提示, 避免 [role='alert'] 撞到 Bootstrap-flash 成功消息.
    """
    error_selectors = [
        ".error:visible",
        ".alert-danger:visible",
        ".alert-error:visible",
        ".el-message--error:visible",
        ".ant-message-error:visible",
        "[role='alert']:visible:not(.alert-success):not(.flash-success):not(.flash.success):not(.toast-success):not(.notification-success)",
        ".toast-error:visible",
        ".notification-error:visible",
        ".error-message:visible",
        ".validation-error:visible",
        ".form-error:visible",
        ".has-error .help-block:visible",
    ]
    result: list[str] = []
    for selector in error_selectors:
        try:
            locator = page.locator(selector)
            count = await locator.count()
            for i in range(count):
                try:
                    text = await locator.nth(i).text_content()
                    if text and text.strip():
                        result.append(text.strip())
                except Exception:
                    pass
        except Exception:
            pass
    return result


async def _detect_loading(page: Any) -> bool:
    """Detect if any loading indicators are visible."""
    loading_selectors = [
        ".loading:visible",
        ".spinner:visible",
        "[aria-busy='true']:visible",
        ".el-loading-mask:visible",
    ]
    for selector in loading_selectors:
        try:
            locator = page.locator(selector)
            if await locator.count() > 0:
                return True
        except Exception:
            pass
    return False


async def _extract_pagination(page: Any) -> dict[str, Any] | None:
    """Extract pagination information if present."""
    # Look for common pagination patterns
    pagi_selectors = [
        ".pagination:visible",
        ".pagination-wrapper:visible",
        "[role='navigation'] .page:visible",
    ]
    for selector in pagi_selectors:
        try:
            locator = page.locator(selector)
            if await locator.count() > 0:
                # Try to extract current/total from data attributes or text
                current = await locator.evaluate("""
                    el => {
                        const active = el.querySelector('.active, .current');
                        if (active) return parseInt(active.textContent) || 1;
                        return 1;
                    }
                """) or 1
                total = await locator.evaluate("""
                    el => {
                        const pages = el.querySelectorAll('.page, [data-page]');
                        if (pages.length) {
                            const last = pages[pages.length - 1];
                            return parseInt(last.textContent) || 1;
                        }
                        return 1;
                    }
                """) or 1
                return {"current": current, "total": total}
        except Exception:
            pass
    return None
