from core.llm_client import _coerce_to_pydantic
from core.skills.case_generator import CaseGenerationResult


def test_coerce_normalizes_case_placeholder_lists_and_numbers():
    result = _coerce_to_pydantic(
        {
            "cases": [{
                "id": "TC-CAND-002",
                "title": "normalize placeholder fields",
                "goal": "accept list and numeric placeholder output",
                "preconditions": [],
                "input_data": [
                    {
                        "name": "candidate_name",
                        "placeholder": ["Alice", "Bob", "Carol"],
                        "source": "generated",
                        "sensitivity": "public",
                    },
                    {
                        "name": "candidate_count",
                        "placeholder": 10,
                        "source": "generated",
                        "sensitivity": "public",
                    },
                ],
                "expected_result": "placeholders are plain strings",
                "priority": "medium",
                "trace_references": ["COV-002"],
                "required_roles": [],
            }],
        },
        CaseGenerationResult,
    )

    placeholders = [datum.placeholder for datum in result.cases[0].input_data]
    assert placeholders == [
        "Alice / Bob / Carol",
        "10",
    ]


def test_coerce_reuses_single_required_role_for_account_precondition():
    result = _coerce_to_pydantic(
        {
            "cases": [{
                "id": "TC-CAND-003",
                "title": "reuse declared role",
                "goal": "keep account preconditions parseable",
                "preconditions": [{
                    "type": "account_role",
                    "description": "use a department leader account",
                    "satisfiable_by_agent": True,
                    "failure_policy": "skipped",
                }],
                "input_data": [],
                "expected_result": "the case stays role-aware",
                "priority": "high",
                "trace_references": ["COV-003"],
                "required_roles": ["department_leader"],
            }],
        },
        CaseGenerationResult,
    )

    precondition = result.cases[0].preconditions[0]
    assert precondition.type == "account_role"
    assert precondition.required_role == "department_leader"
    assert result.cases[0].required_roles == ["department_leader"]


def test_coerce_downgrades_account_precondition_without_role_context():
    result = _coerce_to_pydantic(
        {
            "cases": [{
                "id": "TC-CAND-004",
                "title": "defer ambiguous role requirement",
                "goal": "avoid failing the whole batch on missing role metadata",
                "preconditions": [{
                    "type": "account_role",
                    "description": "use a privileged account",
                    "satisfiable_by_agent": True,
                    "failure_policy": "skipped",
                }],
                "input_data": [],
                "expected_result": "the case becomes review-only",
                "priority": "medium",
                "trace_references": ["COV-004"],
                "required_roles": [],
            }],
        },
        CaseGenerationResult,
    )

    precondition = result.cases[0].preconditions[0]
    assert precondition.type == "environment"
    assert precondition.required_role is None
    assert precondition.satisfiable_by_agent is False
    assert precondition.failure_policy == "human_review_required"
    assert result.cases[0].required_roles == []


def test_coerce_normalizes_dashboard_attention_label_alias():
    result = _coerce_to_pydantic(
        {
            "cases": [{
                "id": "TC-CAND-005",
                "title": "验证待关注公式",
                "goal": "验证“待关注人员数”等于“业绩不佳者”与“关注人才”之和",
                "description": "核对卡片与标签统计口径",
                "preconditions": [{
                    "type": "data",
                    "description": "图表中存在‘关注人才’标签统计",
                    "satisfiable_by_agent": True,
                    "failure_policy": "incomplete",
                }],
                "input_data": [],
                "expected_result": "“待关注人员数” = “业绩不佳者”人数 + “关注人才”人数。",
                "priority": "medium",
                "trace_references": ["COV-005"],
                "required_roles": [],
                "execution_hint": "检查‘关注人才’标签的人数",
            }],
        },
        CaseGenerationResult,
    )

    case = result.cases[0]
    assert "关注人才" not in case.goal
    assert "关注人才" not in case.expected_result
    assert "关注人才" not in case.execution_hint
    assert "关注人才" not in case.preconditions[0].description
    assert "关注" in case.expected_result


def test_coerce_normalizes_overstrict_read_only_control_expectation():
    result = _coerce_to_pydantic(
        {
            "cases": [{
                "id": "TC-CAND-006",
                "title": "验证看板只读展示",
                "goal": "验证数据看板仅展示统计数据，不可在线编辑或操作业务",
                "description": "页面为只读看板",
                "preconditions": [],
                "input_data": [],
                "expected_result": "页面不包含任何输入框、下拉框、可点击编辑按钮或操作按钮。",
                "priority": "medium",
                "trace_references": ["COV-006"],
                "required_roles": [],
                "execution_hint": "检查页面无任何输入框、下拉框或操作按钮",
            }],
        },
        CaseGenerationResult,
    )

    case = result.cases[0]
    assert "不包含任何输入框" not in case.expected_result
    assert "无任何输入框" not in case.execution_hint
    assert "业务编辑输入" in case.expected_result
    assert "筛选" in case.expected_result
    assert "视图切换" in case.execution_hint


def test_coerce_normalizes_dashboard_formula_card_aliases():
    result = _coerce_to_pydantic(
        {
            "cases": [{
                "id": "TC-CAND-007",
                "title": "验证明星人才卡片数值计算",
                "goal": "验证‘明星人才’卡片数值等于九宫格高潜+高绩效区域人数之和",
                "description": "验证“核心人才”卡片数值计算",
                "preconditions": [],
                "input_data": [],
                "expected_result": "“明星人才”卡片和“核心人才”卡片显示正确。",
                "priority": "medium",
                "trace_references": ["COV-007"],
                "required_roles": [],
            }],
        },
        CaseGenerationResult,
    )

    case = result.cases[0]
    combined = "\n".join([
        case.title,
        case.goal,
        case.description,
        case.expected_result,
    ])
    assert "明星人才卡片" not in combined
    assert "“核心人才”卡片" not in combined
    assert "明星/明星/核心人才" not in combined
    assert "明星/核心人才" in combined
