"""core/page_semantic.py — Page Semantic Layer

Extracts a semantic summary from a Playwright page using the Locator API.
This is the "eyes" of the AI testing agent.
"""

from __future__ import annotations

import base64
from typing import Any

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def extract_page_semantics(page: Any) -> dict[str, Any]:
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

    Args:
        page: Playwright Page 对象

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

    # Layer 1: Interactive elements (collected last so we can truncate)
    interactive_elements = await _collect_interactive_elements(page)
    if len(interactive_elements) > 50:
        interactive_elements = interactive_elements[:50]
        result["truncated"] = True
    result["interactive_elements"] = interactive_elements

    # Tables are also interactive / structural
    result["tables"] = await _extract_tables(page)

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


# ---------------------------------------------------------------------------
# Layer 1 — Interactive Elements
# ---------------------------------------------------------------------------


async def _collect_interactive_elements(page: Any) -> list[dict[str, Any]]:
    """Collect all interactive elements using browser-use or fallback to Playwright."""
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
            # Fallback to Playwright if browser-use fails
            print(f"BrowserSession extraction failed: {e}")
            pass

    # Playwright fallback
    elements = []
    counter = 1

    # Inputs (excluding hidden)
    inputs = page.locator("input:visible")
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

    return {
        "id": f"#{counter}",
        "type": "input",
        "input_type": input_type,
        "label": label,
        "placeholder": placeholder,
        "required": required,
        "disabled": disabled,
        "value": value,
    }


async def _extract_button(el: Any, counter: int) -> dict[str, Any] | None:
    """Extract info from a button element."""
    text = await el.text_content() or ""
    button_type = await el.get_attribute("type") or "button"
    disabled = False
    try:
        disabled = await el.is_disabled()
    except Exception:
        pass

    return {
        "id": f"#{counter}",
        "type": "button",
        "text": text.strip(),
        "button_type": button_type,
        "disabled": disabled,
    }


async def _extract_link(el: Any, counter: int) -> dict[str, Any] | None:
    """Extract info from a link element."""
    text = await el.text_content() or ""
    href = await el.get_attribute("href") or ""

    return {
        "id": f"#{counter}",
        "type": "link",
        "text": text.strip(),
        "href": href,
    }


async def _extract_select(page: Any, el: Any, counter: int) -> dict[str, Any] | None:
    """Extract info from a select element."""
    label = await _find_label(page, el)
    options = await el.evaluate("""
        el => Array.from(el.options).map(o => o.text.trim())
    """)

    return {
        "id": f"#{counter}",
        "type": "select",
        "label": label,
        "options": options or [],
    }


async def _extract_checkbox(page: Any, el: Any, counter: int) -> dict[str, Any] | None:
    """Extract info from a checkbox element."""
    label = await _find_label(page, el)
    checked = await el.is_checked() if hasattr(el, "is_checked") else False

    return {
        "id": f"#{counter}",
        "type": "checkbox",
        "label": label,
        "checked": checked,
    }


async def _extract_radio(page: Any, el: Any, counter: int) -> dict[str, Any] | None:
    """Extract info from a radio button element."""
    label = await _find_label(page, el)
    checked = await el.is_checked() if hasattr(el, "is_checked") else False

    return {
        "id": f"#{counter}",
        "type": "radio",
        "label": label,
        "checked": checked,
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
        tag_name = await el.evaluate("el => el.tagName.toLower()")
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
    """Extract visible error/warning messages."""
    error_selectors = [
        ".error:visible",
        ".alert-danger:visible",
        ".el-message--error:visible",
        ".ant-message-error:visible",
        "[role='alert']:visible",
        ".toast-error:visible",
        ".notification-error:visible",
        ".error-message:visible",
        ".validation-error:visible",
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
