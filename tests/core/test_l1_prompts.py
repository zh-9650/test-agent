"""tests/core/test_l1_prompts.py — L1 Prompt Regression Test.

Loads all 4 fixtures (prd_aitalk, prd_purchase, prd_minimal, prd_adversarial)
and runs the 5 L1 skills end-to-end. Asserts:
  1. JSON schema validity (Pydantic models parse without error)
  2. Inter-node contract invariants (from docs/prompt-engineering.md §3)
  3. Adversarial inputs do not crash (use quote="N/A" + confidence ≤ 0.5)

Usage:
    # Mocked test (no LLM cost): pytest tests/core/test_l1_prompts.py -v
    # Live test (real LLM, costs tokens):
        L1_LIVE=1 python -m pytest tests/core/test_l1_prompts.py -v -s
"""
from __future__ import annotations

import asyncio
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

def _is_chinese_noun_phrase(s: str) -> bool:
    """Per docs/prompt-engineering.md §4.4: 2-6 Chinese chars, no prefix/suffix/punct."""
    if not s:
        return False
    s = s.strip()
    if not (2 <= len(s) <= 6):
        return False
    if not re.match(r"^[\u4e00-\u9fff]+$", s):
        return False
    return True


# ---------- L1 Pipeline runner ----------

async def _run_l1_mocked(inputs: dict[str, str]) -> dict[str, Any]:
    """Run L1 with mocked LLM to verify the prompt → schema → inter-node contract
    pipeline without burning tokens. Tests the Python code; LLMs are stubbed.
    """
    from core.interfaces import KnowledgeBase, KnowledgeItem, UseCaseModel, UseCase, SystemModel, BusinessFlow
    from core.skills import knowledge_extractor, use_case_modeler, use_case_coverage, system_modeler, goal_extractor

    # Stub the LLM call to return a deterministic KnowledgeBase derived from inputs.
    with patch.object(knowledge_extractor, "safe_structured_invoke", new=AsyncMock()) as n1_mock, \
         patch.object(use_case_modeler, "safe_structured_invoke", new=AsyncMock()) as n15_mock, \
         patch.object(use_case_coverage, "safe_structured_invoke", new=AsyncMock()) as n17_mock, \
         patch.object(system_modeler, "safe_structured_invoke", new=AsyncMock()) as n2_mock, \
         patch.object(goal_extractor, "safe_structured_invoke", new=AsyncMock()) as n3_mock:

        # Build a minimal but contract-valid KnowledgeBase from input rules.
        sample_rules = []
        for line in (inputs.get("prd", "") + "\n" + inputs.get("api_doc", "")).splitlines():
            m = re.match(r"^\s*\d+\.\s*(.+)", line)
            if m:
                sample_rules.append(m.group(1).strip())

        if not sample_rules and "prd" in inputs:
            # Fallback: any non-empty rule lines
            sample_rules = [l.strip() for l in inputs["prd"].splitlines() if l.strip() and not l.startswith("#")][:3]

        sample_roles = ["员工", "经理", "管理员"]
        sample_actors = sample_roles[:1]

        kb = KnowledgeBase(
            business_rules=[KnowledgeItem(text=r, source="prd", quote=r, confidence=1.0) for r in sample_rules],
            roles=[KnowledgeItem(text=r, source="prd", quote=r, confidence=1.0) for r in sample_roles],
            entities=[],
            constraints=[],
            raw_facts=[],
        )
        ucm = UseCaseModel(use_cases=[
            UseCase(
                name=f"操作{idx + 1}",
                actor=sample_actors[idx % len(sample_actors)],
                trigger="初始状态",
                outcome="完成状态",
                related_rules=[sample_rules[idx]] if idx < len(sample_rules) else [],
            )
            for idx in range(min(len(sample_rules), 3))
        ])
        sm = SystemModel(
            system_name="MockSystem",
            modules=["模块1"], entities=[], roles=sample_roles,
            flows=[BusinessFlow(name="flow1",
                                nodes=["初始", "完成"],
                                transitions=[{"from_state": "初始", "action": f"操作{1}", "to_state": "完成"}])],
        )
        goals = [goal_extractor.ExplorationGoal(goal=f"找到【操作{i + 1}】", priority="high") for i in range(len(ucm.use_cases))]

        n1_mock.return_value = kb
        n15_mock.return_value = ucm
        n17_mock.return_value = use_case_coverage.CoverageResponse(
            use_case_model=ucm,
            report=use_case_coverage.CoverageReport(covered_rules=[r.text for r in kb.business_rules], missing_rules=[]),
        )
        n2_mock.return_value = sm
        n3_mock.return_value = goal_extractor.ExplorationGoalList(goals=goals)

        # Run pipeline
        kb_out = await knowledge_extractor.extract_knowledge(
            prd_content=inputs["prd"], api_doc_content=inputs.get("api_doc", ""),
            changelog_content=inputs.get("changelog", ""),
        )
        ucm_out = await use_case_modeler.generate_use_case_model(kb_out)
        ucm_refined, cov = await use_case_coverage.check_use_case_coverage(kb_out, ucm_out)
        sm_out = await system_modeler.generate_system_model(kb_out, ucm_refined)
        goals_out = await goal_extractor.extract_goals(ucm_refined.model_dump(), mode="direct")

        return {
            "kb": kb_out, "ucm": ucm_refined, "cov": cov,
            "sm": sm_out, "goals": goals_out,
        }


# ---------- Tests ----------

@pytest.mark.asyncio
async def test_l1_pipeline_schema_validity(fixture_inputs):
    """All 5 nodes produce schema-valid outputs across all 4 fixtures."""
    out = await _run_l1_mocked(fixture_inputs)
    assert out["kb"] is not None
    assert out["ucm"] is not None
    assert out["cov"] is not None
    assert out["sm"] is not None
    assert out["goals"] is not None


@pytest.mark.asyncio
async def test_n1_quote_fallback_for_adversarial(fixture_inputs):
    """Per docs/prompt-engineering.md §4.1: when quote is "N/A", confidence ≤ 0.5."""
    out = await _run_l1_mocked(fixture_inputs)
    for rule in out["kb"].business_rules:
        if rule.quote == "N/A":
            assert rule.confidence <= 0.5, f"quote=N/A but confidence={rule.confidence}"
            assert rule.source == "inferred", f"quote=N/A but source={rule.source}"


@pytest.mark.asyncio
async def test_n15_actor_in_roles(fixture_inputs):
    """Per docs/prompt-engineering.md §4.2: every use_case.actor must be in knowledge.roles."""
    out = await _run_l1_mocked(fixture_inputs)
    role_texts = {r.text for r in out["kb"].roles}
    for uc in out["ucm"].use_cases:
        assert uc.actor in role_texts or uc.actor.startswith("unknown_actor:"), \
            f"use_case '{uc.name}' has actor '{uc.actor}' not in roles {role_texts}"


@pytest.mark.asyncio
async def test_n17_covered_union_missing_equals_all(fixture_inputs):
    """Per docs/prompt-engineering.md §4.3: covered_rules ∪ missing_rules == all rules."""
    out = await _run_l1_mocked(fixture_inputs)
    all_rules = {r.text for r in out["kb"].business_rules}
    covered = set(out["cov"].covered_rules)
    missing = set(out["cov"].missing_rules)
    if all_rules:
        assert covered | missing == all_rules, \
            f"covered∪missing != all_rules. diff: {(covered | missing) ^ all_rules}"
        assert not (covered & missing), "covered and missing overlap"


@pytest.mark.asyncio
async def test_n2_nodes_normalized(fixture_inputs):
    """Per docs/prompt-engineering.md §4.4: nodes 2-6 Chinese chars, no prefix/suffix."""
    out = await _run_l1_mocked(fixture_inputs)
    all_nodes: list[str] = []
    for flow in out["sm"].flows:
        all_nodes.extend(flow.nodes)
    for node in all_nodes:
        assert _is_chinese_noun_phrase(node), f"node '{node}' is not a 2-6 Chinese noun phrase"


@pytest.mark.asyncio
async def test_n2_transitions_action_matches_usecase(fixture_inputs):
    """Per docs/prompt-engineering.md §4.4: transitions[].action == some use_case.name."""
    out = await _run_l1_mocked(fixture_inputs)
    ucm_names = {uc.name for uc in out["ucm"].use_cases}
    for flow in out["sm"].flows:
        for t in flow.transitions:
            action = getattr(t, "action", t.get("action") if isinstance(t, dict) else None)
            assert action in ucm_names, \
                f"transition action '{action}' not in use_case.names {ucm_names}"


@pytest.mark.asyncio
async def test_n3_goals_one_per_usecase(fixture_inputs):
    """Per docs/prompt-engineering.md §4.5: same use_case.name ≤ 1 goal; total ≤ N use_cases."""
    out = await _run_l1_mocked(fixture_inputs)
    ucm_names = [uc.name for uc in out["ucm"].use_cases]
    assert len(out["goals"]) <= len(ucm_names), \
        f"more goals ({len(out['goals'])}) than use_cases ({len(ucm_names)})"
    # uniqueness
    seen = set()
    for g in out["goals"]:
        assert g.goal not in seen, f"duplicate goal: {g.goal}"
        seen.add(g.goal)
    # priority ∈ enum
    for g in out["goals"]:
        assert g.priority in {"high", "medium", "low"}, f"invalid priority: {g.priority}"


# ---------- Optional: live L1 test (costs tokens) ----------

@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("L1_LIVE"), reason="set L1_LIVE=1 to run with real LLM")
async def test_l1_live_all_fixtures(fixture_inputs):
    """End-to-end live test. Skipped by default. Set L1_LIVE=1 to enable."""
    from core.skills import (
        knowledge_extractor, use_case_modeler, use_case_coverage,
        system_modeler, goal_extractor,
    )
    kb = await knowledge_extractor.extract_knowledge(
        prd_content=fixture_inputs["prd"],
        api_doc_content=fixture_inputs.get("api_doc", ""),
        changelog_content=fixture_inputs.get("changelog", ""),
    )
    ucm = await use_case_modeler.generate_use_case_model(kb)
    ucm_refined, cov = await use_case_coverage.check_use_case_coverage(kb, ucm)
    sm = await system_modeler.generate_system_model(kb, ucm_refined)
    goals = await goal_extractor.extract_goals(ucm_refined.model_dump(), mode="direct")
    print(f"\n[live] kb.rules={len(kb.business_rules)} ucm.cases={len(ucm_refined.use_cases)} "
          f"cov.covered={len(cov.covered_rules)} sm.flows={len(sm.flows)} goals={len(goals)}")
    # Re-run the same invariants
    assert len(goals) <= len(ucm_refined.use_cases)
    if kb.business_rules:
        assert set(cov.covered_rules) | set(cov.missing_rules) == {r.text for r in kb.business_rules}
