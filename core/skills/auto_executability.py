from __future__ import annotations

"""Deterministic screening for candidate-case automatic executability."""

from dataclasses import dataclass

from core.interfaces import CandidateTestCase


@dataclass(frozen=True)
class AutoExecutabilityAssessment:
    auto_executable: bool
    reasons: tuple[str, ...] = ()


_UNSUPPORTED_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "requires_browser_devtools",
        (
            "开发者工具",
            "浏览器控制台",
            "控制台",
            "执行javascript",
            "执行 javascript",
            "javascript代码",
            "javascript 代码",
            "developer tools",
            "dev tools",
            "elements 面板",
            "elements panel",
            "console 面板",
            "console panel",
        ),
    ),
    (
        "requires_source_view",
        (
            "查看页面源代码",
            "页面源代码",
            "源码",
            "view-source",
        ),
    ),
    (
        "requires_network_panel_inspection",
        (
            "网络面板",
            "network panel",
            "xhr/fetch",
            "xhr",
            "fetch 请求",
            "http方法",
            "http method",
        ),
    ),
    (
        "requires_unsupported_pointer_gesture",
        (
            "右键",
            "右键菜单",
            "context menu",
            "双击",
            "double click",
            "拖拽",
            "drag",
        ),
    ),
    (
        "requires_visual_review",
        (
            "样式",
            "布局",
            "对齐",
            "视觉",
            "设计稿",
            "截图对比",
            "位置及样式",
            "整体布局",
            "图表渲染",
            "正确渲染",
            "正常渲染",
            "九宫格形式",
        ),
    ),
    (
        "requires_database_access",
        (
            "数据库",
            "sql",
            "汇总查询",
            "数据库工具",
            "db query",
            "database",
        ),
    ),
    (
        "requires_external_data_setup",
        (
            "修改源数据",
            "源数据更新",
            "测试数据集",
            "空数据状态",
            "零数据状态",
            "无任何盘点项目",
            "无任何盘点项目或人员数据",
            "无参与计划",
            "从未参与",
            "唯一计划",
            "仅参与过1个",
            "仅参与过 1 个",
            "总任务数为0",
            "总任务数为 0",
            "完成件数为0",
            "完成件数为 0",
            "完成件数等于总任务数",
            "未完成任何盘点任务",
            "所有员工均已完成盘点",
            "无任何员工完成盘点",
            "本部门所有员工",
            "本部门无任何员工",
            "无关联",
            "禁用或断开",
            "不同规模",
            "数据量级",
            "近实时",
            "立即开始计时",
            "数据编辑者",
        ),
    ),
    (
        "requires_cross_module_comparison",
        (
            "分别打开",
            "另一模块",
            "09绩效综合报告",
            "上游模块",
            "数据源一致",
            "对比两者结果",
            "逐一对比",
        ),
    ),
    (
        "requires_http_request_tooling",
        (
            "postman",
            "curl",
            "fetch(",
            "发起http",
            "发起 http",
            "post/put",
            "post/put/delete",
            "post、put",
            "post、put、delete",
            "post请求",
            "put请求",
            "post 请求",
            "put 请求",
            "修改类http请求",
            "修改类请求",
            "http request",
            "http请求",
            "api接口",
            "api调用",
            "api 调用",
            "非法api调用",
            "非法 api 调用",
            "写操作api",
            "写操作 api",
            "method not allowed",
            "forbidden",
        ),
    ),
    (
        "requires_reference_dataset_audit",
        (
            "预置数据",
            "预配置",
            "基准数据",
            "完全匹配",
            "无遗漏",
            "逐一核对",
            "全部部门",
            "全部项目",
            "全公司所有",
            "数据范围覆盖全公司",
            "本部门及下属部门",
            "部门及其下属",
            "不包含其他部门",
            "其他部门的计划",
            "仅展示本部门相关信息",
            "本部门或其下属",
            "所选项目范围",
            "参与过的盘点计划",
            "下属员工曾参与",
            "部门下属员工参与",
            "其他部门参与",
            "本部门未参与",
            "部门维度",
            "独立计算",
            "跨部门汇总",
            "全局跨部门",
            "对比部门数据集",
            "部门数据集",
            "全局数据集",
            "数据源隔离",
            "计算数据源",
            "错误的全局数据",
            "底层盘点数据",
            "与底层",
            "完成件数",
            "总任务数",
            "进度条百分比",
            "进度条计算公式",
            "部分完成",
            "全部完成",
            "零完成",
            "12/20",
            "九宫格区域",
            "区域人数之和",
            "高潜+高绩效",
            "中潜+高绩效",
            "中潜+低绩效",
            "低潜+低绩效",
            "校准后分数",
        ),
    ),
)


def assess_case_auto_executability(
    case: CandidateTestCase,
) -> AutoExecutabilityAssessment:
    reasons: list[str] = []

    if any(not item.satisfiable_by_agent for item in case.preconditions):
        reasons.append("contains_non_agent_precondition")

    haystack = "\n".join(
        filter(
            None,
            [
                case.title,
                case.goal,
                case.description,
                case.expected_result,
                case.execution_hint,
                *case.required_roles,
                *(item.description for item in case.preconditions),
            ],
        )
    ).lower()

    for reason, keywords in _UNSUPPORTED_RULES:
        if any(keyword.lower() in haystack for keyword in keywords):
            reasons.append(reason)

    deduped = tuple(dict.fromkeys(reasons))
    return AutoExecutabilityAssessment(
        auto_executable=not deduped,
        reasons=deduped,
    )
