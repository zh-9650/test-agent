"""Tests for core/page_semantic.py (TDD)

Uses real Playwright with page.set_content() for reliable DOM testing.
"""

import base64

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from core.page_semantic import extract_page_semantics, take_screenshot


@pytest_asyncio.fixture
async def page():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        yield page
        await browser.close()


# ---------------------------------------------------------------------------
# test_extract_login_page
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_login_page(page):
    await page.set_content("""
    <html>
    <head><title>Login Page</title></head>
    <body>
        <h1>Welcome</h1>
        <form id="login-form" action="/login" method="POST">
            <label for="user">Username</label>
            <input id="user" type="text" placeholder="Enter username" required>
            <label for="pass">Password</label>
            <input id="pass" type="password" placeholder="Enter password" required>
            <button type="submit">Login</button>
        </form>
    </body>
    </html>
    """)
    result = await extract_page_semantics(page)

    assert result["title"] == "Login Page"
    assert result["url"] == "about:blank"
    assert len(result["interactive_elements"]) >= 3  # 2 inputs + 1 button
    assert result["interactive_elements"][0]["type"] == "input"
    assert result["interactive_elements"][0]["label"] == "Username"


# ---------------------------------------------------------------------------
# test_extract_data_table
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_data_table(page):
    await page.set_content("""
    <html>
    <head><title>Data Table</title></head>
    <body>
        <h1>Users</h1>
        <table id="users">
            <thead>
                <tr><th>Name</th><th>Age</th></tr>
            </thead>
            <tbody>
                <tr><td>Alice</td><td>30</td></tr>
                <tr><td>Bob</td><td>25</td></tr>
            </tbody>
        </table>
    </body>
    </html>
    """)
    result = await extract_page_semantics(page)

    tables = result.get("tables", [])
    assert len(tables) == 1
    assert tables[0]["id"] == "users"
    assert tables[0]["headers"] == ["Name", "Age"]
    assert tables[0]["rows"] == 2


# ---------------------------------------------------------------------------
# test_numbered_ids
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_numbered_ids(page):
    await page.set_content("""
    <html>
    <body>
        <input type="text" placeholder="a">
        <button>One</button>
        <a href="/x">Link</a>
    </body>
    </html>
    """)
    result = await extract_page_semantics(page)
    ids = [el["id"] for el in result["interactive_elements"]]
    assert ids == ["#1", "#2", "#3"]


# ---------------------------------------------------------------------------
# test_max_50_elements
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_max_50_elements(page, monkeypatch):
    # Generate 110 inputs + 5 buttons = 115 interactive elements
    # Default L2_MAX_INTERACTIVE_ELEMENTS=100, so truncated
    monkeypatch.setenv("L2_MAX_INTERACTIVE_ELEMENTS", "100")
    inputs = "".join(f'<input type="text" placeholder="field {i}">' for i in range(110))
    buttons = "".join(f'<button>Btn {i}</button>' for i in range(5))
    await page.set_content(f"<html><body>{inputs}{buttons}</body></html>")

    result = await extract_page_semantics(page)
    assert result["truncated"] is True
    assert len(result["interactive_elements"]) == 100
    assert result["_total_interactive_count"] == 115


# ---------------------------------------------------------------------------
# test_error_messages_detected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_error_messages_detected(page):
    await page.set_content("""
    <html>
    <body>
        <div class="error">Invalid credentials</div>
        <div class="alert-danger">Session expired</div>
    </body>
    </html>
    """)
    result = await extract_page_semantics(page)

    assert "Invalid credentials" in result["error_messages"]
    assert "Session expired" in result["error_messages"]


# ---------------------------------------------------------------------------
# V2.0 A (2026-06-02): 成功消息不应被识别为错误
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_success_messages_not_detected_as_errors(page):
    """V2.0-A fix: Bootstrap-flash .alert-success / [role='alert'] 不应被识别为错误.

    Repro: practice.expandtesting.com 登录后 flash 成功消息:
    <div class="flash success" role="alert">You logged into a secure area!</div>
    原实现会被 [role='alert'] 撞到, 误判为错误.
    """
    await page.set_content("""
    <html>
    <body>
        <div class="flash success" role="alert">You logged into a secure area!</div>
        <div class="alert-success" role="alert">Login successful</div>
        <div class="toast-success">Saved!</div>
    </body>
    </html>
    """)
    result = await extract_page_semantics(page)

    assert result["error_messages"] == [], (
        f"成功消息不应进入 error_messages, 实际: {result['error_messages']}"
    )


# ---------------------------------------------------------------------------
# test_take_screenshot_returns_base64
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_take_screenshot_returns_base64(page):
    await page.set_content("<html><body><h1>Hello</h1></body></html>")
    screenshot = await take_screenshot(page)

    assert isinstance(screenshot, str)
    assert len(screenshot) > 0
    # Verify valid base64 by decoding
    decoded = base64.b64decode(screenshot)
    assert decoded[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# test_empty_page
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_page(page):
    await page.set_content("<html><body></body></html>")
    result = await extract_page_semantics(page)

    assert result["interactive_elements"] == []
    assert result["error_messages"] == []
    assert result["headings"] == []
    assert result["forms"] == []
    assert result["modals"] == []
    assert result["nav_items"] == []
    assert result["loading"] is False
    assert result.get("truncated", False) is False


# ---------------------------------------------------------------------------
# test_headings_extracted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_headings_extracted(page):
    await page.set_content("""
    <html>
    <body>
        <h1>Main Title</h1>
        <h2>Subtitle</h2>
        <h3>Section</h3>
    </body>
    </html>
    """)
    result = await extract_page_semantics(page)

    assert result["headings"] == ["Main Title", "Subtitle", "Section"]
