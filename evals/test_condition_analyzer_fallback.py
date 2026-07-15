from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.interfaces import RequirementAssertion
from core.skills import condition_analyzer


def test_analyze_conditions_uses_local_fallback_when_llm_batch_is_empty() -> None:
    async def run() -> None:
        original = condition_analyzer._analyze_condition_batch

        async def empty_batch(*args: object, **kwargs: object) -> list[object]:
            return []

        condition_analyzer._analyze_condition_batch = empty_batch  # type: ignore[assignment]
        try:
            conditions = await condition_analyzer.analyze_conditions(
                [
                    RequirementAssertion(
                        id="ASSERT-001",
                        fact_ids=["FACT-001"],
                        assertion_text="Skill scaffold must create SKILL.md and index.js",
                        assertion_type="functional",
                        risk_level="medium",
                        review_status="human_confirmed",
                        source_references=["PRD"],
                    )
                ]
            )
        finally:
            condition_analyzer._analyze_condition_batch = original  # type: ignore[assignment]

        assert len(conditions) == 1
        assert conditions[0].assertion_ref == "ASSERT-001"
        assert conditions[0].branch_type == "positive"

    asyncio.run(run())


if __name__ == "__main__":
    test_analyze_conditions_uses_local_fallback_when_llm_batch_is_empty()
    print("condition analyzer fallback regression checks passed")
