from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.interfaces import CandidateTestCase
from core.skills.auto_executability import assess_case_auto_executability


def _case(title: str, goal: str = "", expected: str = "", hint: str = "") -> CandidateTestCase:
    return CandidateTestCase(
        id="TC-auto-exec-regression",
        title=title,
        goal=goal or title,
        expected_result=expected,
        execution_hint=hint,
        trace_references=["COV-auto-exec-regression"],
    )


def test_business_console_is_not_devtools() -> None:
    case = _case(
        title="管理员登录后进入控制台",
        goal="验证管理员登录成功后进入业务控制台",
        expected="页面显示控制台导航和管理员身份",
        hint="输入管理员凭据登录，观察控制台入口。",
    )

    result = assess_case_auto_executability(case)

    assert result.auto_executable
    assert "requires_browser_devtools" not in result.reasons


def test_browser_console_is_still_blocked() -> None:
    case = _case(
        title="打开浏览器控制台查看错误",
        goal="通过浏览器控制台检查 JavaScript 错误",
        hint="打开浏览器控制台并查看 console 面板。",
    )

    result = assess_case_auto_executability(case)

    assert not result.auto_executable
    assert "requires_browser_devtools" in result.reasons


def test_direct_api_case_is_not_sent_to_ui_runtime() -> None:
    case = _case(
        title="API 有效凭据登录成功",
        goal="发送 POST /auth/login 请求并检查 HTTP 200 和 access_token",
        expected="响应状态码为 200，响应体包含 access_token",
        hint="发送POST /auth/login 请求，携带有效凭据。",
    )

    result = assess_case_auto_executability(case)

    assert not result.auto_executable
    assert "requires_http_request_tooling" in result.reasons


def test_chinese_token_api_case_is_not_sent_to_ui_runtime() -> None:
    case = _case(
        title="使用有效凭证调用登录接口应返回访问令牌",
        goal="调用登录接口并校验响应体包含访问令牌",
        expected="返回访问令牌和 Authorization 请求头可用",
        hint="发送 POST /auth/login 请求。",
    )

    result = assess_case_auto_executability(case)

    assert not result.auto_executable
    assert "requires_http_request_tooling" in result.reasons


def test_api_postcondition_case_is_not_sent_to_ui_runtime() -> None:
    case = _case(
        title="UI 创建智能体后通过 API 查询数据一致性",
        goal="通过 API 查询 /system/agent/list，验证记录存在且字段匹配",
        expected="API 返回包含测试智能体记录",
        hint="UI 保存后执行 API 后置校验。",
    )

    result = assess_case_auto_executability(case)

    assert not result.auto_executable
    assert "requires_http_request_tooling" in result.reasons


def test_ui_primary_case_with_optional_api_oracle_stays_executable() -> None:
    case = _case(
        title="合法 gatewayUrl 新增智能体",
        goal="通过 UI 新增智能体 测试智能体-TA-20260704-AUTO",
        expected=(
            "列表搜索命中测试智能体；也可通过 /system/agent/list "
            "API 后置证据证明持久化。"
        ),
        hint="登录后打开新增智能体弹窗，填写并保存。",
    )

    result = assess_case_auto_executability(case)

    assert result.auto_executable
    assert "requires_http_request_tooling" not in result.reasons


def test_dataset_ui_primary_case_with_optional_api_oracle_stays_executable() -> None:
    case = _case(
        title="通过 UI 新建知识库并列表命中",
        goal="通过 UI 新建知识库 测试知识库-TA-20260704-AUTO",
        expected=(
            "列表显示测试知识库-TA-20260704-AUTO；也可通过 "
            "GET /fastgpt/dataset/list API 后置证据证明持久化。"
        ),
        hint="登录后进入知识库管理，打开新建知识库弹窗，填写名称和描述后保存。",
    )

    result = assess_case_auto_executability(case)

    assert result.auto_executable
    assert "requires_http_request_tooling" not in result.reasons


def test_skill_ui_primary_case_with_optional_api_oracle_stays_executable() -> None:
    case = _case(
        title="通过 UI 快速初始化技能脚手架并验证核心文件",
        goal="通过 UI 技能管理快速初始化脚手架，保存为 测试技能-TA-20260704-AUTO",
        expected=(
            "技能列表显示 测试技能-TA-20260704-AUTO；也可通过 "
            "/system/skill/page 和 /system/skill/{skillId}/files API 后置证据证明持久化。"
        ),
        hint="登录后进入技能管理，点击快速初始化脚手架，在线修编元数据并保存。",
    )

    result = assess_case_auto_executability(case)

    assert result.auto_executable
    assert "requires_http_request_tooling" not in result.reasons


def test_pure_skill_api_case_is_not_sent_to_ui_runtime() -> None:
    case = _case(
        title="API 创建技能脚手架返回 skillId",
        goal="发送 POST /system/skill/scaffold 请求，校验响应体包含 skillId",
        expected="接口返回 HTTP 200 且包含 skillId",
        hint="调用技能脚手架创建 API。",
    )

    result = assess_case_auto_executability(case)

    assert not result.auto_executable
    assert "requires_http_request_tooling" in result.reasons


def test_pure_dataset_api_case_is_not_sent_to_ui_runtime() -> None:
    case = _case(
        title="API 创建知识库返回 datasetId",
        goal="发送 POST /fastgpt/dataset 请求，校验响应体包含 datasetId",
        expected="接口返回 datasetId 且 HTTP 200",
        hint="调用数据集创建 API。",
    )

    result = assess_case_auto_executability(case)

    assert not result.auto_executable
    assert "requires_http_request_tooling" in result.reasons


def test_missing_request_body_field_case_is_not_sent_to_ui_runtime() -> None:
    case = _case(
        title="覆盖缺少必要字段边界",
        goal="请求体缺少username或password字段，验证返回400且服务不崩溃",
        expected="后端返回 400 错误",
        hint="构造缺少字段的请求体。",
    )

    result = assess_case_auto_executability(case)

    assert not result.auto_executable
    assert "requires_http_request_tooling" in result.reasons


def test_invalid_clientid_case_is_not_sent_to_ui_runtime() -> None:
    case = _case(
        title="覆盖错误clientid等价类",
        goal="前端请求携带无效或伪造的clientid值，验证后端拒绝请求或返回错误",
        expected="后端拒绝请求",
        hint="构造非法 clientid 请求。",
    )

    result = assess_case_auto_executability(case)

    assert not result.auto_executable
    assert "requires_http_request_tooling" in result.reasons


def test_agentid_delete_decision_case_is_not_sent_to_ui_runtime() -> None:
    case = _case(
        title="覆盖决策表规则：仅名称包含 TA-20260704 且 agentId 为空时删除成功",
        goal="验证 agentId 为 null 的知识库删除成功",
        expected="删除成功",
        hint="准备 agentId 为空的知识库数据后执行删除。",
    )

    result = assess_case_auto_executability(case)

    assert not result.auto_executable
    assert "requires_external_data_setup" in result.reasons


if __name__ == "__main__":
    test_business_console_is_not_devtools()
    test_browser_console_is_still_blocked()
    test_direct_api_case_is_not_sent_to_ui_runtime()
    test_chinese_token_api_case_is_not_sent_to_ui_runtime()
    test_api_postcondition_case_is_not_sent_to_ui_runtime()
    test_ui_primary_case_with_optional_api_oracle_stays_executable()
    test_dataset_ui_primary_case_with_optional_api_oracle_stays_executable()
    test_skill_ui_primary_case_with_optional_api_oracle_stays_executable()
    test_pure_skill_api_case_is_not_sent_to_ui_runtime()
    test_pure_dataset_api_case_is_not_sent_to_ui_runtime()
    test_missing_request_body_field_case_is_not_sent_to_ui_runtime()
    test_invalid_clientid_case_is_not_sent_to_ui_runtime()
    test_agentid_delete_decision_case_is_not_sent_to_ui_runtime()
    print("auto_executability regression checks passed")
