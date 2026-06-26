from core.interfaces import CandidateTestCase, StructuredPrecondition
from core.skills.auto_executability import assess_case_auto_executability


def _case(**updates) -> CandidateTestCase:
    values = {
        "id": "TC-001",
        "title": "case",
        "goal": "验证页面",
        "trace_references": ["COV-001"],
    }
    values.update(updates)
    return CandidateTestCase(**values)


def test_assessment_flags_unsupported_browser_capabilities():
    case = _case(
        goal="打开开发者工具并查看网络面板请求",
        expected_result="通过右键菜单查看页面源代码，确认只有 GET 请求",
    )

    assessment = assess_case_auto_executability(case)

    assert assessment.auto_executable is False
    assert set(assessment.reasons) == {
        "requires_browser_devtools",
        "requires_source_view",
        "requires_network_panel_inspection",
        "requires_unsupported_pointer_gesture",
    }


def test_assessment_flags_non_agent_precondition():
    case = _case(
        preconditions=[
            StructuredPrecondition(
                type="business_state",
                description="需要外部系统先生成一笔审批中的订单",
                satisfiable_by_agent=False,
                failure_policy="human_review_required",
            )
        ]
    )

    assessment = assess_case_auto_executability(case)

    assert assessment.auto_executable is False
    assert assessment.reasons == ("contains_non_agent_precondition",)


def test_assessment_flags_visual_db_and_data_setup_cases():
    assessment = assess_case_auto_executability(
        _case(
            title="验证卡片布局与样式",
            goal="验证顶部指标卡片区的整体布局、位置及样式是否符合设计稿",
            execution_hint="导航后截图对比，再使用数据库工具执行汇总查询；必要时修改源数据观察近实时刷新",
            required_roles=["数据编辑者"],
        )
    )

    assert assessment.auto_executable is False
    assert set(assessment.reasons) == {
        "requires_visual_review",
        "requires_database_access",
        "requires_external_data_setup",
    }


def test_assessment_flags_cross_module_comparison():
    assessment = assess_case_auto_executability(
        _case(
            goal="分别打开看板页面和 09绩效综合报告，对比两者结果",
        )
    )

    assert assessment.auto_executable is False
    assert assessment.reasons == ("requires_cross_module_comparison",)


def test_assessment_flags_http_request_tooling_and_reference_audit():
    assessment = assess_case_auto_executability(
        _case(
            title="看板 API 修改请求拒绝验证",
            goal="验证向 API接口 发送 POST/PUT/DELETE 修改类HTTP请求时系统拒绝请求",
            expected_result="对比预置数据与返回结果，确保全公司所有项目完全匹配且无遗漏",
            execution_hint="使用 Postman 或 curl 获取基准数据后逐一核对",
        )
    )

    assert assessment.auto_executable is False
    assert set(assessment.reasons) == {
        "requires_http_request_tooling",
        "requires_reference_dataset_audit",
    }


def test_assessment_flags_console_api_write_request_case():
    assessment = assess_case_auto_executability(
        _case(
            title="验证控制台写请求被拒绝",
            goal="验证通过浏览器控制台发起POST/PUT等可能用于修改看板数据的API调用",
            expected_result="返回403/404/405等非200状态码",
            execution_hint="在浏览器控制台执行JavaScript代码发起POST请求",
        )
    )

    assert assessment.auto_executable is False
    assert set(assessment.reasons) == {
        "requires_browser_devtools",
        "requires_http_request_tooling",
    }


def test_assessment_flags_illegal_api_call_integrity_case():
    assessment = assess_case_auto_executability(
        _case(
            title="非法API调用后数据完整性",
            goal="验证非法API调用执行后，页面UI展示的数据未发生任何变化",
            expected_result="后端正确拒绝未授权写操作API，页面展示数据保持不变",
        )
    )

    assert assessment.auto_executable is False
    assert assessment.reasons == ("requires_http_request_tooling",)


def test_assessment_flags_grid_region_formula_reference_mapping():
    assessment = assess_case_auto_executability(
        _case(
            title="验证明星人才卡片数值计算",
            goal="验证‘明星人才’卡片数值等于九宫格高潜+高绩效区域人数之和",
            expected_result="卡片显示值与九宫格区域人数之和一致",
        )
    )

    assert assessment.auto_executable is False
    assert assessment.reasons == ("requires_reference_dataset_audit",)


def test_assessment_flags_department_plan_scope_reference_mapping():
    assessment = assess_case_auto_executability(
        _case(
            title="验证部门领导下拉列表展示已参与的盘点计划",
            goal="验证部门领导打开全部盘点计划下拉列表时，仅展示本部门或其下属员工曾参与过的盘点计划项目",
        )
    )

    assert assessment.auto_executable is False
    assert assessment.reasons == ("requires_reference_dataset_audit",)


def test_assessment_flags_progress_formula_source_counts():
    assessment = assess_case_auto_executability(
        _case(
            title="验证盘点项目进展列表中进度百分比的正常计算",
            goal="验证部门领导视角下盘点项目进展列表的进度百分比按公式（完成件数/总任务数×100%）正确计算，如12/20=60%",
        )
    )

    assert assessment.auto_executable is False
    assert assessment.reasons == ("requires_reference_dataset_audit",)


def test_assessment_flags_progress_bar_formula_without_source_counts():
    assessment = assess_case_auto_executability(
        _case(
            title="部门领导看板进度条计算公式验证",
            goal="验证部门领导查看看板时进度条百分比计算公式正确",
        )
    )

    assert assessment.auto_executable is False
    assert assessment.reasons == ("requires_reference_dataset_audit",)


def test_assessment_flags_progress_bar_boundary_state_setup():
    assessment = assess_case_auto_executability(
        _case(
            title="部门进度条100%边界值验证",
            goal="验证部门领导查看看板时，本部门所有员工均已完成盘点时进度条显示100%",
        )
    )

    assert assessment.auto_executable is False
    assert assessment.reasons == ("requires_external_data_setup",)


def test_assessment_flags_progress_data_source_isolation_audit():
    assessment = assess_case_auto_executability(
        _case(
            title="部门领导视角-进度条数据源隔离性验证",
            goal="通过对比部门数据集与全局数据集，验证部门领导进度条数值的计算数据源隔离性，确保未使用错误的全局数据",
        )
    )

    assert assessment.auto_executable is False
    assert assessment.reasons == ("requires_reference_dataset_audit",)


def test_assessment_flags_underlying_inventory_data_consistency():
    assessment = assess_case_auto_executability(
        _case(
            title="人才标签分布区域正确展示九大标准标签",
            goal="验证人才标签分布区域严格按照九大标准人才标签分别展示对应人数，标签名称匹配且人数与底层盘点数据一致",
        )
    )

    assert assessment.auto_executable is False
    assert assessment.reasons == ("requires_reference_dataset_audit",)


def test_assessment_flags_unfinished_progress_boundary_state_setup():
    assessment = assess_case_auto_executability(
        _case(
            title="部门领导视角进度百分比下限边界值(0%)验证",
            goal="验证当部门员工未完成任何盘点任务时，部门领导视角的进度百分比显示为0%下限边界值",
        )
    )

    assert assessment.auto_executable is False
    assert assessment.reasons == ("requires_external_data_setup",)


def test_assessment_flags_specific_data_state_setup():
    assessment = assess_case_auto_executability(
        _case(
            title="验证无参与计划时下拉列表为空状态",
            goal="验证当部门及其下属从未参与任何盘点计划时，下拉列表为空或展示暂无数据提示，不出现其他部门的计划",
        )
    )

    assert assessment.auto_executable is False
    assert set(assessment.reasons) == {
        "requires_external_data_setup",
        "requires_reference_dataset_audit",
    }


def test_assessment_flags_zero_dashboard_data_state_setup():
    assessment = assess_case_auto_executability(
        _case(
            title="系统零数据状态下看板页面稳定性验证",
            goal="验证系统无任何盘点项目或人员数据时，指标卡片区域不报错、不崩溃，各卡片显示0或相应的空状态提示，页面正常渲染",
        )
    )

    assert assessment.auto_executable is False
    assert set(assessment.reasons) == {
        "requires_external_data_setup",
        "requires_visual_review",
    }


def test_assessment_flags_selected_project_scope_reference_mapping():
    assessment = assess_case_auto_executability(
        _case(
            title="切换盘点项目后数据联动刷新验证",
            goal="验证用户切换盘点项目后，指标卡片、流程完成率、九宫格、标签分布、部门结构五个组件联动刷新，数据仅展示所选项目范围",
        )
    )

    assert assessment.auto_executable is False
    assert assessment.reasons == ("requires_reference_dataset_audit",)


def test_assessment_flags_grid_chart_rendering_visual_review():
    assessment = assess_case_auto_executability(
        _case(
            title="人才标签分布与九宫格图表渲染验证",
            goal="验证人才标签分布区域基于九大标准人才标签展示各标签人数统计，且九宫格分布图正确渲染为九宫格形式并标注各格子内人数",
        )
    )

    assert assessment.auto_executable is False
    assert "requires_visual_review" in assessment.reasons


def test_assessment_allows_normal_case():
    assessment = assess_case_auto_executability(
        _case(
            goal="点击提交按钮并保存表单",
            expected_result="页面显示保存成功提示",
            execution_hint="优先使用页面上的按钮文本定位",
        )
    )

    assert assessment.auto_executable is True
    assert assessment.reasons == ()
