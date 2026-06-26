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


@pytest.mark.asyncio
async def test_extract_visible_read_only_texts(page):
    await page.set_content("""
    <html>
    <body>
        <main>
            <div class="metric-card">
                <span>盘点项目</span>
                <span>6个</span>
            </div>
            <div class="metric-card">
                <span>明星/核心人才</span>
                <span>10人</span>
            </div>
            <button>刷新</button>
        </main>
    </body>
    </html>
    """)

    result = await extract_page_semantics(page)

    assert "盘点项目" in result["visible_texts"]
    assert "6个" in result["visible_texts"]
    assert "明星/核心人才" in result["visible_texts"]
    assert "10人" in result["visible_texts"]
    assert "刷新" not in result["visible_texts"]


@pytest.mark.asyncio
async def test_extract_iframe_summary(page):
    await page.set_content("""
    <html>
    <body>
        <iframe
            name="detail-frame"
            srcdoc='<!doctype html><html><head><title>Frame Detail</title></head>
            <body><h2>Frame Details</h2><button>Approve</button></body></html>'>
        </iframe>
    </body>
    </html>
    """)
    await page.wait_for_selector("iframe")

    result = await extract_page_semantics(page)

    assert result["frames"]
    frame = result["frames"][0]
    assert frame["name"] == "detail-frame"
    assert frame["title"] == "Frame Detail"
    assert "Frame Details" in frame["text"]
    assert frame["interactive_count"] >= 1


@pytest.mark.asyncio
async def test_extract_shadow_dom_summary(page):
    await page.set_content("""
    <html>
    <body>
        <div id="shadow-host"></div>
        <script>
            const root = document.querySelector("#shadow-host").attachShadow({ mode: "open" });
            root.innerHTML = `
                <section>
                    <span>Shadow status ready</span>
                    <button aria-label="Shadow save">Save</button>
                </section>
            `;
        </script>
    </body>
    </html>
    """)

    result = await extract_page_semantics(page)

    assert result["shadow_dom"]
    shadow = result["shadow_dom"][0]
    assert shadow["host"] == "div#shadow-host"
    assert "Shadow status ready" in shadow["text"]
    assert shadow["interactive_count"] == 1
    assert shadow["controls"][0]["label"] == "Shadow save"


@pytest.mark.asyncio
async def test_extract_multi_tab_summary(page):
    await page.set_content("<html><head><title>Active Tab</title></head><body></body></html>")
    async with page.expect_popup() as popup_info:
        await page.evaluate("window.open('about:blank', '_blank')")
    other = await popup_info.value
    try:
        await other.set_content(
            "<html><head><title>Background Tab</title></head><body></body></html>"
        )
        await other.wait_for_load_state("domcontentloaded")

        result = await extract_page_semantics(page)
    finally:
        await other.close()

    tabs = result["tabs"]
    assert len(tabs) >= 2
    assert any(tab["title"] == "Active Tab" and tab["active"] for tab in tabs)
    assert any(tab["title"] == "Background Tab" and not tab["active"] for tab in tabs)


@pytest.mark.asyncio
async def test_extract_file_upload_and_complex_form_controls(page):
    await page.set_content("""
    <html>
    <body>
        <form id="profile-form" action="/profile" method="post">
            <label for="resume">简历文件</label>
            <input id="resume" name="resume" type="file" required>

            <label for="bio">个人简介</label>
            <textarea id="bio" name="bio" placeholder="请输入简介">已有简介</textarea>

            <label for="level">人才等级</label>
            <select id="level" name="level">
                <option>明星人才</option>
                <option selected>核心人才</option>
            </select>

            <label><input id="notify" name="notify" type="checkbox" checked>接收通知</label>
            <button type="submit">提交</button>
        </form>
    </body>
    </html>
    """)

    result = await extract_page_semantics(page)

    upload = next(
        el for el in result["interactive_elements"]
        if el["type"] == "input" and el["input_type"] == "file"
    )
    textarea = next(
        el for el in result["interactive_elements"]
        if el["type"] == "textarea"
    )
    select = next(
        el for el in result["interactive_elements"]
        if el["type"] == "select"
    )

    assert upload["label"] == "简历文件"
    assert upload["required"] is True
    assert textarea["label"] == "个人简介"
    assert textarea["value"] == "已有简介"
    assert select["label"] == "人才等级"
    assert select["options"] == ["明星人才", "核心人才"]

    form = result["forms"][0]
    assert form["id"] == "profile-form"
    assert form["method"] == "POST"
    assert form["field_count"] == 4
    assert form["submit_count"] == 1
    assert [field["field_type"] for field in form["fields"]] == [
        "file",
        "textarea",
        "select",
        "checkbox",
    ]


@pytest.mark.asyncio
async def test_playwright_fallback_extracts_hidden_file_and_textarea(page, monkeypatch):
    async def no_cdp_session(_page):
        return None

    monkeypatch.setattr("core.cdp_client.get_cdp_session", no_cdp_session)
    await page.set_content("""
    <html>
    <body>
        <label for="attachment">附件</label>
        <input id="attachment" type="file" style="display: none">
        <label for="comment">备注</label>
        <textarea id="comment">回退路径</textarea>
    </body>
    </html>
    """)

    result = await extract_page_semantics(page)

    assert result["semantic_extraction"]["source"] == "playwright_locator"
    assert any(
        el["type"] == "input" and el["input_type"] == "file"
        for el in result["interactive_elements"]
    )
    assert any(
        el["type"] == "textarea" and el["value"] == "回退路径"
        for el in result["interactive_elements"]
    )
