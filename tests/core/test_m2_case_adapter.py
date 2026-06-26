"""CandidateTestCase to RuntimeExecutableCase must be lossless."""

import pytest

from core.interfaces import CandidateTestCase, StructuredPrecondition
from core.skills.case_adapter import adapt_executable_cases, adapt_single_case


def make_case(**overrides):
    values = {
        "id": "TC-CAND-001",
        "title": "登录验证",
        "goal": "验证管理员能够登录",
        "expected_result": "进入首页",
        "execution_hint": "从登录入口开始",
        "trace_references": ["COV-001"],
        "priority": "high",
        "required_roles": ["admin"],
        "preconditions": [
            StructuredPrecondition(
                type="account_role",
                description="使用管理员账号",
                required_role="admin",
            )
        ],
    }
    values.update(overrides)
    return CandidateTestCase(**values)


def test_single_case_is_lossless():
    source = make_case()
    adapted = adapt_single_case(source)
    assert adapted.id == source.id
    assert adapted.objective == source.goal
    assert adapted.expected == source.expected_result
    assert adapted.hints == source.execution_hint
    assert adapted.preconditions == source.preconditions
    assert adapted.required_roles == source.required_roles
    assert adapted.trace_references == source.trace_references


def test_adapter_does_not_infer_natural_language_preconditions():
    with pytest.raises(Exception):
        make_case(preconditions=["管理员登录"])


def test_batch_preserves_order_and_empty_input():
    cases = [
        make_case(id="TC-1"),
        make_case(id="TC-2"),
    ]
    assert [case.id for case in adapt_executable_cases(cases)] == ["TC-1", "TC-2"]
    assert adapt_executable_cases([]) == []
