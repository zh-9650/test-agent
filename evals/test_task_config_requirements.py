from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.input_normalization import combine_text_inputs, normalize_task_config


def test_case_generation_requirements_are_normalized_as_text() -> None:
    normalized = normalize_task_config(
        {
            "case_generation_requirements": [
                "generate a UI login case",
                "generate a quick-fill field-value case",
            ]
        }
    )

    assert normalized["case_generation_requirements"] == (
        "generate a UI login case\n"
        "generate a quick-fill field-value case"
    )


def test_case_generation_requirements_are_merged_into_rules() -> None:
    merged = combine_text_inputs(
        ["stay on http://localhost:3001/"],
        "generate a UI login case",
    )

    assert "stay on http://localhost:3001/" in merged
    assert "generate a UI login case" in merged


if __name__ == "__main__":
    test_case_generation_requirements_are_normalized_as_text()
    test_case_generation_requirements_are_merged_into_rules()
    print("task config requirement regression checks passed")
