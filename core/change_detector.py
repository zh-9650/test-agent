"""core/change_detector.py — 页面状态变化检测器

纯函数实现：dict in → ChangeReport out
只报告事实（发生了什么），不做对错判断。
"""

from __future__ import annotations

from typing import Any

from core.interfaces import ChangeReport


def _describe_element(element: dict[str, Any]) -> str:
    """将交互元素描述为 '#id type: label/text' 格式。"""
    element_id = element.get("id", "")
    element_type = element.get("type", "")
    # 优先使用 label，其次 text，否则留空
    label = element.get("label") or element.get("text") or ""
    return f"{element_id} {element_type}: {label}".strip()


def detect_changes(state_before: dict[str, Any], state_after: dict[str, Any]) -> ChangeReport:
    """对比操作前后的页面状态快照，生成变化报告。

    只报告事实（发生了什么），不做对错判断。
    检测项：URL 变化、元素增删、JS 报错、网络错误、弹窗、错误提示。

    Args:
        state_before: execute 前的页面状态快照
        state_after: execute 后的页面状态快照

    Returns:
        ChangeReport 实例
    """
    # 安全取值：字段缺失时返回空默认值
    before_url = state_before.get("url", "")
    after_url = state_after.get("url", "")

    before_elements = state_before.get("interactive_elements", []) or []
    after_elements = state_after.get("interactive_elements", []) or []

    before_modals = state_before.get("modals", []) or []
    after_modals = state_after.get("modals", []) or []

    url_changed = before_url != after_url

    # 元素增删：基于 id 集合比较
    before_ids = {el.get("id") for el in before_elements if el.get("id") is not None}
    after_ids = {el.get("id") for el in after_elements if el.get("id") is not None}

    new_elements: list[str] = []
    gone_elements: list[str] = []

    for el in after_elements:
        el_id = el.get("id")
        if el_id is not None and el_id not in before_ids:
            new_elements.append(_describe_element(el))

    for el in before_elements:
        el_id = el.get("id")
        if el_id is not None and el_id not in after_ids:
            gone_elements.append(_describe_element(el))

    # 弹窗出现：before 无弹窗且 after 有弹窗
    modal_appeared = not before_modals and bool(after_modals)

    return ChangeReport(
        url_changed=url_changed,
        url_before=before_url if url_changed else "",
        url_after=after_url if url_changed else "",
        new_elements=new_elements,
        gone_elements=gone_elements,
        js_errors=state_after.get("js_errors", []) or [],
        network_errors=state_after.get("network_errors", []) or [],
        error_messages_visible=state_after.get("error_messages", []) or [],
        modal_appeared=modal_appeared,
        page_loading=bool(state_after.get("loading", False)),
    )
