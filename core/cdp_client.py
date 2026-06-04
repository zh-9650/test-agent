"""core/cdp_client.py — CDP (Chrome DevTools Protocol) session wrapper.

Phase 2.0C: replaces Playwright locator-based element perception with CDP
Accessibility.getFullAXTree for deterministic element anchoring via backendNodeId.

Two-phase migration:
  Sprint 1: CDP AXTree perception + backendNodeId anchoring
  Sprint 2: CDP Input.dispatchMouseEvent for click + CDP key events for input
"""

from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# CDP Session Management
# ---------------------------------------------------------------------------

_cdp_sessions: dict[str, Any] = {}


async def get_cdp_session(page: Any, task_id: str = "") -> Any | None:
    """Get or create a CDP session.

    Priority:
    1. Already cached for task_id
    2. Already registered in tools context (via runtime.py set_cdp_session)
    3. Create new session from page

    Returns None if CDP is unavailable (Firefox, WebKit, or error).
    """
    if task_id and task_id in _cdp_sessions:
        return _cdp_sessions[task_id]

    # Check tools context first (most common path — runtime already created one)
    try:
        from agents.ui.tools import get_cdp_session_ctx as tools_get_cdp
        existing = tools_get_cdp()
        if existing is not None:
            if task_id:
                _cdp_sessions[task_id] = existing
            return existing
    except Exception:
        pass

    try:
        context = page.context
        cdp_session = await context.new_cdp_session(page)
        if task_id:
            _cdp_sessions[task_id] = cdp_session
        return cdp_session
    except Exception:
        return None


def cleanup_cdp_session(task_id: str) -> None:
    _cdp_sessions.pop(task_id, None)


# ---------------------------------------------------------------------------
# CDP Accessibility Tree
# ---------------------------------------------------------------------------

INTERACTIVE_ROLES = {
    "button", "textbox", "combobox", "checkbox", "radio", "link",
    "menuitem", "tab", "switch", "slider", "searchbox",
    "spinbutton", "listbox", "menu", "treeitem",
}

STRUCTURAL_ROLES = {
    "heading", "list", "listitem", "row", "gridcell", "columnheader",
    "rowheader", "cell", "table", "grid",
}


async def get_full_ax_tree(cdp_session: Any, max_depth: int = 10) -> list[dict]:
    """Get the full accessibility tree via CDP.

    Returns:
        List of AX node dicts, each containing:
        - nodeId, ignored, role, name, value, properties
        - backendDOMNodeId (int) — the backendNodeId for anchoring
        - childIds (list[str])
    """
    try:
        result = await cdp_session.send("Accessibility.getFullAXTree", {
            "max_depth": max_depth,
        })
        return result.get("nodes", [])
    except Exception:
        return []


async def get_node_attributes(cdp_session: Any, backend_node_id: int) -> dict[str, str]:
    """Get HTML attributes for a backendNodeId via DOM.describeNode."""
    try:
        desc = await cdp_session.send("DOM.describeNode", {
            "backendNodeId": backend_node_id,
        })
        node = desc.get("node", {})
        attrs_list = node.get("attributes", [])
        attrs = {}
        for i in range(0, len(attrs_list), 2):
            key = attrs_list[i]
            val = attrs_list[i + 1] if i + 1 < len(attrs_list) else ""
            attrs[key] = val
        return attrs
    except Exception:
        return {}


async def get_node_box_model(cdp_session: Any, backend_node_id: int) -> dict | None:
    """Get the bounding box for a node via DOM.getBoxModel.

    Returns:
        dict with x, y, width, height in viewport coordinates, or None.
    """
    try:
        box = await cdp_session.send("DOM.getBoxModel", {
            "backendNodeId": backend_node_id,
        })
        model = box.get("model", {})
        content = model.get("content", [])
        if content and len(content) >= 8:
            xs = [content[i] for i in range(0, 8, 2)]
            ys = [content[i + 1] for i in range(0, 8, 2)]
            x = min(xs)
            y = min(ys)
            w = max(xs) - x
            h = max(ys) - y
            return {"x": x, "y": y, "width": w, "height": h}
        return None
    except Exception:
        return None


async def resolve_node(cdp_session: Any, backend_node_id: int) -> dict[str, Any] | None:
    """Resolve a backendNodeId to its runtime objectId and frameId via DOM.resolveNode.

    This is the key to Phase 2.0D backendNodeId persistence: once an element
    is anchored by its backendNodeId, subsequent steps can re-resolve it without
    re-running the full AXTree query.

    Returns:
        dict with objectId, frameId, backendNodeId, or None on failure.
        objectId is a high-cost handle — release with release_object() after use.
    """
    if not cdp_session or not backend_node_id:
        return None
    try:
        result = await cdp_session.send("DOM.resolveNode", {
            "backendNodeId": backend_node_id,
        })
        return {
            "object": result.get("object", {}),
            "objectId": result.get("object", {}).get("objectId", ""),
            "frameId": result.get("object", {}).get("frameId", ""),
            "backendNodeId": backend_node_id,
        }
    except Exception:
        return None


async def release_object(cdp_session: Any, object_id: str) -> None:
    """Release a runtime object handle obtained from resolveNode.

    CDP requires this to avoid leaks; should be called after the action that
    used the objectId completes.
    """
    if not cdp_session or not object_id:
        return
    try:
        await cdp_session.send("Runtime.releaseObject", {"objectId": object_id})
    except Exception:
        pass


def _get_ax_property(node: dict, prop_name: str) -> Any:
    """Get a property value from an AX node's properties list."""
    for prop in node.get("properties", []):
        if prop.get("name") == prop_name:
            val = prop.get("value", {})
            return val.get("value") if isinstance(val, dict) else val
    return None


def _ax_role(node: dict) -> str:
    """Get the role string from an AX node."""
    role = node.get("role", {})
    if isinstance(role, dict):
        return role.get("value", "Unknown")
    return str(role)


def _ax_name(node: dict) -> str:
    """Get the name (accessible name) from an AX node."""
    name = node.get("name", {})
    if isinstance(name, dict):
        return name.get("value", "")
    return str(name)


def _ax_value(node: dict) -> str:
    """Get the value from an AX node."""
    val = node.get("value", {})
    if isinstance(val, dict):
        return val.get("value", "")
    return str(val)


def _is_interactive(node: dict) -> bool:
    """Check if an AX node is an interactive element."""
    if node.get("ignored", True):
        return False
    role = _ax_role(node)
    return role.lower() in INTERACTIVE_ROLES


def _is_structural(node: dict) -> bool:
    """Check if an AX node is a structural element (headings, lists, tables)."""
    if node.get("ignored", True):
        return False
    role = _ax_role(node)
    return role.lower() in STRUCTURAL_ROLES


async def extract_elements_via_cdp(page: Any, cdp_session: Any) -> list[dict[str, Any]]:
    """Extract interactive elements from the page using CDP AXTree.

    Returns a list of element dicts compatible with the existing
    _collect_interactive_elements() format but with backendNodeId anchoring.

    Each element:
        id: "#N" (sequential index)
        type: element type
        text: label / text content
        backend_node_id: int (for CDP anchoring)
        xpath: computed xpath
        visible, enabled, readonly, required, checked, role
        coords: {x, y, w, h} for click positioning
    """
    nodes = await get_full_ax_tree(cdp_session)
    if not nodes:
        return []

    elements = []
    counter = 1

    # Build a map of nodeId -> node for parent lookups
    node_map = {n.get("nodeId", ""): n for n in nodes}

    for node in nodes:
        if not _is_interactive(node):
            continue

        role = _ax_role(node).lower()
        name = _ax_name(node)
        value = _ax_value(node)
        backend_id = node.get("backendDOMNodeId", 0)
        if not backend_id:
            continue

        # Get HTML attributes and box model
        attrs = await get_node_attributes(cdp_session, backend_id) if cdp_session else {}
        box = await get_node_box_model(cdp_session, backend_id) if cdp_session else None

        el_type = _ax_role_to_type(role, attrs)
        input_type = attrs.get("type", "text") if el_type == "input" else None

        # Determine visible/enabled/readonly from AX properties
        disabled = _get_ax_property(node, "disabled") or False
        if isinstance(disabled, bool):
            pass
        elif isinstance(disabled, str):
            disabled = disabled.lower() == "true"
        else:
            disabled = False

        readonly = _get_ax_property(node, "readonly") or False
        if isinstance(readonly, bool):
            pass
        elif isinstance(readonly, str):
            readonly = readonly.lower() == "true"
        else:
            readonly = False

        required_node = _get_ax_property(node, "required") or False
        required = required_node if isinstance(required_node, bool) else str(required_node).lower() == "true"

        checked_val = _get_ax_property(node, "checked")
        if checked_val in (True, "true", "True"):
            checked = True
        elif checked_val in (False, "false", "False"):
            checked = False
        else:
            checked = None

        # Determine visibility: non-ignored AX nodes with coordinates are visible
        visible = box is not None and box.get("width", 0) > 0 and box.get("height", 0) > 0

        # Build text/label/placeholder
        label = name or ""
        placeholder = attrs.get("placeholder", "")

        el_text = label or placeholder or value

        # Build element dict compatible with existing format
        el = {
            "id": f"#{counter}",
            "type": el_type,
            "text": el_text,
            "backend_node_id": backend_id,
            "xpath": attrs.get("xpath", f"//{attrs.get('tagName', '*').lower()}[{counter}]"),
            "visible": visible,
            "enabled": not disabled,
            "interactable": visible and not disabled,
            "readonly": readonly,
            "required": required,
            "checked": checked,
            "role": role,
            "coords": box or {},
        }

        if el_type == "input" and input_type:
            el["input_type"] = input_type
        if placeholder:
            el["placeholder"] = placeholder
        if label and label != placeholder:
            el["label"] = label

        elements.append(el)
        counter += 1

    return elements


def _ax_role_to_type(role: str, attrs: dict[str, str]) -> str:
    """Map AX role to element type string."""
    tag = attrs.get("tagName", "").lower()
    mapping = {
        "textbox": "input",
        "combobox": "select",
        "button": "button",
        "checkbox": "checkbox",
        "radio": "radio",
        "link": "link",
        "searchbox": "input",
        "spinbutton": "input",
        "slider": "input",
    }
    result = mapping.get(role, tag or role)
    if result == "input":
        input_type = attrs.get("type", "text")
        if input_type in ("submit", "button", "reset"):
            return "button"
    return result


# ---------------------------------------------------------------------------
# CDP-based DOM Fingerprint
# ---------------------------------------------------------------------------


async def get_dom_fingerprint(page: Any, cdp_session: Any | None = None) -> str:
    """Get DOM fingerprint via CDP for more reliable page change detection.

    Uses DOM.getDocument to get node count + document URL.
    Falls back to JS evaluate if CDP unavailable.
    """
    if cdp_session:
        try:
            doc = await cdp_session.send("DOM.getDocument", {"depth": 0})
            root = doc.get("root", {})
            node_count = root.get("childNodeCount", 0)
            doc_url = root.get("documentURL", "")
            return f"{node_count}_{doc_url}_{hash(doc_url)}"
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


# ---------------------------------------------------------------------------
# CDP Mouse / Keyboard Actions
# ---------------------------------------------------------------------------


async def cdp_click(page: Any, cdp_session: Any, x: float, y: float) -> bool:
    """Click at viewport coordinates via CDP Input.dispatchMouseEvent.

    Args:
        page: Playwright page (for fallback)
        cdp_session: CDP session
        x, y: viewport coordinates

    Returns:
        True if CDP click succeeded, False (caller should fallback to Playwright)
    """
    if not cdp_session:
        return False
    try:
        await cdp_session.send("Input.dispatchMouseEvent", {
            "type": "mousePressed",
            "x": round(x),
            "y": round(y),
            "button": "left",
            "clickCount": 1,
        })
        await cdp_session.send("Input.dispatchMouseEvent", {
            "type": "mouseReleased",
            "x": round(x),
            "y": round(y),
            "button": "left",
            "clickCount": 1,
        })
        return True
    except Exception:
        return False


async def cdp_input_text(cdp_session: Any, text: str) -> bool:
    """Type text into the focused element via CDP Input.dispatchKeyEvent.

    Uses raw keyDown/keyUp events for each character to trigger
    full JS event chains (input, change, keydown, keyup, keypress).
    """
    if not cdp_session:
        return False
    try:
        # First clear existing content via selectAll + delete
        await cdp_session.send("Input.dispatchKeyEvent", {
            "type": "keyDown",
            "windowsVirtualKeyCode": 65,
            "key": "a",
            "code": "KeyA",
            "modifiers": 8,
        })
        await cdp_session.send("Input.dispatchKeyEvent", {
            "type": "keyUp",
            "windowsVirtualKeyCode": 65,
            "key": "a",
            "code": "KeyA",
            "modifiers": 8,
        })
        await cdp_session.send("Input.dispatchKeyEvent", {
            "type": "keyDown",
            "windowsVirtualKeyCode": 46,
            "key": "Delete",
            "code": "Delete",
        })
        await cdp_session.send("Input.dispatchKeyEvent", {
            "type": "keyUp",
            "windowsVirtualKeyCode": 46,
            "key": "Delete",
            "code": "Delete",
        })

        # Type each character
        for char in text:
            code = _char_to_key_code(char)
            if code:
                await cdp_session.send("Input.dispatchKeyEvent", {
                    "type": "keyDown",
                    "key": char,
                    "text": char,
                    "code": code,
                })
                await cdp_session.send("Input.dispatchKeyEvent", {
                    "type": "keyUp",
                    "key": char,
                    "text": char,
                    "code": code,
                })
            else:
                await cdp_session.send("Input.insertText", {"text": char})
        return True
    except Exception:
        return False


def _char_to_key_code(char: str) -> str | None:
    """Map a character to a reasonable USB key code string."""
    if char.isalpha():
        return f"Key{char.upper()}"
    if char.isdigit():
        return f"Digit{char}"
    key_map = {
        " ": "Space", ".": "Period", ",": "Comma", "-": "Minus",
        "=": "Equal", "/": "Slash", "\\": "Backslash", ";": "Semicolon",
        "'": "Quote", "[": "BracketLeft", "]": "BracketRight",
        "`": "Backquote", "\t": "Tab", "\n": "Enter",
    }
    return key_map.get(char, None)


# ---------------------------------------------------------------------------
# CDP Viewport / Page Info
# ---------------------------------------------------------------------------


async def get_viewport_size(cdp_session: Any) -> dict[str, int]:
    """Get the current viewport size via CDP."""
    try:
        result = await cdp_session.send("Browser.getWindowForTarget")
        bounds = result.get("bounds", {})
        return {"width": bounds.get("width", 1280), "height": bounds.get("height", 720)}
    except Exception:
        return {"width": 1280, "height": 720}


# ---------------------------------------------------------------------------
# CDP Iframe Detection (Phase 2.0C Sprint 4)
# ---------------------------------------------------------------------------


async def get_frame_tree(cdp_session: Any) -> list[dict[str, Any]]:
    """Discover all frames via CDP Page.getFrameTree.

    Returns:
        List of {id, url, parent_id} for all frames.
    """
    try:
        result = await cdp_session.send("Page.getFrameTree")
        frames = []

        def walk(frame_tree: dict, parent_id: str = ""):
            frame = frame_tree.get("frame", {})
            fid = frame.get("id", "")
            furl = frame.get("url", "")
            frames.append({"id": fid, "url": furl, "parent_id": parent_id})
            for child in frame_tree.get("childFrames", []):
                walk(child, fid)

        walk(result.get("frameTree", {}))
        return frames
    except Exception:
        return []


async def cdp_right_click(page: Any, cdp_session: Any, x: float, y: float) -> bool:
    """Right-click at viewport coordinates via CDP Input.dispatchMouseEvent.

    Args:
        page: Playwright page (for fallback)
        cdp_session: CDP session
        x, y: viewport coordinates

    Returns:
        True if CDP right-click succeeded, False
    """
    if not cdp_session:
        return False
    try:
        await cdp_session.send("Input.dispatchMouseEvent", {
            "type": "mousePressed",
            "x": round(x),
            "y": round(y),
            "button": "right",
            "clickCount": 1,
        })
        await cdp_session.send("Input.dispatchMouseEvent", {
            "type": "mouseReleased",
            "x": round(x),
            "y": round(y),
            "button": "right",
            "clickCount": 1,
        })
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# CDP Hover (Phase 2.0C Sprint 4)
# ---------------------------------------------------------------------------


async def cdp_hover(cdp_session: Any, x: float, y: float) -> bool:
    """Move mouse to viewport coordinates via CDP Input.dispatchMouseEvent.

    Args:
        cdp_session: CDP session
        x, y: viewport coordinates

    Returns:
        True if CDP hover succeeded, False
    """
    if not cdp_session:
        return False
    try:
        await cdp_session.send("Input.dispatchMouseEvent", {
            "type": "mouseMoved",
            "x": round(x),
            "y": round(y),
        })
        return True
    except Exception:
        return False
