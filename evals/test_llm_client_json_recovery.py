from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.llm_client import _coerce_to_pydantic, _salvage_single_list_field_from_text
from core.skills.condition_analyzer import ConditionResult


def test_list_field_salvage_drops_provider_thinking_blocks() -> None:
    raw = """
    [
      {"type": "thinking", "thinking": "private chain", "signature": "sig"},
      {
        "id": "COND-001",
        "assertion_ref": "ASSERT-001",
        "condition_type": "functional",
        "statement": "Skill scaffold creates core files",
        "oracle_type": "ui_state",
        "oracle": "SKILL.md and index.js are visible"
      }
    ]
    """

    salvaged = _salvage_single_list_field_from_text(raw, ConditionResult)
    assert salvaged is not None
    assert len(salvaged["conditions"]) == 1

    result = _coerce_to_pydantic(salvaged, ConditionResult)
    assert result.conditions[0].id == "COND-001"
    assert result.conditions[0].oracle_type == "ui_state"


def test_nested_jsonish_decoder_filters_control_blocks_in_lists() -> None:
    result = _coerce_to_pydantic(
        {
            "conditions": [
                {"type": "thinking", "thinking": "private chain", "signature": "sig"},
                {
                    "id": "COND-002",
                    "assertion_ref": "ASSERT-002",
                    "condition_type": "validation",
                    "statement": "Duplicate SKILL.md is blocked",
                    "oracle_type": "business_rule",
                    "oracle": "No second SKILL.md is created",
                },
            ]
        },
        ConditionResult,
    )

    assert [condition.id for condition in result.conditions] == ["COND-002"]


def test_condition_result_normalizes_common_llm_enum_aliases() -> None:
    result = _coerce_to_pydantic(
        {
            "conditions": [
                {
                    "id": "COND-003",
                    "assertion_ref": "ASSERT-003",
                    "condition_type": "security",
                    "statement": "Core skill files cannot be duplicated",
                    "oracle_type": "ui",
                    "oracle": "The UI shows a duplicate-file block",
                }
            ]
        },
        ConditionResult,
    )

    assert result.conditions[0].condition_type == "risk_case"
    assert result.conditions[0].oracle_type == "ui_state"


if __name__ == "__main__":
    test_list_field_salvage_drops_provider_thinking_blocks()
    test_nested_jsonish_decoder_filters_control_blocks_in_lists()
    test_condition_result_normalizes_common_llm_enum_aliases()
    print("llm client json recovery regression checks passed")
