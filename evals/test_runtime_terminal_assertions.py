from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.interfaces import RuntimeExecutableCase
from core.page_semantic import _find_label
from core.runtime import Runtime


def test_root_url_is_not_treated_as_expected_path() -> None:
    assert Runtime._expected_paths_from_text("http://localhost:3001/") == []
    assert Runtime._expected_paths_from_text("see http://localhost:3001/dashboard") == [
        "/dashboard"
    ]


def test_action_case_requires_successful_input_and_submit_evidence() -> None:
    case = RuntimeExecutableCase(
        id="TC-action",
        objective="\u8f93\u5165\u65e0\u6548\u5bc6\u7801\u5e76\u70b9\u51fb\u767b\u5f55",
        expected="\u9875\u9762 URL \u4ecd\u4e3a http://localhost:3001/",
    )

    assert not Runtime._has_required_action_evidence(case, [])
    assert not Runtime._has_required_action_evidence(case, ["input: #username"])
    assert Runtime._has_required_action_evidence(
        case,
        ["input: #username", "clicked: #login-submit-button"],
    )


def test_completion_action_requires_action_evidence_when_case_is_interactive() -> None:
    passive_case = RuntimeExecutableCase(
        id="TC-passive",
        objective="\u9a8c\u8bc1\u767b\u5f55\u9875\u5b58\u5728\u4e00\u952e\u586b\u503c\u6309\u94ae",
        expected="\u9875\u9762\u53ef\u89c1\u4e00\u952e\u586b\u503c\u4f53\u9a8c",
    )
    action_case = RuntimeExecutableCase(
        id="TC-action",
        objective="\u8f93\u5165 admin/admin123 \u5e76\u70b9\u51fb\u7acb\u5373\u767b\u5f55",
        expected="\u8fdb\u5165\u63a7\u5236\u53f0",
    )

    assert Runtime._completion_action_allowed(passive_case, [])
    assert not Runtime._completion_action_allowed(action_case, [])
    assert Runtime._completion_action_allowed(
        action_case,
        ["input: #username-input", "clicked: #login-submit-button"],
    )


def test_execute_single_case_returns_passed_on_allowed_completion_action() -> None:
    async def run() -> None:
        runtime = Runtime(
            {
                "task_id": "completion-action",
                "target_url": "http://localhost:3001/",
            }
        )
        case = RuntimeExecutableCase(
            id="TC-passive",
            objective="\u9a8c\u8bc1\u767b\u5f55\u9875\u5b58\u5728\u4e00\u952e\u586b\u503c\u6309\u94ae",
            expected="\u4e00\u952e\u586b\u503c\u4f53\u9a8c\u6309\u94ae\u53ef\u89c1",
        )
        recorded: list[str] = []

        async def observe() -> dict[str, object]:
            return {
                "url": "http://localhost:3001/",
                "title": "\u4ed3\u9889\u77e5\u90533.0",
                "visible_texts": ["\u4e00\u952e\u586b\u503c\u4f53\u9a8c"],
            }

        async def evaluate(
            current_case: RuntimeExecutableCase,
            page_info: dict[str, object],
            evidence_refs: list[str],
        ) -> object:
            return None

        async def decide(
            current_case: RuntimeExecutableCase,
            page_info: dict[str, object],
            step_count: int,
        ) -> dict[str, object]:
            return {
                "tool": "mark_task_complete",
                "args": {
                    "message": "\u4e00\u952e\u586b\u503c\u4f53\u9a8c\u6309\u94ae\u53ef\u89c1"
                },
            }

        async def record_step(
            case_id: str,
            action: dict[str, object],
            result: str,
            tool_result: object,
        ) -> None:
            recorded.append(result)

        runtime._observe_page = observe  # type: ignore[method-assign]
        runtime._evaluate_terminal_assertion = evaluate  # type: ignore[method-assign]
        runtime._decide_execute_action = decide  # type: ignore[method-assign]
        runtime._record_step = record_step  # type: ignore[method-assign]

        result = await runtime._execute_single_case(case)
        assert result.terminal_status == "passed"
        assert len(recorded) == 1
        assert any("completion_action" in ref for ref in result.evidence_refs)

    asyncio.run(run())


def test_quick_fill_case_accepts_click_evidence() -> None:
    case = RuntimeExecutableCase(
        id="TC-quick-fill",
        objective=(
            "\u70b9\u51fb\u4e00\u952e\u586b\u503c\u4f53\u9a8c"
            "\u540e\u9a8c\u8bc1 username=admin"
        ),
        expected="password=cangjie*2026",
    )

    assert Runtime._has_required_action_evidence(case, ["clicked: #quick-fill"])
    assert Runtime._has_quick_fill_action_evidence(
        ["clicked: #1 -> role=button, name=\u4e00\u952e\u586b\u503c\u4f53\u9a8c"]
    )


def test_quick_fill_action_detection_excludes_passive_existence_case() -> None:
    passive_case = RuntimeExecutableCase(
        id="TC-quick-passive",
        objective="\u9a8c\u8bc1\u767b\u5f55\u9875\u5b58\u5728\u4e00\u952e\u586b\u503c\u4f53\u9a8c\u6309\u94ae",
        expected="\u6309\u94ae\u53ef\u89c1",
    )
    action_case = RuntimeExecutableCase(
        id="TC-quick-action",
        objective="\u70b9\u51fb\u4e00\u952e\u586b\u503c\u4f53\u9a8c\u540e\u9a8c\u8bc1 username=admin",
        expected="password=cangjie*2026",
    )

    assert not Runtime._case_requires_quick_fill_action(passive_case)
    assert Runtime._case_requires_quick_fill_action(action_case)


def test_deterministic_quick_fill_action_clicks_button_once() -> None:
    async def run() -> None:
        runtime = Runtime(
            {
                "task_id": "quick-fill-action",
                "target_url": "http://localhost:3001/",
            }
        )
        runtime.page = object()
        case = RuntimeExecutableCase(
            id="TC-quick-action",
            objective="\u70b9\u51fb\u4e00\u952e\u586b\u503c\u4f53\u9a8c\u540e\u9a8c\u8bc1 username=admin",
            expected="password=cangjie*2026",
        )

        action = await runtime._deterministic_quick_fill_action(case, [])
        assert action == {
            "tool": "click",
            "args": {"selector": "button:has-text(\"\u4e00\u952e\u586b\u503c\u4f53\u9a8c\")"},
        }
        assert await runtime._deterministic_quick_fill_action(
            case,
            ["clicked: #1 -> role=button, name=\u4e00\u952e\u586b\u503c\u4f53\u9a8c"],
        ) is None

    asyncio.run(run())


def test_execution_prompt_includes_configured_accounts() -> None:
    runtime = Runtime(
        {
            "task_id": "account-context",
            "target_url": "http://localhost:3001/",
            "accounts": [
                {
                    "role": "admin",
                    "username": "admin",
                    "password": "admin123",
                    "display_name": "zhanghong",
                }
            ],
        }
    )
    case = RuntimeExecutableCase(
        id="TC-login",
        objective="valid admin login",
        expected="dashboard",
        required_roles=["admin"],
    )

    section = runtime._execution_account_context_section(case)
    assert "username=admin" in section
    assert "password=admin123" in section
    assert "zhanghong" in section
    assert "cangjie*2026" in section


def test_configured_login_terminal_accepts_display_name_alias() -> None:
    runtime = Runtime(
        {
            "task_id": "configured-login-terminal",
            "target_url": "http://localhost:3001/",
            "accounts": [
                {
                    "role": "admin",
                    "username": "admin",
                    "password": "admin123",
                    "display_name": "zhanghong",
                }
            ],
        }
    )
    case = RuntimeExecutableCase(
        id="TC-login",
        objective="\u6709\u6548\u51ed\u636e\u767b\u5f55\u540e\u8fdb\u5165\u63a7\u5236\u53f0",
        expected=(
            "\u663e\u793a admin \u548c"
            "\u667a\u80fd\u4f53\u5e7f\u573a\u3001"
            "\u77e5\u8bc6\u5e93\u7ba1\u7406"
        ),
        required_roles=["admin"],
    )
    page_info = {
        "title": "\u4ed3\u9889\u77e5\u90533.0",
        "headings": [],
        "visible_texts": [
            "zhanghong",
            "\u667a\u80fd\u4f53\u5e7f\u573a",
            "\u77e5\u8bc6\u5e93\u7ba1\u7406",
            "\u6280\u80fd\u7ba1\u7406",
        ],
        "error_messages": [],
    }

    assertion = runtime._deterministic_configured_login_terminal_assertion(
        case,
        page_info,
        ["clicked: #login-submit-button -> #login-submit-button"],
    )

    assert assertion is not None
    assert assertion.objective_satisfied
    assert assertion.expected_result_supported


def test_configured_login_terminal_reads_interactive_entry_labels() -> None:
    runtime = Runtime(
        {
            "task_id": "configured-login-interactive-terminal",
            "target_url": "http://localhost:3001/",
            "accounts": [
                {
                    "role": "admin",
                    "username": "admin",
                    "password": "admin123",
                    "display_name": "zhanghong",
                }
            ],
        }
    )
    case = RuntimeExecutableCase(
        id="TC-login",
        objective="\u6709\u6548\u51ed\u636e\u767b\u5f55\u540e\u8fdb\u5165\u63a7\u5236\u53f0",
        expected="\u63a7\u5236\u53f0\u5165\u53e3\u53ef\u89c1",
        required_roles=["admin"],
    )
    page_info = {
        "title": "\u4ed3\u9889\u77e5\u90533.0",
        "headings": ["zhanghong"],
        "visible_texts": [],
        "error_messages": [],
        "interactive_elements": [
            {"type": "button", "text": "\u667a\u80fd\u4f53\u5e7f\u573a"},
            {"type": "button", "label": "\u77e5\u8bc6\u5e93\u7ba1\u7406"},
            {"type": "button", "text": "\u6280\u80fd\u7ba1\u7406"},
        ],
    }

    assertion = runtime._deterministic_configured_login_terminal_assertion(
        case,
        page_info,
        ["clicked: #login-submit-button -> #login-submit-button"],
    )

    assert assertion is not None
    assert assertion.objective_satisfied


def test_configured_login_detection_excludes_quick_fill() -> None:
    login_case = RuntimeExecutableCase(
        id="TC-login",
        objective="\u6709\u6548\u51ed\u636e\u767b\u5f55\u540e\u8fdb\u5165\u63a7\u5236\u53f0",
        expected="dashboard",
        required_roles=["admin"],
    )
    quick_fill_case = RuntimeExecutableCase(
        id="TC-quick",
        objective="\u70b9\u51fb\u4e00\u952e\u586b\u503c\u4f53\u9a8c",
        expected="username=admin password=cangjie*2026",
    )

    assert Runtime._case_requires_configured_login(login_case)
    assert not Runtime._case_requires_configured_login(quick_fill_case)


def test_configured_login_action_requires_visible_login_controls() -> None:
    class FakePage:
        def __init__(self, values: dict[str, object]) -> None:
            self.values = values

        async def evaluate(self, script: str) -> dict[str, object]:
            return self.values

    async def run() -> None:
        runtime = Runtime(
            {
                "task_id": "configured-login-action",
                "target_url": "http://localhost:3001/",
                "accounts": [
                    {"role": "admin", "username": "admin", "password": "admin123"}
                ],
            }
        )
        case = RuntimeExecutableCase(
            id="TC-login",
            objective="\u6709\u6548\u51ed\u636e\u767b\u5f55\u540e\u8fdb\u5165\u63a7\u5236\u53f0",
            expected="dashboard",
            required_roles=["admin"],
        )

        runtime.page = FakePage(
            {
                "usernamePresent": False,
                "passwordPresent": False,
                "submitVisible": False,
                "username": "",
                "password": "",
            }
        )
        assert await runtime._deterministic_login_action(case) is None

        runtime.page = FakePage(
            {
                "usernamePresent": True,
                "passwordPresent": True,
                "submitVisible": True,
                "username": "",
                "password": "",
            }
        )
        assert await runtime._deterministic_login_action(case) == {
            "tool": "input_text",
            "args": {"selector": "#username-input", "text": "admin"},
        }

        runtime.page = FakePage(
            {
                "usernamePresent": True,
                "passwordPresent": True,
                "submitVisible": True,
                "username": "admin",
                "password": "",
            }
        )
        assert await runtime._deterministic_login_action(case) == {
            "tool": "input_text",
            "args": {"selector": "#password-input", "text": "admin123"},
        }

        runtime.page = FakePage(
            {
                "usernamePresent": True,
                "passwordPresent": True,
                "submitVisible": True,
                "username": "admin",
                "password": "admin123",
            }
        )
        assert await runtime._deterministic_login_action(case) == {
            "tool": "click",
            "args": {"selector": "#login-submit-button"},
        }

    asyncio.run(run())


def test_configured_login_sequence_refills_username_and_password() -> None:
    class FakePage:
        async def evaluate(self, script: str) -> dict[str, object]:
            return {
                "usernamePresent": True,
                "passwordPresent": True,
                "submitVisible": True,
                "username": "admin",
                "password": "cangjie*2026",
            }

        async def wait_for_timeout(self, timeout: int) -> None:
            assert timeout == 500

    class FakeToolResult:
        def __init__(self, action: dict[str, object]) -> None:
            self.action = action

        def feedback_text(self) -> str:
            tool = self.action["tool"]
            selector = self.action["args"]["selector"]  # type: ignore[index]
            return f"{tool}: {selector}"

        def is_failure(self) -> bool:
            return False

    async def run() -> None:
        runtime = Runtime(
            {
                "task_id": "configured-login-sequence",
                "target_url": "http://localhost:3001/",
                "accounts": [
                    {"role": "admin", "username": "admin", "password": "admin123"}
                ],
            }
        )
        runtime.page = FakePage()
        case = RuntimeExecutableCase(
            id="TC-login",
            objective="\u6709\u6548\u51ed\u636e\u767b\u5f55\u540e\u8fdb\u5165\u63a7\u5236\u53f0",
            expected="dashboard",
            required_roles=["admin"],
        )
        actions: list[dict[str, object]] = []

        async def execute(action: dict[str, object]) -> FakeToolResult:
            actions.append(action)
            return FakeToolResult(action)

        async def record_step(
            case_id: str,
            action: dict[str, object],
            result: str,
            tool_result: object,
        ) -> None:
            assert case_id == "TC-login"

        runtime._execute_test_action = execute  # type: ignore[method-assign]
        runtime._record_step = record_step  # type: ignore[method-assign]

        evidence: list[str] = []
        assert await runtime._execute_configured_login_sequence(case, evidence)
        assert actions == [
            {
                "tool": "input_text",
                "args": {"selector": "#username-input", "text": "admin"},
            },
            {
                "tool": "input_text",
                "args": {"selector": "#password-input", "text": "admin123"},
            },
            {"tool": "click", "args": {"selector": "#login-submit-button"}},
        ]
        assert any("#username-input" in item for item in evidence)
        assert any("#password-input" in item for item in evidence)

    asyncio.run(run())


def test_invalid_login_terminal_requires_error_on_login_page() -> None:
    runtime = Runtime(
        {
            "task_id": "invalid-login-terminal",
            "target_url": "http://localhost:3001/",
            "accounts": [
                {"role": "admin", "username": "admin", "password": "admin123"}
            ],
        }
    )
    case = RuntimeExecutableCase(
        id="TC-invalid-login",
        objective="\u8f93\u5165 admin/cangjie*2026 \u5e76\u70b9\u51fb\u767b\u5f55",
        expected="\u505c\u7559\u5728\u767b\u5f55\u9875\u5e76\u663e\u793a\u5bc6\u7801\u9519\u8bef",
    )

    assertion = runtime._deterministic_invalid_login_terminal_assertion(
        case,
        {
            "url": "http://localhost:3001/",
            "title": "\u4ed3\u9889\u77e5\u90533.0",
            "visible_texts": ["\u7528\u6237\u540d", "\u5bc6\u7801", "\u7acb\u5373\u767b\u5f55"],
            "error_messages": ["\u5bc6\u7801\u9519\u8bef"],
            "interactive_elements": [],
        },
        ["input: #username-input", "clicked: #login-submit-button"],
    )

    assert assertion is not None
    assert assertion.objective_satisfied

    failed = runtime._deterministic_invalid_login_terminal_assertion(
        case,
        {
            "title": "\u4ed3\u9889\u77e5\u90533.0",
            "visible_texts": ["zhanghong", "\u667a\u80fd\u4f53\u5e7f\u573a", "\u77e5\u8bc6\u5e93\u7ba1\u7406"],
            "error_messages": [],
            "interactive_elements": [],
        },
        ["input: #username-input", "clicked: #login-submit-button"],
    )

    assert failed is not None
    assert not failed.objective_satisfied


def test_invalid_login_password_falls_back_to_task_config_demo_password() -> None:
    runtime = Runtime(
        {
            "task_id": "invalid-login-password-fallback",
            "target_url": "http://localhost:3001/",
            "accounts": [
                {"role": "admin", "username": "admin", "password": "admin123"}
            ],
            "prd": [
                "一键填值体验当前填入 admin/cangjie*2026，该密码应登录失败。"
            ],
        }
    )
    case = RuntimeExecutableCase(
        id="TC-invalid-vague",
        objective="覆盖错误输入方式的完整错误流程",
        expected="登录失败并显示错误提示",
    )

    assert Runtime._case_requires_invalid_login_submission(case)
    assert runtime._invalid_login_password_for_case(case) == "cangjie*2026"


def test_reset_browser_state_clears_rich_browser_storage() -> None:
    class FakeContext:
        def __init__(self) -> None:
            self.cookies_cleared = False
            self.permissions_cleared = False

        async def clear_cookies(self) -> None:
            self.cookies_cleared = True

        async def clear_permissions(self) -> None:
            self.permissions_cleared = True

    class FakeCdpSession:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, str]]] = []

        async def send(self, method: str, payload: dict[str, str]) -> None:
            self.calls.append((method, payload))

    class FakePage:
        def __init__(self) -> None:
            self.scripts: list[str] = []
            self.gotos: list[tuple[str, str, int]] = []

        def is_closed(self) -> bool:
            return False

        async def evaluate(self, script: str) -> None:
            self.scripts.append(script)

        async def goto(
            self,
            url: str,
            *,
            wait_until: str,
            timeout: int,
        ) -> None:
            self.gotos.append((url, wait_until, timeout))

    runtime = Runtime(
        {
            "task_id": "reset-storage",
            "target_url": "http://localhost:3001/",
        }
    )
    context = FakeContext()
    cdp_session = FakeCdpSession()
    page = FakePage()
    runtime.context = context
    runtime._cdp_session = cdp_session
    runtime.page = page

    asyncio.run(runtime._reset_browser_state())

    assert context.cookies_cleared
    assert context.permissions_cleared
    assert any("indexedDB.deleteDatabase" in script for script in page.scripts)
    assert any("caches.keys" in script for script in page.scripts)
    assert page.gotos == [
        ("about:blank", "domcontentloaded", 15000),
        ("http://localhost:3001/", "networkidle", 30000),
    ]
    assert (
        "Storage.clearDataForOrigin",
        {"origin": "http://localhost:3001", "storageTypes": "all"},
    ) in cdp_session.calls


def test_agent_write_case_requires_configured_login_even_when_negative() -> None:
    create_case = RuntimeExecutableCase(
        id="TC-agent-create",
        objective="通过 UI 新增智能体 测试智能体-TA-20260704-AUTO",
        expected="列表搜索 TA-20260704-AUTO 后显示测试智能体-TA-20260704-AUTO",
        required_roles=["管理员"],
    )
    invalid_case = RuntimeExecutableCase(
        id="TC-agent-invalid",
        objective="新增智能体时 gatewayUrl 填 not-url",
        expected="显示 URL 格式错误，搜索 TA-20260704-INVALID 不存在",
        required_roles=["管理员"],
    )

    assert Runtime._case_requires_agent_create(create_case)
    assert Runtime._case_requires_agent_invalid_gateway(invalid_case)
    assert Runtime._case_requires_configured_login(create_case)
    assert Runtime._case_requires_configured_login(invalid_case)


def test_agent_invalid_gateway_is_not_invalid_login_submission() -> None:
    case = RuntimeExecutableCase(
        id="TC-agent-invalid-not-login",
        objective=(
            "管理员登录后新增智能体，gatewayUrl 为 not-url 无效格式，"
            "提交保存应被拒绝"
        ),
        expected="停留在新增智能体弹窗，显示错误，不能创建 TA-20260704-INVALID",
        required_roles=["管理员"],
    )

    assert Runtime._case_requires_agent_invalid_gateway(case)
    assert not Runtime._case_requires_invalid_login_submission(case)


def test_agent_write_data_uses_explicit_names_and_gateway() -> None:
    create_case = RuntimeExecutableCase(
        id="TC-agent-create",
        objective="通过 UI 新增智能体 测试智能体-TA-20260704-AUTO",
        expected="gatewayUrl=https://agent-gateway.cangjie.ai/v1/ta-20260704-auto",
    )
    invalid_case = RuntimeExecutableCase(
        id="TC-agent-invalid",
        objective="通过 UI 新增智能体 测试智能体-TA-20260704-INVALID",
        expected="gatewayUrl=not-url 被校验阻断",
    )

    assert Runtime._agent_write_data_for_case(create_case) == (
        "测试智能体-TA-20260704-AUTO",
        "由 test_agent 自动化验收创建，可安全清理 TA-20260704",
        "https://agent-gateway.cangjie.ai/v1/ta-20260704-auto",
    )
    assert Runtime._agent_write_data_for_case(invalid_case) == (
        "测试智能体-TA-20260704-INVALID",
        "由 test_agent 自动化验收创建，可安全清理 TA-20260704",
        "not-url",
    )


def test_agent_create_terminal_requires_visible_created_record() -> None:
    async def run() -> None:
        runtime = Runtime(
            {
                "task_id": "agent-create-terminal",
                "target_url": "http://localhost:3001/",
            }
        )
        case = RuntimeExecutableCase(
            id="TC-agent-create",
            objective="通过 UI 新增智能体 测试智能体-TA-20260704-AUTO",
            expected="列表显示测试智能体-TA-20260704-AUTO",
        )

        assertion = await runtime._deterministic_agent_write_terminal_assertion(
            case,
            {
                "title": "仓颉知道3.0",
                "visible_texts": ["测试智能体-TA-20260704-AUTO", "端点地址:"],
                "error_messages": [],
            },
            [
                "input: input[placeholder=\"https://...\"]",
                "clicked: button[type=\"submit\"]:has-text(\"保存\")",
            ],
        )

        assert assertion is not None
        assert assertion.objective_satisfied

    asyncio.run(run())


def test_agent_invalid_gateway_terminal_uses_browser_validity() -> None:
    class FakePage:
        async def evaluate(self, script: str) -> dict[str, object]:
            return {
                "name": "测试智能体-TA-20260704-INVALID",
                "description": "",
                "gateway": "not-url",
                "gatewayValid": False,
                "gatewayValidation": "请输入网址",
                "saveVisible": True,
                "titleVisible": True,
            }

    async def run() -> None:
        runtime = Runtime(
            {
                "task_id": "agent-invalid-terminal",
                "target_url": "http://localhost:3001/",
            }
        )
        runtime.page = FakePage()
        case = RuntimeExecutableCase(
            id="TC-agent-invalid",
            objective="通过 UI 新增智能体 测试智能体-TA-20260704-INVALID",
            expected="gatewayUrl=not-url 被校验阻断",
        )

        assertion = await runtime._deterministic_agent_write_terminal_assertion(
            case,
            {
                "title": "仓颉知道3.0",
                "visible_texts": ["新增智能体", "保存"],
                "error_messages": [],
            },
            ["clicked: button[type=\"submit\"]:has-text(\"保存\")"],
        )

        assert assertion is not None
        assert assertion.objective_satisfied

    asyncio.run(run())


def test_agent_write_sequence_fills_name_description_gateway_and_saves() -> None:
    class FakePage:
        async def evaluate(self, script: str) -> object:
            if "#username-input" in script:
                return None
            return None

        async def wait_for_timeout(self, timeout: int) -> None:
            assert timeout == 700

    class FakeToolResult:
        def __init__(self, action: dict[str, object]) -> None:
            self.action = action

        def feedback_text(self) -> str:
            selector = self.action["args"]["selector"]  # type: ignore[index]
            return f"{self.action['tool']}: {selector}"

        def is_failure(self) -> bool:
            return False

    async def run() -> None:
        runtime = Runtime(
            {
                "task_id": "agent-write-sequence",
                "target_url": "http://localhost:3001/",
            }
        )
        runtime.page = FakePage()
        case = RuntimeExecutableCase(
            id="TC-agent-create",
            objective="通过 UI 新增智能体 测试智能体-TA-20260704-AUTO",
            expected="列表搜索 TA-20260704-AUTO",
        )
        actions: list[dict[str, object]] = []

        async def execute(action: dict[str, object]) -> FakeToolResult:
            actions.append(action)
            return FakeToolResult(action)

        async def record_step(
            case_id: str,
            action: dict[str, object],
            result: str,
            tool_result: object,
        ) -> None:
            assert case_id == "TC-agent-create"

        runtime._execute_test_action = execute  # type: ignore[method-assign]
        runtime._record_step = record_step  # type: ignore[method-assign]

        evidence: list[str] = []
        assert await runtime._execute_agent_write_sequence(case, evidence)
        assert [action["tool"] for action in actions] == [
            "click",
            "input_text",
            "input_text",
            "input_text",
            "click",
        ]
        assert actions[-1]["args"]["selector"] == "button[type=\"submit\"]:has-text(\"保存\")"  # type: ignore[index]
        assert any("https://..." in item for item in evidence)

    asyncio.run(run())


def test_dataset_write_case_requires_configured_login_even_when_negative() -> None:
    create_case = RuntimeExecutableCase(
        id="TC-dataset-create",
        objective="通过 UI 新建知识库 测试知识库-TA-20260704-AUTO",
        expected="列表显示测试知识库-TA-20260704-AUTO",
        required_roles=["管理员"],
    )
    empty_case = RuntimeExecutableCase(
        id="TC-dataset-empty",
        objective="通过 UI 新建知识库时名称留空，描述填写测试空名称-TA-20260704-EMPTY",
        expected="名称必填校验阻断，不能创建 TA-20260704-EMPTY 记录",
        required_roles=["管理员"],
    )

    assert Runtime._case_requires_dataset_create(create_case)
    assert Runtime._case_requires_dataset_empty_name(empty_case)
    assert Runtime._case_requires_configured_login(create_case)
    assert Runtime._case_requires_configured_login(empty_case)
    assert not Runtime._case_requires_invalid_login_submission(empty_case)


def test_dataset_write_data_uses_explicit_names_and_empty_marker() -> None:
    create_case = RuntimeExecutableCase(
        id="TC-dataset-create",
        objective="通过 UI 新建知识库 测试知识库-TA-20260704-AUTO",
        expected="列表显示测试知识库-TA-20260704-AUTO",
    )
    empty_case = RuntimeExecutableCase(
        id="TC-dataset-empty",
        objective="通过 UI 新建知识库时名称留空",
        expected="测试空名称-TA-20260704-EMPTY 不能创建",
    )

    assert Runtime._dataset_write_data_for_case(create_case) == (
        "测试知识库-TA-20260704-AUTO",
        "由 test_agent 自动化验收创建，可安全清理 TA-20260704",
        "TA-20260704-EMPTY",
    )
    assert Runtime._dataset_write_data_for_case(empty_case) == (
        "",
        "测试空名称-TA-20260704-EMPTY",
        "TA-20260704-EMPTY",
    )


def test_dataset_create_terminal_requires_visible_created_record() -> None:
    async def run() -> None:
        runtime = Runtime(
            {
                "task_id": "dataset-create-terminal",
                "target_url": "http://localhost:3001/",
            }
        )
        case = RuntimeExecutableCase(
            id="TC-dataset-create",
            objective="通过 UI 新建知识库 测试知识库-TA-20260704-AUTO",
            expected="列表显示测试知识库-TA-20260704-AUTO",
        )

        assertion = await runtime._deterministic_dataset_write_terminal_assertion(
            case,
            {
                "title": "仓颉知道3.0",
                "visible_texts": ["测试知识库-TA-20260704-AUTO", "文档数 0"],
                "error_messages": [],
            },
            [
                "input: input[placeholder=\"例如：财务政策库\"]",
                "clicked: button[type=\"submit\"]:has-text(\"保存\")",
            ],
        )

        assert assertion is not None
        assert assertion.objective_satisfied

    asyncio.run(run())


def test_dataset_empty_name_terminal_uses_browser_validity() -> None:
    class FakePage:
        async def evaluate(self, script: str) -> dict[str, object]:
            return {
                "name": "",
                "intro": "测试空名称-TA-20260704-EMPTY",
                "nameValid": False,
                "nameValidation": "请填写此字段",
                "saveVisible": True,
                "titleVisible": True,
            }

    async def run() -> None:
        runtime = Runtime(
            {
                "task_id": "dataset-empty-terminal",
                "target_url": "http://localhost:3001/",
            }
        )
        runtime.page = FakePage()
        case = RuntimeExecutableCase(
            id="TC-dataset-empty",
            objective="通过 UI 新建知识库时名称留空，描述填写测试空名称-TA-20260704-EMPTY",
            expected="名称必填校验阻断，不能创建 TA-20260704-EMPTY 记录",
        )

        assertion = await runtime._deterministic_dataset_write_terminal_assertion(
            case,
            {
                "title": "仓颉知道3.0",
                "visible_texts": ["新建知识库", "保存"],
                "error_messages": [],
            },
            ["clicked: button[type=\"submit\"]:has-text(\"保存\")"],
        )

        assert assertion is not None
        assert assertion.objective_satisfied

    asyncio.run(run())


def test_dataset_write_sequence_fills_name_intro_and_saves() -> None:
    class FakePage:
        async def evaluate(self, script: str) -> object:
            return None

        async def wait_for_timeout(self, timeout: int) -> None:
            assert timeout == 700

    class FakeToolResult:
        def __init__(self, action: dict[str, object]) -> None:
            self.action = action

        def feedback_text(self) -> str:
            selector = self.action["args"]["selector"]  # type: ignore[index]
            return f"{self.action['tool']}: {selector}"

        def is_failure(self) -> bool:
            return False

    async def run() -> None:
        runtime = Runtime(
            {
                "task_id": "dataset-write-sequence",
                "target_url": "http://localhost:3001/",
            }
        )
        runtime.page = FakePage()
        case = RuntimeExecutableCase(
            id="TC-dataset-create",
            objective="通过 UI 新建知识库 测试知识库-TA-20260704-AUTO",
            expected="列表显示 TA-20260704-AUTO",
        )
        actions: list[dict[str, object]] = []

        async def execute(action: dict[str, object]) -> FakeToolResult:
            actions.append(action)
            return FakeToolResult(action)

        async def record_step(
            case_id: str,
            action: dict[str, object],
            result: str,
            tool_result: object,
        ) -> None:
            assert case_id == "TC-dataset-create"

        runtime._execute_test_action = execute  # type: ignore[method-assign]
        runtime._record_step = record_step  # type: ignore[method-assign]

        evidence: list[str] = []
        assert await runtime._execute_dataset_write_sequence(case, evidence)
        assert [action["tool"] for action in actions] == [
            "click",
            "click",
            "input_text",
            "input_text",
            "click",
        ]
        assert actions[0]["args"]["selector"] == "#tab-kb-mgmt"  # type: ignore[index]
        assert actions[-1]["args"]["selector"] == "button[type=\"submit\"]:has-text(\"保存\")"  # type: ignore[index]
        assert any("财务政策库" in item for item in evidence)

    asyncio.run(run())


def test_skill_write_case_requires_configured_login_and_uses_explicit_data() -> None:
    scaffold_case = RuntimeExecutableCase(
        id="TC-skill-scaffold",
        objective="通过 UI 技能管理快速初始化脚手架，保存为 测试技能-TA-20260704-AUTO 后验证 SKILL.md 和 index.js",
        expected="技能列表显示 测试技能-TA-20260704-AUTO",
        required_roles=["管理员"],
    )
    duplicate_case = RuntimeExecutableCase(
        id="TC-skill-duplicate",
        objective="通过 UI 在线修编尝试新建重复核心文件 SKILL.md",
        expected="重复创建 SKILL.md 核心文件被阻断",
        required_roles=["管理员"],
    )

    assert Runtime._case_requires_skill_scaffold(scaffold_case)
    assert Runtime._case_requires_skill_duplicate_core_file(duplicate_case)
    assert Runtime._case_requires_configured_login(scaffold_case)
    assert Runtime._case_requires_configured_login(duplicate_case)
    assert not Runtime._case_requires_invalid_login_submission(duplicate_case)
    assert Runtime._skill_write_data_for_case(scaffold_case) == (
        "测试技能-TA-20260704-AUTO",
        "test_agent",
        "由 test_agent 自动化验收创建，可安全清理 TA-20260704",
    )


def test_skill_scaffold_terminal_requires_visible_skill_and_core_files() -> None:
    async def run() -> None:
        runtime = Runtime(
            {
                "task_id": "skill-scaffold-terminal",
                "target_url": "http://localhost:3001/",
            }
        )
        case = RuntimeExecutableCase(
            id="TC-skill-scaffold",
            objective="通过 UI 技能管理快速初始化脚手架，保存为 测试技能-TA-20260704-AUTO 后验证 SKILL.md 和 index.js",
            expected="技能列表显示 测试技能-TA-20260704-AUTO，文件树包含 SKILL.md 和 index.js",
        )

        assertion = await runtime._deterministic_skill_write_terminal_assertion(
            case,
            {
                "title": "仓颉知道3.0",
                "visible_texts": ["测试技能-TA-20260704-AUTO"],
                "error_messages": [],
            },
            [
                'clicked: button:has-text("快速初始化脚手架")',
                'clicked: div.fixed button:has-text("编译构建并加载")',
                "skill_file_tree: SKILL.md,index.js",
            ],
        )

        assert assertion is not None
        assert assertion.objective_satisfied

        weak_assertion = await runtime._deterministic_skill_write_terminal_assertion(
            case,
            {
                "title": "仓颉知道3.0",
                "visible_texts": ["测试技能-TA-20260704-AUTO"],
                "error_messages": [],
            },
            [
                'clicked: button:has-text("快速初始化脚手架")',
                'clicked: div.fixed button:has-text("编译构建并加载")',
            ],
        )
        assert weak_assertion is None

    asyncio.run(run())


def test_skill_duplicate_core_terminal_uses_dialog_evidence() -> None:
    async def run() -> None:
        runtime = Runtime(
            {
                "task_id": "skill-duplicate-terminal",
                "target_url": "http://localhost:3001/",
            }
        )
        case = RuntimeExecutableCase(
            id="TC-skill-duplicate",
            objective="通过 UI 在线修编尝试新建重复核心文件 SKILL.md",
            expected="重复创建 SKILL.md 核心文件被阻断",
        )

        assertion = await runtime._deterministic_skill_write_terminal_assertion(
            case,
            {
                "title": "仓颉知道3.0",
                "visible_texts": ["测试技能-TA-20260704-AUTO", "SKILL.md", "index.js"],
                "error_messages": [],
            },
            [
                "pressed: Enter on SKILL.md duplicate file path",
                "dialog: SKILL.md为核心文件，不可重复创建",
            ],
        )

        assert assertion is not None
        assert assertion.objective_satisfied

    asyncio.run(run())


def test_skill_scaffold_sequence_creates_renames_and_reopens_editor() -> None:
    class FakeLocator:
        def __init__(self, selector: str, page: "FakePage") -> None:
            self.selector = selector
            self.page = page

        def first(self) -> "FakeLocator":
            return self

        async def click(self, timeout: int = 0) -> None:
            assert timeout == 5000
            if self.selector.startswith("#edit-skill-btn-"):
                self.page.modal_open = True

        async def fill(self, value: str, timeout: int = 0) -> None:
            raise AssertionError("positive scaffold path should fill via _execute_test_action")

        async def press(self, key: str, timeout: int = 0) -> None:
            raise AssertionError("positive scaffold path should not press keys")

    class FakePage:
        def __init__(self) -> None:
            self.editor_clicks = 0
            self.modal_open = False

        async def evaluate(self, script: str, target_name: str = "") -> object:
            if "return {modal: false, closed: false}" in script:
                if self.modal_open:
                    self.modal_open = False
                    return {"modal": True, "closed": True}
                return {"modal": False, "closed": False}
            if "hasSkillMd" in script and "hasIndexJs" in script:
                return {
                    "hasSkillMd": True,
                    "hasIndexJs": True,
                    "excerpt": "SKILL.md index.js",
                }
            self.editor_clicks += 1
            return "edit-skill-btn-sk-cst-1"

        def locator(self, selector: str) -> FakeLocator:
            return FakeLocator(selector, self)

        async def wait_for_timeout(self, timeout: int) -> None:
            assert timeout in {300, 700, 900}

    class FakeToolResult:
        def __init__(self, action: dict[str, object]) -> None:
            self.action = action

        def feedback_text(self) -> str:
            selector = self.action["args"]["selector"]  # type: ignore[index]
            return f"{self.action['tool']}: {selector}"

        def is_failure(self) -> bool:
            return False

    async def run() -> None:
        runtime = Runtime(
            {
                "task_id": "skill-scaffold-sequence",
                "target_url": "http://localhost:3001/",
            }
        )
        runtime.page = FakePage()
        case = RuntimeExecutableCase(
            id="TC-skill-scaffold",
            objective="通过 UI 技能管理快速初始化脚手架，保存为 测试技能-TA-20260704-AUTO 后验证 SKILL.md 和 index.js",
            expected="技能列表显示 测试技能-TA-20260704-AUTO",
        )
        actions: list[dict[str, object]] = []

        async def execute(action: dict[str, object]) -> FakeToolResult:
            actions.append(action)
            return FakeToolResult(action)

        async def record_step(
            case_id: str,
            action: dict[str, object],
            result: str,
            tool_result: object,
        ) -> None:
            assert case_id == "TC-skill-scaffold"

        runtime._execute_test_action = execute  # type: ignore[method-assign]
        runtime._record_step = record_step  # type: ignore[method-assign]

        evidence: list[str] = []
        assert await runtime._execute_skill_write_sequence(case, evidence)
        assert [action["tool"] for action in actions] == [
            "click",
            "click",
            "input_text",
            "input_text",
            "input_text",
            "input_text",
            "click",
        ]
        assert actions[0]["args"]["selector"] == "#tab-skills-mgmt"  # type: ignore[index]
        assert actions[1]["args"]["selector"] == 'button:has-text("快速初始化脚手架")'  # type: ignore[index]
        assert actions[-1]["args"]["selector"] == 'div.fixed button:has-text("编译构建并加载")'  # type: ignore[index]
        assert evidence.count("clicked: skill editor button #edit-skill-btn-sk-cst-1") == 2
        assert "skill_file_tree: SKILL.md,index.js" in evidence
        assert any(item.startswith("closed: skill editor modal") for item in evidence)

    asyncio.run(run())


def test_skill_duplicate_sequence_accepts_first_locator_property() -> None:
    class FakeLocator:
        def __init__(self, selector: str, page: "FakePage") -> None:
            self.selector = selector
            self.page = page

        @property
        def first(self) -> "FakeLocator":
            return self

        async def click(self, timeout: int = 0) -> None:
            assert timeout == 5000
            if self.selector.startswith("#edit-skill-btn-"):
                self.page.modal_open = True

        async def fill(self, value: str, timeout: int = 0) -> None:
            assert timeout == 5000
            assert value == "SKILL.md"

        async def press(self, key: str, timeout: int = 0) -> None:
            assert timeout == 5000
            assert key == "Enter"

    class FakePage:
        def __init__(self) -> None:
            self.modal_open = False

        async def evaluate(self, script: str, target_name: str = "") -> object:
            if "return {modal: false, closed: false}" in script:
                if self.modal_open:
                    self.modal_open = False
                    return {"modal": True, "closed": True}
                return {"modal": False, "closed": False}
            if "hasSkillMd" in script and "matched" in script:
                return {
                    "hasSkillMd": True,
                    "matched": ["duplicate"],
                    "excerpt": "SKILL.md duplicate core file",
                }
            return "edit-skill-btn-sk-cst-1"

        def locator(self, selector: str) -> FakeLocator:
            return FakeLocator(selector, self)

        def once(self, event: str, callback: object) -> None:
            assert event == "dialog"

        async def wait_for_timeout(self, timeout: int) -> None:
            assert timeout in {300, 700, 900, 1200}

    class FakeToolResult:
        def __init__(self, action: dict[str, object]) -> None:
            self.action = action

        def feedback_text(self) -> str:
            selector = self.action["args"]["selector"]  # type: ignore[index]
            return f"{self.action['tool']}: {selector}"

        def is_failure(self) -> bool:
            return False

    async def run() -> None:
        runtime = Runtime(
            {
                "task_id": "skill-duplicate-sequence",
                "target_url": "http://localhost:3001/",
            }
        )
        runtime.page = FakePage()
        case = RuntimeExecutableCase(
            id="TC-skill-duplicate",
            objective="通过 UI 在线修编尝试新建重复核心文件 SKILL.md",
            expected="重复创建 SKILL.md 核心文件被阻断",
        )
        actions: list[dict[str, object]] = []

        async def execute(action: dict[str, object]) -> FakeToolResult:
            actions.append(action)
            return FakeToolResult(action)

        async def record_step(
            case_id: str,
            action: dict[str, object],
            result: str,
            tool_result: object,
        ) -> None:
            assert case_id == "TC-skill-duplicate"

        runtime._execute_test_action = execute  # type: ignore[method-assign]
        runtime._record_step = record_step  # type: ignore[method-assign]

        evidence: list[str] = []
        assert await runtime._execute_skill_write_sequence(case, evidence)
        assert actions[0]["args"]["selector"] == "#tab-skills-mgmt"  # type: ignore[index]
        assert "pressed: Enter on SKILL.md duplicate file path" in evidence
        assert "duplicate_block_visible: SKILL.md duplicate core file" in evidence
        assert not any(item.startswith("skill_duplicate_submit_failed") for item in evidence)

    asyncio.run(run())


def test_label_lookup_uses_bounded_dom_query() -> None:
    class FakeElement:
        async def get_attribute(self, name: str) -> str:
            values = {
                "aria-label": "",
                "id": "password-input",
                "placeholder": "Password",
            }
            return values.get(name, "")

    class FakePage:
        def locator(self, selector: str) -> object:
            raise AssertionError("label lookup should not use locator waits")

        async def evaluate(self, script: str, value: str) -> str:
            assert value == "password-input"
            return " Password "

    assert asyncio.run(_find_label(FakePage(), FakeElement())) == "Password"


def test_action_case_without_evidence_cannot_terminal_pass() -> None:
    async def run() -> None:
        runtime = Runtime(
            {
                "task_id": "terminal-assertion-regression",
                "target_url": "http://localhost:3001/",
            }
        )
        case = RuntimeExecutableCase(
            id="TC-invalid-password",
            objective=(
                "\u8f93\u5165 admin/cangjie*2026 "
                "\u5e76\u70b9\u51fb\u7acb\u5373\u767b\u5f55"
            ),
            expected=(
                "\u4ecd\u505c\u7559\u5728\u767b\u5f55\u9875 "
                "http://localhost:3001/"
            ),
        )
        page_info = {
            "url": "http://localhost:3001/",
            "title": "Cangjie",
            "headings": [],
            "visible_texts": [],
            "error_messages": [],
            "modals": [],
        }

        assertion = await runtime._evaluate_terminal_assertion(case, page_info, [])
        assert assertion is None

    asyncio.run(run())


if __name__ == "__main__":
    test_root_url_is_not_treated_as_expected_path()
    test_action_case_requires_successful_input_and_submit_evidence()
    test_completion_action_requires_action_evidence_when_case_is_interactive()
    test_execute_single_case_returns_passed_on_allowed_completion_action()
    test_quick_fill_case_accepts_click_evidence()
    test_quick_fill_action_detection_excludes_passive_existence_case()
    test_deterministic_quick_fill_action_clicks_button_once()
    test_execution_prompt_includes_configured_accounts()
    test_configured_login_terminal_accepts_display_name_alias()
    test_configured_login_terminal_reads_interactive_entry_labels()
    test_configured_login_detection_excludes_quick_fill()
    test_configured_login_action_requires_visible_login_controls()
    test_configured_login_sequence_refills_username_and_password()
    test_invalid_login_terminal_requires_error_on_login_page()
    test_invalid_login_password_falls_back_to_task_config_demo_password()
    test_reset_browser_state_clears_rich_browser_storage()
    test_agent_write_case_requires_configured_login_even_when_negative()
    test_agent_invalid_gateway_is_not_invalid_login_submission()
    test_agent_write_data_uses_explicit_names_and_gateway()
    test_agent_create_terminal_requires_visible_created_record()
    test_agent_invalid_gateway_terminal_uses_browser_validity()
    test_agent_write_sequence_fills_name_description_gateway_and_saves()
    test_dataset_write_case_requires_configured_login_even_when_negative()
    test_dataset_write_data_uses_explicit_names_and_empty_marker()
    test_dataset_create_terminal_requires_visible_created_record()
    test_dataset_empty_name_terminal_uses_browser_validity()
    test_dataset_write_sequence_fills_name_intro_and_saves()
    test_skill_write_case_requires_configured_login_and_uses_explicit_data()
    test_skill_scaffold_terminal_requires_visible_skill_and_core_files()
    test_skill_duplicate_core_terminal_uses_dialog_evidence()
    test_skill_scaffold_sequence_creates_renames_and_reopens_editor()
    test_skill_duplicate_sequence_accepts_first_locator_property()
    test_label_lookup_uses_bounded_dom_query()
    test_action_case_without_evidence_cannot_terminal_pass()
    print("runtime terminal assertion regression checks passed")
