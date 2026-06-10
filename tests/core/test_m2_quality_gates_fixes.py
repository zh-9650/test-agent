"""tests/core/test_m2_quality_gates_fixes.py — M2 修复验证测试。

覆盖审查记录中的:
- S8: CandidateTestCase schema_version 字段
- W2: Quality Gates schema_version 校验
- W3: Quality Gates required_roles 校验
"""

import pytest
from core.interfaces import (
    CandidateTestCase,
    TestAssetPackage,
)
from core.skills.quality_gates import run_quality_gates


class TestCandidateTestCaseSchemaVersion:
    """S8: CandidateTestCase 必须有 schema_version 字段。"""

    def test_default_schema_version(self):
        case = CandidateTestCase(
            id="TC-CAND-001",
            title="测试",
            goal="验证",
            trace_references=["COV-001"],
        )
        assert case.schema_version == "candidate_test_case.v1"

    def test_custom_schema_version(self):
        case = CandidateTestCase(
            id="TC-CAND-002",
            title="测试",
            goal="验证",
            trace_references=["COV-001"],
            schema_version="candidate_test_case.v2",
        )
        assert case.schema_version == "candidate_test_case.v2"


class TestQualityGatesSchemaVersion:
    """W2: Quality Gates 必须检查 schema_version。"""

    def test_missing_schema_version_detected(self):
        case = CandidateTestCase(
            id="TC-CAND-001",
            title="测试",
            goal="验证",
            trace_references=["COV-001"],
            schema_version="",  # 故意清空
        )
        package = TestAssetPackage(candidate_cases=[case])
        report = run_quality_gates(package)
        codes = [f.code for f in report.findings]
        assert "missing_schema_version" in codes

    def test_valid_schema_version_passes(self):
        case = CandidateTestCase(
            id="TC-CAND-001",
            title="测试",
            goal="验证",
            trace_references=["COV-001"],
        )
        package = TestAssetPackage(candidate_cases=[case])
        report = run_quality_gates(package)
        codes = [f.code for f in report.findings]
        assert "missing_schema_version" not in codes


class TestQualityGatesRequiredRoles:
    """W3: Quality Gates 必须验证 required_roles 完整性。"""

    def test_missing_required_roles_with_role_keyword(self):
        """前置条件含角色关键词但 required_roles 为空时，应该警告。"""
        case = CandidateTestCase(
            id="TC-CAND-001",
            title="测试",
            goal="验证",
            preconditions=["需要管理员登录"],
            trace_references=["COV-001"],
            required_roles=[],  # 故意清空
        )
        package = TestAssetPackage(candidate_cases=[case])
        report = run_quality_gates(package)
        codes = [f.code for f in report.findings]
        assert "missing_required_roles" in codes
        # 警告级别，不阻断
        findings_with_code = [f for f in report.findings if f.code == "missing_required_roles"]
        assert findings_with_code[0].severity == "warning"

    def test_required_roles_filled_passes(self):
        """required_roles 已填写时不应该报警告。"""
        case = CandidateTestCase(
            id="TC-CAND-001",
            title="测试",
            goal="验证",
            preconditions=["需要管理员登录"],
            trace_references=["COV-001"],
            required_roles=["admin"],
        )
        package = TestAssetPackage(candidate_cases=[case])
        report = run_quality_gates(package)
        codes = [f.code for f in report.findings]
        assert "missing_required_roles" not in codes

    def test_no_role_keyword_no_warning(self):
        """前置条件不含角色关键词时，不应该报警告。"""
        case = CandidateTestCase(
            id="TC-CAND-001",
            title="测试",
            goal="验证",
            preconditions=["用户已在订单页面"],
            trace_references=["COV-001"],
            required_roles=[],
        )
        package = TestAssetPackage(candidate_cases=[case])
        report = run_quality_gates(package)
        codes = [f.code for f in report.findings]
        assert "missing_required_roles" not in codes

    def test_english_role_keyword(self):
        """英文角色关键词也能检测到。"""
        case = CandidateTestCase(
            id="TC-CAND-002",
            title="测试",
            goal="验证",
            preconditions=["login as admin"],
            trace_references=["COV-001"],
            required_roles=[],
        )
        package = TestAssetPackage(candidate_cases=[case])
        report = run_quality_gates(package)
        codes = [f.code for f in report.findings]
        assert "missing_required_roles" in codes