from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.interfaces import CoverageItem
from core.skills.case_generator import fallback_cases


def test_fallback_cases_preserve_trace_and_negative_branch() -> None:
    coverage = CoverageItem(
        id="COV-wrong-password",
        condition_id="COND-wrong-password",
        technique_id="TECH-wrong-password",
        coverage_dimension="negative",
        goal="使用 admin/cangjie*2026 提交登录时显示密码错误并停留在登录页",
        risk_level="medium",
        branch_type="negative",
    )

    cases = fallback_cases([coverage])

    assert len(cases) == 1
    assert cases[0].trace_references == ["COV-wrong-password"]
    assert cases[0].branch_type == "negative"
    assert "密码错误" in cases[0].expected_result


if __name__ == "__main__":
    test_fallback_cases_preserve_trace_and_negative_branch()
    print("case generator fallback regression checks passed")
