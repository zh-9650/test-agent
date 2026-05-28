"""Tests for core/change_detector.py (TDD)

Covers all detection logic and graceful degradation for missing fields.
"""

import pytest
from core.change_detector import detect_changes
from core.interfaces import ChangeReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(
    *,
    url="http://example.com/page",
    interactive_elements=None,
    modals=None,
    error_messages=None,
    js_errors=None,
    network_errors=None,
    loading=False,
):
    """Build a minimal state snapshot dict with safe defaults."""
    return {
        "url": url,
        "title": "Page Title",
        "interactive_elements": interactive_elements or [],
        "headings": [],
        "modals": modals or [],
        "error_messages": error_messages or [],
        "js_errors": js_errors or [],
        "network_errors": network_errors or [],
        "loading": loading,
        "forms": [],
    }


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_no_changes():
    before = _make_state()
    after = _make_state()
    report = detect_changes(before, after)
    assert report == ChangeReport()


def test_url_changed():
    before = _make_state(url="http://example.com/a")
    after = _make_state(url="http://example.com/b")
    report = detect_changes(before, after)
    assert report.url_changed is True
    assert report.url_before == "http://example.com/a"
    assert report.url_after == "http://example.com/b"


def test_new_elements_appeared():
    before = _make_state(
        interactive_elements=[
            {"id": "#1", "type": "input", "label": "Username", "input_type": "text", "placeholder": ""}
        ]
    )
    after = _make_state(
        interactive_elements=[
            {"id": "#1", "type": "input", "label": "Username", "input_type": "text", "placeholder": ""},
            {"id": "#2", "type": "button", "text": "Login", "button_type": "submit"},
        ]
    )
    report = detect_changes(before, after)
    assert report.new_elements == ["#2 button: Login"]
    assert report.gone_elements == []


def test_elements_disappeared():
    before = _make_state(
        interactive_elements=[
            {"id": "#1", "type": "input", "label": "Username", "input_type": "text", "placeholder": ""},
            {"id": "#2", "type": "button", "text": "Login", "button_type": "submit"},
        ]
    )
    after = _make_state(
        interactive_elements=[
            {"id": "#1", "type": "input", "label": "Username", "input_type": "text", "placeholder": ""},
        ]
    )
    report = detect_changes(before, after)
    assert report.gone_elements == ["#2 button: Login"]
    assert report.new_elements == []


def test_js_errors_detected():
    before = _make_state(js_errors=[])
    after = _make_state(js_errors=["ReferenceError: x is not defined", "TypeError: Cannot read property 'y'"])
    report = detect_changes(before, after)
    assert report.js_errors == ["ReferenceError: x is not defined", "TypeError: Cannot read property 'y'"]


def test_network_errors_detected():
    before = _make_state(network_errors=[])
    after = _make_state(network_errors=["GET /api/users 500", "POST /api/login 403"])
    report = detect_changes(before, after)
    assert report.network_errors == ["GET /api/users 500", "POST /api/login 403"]


def test_error_messages_visible():
    before = _make_state(error_messages=[])
    after = _make_state(error_messages=["Invalid credentials", "Session expired"])
    report = detect_changes(before, after)
    assert report.error_messages_visible == ["Invalid credentials", "Session expired"]


def test_modal_appeared():
    before = _make_state(modals=[])
    after = _make_state(modals=[{"title": "Confirm", "content": "Are you sure?"}])
    report = detect_changes(before, after)
    assert report.modal_appeared is True


def test_page_loading():
    before = _make_state(loading=False)
    after = _make_state(loading=True)
    report = detect_changes(before, after)
    assert report.page_loading is True


def test_missing_fields_graceful():
    before = {}
    after = {"url": "http://example.com/new"}
    report = detect_changes(before, after)
    assert report.url_changed is True
    assert report.url_before == ""
    assert report.url_after == "http://example.com/new"
    assert report.new_elements == []
    assert report.gone_elements == []
    assert report.js_errors == []
    assert report.network_errors == []
    assert report.error_messages_visible == []
    assert report.modal_appeared is False
    assert report.page_loading is False


def test_empty_dicts():
    report = detect_changes({}, {})
    assert report == ChangeReport()
