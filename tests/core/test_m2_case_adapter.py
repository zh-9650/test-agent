"""tests/core/test_m2_case_adapter.py — CandidateTestCase → RuntimeExecutableCase 适配测试。"""

import pytest
from core.interfaces import CandidateTestCase, RuntimeExecutableCase
from core.skills.case_adapter import (
    adapt_single_case,
    adapt_executable_cases,
    _adapt_preconditions,
    _extract_role,
)


class TestAdaptSingleCase:
    """adapt_single_case 函数测试。"""

    def test_basic_adaptation(self):
        case = CandidateTestCase(
            id="TC-CAND-001",
            title="测试登录",
            goal="验证登录功能",
            expected_result="登录成功",
            execution_hint="输入用户名密码",
            trace_references=["COV-001"],
            priority="high",
        )
        rec = adapt_single_case(case)
        assert rec.id == "TC-CAND-001"
        assert rec.objective == "验证登录功能"
        assert rec.expected == "登录成功"
        assert rec.hints == "输入用户名密码"
        assert rec.priority == "high"
        assert rec.trace_references == ["COV-001"]

    def test_preserves_id(self):
        """ID 必须保持不变。"""
        case = CandidateTestCase(
            id="TC-CAND-999",
            title="测试",
            goal="验证",
            trace_references=["COV-001"],
        )
        rec = adapt_single_case(case)
        assert rec.id == "TC-CAND-999"

    def test_preserves_goal(self):
        """goal 必须保持不变。"""
        case = CandidateTestCase(
            id="TC-001",
            title="测试",
            goal="这是一个非常具体的测试目标",
            trace_references=["COV-001"],
        )
        rec = adapt_single_case(case)
        assert rec.objective == "这是一个非常具体的测试目标"

    def test_preserves_expected_result(self):
        """expected_result 必须保持不变。"""
        case = CandidateTestCase(
            id="TC-001",
            title="测试",
            goal="验证",
            expected_result="页面显示成功提示",
            trace_references=["COV-001"],
        )
        rec = adapt_single_case(case)
        assert rec.expected == "页面显示成功提示"

    def test_with_structured_preconditions(self):
        """带前置条件的适配。"""
        case = CandidateTestCase(
            id="TC-001",
            title="测试",
            goal="验证",
            preconditions=["需要管理员账号登录"],
            trace_references=["COV-001"],
        )
        rec = adapt_single_case(case)
        assert len(rec.preconditions) == 1
        assert rec.preconditions[0].type == "account_role"
        assert rec.preconditions[0].required_role == "admin"

    def test_no_steps_generated(self):
        """RuntimeExecutableCase 不应生成固定步骤。"""
        case = CandidateTestCase(
            id="TC-001",
            title="测试",
            goal="验证",
            trace_references=["COV-001"],
        )
        rec = adapt_single_case(case)
        # RuntimeExecutableCase 没有 steps 字段
        assert not hasattr(rec, "steps")


class TestAdaptExecutableCases:
    """adapt_executable_cases 函数测试。"""

    def test_batch_adaptation(self):
        cases = [
            CandidateTestCase(id=f"TC-{i}", title=f"测试{i}", goal=f"验证{i}", trace_references=["COV-001"])
            for i in range(3)
        ]
        recs = adapt_executable_cases(cases)
        assert len(recs) == 3
        for i, rec in enumerate(recs):
            assert rec.id == f"TC-{i}"
            assert rec.objective == f"验证{i}"

    def test_preserves_order(self):
        cases = [
            CandidateTestCase(id="TC-first", title="第一个", goal="验证A", trace_references=["COV-001"]),
            CandidateTestCase(id="TC-second", title="第二个", goal="验证B", trace_references=["COV-002"]),
        ]
        recs = adapt_executable_cases(cases)
        assert recs[0].id == "TC-first"
        assert recs[1].id == "TC-second"

    def test_empty_list(self):
        recs = adapt_executable_cases([])
        assert recs == []


class TestAdaptPreconditions:
    """_adapt_preconditions 函数测试。"""

    def test_login_precondition(self):
        result = _adapt_preconditions(["需要管理员账号登录"])
        assert len(result) == 1
        assert result[0].type == "account_role"
        assert result[0].required_role == "admin"

    def test_data_precondition(self):
        result = _adapt_preconditions(["需要预置测试数据"])
        assert len(result) == 1
        assert result[0].type == "data"
        assert result[0].satisfiable_by_agent is False

    def test_environment_precondition(self):
        result = _adapt_preconditions(["需要网络连接"])
        assert len(result) == 1
        assert result[0].type == "environment"

    def test_business_state_precondition(self):
        result = _adapt_preconditions(["用户已在订单页面"])
        assert len(result) == 1
        assert result[0].type == "business_state"

    def test_empty_input(self):
        result = _adapt_preconditions([])
        assert result == []

    def test_blank_strings(self):
        result = _adapt_preconditions(["", "  ", "有效条件"])
        assert len(result) == 1
        assert result[0].description == "有效条件"

    def test_multiple_preconditions(self):
        result = _adapt_preconditions([
            "需要管理员账号",
            "需要预置数据",
            "用户已在首页",
        ])
        assert len(result) == 3
        assert result[0].type == "account_role"
        assert result[1].type == "data"
        assert result[2].type == "business_state"


class TestExtractRole:
    """_extract_role 函数测试。"""

    def test_admin_role(self):
        assert _extract_role("需要管理员账号") == "admin"

    def test_user_role(self):
        assert _extract_role("普通用户登录") == "user"

    def test_guest_role(self):
        assert _extract_role("访客权限") == "guest"

    def test_reviewer_role(self):
        assert _extract_role("审核员账号") == "reviewer"

    def test_super_admin_role(self):
        assert _extract_role("超级管理员") == "super_admin"

    def test_no_role_found(self):
        assert _extract_role("需要登录") is None

    def test_english_role(self):
        assert _extract_role("login as admin") == "admin"
