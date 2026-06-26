from core.llm_client import _coerce_to_pydantic
from core.skills.coverage_analyzer import CoverageResult


def test_coerce_normalizes_e2e_coverage_dimension_alias():
    result = _coerce_to_pydantic(
        {
            "items": [{
                "id": "COV-001",
                "condition_id": "COND-001",
                "technique_id": "TECH-COND-001",
                "coverage_dimension": "e2e",
                "goal": "validate the main dashboard flow",
                "risk_level": "high",
                "branch_type": "positive",
            }],
        },
        CoverageResult,
    )

    item = result.items[0]
    assert item.coverage_dimension == "normal"
    assert item.branch_type == "positive"
