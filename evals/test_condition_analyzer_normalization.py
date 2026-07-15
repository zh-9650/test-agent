from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.interfaces import RequirementAssertion, TestCondition
from core.skills.condition_analyzer import _normalize_conditions


def test_condition_multi_assertion_ref_is_repaired_to_existing_assertion() -> None:
    assertions = [
        RequirementAssertion(
            id="ASSERT-001",
            fact_ids=["FACT-001"],
            assertion_text="登录成功后显示控制台",
            assertion_type="functional",
            risk_level="medium",
        ),
        RequirementAssertion(
            id="ASSERT-002",
            fact_ids=["FACT-002"],
            assertion_text="错误密码登录失败",
            assertion_type="validation",
            risk_level="medium",
        ),
    ]
    condition = TestCondition(
        id="COND-001",
        assertion_ref="ASSERT-001,ASSERT-002",
        condition_type="functional",
        statement="覆盖登录主路径",
        oracle_type="ui_state",
    )

    normalized = _normalize_conditions(assertions, [condition])

    assert len(normalized) == 1
    assert normalized[0].assertion_ref == "ASSERT-001"


def test_condition_with_unknown_assertion_ref_is_dropped() -> None:
    assertion = RequirementAssertion(
        id="ASSERT-001",
        fact_ids=["FACT-001"],
        assertion_text="登录成功后显示控制台",
        assertion_type="functional",
        risk_level="medium",
    )
    condition = TestCondition(
        id="COND-unknown",
        assertion_ref="ASSERT-missing",
        condition_type="functional",
        statement="无效引用条件",
        oracle_type="ui_state",
    )

    assert _normalize_conditions([assertion], [condition]) == []


if __name__ == "__main__":
    test_condition_multi_assertion_ref_is_repaired_to_existing_assertion()
    test_condition_with_unknown_assertion_ref_is_dropped()
    print("condition analyzer normalization regression checks passed")
