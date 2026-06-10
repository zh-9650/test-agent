"""tests/core/test_m2_models.py — M2 数据模型和适配函数测试。"""

import pytest
from core.interfaces import (
    GoalResult,
    StructuredPrecondition,
    RuntimeExecutableCase,
    TerminalAssertion,
    ExecutionRun,
    CaseResult,
    ExplorationResult,
    CandidateTestCase,
    ExplorationGoal,
)


class TestGoalResult:
    """GoalResult 模型测试。"""

    def test_goal_result_found(self):
        gr = GoalResult(
            goal_id="GOAL-test123",
            status="found",
            evidence_refs=["http://example.com"],
            stop_reason="找到证据",
            observed_at="2026-06-10T00:00:00Z",
        )
        assert gr.goal_id == "GOAL-test123"
        assert gr.status == "found"
        assert len(gr.evidence_refs) == 1

    def test_goal_result_not_found(self):
        gr = GoalResult(
            goal_id="GOAL-test456",
            status="not_found",
            stop_reason="未找到证据",
        )
        assert gr.status == "not_found"
        assert gr.evidence_refs == []

    def test_goal_result_blocked(self):
        gr = GoalResult(
            goal_id="GOAL-test789",
            status="blocked",
            stop_reason="页面无法访问",
        )
        assert gr.status == "blocked"

    def test_goal_result_insufficient(self):
        gr = GoalResult(
            goal_id="GOAL-test000",
            status="insufficient",
            stop_reason="证据不足",
        )
        assert gr.status == "insufficient"

    def test_goal_result_schema_version(self):
        gr = GoalResult(goal_id="GOAL-x", status="found")
        assert gr.schema_version == "goal_result.v1"


class TestStructuredPrecondition:
    """StructuredPrecondition 模型测试。"""

    def test_account_role_precondition(self):
        sp = StructuredPrecondition(
            type="account_role",
            description="需要管理员账号",
            required_role="admin",
        )
        assert sp.type == "account_role"
        assert sp.required_role == "admin"
        assert sp.satisfiable_by_agent is True

    def test_data_precondition(self):
        sp = StructuredPrecondition(
            type="data",
            description="需要预置测试数据",
            satisfiable_by_agent=False,
            failure_policy="skipped",
        )
        assert sp.type == "data"
        assert sp.satisfiable_by_agent is False
        assert sp.failure_policy == "skipped"

    def test_environment_precondition(self):
        sp = StructuredPrecondition(
            type="environment",
            description="需要网络连接",
            satisfiable_by_agent=False,
        )
        assert sp.type == "environment"

    def test_business_state_precondition(self):
        sp = StructuredPrecondition(
            type="business_state",
            description="用户已登录",
        )
        assert sp.type == "business_state"
        assert sp.satisfiable_by_agent is True

    def test_default_failure_policy(self):
        sp = StructuredPrecondition(
            type="business_state",
            description="测试",
        )
        assert sp.failure_policy == "incomplete"


class TestRuntimeExecutableCase:
    """RuntimeExecutableCase 模型测试。"""

    def test_basic_creation(self):
        rec = RuntimeExecutableCase(
            id="TC-CAND-001",
            objective="验证登录功能",
            expected="登录成功后跳转到首页",
        )
        assert rec.id == "TC-CAND-001"
        assert rec.objective == "验证登录功能"
        assert rec.expected == "登录成功后跳转到首页"
        assert rec.priority == "medium"
        assert rec.preconditions == []
        assert rec.required_roles == []

    def test_with_preconditions(self):
        rec = RuntimeExecutableCase(
            id="TC-CAND-002",
            objective="验证数据导出",
            expected="导出 CSV 文件",
            preconditions=[
                StructuredPrecondition(
                    type="account_role",
                    description="管理员账号",
                    required_role="admin",
                ),
            ],
            required_roles=["admin"],
        )
        assert len(rec.preconditions) == 1
        assert rec.preconditions[0].required_role == "admin"
        assert rec.required_roles == ["admin"]

    def test_id_matches_candidate_case(self):
        """验证 RuntimeExecutableCase.id 等于 CandidateTestCase.id。"""
        case = CandidateTestCase(
            id="TC-CAND-003",
            title="测试",
            goal="验证功能",
            trace_references=["COV-001"],
        )
        rec = RuntimeExecutableCase(
            id=case.id,
            objective=case.goal,
            expected=case.expected_result,
        )
        assert rec.id == case.id


class TestTerminalAssertion:
    """TerminalAssertion 模型测试。"""

    def test_all_satisfied(self):
        ta = TerminalAssertion(
            objective_satisfied=True,
            expected_result_supported=True,
            terminal_evidence_sufficient=True,
            reasoning="全部满足",
        )
        assert ta.objective_satisfied is True
        assert ta.expected_result_supported is True
        assert ta.terminal_evidence_sufficient is True

    def test_partial_satisfaction(self):
        ta = TerminalAssertion(
            objective_satisfied=True,
            expected_result_supported=False,
            terminal_evidence_sufficient=False,
        )
        assert ta.objective_satisfied is True
        assert ta.expected_result_supported is False

    def test_none_satisfied(self):
        ta = TerminalAssertion(
            objective_satisfied=False,
            expected_result_supported=False,
            terminal_evidence_sufficient=False,
        )
        assert not (ta.objective_satisfied and ta.expected_result_supported and ta.terminal_evidence_sufficient)


class TestCaseResult:
    """CaseResult 模型测试。"""

    def test_passed_case(self):
        cr = CaseResult(
            run_id="RUN-001",
            candidate_case_id="TC-CAND-001",
            terminal_status="passed",
            attempt_count=1,
            started_at="2026-06-10T00:00:00Z",
            completed_at="2026-06-10T00:01:00Z",
            summary="通过",
        )
        assert cr.terminal_status == "passed"
        assert cr.attempt_count == 1
        assert cr.failure_reason is None

    def test_failed_case(self):
        cr = CaseResult(
            run_id="RUN-001",
            candidate_case_id="TC-CAND-002",
            terminal_status="failed",
            attempt_count=2,
            started_at="2026-06-10T00:00:00Z",
            completed_at="2026-06-10T00:02:00Z",
            summary="失败",
            failure_reason="objective=False, expected=False, evidence=False",
        )
        assert cr.terminal_status == "failed"
        assert cr.attempt_count == 2
        assert cr.failure_reason is not None

    def test_skipped_case(self):
        cr = CaseResult(
            run_id="RUN-001",
            candidate_case_id="TC-CAND-003",
            terminal_status="skipped",
            attempt_count=0,
            started_at="2026-06-10T00:00:00Z",
            completed_at="2026-06-10T00:00:00Z",
            summary="前置条件不满足",
            failure_reason="precondition_skipped",
        )
        assert cr.terminal_status == "skipped"
        assert cr.attempt_count == 0

    def test_incomplete_case(self):
        cr = CaseResult(
            run_id="RUN-001",
            candidate_case_id="TC-CAND-004",
            terminal_status="incomplete",
            attempt_count=1,
            started_at="2026-06-10T00:00:00Z",
            completed_at="2026-06-10T00:00:15Z",
            summary="未完成",
            failure_reason="达到最大步数",
        )
        assert cr.terminal_status == "incomplete"

    def test_human_review_required(self):
        cr = CaseResult(
            run_id="RUN-001",
            candidate_case_id="TC-CAND-005",
            terminal_status="human_review_required",
            attempt_count=3,
            started_at="2026-06-10T00:00:00Z",
            completed_at="2026-06-10T00:03:00Z",
            summary="需人工审查",
        )
        assert cr.terminal_status == "human_review_required"


class TestExecutionRun:
    """ExecutionRun 模型测试。"""

    def test_basic_creation(self):
        er = ExecutionRun(
            run_id="RUN-001",
            task_id="task-123",
            candidate_case_ids=["TC-CAND-001", "TC-CAND-002"],
        )
        assert er.run_id == "RUN-001"
        assert er.status == "running"
        assert len(er.candidate_case_ids) == 2

    def test_completed_run(self):
        er = ExecutionRun(
            run_id="RUN-002",
            task_id="task-456",
            status="completed",
            started_at="2026-06-10T00:00:00Z",
            completed_at="2026-06-10T00:05:00Z",
            candidate_case_ids=["TC-CAND-001"],
            summary={"passed": 1, "failed": 0},
        )
        assert er.status == "completed"
        assert er.completed_at is not None

    def test_schema_version(self):
        er = ExecutionRun(run_id="RUN-003", task_id="task-789")
        assert er.schema_version == "execution_run.v1"


class TestExplorationResult:
    """ExplorationResult 模型测试。"""

    def test_empty_result(self):
        er = ExplorationResult()
        assert er.system_map is not None
        assert er.goal_results == []

    def test_with_goal_results(self):
        er = ExplorationResult(
            goal_results=[
                GoalResult(goal_id="GOAL-1", status="found"),
                GoalResult(goal_id="GOAL-2", status="not_found"),
            ],
        )
        assert len(er.goal_results) == 2
        assert er.goal_results[0].status == "found"
        assert er.goal_results[1].status == "not_found"

    def test_all_goals_found(self):
        results = [
            GoalResult(goal_id="GOAL-1", status="found"),
            GoalResult(goal_id="GOAL-2", status="found"),
        ]
        er = ExplorationResult(goal_results=results)
        assert all(r.status == "found" for r in er.goal_results)

    def test_all_goals_not_found(self):
        results = [
            GoalResult(goal_id="GOAL-1", status="not_found"),
            GoalResult(goal_id="GOAL-2", status="blocked"),
        ]
        er = ExplorationResult(goal_results=results)
        assert not any(r.status == "found" for r in er.goal_results)
