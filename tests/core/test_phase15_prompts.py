"""tests/core/test_phase15_prompts.py — Phase 1.5 Skill Prompt Regression Test.

Loads L1 fixtures and runs the 3 Phase 1.5 skills (risk_analyzer, scenario_extractor,
session_summary). Asserts:
  1. JSON schema validity (Pydantic models parse without error)
  2. Inter-skill contract invariants
  3. Adversarial inputs do not crash

Usage:
    # Mocked test (no LLM cost): pytest tests/core/test_phase15_prompts.py -v
    # Live test (real LLM, costs tokens):
        L1_LIVE=1 python -m pytest tests/core/test_phase15_prompts.py -v -s
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


FIXTURES_DIR = Path(__file__).resolve().parents[2] / "data" / "fixtures"


# ---------- Fixtures ----------

@pytest.fixture(params=["prd_aitalk", "prd_purchase", "prd_minimal", "prd_adversarial"])
def fixture_name(request) -> str:
    return request.param


@pytest.fixture
def fixture_inputs(fixture_name) -> dict[str, str]:
    prd_path = FIXTURES_DIR / f"{fixture_name}.md"
    inputs: dict[str, str] = {"prd": prd_path.read_text(encoding="utf-8") if prd_path.exists() else ""}
    if fixture_name == "prd_aitalk":
        inputs["api_doc"] = (FIXTURES_DIR / "swagger_aitalk.yaml").read_text(encoding="utf-8")
        inputs["changelog"] = (FIXTURES_DIR / "changelog_aitalk.md").read_text(encoding="utf-8")
    else:
        inputs["api_doc"] = ""
        inputs["changelog"] = ""
    return inputs


# ---------- Helpers ----------

def _is_scenario_id(s: str) -> bool:
    """Per scenario_extractor.py: id format S-NNN, 3 digits."""
    return bool(re.match(r"^S-\d{3}$", s))


# ---------- Mocked runner ----------

async def _run_phase15_mocked(fixture_inputs: dict[str, str]) -> dict[str, Any]:
    """Run all 3 Phase 1.5 skills with mocked LLM. Verifies prompt → schema
    → inter-skill contract pipeline without burning tokens.
    """
    from core.skills import risk_analyzer, scenario_extractor, session_summary

    with patch.object(risk_analyzer, "safe_structured_invoke", new=AsyncMock()) as ra_mock, \
         patch.object(scenario_extractor, "safe_structured_invoke", new=AsyncMock()) as se_mock, \
         patch.object(session_summary, "safe_structured_invoke", new=AsyncMock()) as ss_mock:

        # --- Mock return values for each skill ---

        # risk_analyzer: 1 high + 1 medium risk point
        ra_mock.return_value = risk_analyzer.RiskAnalysisOutput(
            risk_points=[
                risk_analyzer.RiskPoint(
                    element="e_42: 采购金额 (input)",
                    risk_type="涉及金额计算",
                    severity="high",
                    suggestions=["输入负数", "输入 0", "输入超长数字"],
                ),
                risk_analyzer.RiskPoint(
                    element="e_43: 提交订单 (button)",
                    risk_type="不可逆操作",
                    severity="medium",
                    suggestions=["连续点击 3 次", "未填必填项时点击"],
                ),
            ]
        )

        # scenario_extractor: 3 scenarios with valid id format
        se_mock.return_value = scenario_extractor.ScenarioList(
            scenarios=[
                scenario_extractor.Scenario(
                    id="S-001", name="采购员提交采购申请",
                    entry_hint="寻找'新建采购申请'按钮",
                    priority="high",
                ),
                scenario_extractor.Scenario(
                    id="S-002", name="经理审批",
                    entry_hint="进入审批中心",
                    priority="high",
                ),
                scenario_extractor.Scenario(
                    id="S-003", name="查看历史记录",
                    entry_hint="进入采购列表",
                    priority="medium",
                ),
            ]
        )

        # session_summary: typical pass case
        ss_mock.return_value = session_summary.CaseSummary(
            case_id="TC-001", status="pass",
            summary="用 test_c 登录后跳转到首页,验证无验证码。",
            key_findings=["已登录状态已建立", "无验证码校验"],
        )

        # --- Run pipeline ---

        sample_elements = [
            {"id": "e_42", "type": "input", "label": "采购金额"},
            {"id": "e_43", "type": "button", "label": "提交订单"},
            {"id": "e_44", "type": "select", "label": "收货地址"},
        ]
        risk_points = await risk_analyzer.analyze_risks(
            page_elements=sample_elements,
            swagger=fixture_inputs.get("api_doc", ""),
            prd=fixture_inputs.get("prd", ""),
        )

        scenarios = await scenario_extractor.extract_scenarios(
            prd=fixture_inputs.get("prd", ""),
            changelog=fixture_inputs.get("changelog", ""),
            focus_areas="",
            system_model=None,
        )

        # Build a minimal fake step
        class FakeAssertion:
            status = "pass"

        class FakeStep:
            action_type = "navigate"
            action_target = "/login"
            result = "导航成功"
            assertion = FakeAssertion()

        summary = await session_summary.generate_case_summary(
            test_case_id="TC-001",
            test_case_title="登录成功",
            status="pass",
            steps=[FakeStep()],
            page_urls=["/login", "/"],
        )

        return {
            "risk_points": risk_points,
            "scenarios": scenarios,
            "summary": summary,
        }


# ---------- Tests ----------

@pytest.mark.asyncio
async def test_phase15_schema_validity(fixture_inputs):
    """All 3 Phase 1.5 skills produce schema-valid outputs across all 4 fixtures."""
    out = await _run_phase15_mocked(fixture_inputs)
    assert out["risk_points"] is not None
    assert out["scenarios"] is not None
    assert out["summary"] is not None
    assert "summary" in out["summary"]


@pytest.mark.asyncio
async def test_risk_analyzer_invariants(fixture_inputs):
    """Per risk_analyzer.py:
    - severity ∈ {high, medium, low}
    - risk_points length 0-8
    - suggestions length 2-5 (when present)
    - element non-empty
    """
    out = await _run_phase15_mocked(fixture_inputs)
    risk_points = out["risk_points"]
    assert 0 <= len(risk_points) <= 8, f"risk_points length {len(risk_points)} out of 0-8 range"
    for rp in risk_points:
        assert rp["severity"] in {"high", "medium", "low"}, f"invalid severity: {rp['severity']}"
        assert rp["element"], "element is empty"
        # suggestions can be empty only when no risk_points at all
        if risk_points:
            assert 2 <= len(rp["suggestions"]) <= 5, \
                f"suggestions length {len(rp['suggestions'])} out of 2-5 range"
            for s in rp["suggestions"]:
                assert s, "suggestion is empty string"


@pytest.mark.asyncio
async def test_scenario_extractor_invariants(fixture_inputs):
    """Per scenario_extractor.py:
    - id format S-NNN
    - priority ∈ {high, medium, low}
    - scenarios length 0-12
    - name ≤ 30 字, entry_hint ≤ 60 字
    """
    out = await _run_phase15_mocked(fixture_inputs)
    scenarios = out["scenarios"]
    assert 0 <= len(scenarios) <= 12, f"scenarios length {len(scenarios)} out of 0-12 range"
    seen_ids = set()
    for sc in scenarios:
        assert _is_scenario_id(sc["id"]), f"invalid scenario id format: {sc['id']}"
        assert sc["id"] not in seen_ids, f"duplicate scenario id: {sc['id']}"
        seen_ids.add(sc["id"])
        assert sc["priority"] in {"high", "medium", "low"}, f"invalid priority: {sc['priority']}"
        assert len(sc["name"]) <= 30, f"name too long ({len(sc['name'])} chars): {sc['name']}"
        assert len(sc["entry_hint"]) <= 60, f"entry_hint too long ({len(sc['entry_hint'])} chars)"


@pytest.mark.asyncio
async def test_session_summary_invariants(fixture_inputs):
    """Per session_summary.py:
    - case_id 透传
    - status 透传
    - summary ≤ 100 字
    - key_findings length 0-3
    """
    out = await _run_phase15_mocked(fixture_inputs)
    summary = out["summary"]
    assert summary["case_id"] == "TC-001", "case_id not transmitted"
    assert summary["status"] == "pass", "status not transmitted"
    assert len(summary["summary"]) <= 100, f"summary too long ({len(summary['summary'])} chars)"
    assert 0 <= len(summary["key_findings"]) <= 3, \
        f"key_findings length {len(summary['key_findings'])} out of 0-3 range"


@pytest.mark.asyncio
async def test_session_summary_status_透传(fixture_inputs):
    """Status field must equal input status exactly (no LLM rewrites)."""
    from core.skills import session_summary

    with patch.object(session_summary, "safe_structured_invoke", new=AsyncMock()) as ss_mock:
        for status in ["pass", "fail", "skipped", "incomplete"]:
            ss_mock.return_value = session_summary.CaseSummary(
                case_id="TC-X", status=status,
                summary=f"测试 {status}", key_findings=[],
            )
            class FakeStep:
                action_type = "navigate"
                action_target = "/"
                result = "ok"
                assertion = None
            result = await session_summary.generate_case_summary(
                test_case_id="TC-X", test_case_title="t", status=status,
                steps=[FakeStep()], page_urls=[],
            )
            assert result["status"] == status, \
                f"status changed: input={status} output={result['status']}"


# ---------- Optional: live test (costs tokens) ----------

@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("L1_LIVE"), reason="set L1_LIVE=1 to run with real LLM")
async def test_phase15_live_all_fixtures(fixture_inputs):
    """End-to-end live test for Phase 1.5 skills. Skipped by default."""
    from core.skills import risk_analyzer, scenario_extractor

    sample_elements = [
        {"id": "e_42", "type": "input", "label": "采购金额"},
        {"id": "e_43", "type": "button", "label": "提交订单"},
        {"id": "e_44", "type": "select", "label": "收货地址"},
        {"id": "e_99", "type": "link", "label": "关于我们"},
    ]
    rp = await risk_analyzer.analyze_risks(
        page_elements=sample_elements,
        swagger=fixture_inputs.get("api_doc", ""),
        prd=fixture_inputs.get("prd", ""),
    )
    sc = await scenario_extractor.extract_scenarios(
        prd=fixture_inputs.get("prd", ""),
        changelog=fixture_inputs.get("changelog", ""),
    )
    print(f"\n[live] risks={len(rp)} scenarios={len(sc)}")

    # Invariants
    for r in rp:
        assert r["severity"] in {"high", "medium", "low"}
        if rp:
            assert 2 <= len(r["suggestions"]) <= 5
    for s in sc:
        assert _is_scenario_id(s["id"])
        assert s["priority"] in {"high", "medium", "low"}
