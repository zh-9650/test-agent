from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.interfaces import CandidateTestCase, TestAssetPackage, TestInputDatum
from core.skills.execution_selector import select_execution_cases


def _case(
    case_id: str,
    title: str,
    *,
    goal: str | None = None,
    expected: str = "页面呈现与覆盖目标一致的可观察结果。",
    hint: str = "打开目标页面，按覆盖目标完成对应 UI 操作并观察结果。",
    branch_type: str = "negative",
    input_data: list[TestInputDatum] | None = None,
) -> CandidateTestCase:
    return CandidateTestCase(
        id=case_id,
        title=title,
        goal=goal or title,
        expected_result=expected,
        execution_hint=hint,
        priority="high",
        estimated_cost="low",
        branch_type=branch_type,  # type: ignore[arg-type]
        trace_references=[f"COV-{case_id}"],
        input_data=input_data or [],
    )


def test_smoke_selection_keeps_specific_agent_invalid_gateway_representative() -> None:
    package = TestAssetPackage(
        candidate_cases=[
            _case(
                "TC-generic-invalid-1",
                "覆盖UI表单gatewayUrl输入非法值的无效等价类及边界",
            ),
            _case(
                "TC-generic-invalid-2",
                "覆盖业务规则对无效gatewayUrl拒绝创建的高风险场景",
            ),
            _case(
                "TC-specific-invalid",
                "非法 gatewayUrl 新增智能体被阻断",
                goal=(
                    "通过 UI 尝试新增智能体 测试智能体-TA-20260704-INVALID，"
                    "gatewayUrl 填 not-url，验证不会创建记录。"
                ),
                expected=(
                    "提交后显示 URL 格式错误；搜索 TA-20260704-INVALID "
                    "证明未创建记录。"
                ),
                hint=(
                    "登录后进入智能体广场，打开新增智能体弹窗，"
                    "填写负向测试名称和 not-url。"
                ),
                input_data=[
                    TestInputDatum(
                        name="agent_name",
                        placeholder="测试智能体-TA-20260704-INVALID",
                        source="generated",
                        generation_strategy="explicit agent invalid-url requirement",
                        boundary_category="negative",
                    ),
                    TestInputDatum(
                        name="gateway_url",
                        placeholder="not-url",
                        source="generated",
                        generation_strategy="explicit agent invalid-url requirement",
                        boundary_category="negative",
                    ),
                ],
            ),
            _case(
                "TC-agent-create",
                "覆盖通过UI新增外部智能体接入配置的完整正向流程",
                goal=(
                    "通过 UI 新增智能体 测试智能体-TA-20260704-AUTO，"
                    "保存后搜索 TA-20260704-AUTO。"
                ),
                branch_type="e2e",
                input_data=[
                    TestInputDatum(
                        name="agent_name",
                        placeholder="测试智能体-TA-20260704-AUTO",
                        source="generated",
                    )
                ],
            ),
            _case(
                "TC-generic-login",
                "验证通过 UI 成功登录并展示主界面",
                branch_type="e2e",
            ),
            _case(
                "TC-specific-login",
                "真实管理员凭据登录成功进入控制台",
                goal="输入 admin/admin123 并点击立即登录后验证进入控制台",
                expected="进入控制台，并显示 zhanghong 或智能体广场。",
                hint="回到登录页，输入 admin/admin123，点击立即登录。",
                branch_type="positive",
            ),
        ]
    )

    selection = select_execution_cases(package, profile="smoke", target=3)

    assert "TC-specific-invalid" in selection.selected_case_ids
    assert "TC-generic-invalid-1" not in selection.selected_case_ids
    assert "TC-generic-invalid-2" not in selection.selected_case_ids
    assert "TC-agent-create" in selection.selected_case_ids
    assert "TC-specific-login" in selection.selected_case_ids
    assert "TC-generic-login" not in selection.selected_case_ids
    assert selection.selected_count == 3


def test_smoke_selection_keeps_dataset_write_representatives_and_defers_api_cases() -> None:
    package = TestAssetPackage(
        candidate_cases=[
            _case(
                "TC-dataset-create-generated",
                "覆盖知识库新增正向流程",
                goal="通过 UI 新建知识库 测试知识库-TA-20260704-AUTO",
                expected="列表显示测试知识库-TA-20260704-AUTO。",
                hint="登录后进入知识库管理，填写名称和描述并保存。",
                branch_type="e2e",
            ),
            _case(
                "TC-dataset-empty-generated",
                "覆盖空名称边界值",
                goal="通过 UI 提交空名称创建知识库，触发 required 校验阻断且不创建记录",
                expected="不能创建 TA-20260704-EMPTY 记录。",
            ),
            _case(
                "TC-dataset-empty-explicit",
                "空名称新建知识库被阻断",
                goal="通过 UI 新建知识库时名称留空，描述填写 测试空名称-TA-20260704-EMPTY，验证必填校验阻断。",
                expected="名称为空时保存被 required 阻断，弹窗保持打开。",
                hint="登录后进入知识库管理，打开新建知识库弹窗，名称留空，填写描述后提交。",
            ),
            _case(
                "TC-login",
                "真实管理员凭据登录成功进入控制台",
                goal="输入 admin/admin123 并点击立即登录后验证进入控制台",
                expected="进入控制台，并显示 zhanghong 或知识库管理。",
                hint="回到登录页，输入 admin/admin123，点击立即登录。",
                branch_type="positive",
            ),
            _case(
                "TC-missing-fields-api",
                "覆盖缺少必要字段边界",
                goal="请求体缺少username或password字段，验证返回400且服务不崩溃",
                expected="后端返回 400 错误",
                hint="构造缺少字段的请求体。",
            ),
            _case(
                "TC-invalid-clientid-api",
                "覆盖错误clientid等价类",
                goal="前端请求携带无效或伪造的clientid值，验证后端拒绝请求或返回错误",
                expected="后端拒绝请求",
                hint="构造非法 clientid 请求。",
            ),
            _case(
                "TC-delete-cleanup-rule",
                "覆盖决策表规则：仅名称包含 TA-20260704 且 agentId 为空时删除成功",
                goal="验证 agentId 为 null 的知识库删除成功",
                expected="删除成功",
                hint="准备 agentId 为空的知识库数据后执行删除。",
            ),
            _case(
                "TC-generic-high-risk",
                "覆盖页面中高风险提示展示",
                goal="打开目标页面并观察高风险提示展示",
                expected="页面呈现与覆盖目标一致的可观察结果。",
                hint="打开目标页面观察结果。",
            ),
        ]
    )

    selection = select_execution_cases(package, profile="smoke", target=3)

    assert "TC-dataset-create-generated" in selection.selected_case_ids
    assert "TC-dataset-empty-explicit" in selection.selected_case_ids
    assert "TC-login" in selection.selected_case_ids
    assert "TC-dataset-empty-generated" not in selection.selected_case_ids
    assert "TC-missing-fields-api" not in selection.selected_case_ids
    assert "TC-invalid-clientid-api" not in selection.selected_case_ids
    assert "TC-delete-cleanup-rule" not in selection.selected_case_ids
    assert "TC-generic-high-risk" not in selection.selected_case_ids
    assert selection.selected_count == 3


def test_smoke_selection_keeps_skill_scaffold_and_duplicate_core_file() -> None:
    package = TestAssetPackage(
        candidate_cases=[
            _case(
                "TC-skill-scaffold",
                "通过 UI 快速初始化技能脚手架",
                goal="通过 UI 技能管理快速初始化脚手架，保存为 测试技能-TA-20260704-AUTO 后验证 SKILL.md 和 index.js。",
                expected="技能列表显示 测试技能-TA-20260704-AUTO，文件树包含 SKILL.md 与 index.js。",
                hint="进入技能管理，点击快速初始化脚手架，在线修编元数据并保存。",
                branch_type="e2e",
            ),
            _case(
                "TC-skill-duplicate",
                "重复创建 SKILL.md 核心文件被阻断",
                goal="通过 UI 在线修编尝试新建重复核心文件 SKILL.md，验证被阻断。",
                expected="页面出现 SKILL.md 核心文件不可重复创建或禁止创建提示。",
                hint="打开测试技能在线修编，在创建新文件输入 SKILL.md 并回车。",
            ),
            _case(
                "TC-skill-generic",
                "验证技能管理页面加载",
                goal="打开技能管理页面并观察列表加载。",
                expected="页面显示技能管理相关内容。",
                hint="点击技能管理。",
                branch_type="positive",
            ),
            _case(
                "TC-login",
                "真实管理员凭据登录成功进入控制台",
                goal="输入 admin/admin123 并点击立即登录后验证进入控制台",
                expected="进入控制台，并显示 zhanghong 或技能管理。",
                hint="回到登录页，输入 admin/admin123，点击立即登录。",
                branch_type="positive",
            ),
        ]
    )

    selection = select_execution_cases(package, profile="smoke", target=3)

    assert "TC-skill-scaffold" in selection.selected_case_ids
    assert "TC-skill-duplicate" in selection.selected_case_ids
    assert "TC-login" in selection.selected_case_ids
    assert "TC-skill-generic" not in selection.selected_case_ids
    assert selection.selected_count == 3


def test_smoke_selection_recognizes_skill_scaffold_by_stable_file_markers() -> None:
    package = TestAssetPackage(
        candidate_cases=[
            _case(
                "TC-stable-skill-scaffold",
                "技能写路径候选",
                goal="UI saves 测试技能-TA-20260704-AUTO and verifies SKILL.md plus index.js",
                expected="TA-20260704-AUTO is listed; SKILL.md and index.js exist.",
                hint="Use the real browser UI.",
                branch_type="e2e",
            ),
            _case(
                "TC-skill-duplicate",
                "重复创建 SKILL.md 核心文件被阻断",
                goal="通过 UI 在线修编尝试新建重复核心文件 SKILL.md，验证被阻断。",
                expected="页面出现 SKILL.md duplicate core file blocked 提示。",
            ),
            _case(
                "TC-skill-element-low",
                "验证技能管理页面元素存在",
                goal="观察 #tab-skills-mgmt 和 #skills-list-container。",
                expected="页面元素存在。",
                branch_type="positive",
            ),
            _case(
                "TC-login",
                "真实管理员凭据登录成功进入控制台",
                goal="输入 admin/admin123 并点击立即登录后验证进入控制台",
                expected="进入控制台，并显示 zhanghong 或技能管理。",
                hint="回到登录页，输入 admin/admin123，点击立即登录。",
                branch_type="positive",
            ),
        ]
    )

    selection = select_execution_cases(package, profile="smoke", target=3)

    assert "TC-stable-skill-scaffold" in selection.selected_case_ids
    assert "TC-skill-duplicate" in selection.selected_case_ids
    assert "TC-login" in selection.selected_case_ids
    assert "TC-skill-element-low" not in selection.selected_case_ids


def test_smoke_selection_dedupes_quick_fill_representatives() -> None:
    package = TestAssetPackage(
        candidate_cases=[
            _case(
                "TC-quick-fill-ambiguous",
                "一键填值成功登录",
                goal="验证一键填值体验按钮填充有效凭据后，登录流程成功完成。",
                expected="跳转控制台并显示昵称。",
                hint="点击一键填值体验按钮并观察输入框值。",
                branch_type="positive",
            ),
            _case(
                "TC-quick-fill-specific",
                "一键填值体验填充演示凭据",
                goal="点击一键填值体验后验证 username=admin 且 password=cangjie*2026",
                expected="username=admin，password=cangjie*2026",
                hint="回到登录页，点击一键填值体验按钮并观察输入框值。",
                branch_type="positive",
            ),
            _case(
                "TC-invalid-password",
                "错误密码登录失败",
                goal="使用 admin/cangjie*2026 提交登录时停留在登录页并显示密码错误",
                expected="登录失败。",
                branch_type="negative",
            ),
            _case(
                "TC-login",
                "真实管理员凭据登录成功进入控制台",
                goal="输入 admin/admin123 并点击立即登录后验证进入控制台",
                expected="进入控制台，并显示 zhanghong。",
                hint="回到登录页，输入 admin/admin123，点击立即登录。",
                branch_type="positive",
            ),
        ]
    )

    selection = select_execution_cases(package, profile="smoke", target=3)

    assert "TC-quick-fill-specific" in selection.selected_case_ids
    assert "TC-quick-fill-ambiguous" not in selection.selected_case_ids
    assert "TC-invalid-password" in selection.selected_case_ids
    assert "TC-login" in selection.selected_case_ids
    assert selection.selected_count == 3


if __name__ == "__main__":
    test_smoke_selection_keeps_specific_agent_invalid_gateway_representative()
    test_smoke_selection_keeps_dataset_write_representatives_and_defers_api_cases()
    test_smoke_selection_keeps_skill_scaffold_and_duplicate_core_file()
    test_smoke_selection_recognizes_skill_scaffold_by_stable_file_markers()
    test_smoke_selection_dedupes_quick_fill_representatives()
    print("execution selector regression checks passed")
