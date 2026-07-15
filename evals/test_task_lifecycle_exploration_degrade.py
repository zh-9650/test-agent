from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.interfaces import (
    ExplorationGoal,
    RequirementAssertion,
    RequirementFact,
    TestAssetPackage,
)
from core.task_lifecycle import TaskLifecycleService


def _package_with_static_assets() -> TestAssetPackage:
    fact = RequirementFact(
        id="FACT-001",
        source_type="prd",
        source_reference="prd",
        quote="登录页必须支持管理员登录。",
        subject="登录页",
        action="支持",
        object="管理员登录",
        confidence=0.9,
    )
    assertion = RequirementAssertion(
        id="ASSERT-001",
        fact_ids=["FACT-001"],
        assertion_text="管理员使用有效凭据后必须进入控制台。",
        assertion_type="functional",
        risk_level="high",
    )
    goal = ExplorationGoal(
        id="GOAL-001",
        assertion_refs=["ASSERT-001"],
        goal="验证管理员登录入口",
        expected_evidence=["登录表单", "控制台导航"],
        stop_condition="观察到登录表单或控制台导航",
        priority="high",
        source_refs=["FACT-001"],
    )
    return TestAssetPackage(
        facts=[fact],
        assertions=[assertion],
        exploration_goals=[goal],
    )


def test_degraded_exploration_can_continue_with_static_assets() -> None:
    package = _package_with_static_assets()
    summary = {
        "total": 1,
        "found": 0,
        "pages": 0,
        "actions": 0,
        "forms": 0,
        "navigations": 0,
    }

    assert TaskLifecycleService._can_continue_after_degraded_exploration(
        package,
        summary,
    )


def test_degraded_exploration_still_blocks_empty_analysis() -> None:
    package = TestAssetPackage()
    summary = {
        "total": 0,
        "found": 0,
        "pages": 0,
        "actions": 0,
        "forms": 0,
        "navigations": 0,
    }

    assert not TaskLifecycleService._can_continue_after_degraded_exploration(
        package,
        summary,
    )


def test_memory_context_disabled_accepts_boolean_and_string_flags() -> None:
    assert TaskLifecycleService._memory_context_disabled(
        {"disable_memory_context": True}
    )
    assert TaskLifecycleService._memory_context_disabled(
        {"disable_memory_context": "true"}
    )
    assert not TaskLifecycleService._memory_context_disabled(
        {"disable_memory_context": False}
    )
    assert not TaskLifecycleService._memory_context_disabled({})
