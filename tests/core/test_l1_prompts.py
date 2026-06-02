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

# V1.6.1: 节点校验逻辑统一在 core.skills.system_modeler 里, 测试直接 import, 防止漂移
from core.skills.system_modeler import (  # noqa: E402
    _is_chinese_noun_phrase,
    _strip_node_suffix,
    _align_action,
    _normalize_system_model,
    _derive_minimal_system_model,
)


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


@pytest.mark.asyncio
async def test_n17_unknown_actor_accounting(fixture_inputs):
    """Per V1.6 hardening: CoverageReport.unknown_actor_count tracks LLM-invented roles.

    Mocked pipeline uses roles=['员工', '经理', '管理员'] and actors=['员工'] only,
    so the count should be 0. A separate test with invented actor would surface > 0.
    """
    out = await _run_l1_mocked(fixture_inputs)
    assert out["cov"].unknown_actor_count == 0, \
        f"unexpected unknown_actor_count: {out['cov'].unknown_actor_count} {out['cov'].unknown_actor_names}"
    assert out["cov"].unknown_actor_names == []


@pytest.mark.asyncio
async def test_n17_unknown_actor_detects_hallucination():
    """If UCM contains an actor NOT in roles, unknown_actor_count must be > 0.

    This is the V1.6 hardening (2026-06-01) — silent LLM inventions used to be
    swallowed. Now they surface to the HTML report.
    """
    from core.interfaces import KnowledgeBase, KnowledgeItem, UseCaseModel, UseCase
    from core.skills import use_case_coverage
    from core.skills.use_case_coverage import _compute_unknown_actors

    kb = KnowledgeBase(
        business_rules=[],
        roles=[KnowledgeItem(text="员工", source="prd", quote="员工", confidence=1.0)],
        entities=[], constraints=[], raw_facts=[],
    )
    ucm = UseCaseModel(use_cases=[
        UseCase(name="操作1", actor="员工", trigger="t", outcome="o", related_rules=[]),
        UseCase(name="操作2", actor="GhostAdmin", trigger="t", outcome="o", related_rules=[]),
        UseCase(name="操作3", actor="unknown_actor:User", trigger="t", outcome="o", related_rules=[]),
    ])
    count, names = _compute_unknown_actors(ucm, kb)
    assert count == 1, f"expected 1 unknown (GhostAdmin), got {count}: {names}"
    assert "操作2 → GhostAdmin" in names[0]
    # "unknown_actor:User" is the explicit fallback, NOT a hallucination
    assert not any("操作3" in n for n in names)


# ---------- V1.6.1 N2 加固新增测试 (2026-06-02) ----------

@pytest.mark.asyncio
async def test_v161_strip_node_suffix_basic():
    """V1.6.1: _strip_node_suffix 剥常见后缀, 保护短节点不被剥穿。"""
    assert _strip_node_suffix("草稿状态") == "草稿"
    assert _strip_node_suffix("待审批状态") == "待审批"
    assert _strip_node_suffix("采购审批流程") == "采购审批"
    assert _strip_node_suffix("用户登录页") == "用户登录"
    assert _strip_node_suffix("审核中") == "审核"
    assert _strip_node_suffix("执行期") == "执行"
    # 无后缀
    assert _strip_node_suffix("草稿") == "草稿"
    # 短保护: 2 字符不能再剥
    assert _strip_node_suffix("期中") == "期中"
    # 多层后缀
    assert _strip_node_suffix("审核中状态") == "审核"
    # 空 / 非字符串
    assert _strip_node_suffix("") == ""
    # 不剥前缀 (LLM 发明前缀是另一类问题, 不应自动掩盖)
    assert _strip_node_suffix("用户未登录") == "用户未登录"


@pytest.mark.asyncio
async def test_v161_align_action_to_usecase():
    """V1.6.1: _align_action 用 substring 策略把 LLM 改写的 action 还原成 use_case.name。"""
    ucm = ["提交采购申请", "部门经理审批采购申请", "总监审批采购申请", "确认打款"]
    # 1. 精确匹配
    assert _align_action("提交采购申请", ucm) == "提交采购申请"
    # 2. action 是 ucm_name 子串 (LLM 缩写)
    assert _align_action("提交", ucm) == "提交采购申请"
    assert _align_action("确认", ucm) == "确认打款"
    # 3. ucm_name 是 action 的连续子串 (LLM 扩展)
    assert _align_action("登录后访问首页", ["登录"]) == "登录"
    assert _align_action("提交采购申请并确认", ["提交采购申请"]) == "提交采购申请"
    # 4. 无匹配
    assert _align_action("完全无关", ["登录", "登出"]) == "完全无关"
    # 5. 空 / 无 ucm
    assert _align_action("", ["登录"]) == ""
    assert _align_action("登录", []) == "登录"


@pytest.mark.asyncio
async def test_v161_normalize_system_model_end_to_end():
    """V1.6.1: 给一个 LLM-typical 烂输出, normalize 后能修好 + 满足 invariant。"""
    from core.interfaces import SystemModel, BusinessFlow, StateTransition, UseCaseModel, UseCase

    sm_raw = SystemModel(
        system_name="采购系统",
        modules=["采购"],
        entities=["采购申请"],
        roles=["员工"],
        flows=[
            BusinessFlow(
                name="采购审批流程",
                nodes=["草稿状态", "待审批状态", "待付款状态", "已完成状态"],
                transitions=[
                    # "提交" 是 "提交采购申请" 的子串 → 应被对齐
                    StateTransition(from_state="草稿状态", action="提交", to_state="待审批状态"),
                    # 重复 (from_state, action) → 应被去重, 保留 to_state="待付款"
                    StateTransition(from_state="待审批状态", action="部门经理审批采购申请", to_state="待付款状态"),
                    StateTransition(from_state="待审批状态", action="部门经理审批采购申请", to_state="草稿状态"),
                ],
            )
        ],
    )
    ucm = UseCaseModel(use_cases=[
        UseCase(name="提交采购申请", actor="员工", trigger="草稿", outcome="待审批", related_rules=[]),
        UseCase(name="部门经理审批采购申请", actor="部门经理", trigger="待审批", outcome="待付款", related_rules=[]),
    ])
    fixed = _normalize_system_model(sm_raw, ucm)
    # 1. 节点名剥后缀
    assert fixed.flows[0].name == "采购审批"
    assert fixed.flows[0].nodes == ["草稿", "待审批", "待付款", "已完成"]
    # 2. action 对齐到 use_case.name
    actions = [(t.from_state, t.action, t.to_state) for t in fixed.flows[0].transitions]
    assert ("草稿", "提交采购申请", "待审批") in actions
    # 3. transitions 去重, 只保留 (待审批, 部门经理审批采购申请, 待付款)
    assert len(fixed.flows[0].transitions) == 2
    assert ("待审批", "部门经理审批采购申请", "待付款") in actions
    assert ("待审批", "部门经理审批采购申请", "草稿") not in actions
    # 4. 所有 nodes 满足 _is_chinese_noun_phrase
    for n in fixed.flows[0].nodes:
        assert _is_chinese_noun_phrase(n), f"normalized node '{n}' still violates invariant"
    # 5. 所有 action 都在 ucm.names 中 (满足 test_n2_transitions_action_matches_usecase 契约)
    ucm_names = {uc.name for uc in ucm.use_cases}
    for t in fixed.flows[0].transitions:
        assert t.action in ucm_names, f"normalized action '{t.action}' still not in ucm.names"


@pytest.mark.asyncio
async def test_v161_derive_minimal_system_model_never_empty():
    """V1.6.1: LLM 完全失败时, 兜底能从任意 UseCaseModel 推导非空 SystemModel。"""
    from core.interfaces import UseCaseModel, UseCase

    ucm = UseCaseModel(use_cases=[
        UseCase(name="提交采购申请", actor="员工", trigger="草稿状态", outcome="待审批", related_rules=[]),
        UseCase(name="部门经理审批", actor="部门经理", trigger="待审批", outcome="待付款", related_rules=[]),
        UseCase(name="确认打款", actor="财务", trigger="待付款", outcome="已完成", related_rules=[]),
    ])
    sm = _derive_minimal_system_model(ucm)
    # 1. 兜底不能是空
    assert sm.flows, "minimal fallback should not produce empty flows"
    # 2. 至少有一个 transition 用 use_case.name 作为 action (满足 N2 → N3 契约)
    all_actions = [t.action for f in sm.flows for t in f.transitions]
    assert "提交采购申请" in all_actions
    assert "部门经理审批" in all_actions
    assert "确认打款" in all_actions
    # 3. 节点名经过 _strip_node_suffix 清理 (满足 test_n2_nodes_normalized)
    for f in sm.flows:
        for n in f.nodes:
            assert _is_chinese_noun_phrase(n), f"minimal fallback node '{n}' not normalized"
    # 4. trigger/outcome 后缀也被剥掉
    all_nodes = {n for f in sm.flows for n in f.nodes}
    assert "草稿" in all_nodes and "草稿状态" not in all_nodes
    assert "待审批" in all_nodes and "待审批状态" not in all_nodes
    # 5. 即使 UseCaseModel 只有一个 use_case 也能跑
    sm_solo = _derive_minimal_system_model(UseCaseModel(use_cases=[
        UseCase(name="登录", actor="用户", trigger="未登录", outcome="已登录", related_rules=[]),
    ]))
    assert sm_solo.flows
    assert sm_solo.flows[0].transitions[0].action == "登录"


@pytest.mark.asyncio
async def test_v161_chinese_noun_phrase_validator_tightened():
    """V1.6.1: _is_chinese_noun_phrase 现在 ban 常见后缀 (状态/流程/页/中/期)。

    V1.7 之前测试漏掉了这些后缀, prd_purchase live 跑出过 "草稿状态"/"待审批状态"。
    """
    # 之前能过的 (含后缀) — 现在应被 ban
    assert not _is_chinese_noun_phrase("草稿状态")
    assert not _is_chinese_noun_phrase("待审批状态")
    assert not _is_chinese_noun_phrase("采购流程")
    assert not _is_chinese_noun_phrase("登录页")
    assert not _is_chinese_noun_phrase("审核中")
    assert not _is_chinese_noun_phrase("执行期")
    # 之前就过的 (干净)
    assert _is_chinese_noun_phrase("草稿")
    assert _is_chinese_noun_phrase("待审批")
    assert _is_chinese_noun_phrase("已完成")
    # 长度违规
    assert not _is_chinese_noun_phrase("草")       # < 2
    assert not _is_chinese_noun_phrase("一二三四五六七")  # > 6
    # 非纯中文
    assert not _is_chinese_noun_phrase("草稿1")
    assert not _is_chinese_noun_phrase("draft")
    assert not _is_chinese_noun_phrase("草-稿")


@pytest.mark.asyncio
async def test_v161_normalize_handles_empty_and_edge_cases():
    """V1.6.1: 极端输入下 normalize 不能崩, 应安全返回。"""
    from core.interfaces import SystemModel, BusinessFlow, StateTransition, UseCaseModel, UseCase

    # 1. 空 flows
    sm_empty = SystemModel(system_name="", modules=[], entities=[], roles=[], flows=[])
    ucm = UseCaseModel(use_cases=[UseCase(name="x", actor="r", trigger="t", outcome="o", related_rules=[])])
    fixed = _normalize_system_model(sm_empty, ucm)
    assert fixed.flows == []

    # 2. node 是空字符串 / 全是后缀
    sm_weird = SystemModel(
        system_name="s", modules=[], entities=[], roles=[],
        flows=[BusinessFlow(name="f", nodes=["", "状态"], transitions=[])],
    )
    fixed2 = _normalize_system_model(sm_weird, ucm)
    # "_strip_node_suffix('状态')" -> '状态' (1 char, can't strip) — 仍会留在 nodes
    # 这没关系, normalize 不强行删除
    assert fixed2.flows[0].nodes == ["", "状态"]

    # 3. transition 引用不存在的 node
    sm_dangling = SystemModel(
        system_name="s", modules=[], entities=[], roles=[],
        flows=[BusinessFlow(
            name="f", nodes=["草稿"],
            transitions=[
                StateTransition(from_state="草稿", action="x", to_state="已删除"),
            ],
        )],
    )
    fixed3 = _normalize_system_model(sm_dangling, ucm)
    assert fixed3.flows[0].transitions == []  # dangling transition 被清掉


@pytest.mark.asyncio
async def test_v161_action_alignment_with_substring_lcp_heuristic():
    """V1.6.1: 多个候选时, 选最长 (最具体) 的 use_case.name。

    设计理由: action 越具体, 跟 use_case 的语义对齐度越高。避免把 "经理审批" 错误
    对齐到过短/过宽泛的 "审批" 上。
    """
    ucm = ["审批", "部门经理审批", "部门经理审批采购申请"]
    # "经理审批" 是后 2 个的子串 — 选最长的 (最具体)
    assert _align_action("经理审批", ucm) == "部门经理审批采购申请"
    # "审批采购" 是最长的子串
    assert _align_action("审批采购", ucm) == "部门经理审批采购申请"
    # 多个匹配时 (e.g., "经理审批" 同时在 "部门经理审批" 和 "部门经理审批采购申请" 中) → 选最长
    assert len(_align_action("经理审批", ucm)) > len("部门经理审批")


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
