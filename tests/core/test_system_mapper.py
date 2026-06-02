"""tests/core/test_system_mapper.py — SystemMap Prompt Regression Test.

V1.6.3 新增 (2026-06-02, Phase 1.6):
  - 验证 sampling 10/15 → 20/30 (env 可降级)
  - 验证 prompt V1.6 5 段 XML + few-shot + output_contract
  - 验证 safe_structured_invoke 集成 (内层 fallback)
  - Invariant: 3 字段 schema 有效, 空 history 兜底, 大 history 不爆 token

用法:
  # Mocked (不消耗 token): pytest tests/core/test_system_mapper.py -v
  # Live (消耗 token):     SYSTEM_MAP_LIVE=1 pytest tests/core/test_system_mapper.py -v -s
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


FIXTURES_DIR = Path(__file__).resolve().parents[2] / "data" / "fixtures"


# ---------- Sample history (covers login → home → order list) ----------

def make_sample_history(num_pages: int = 25, elements_per_page: int = 35) -> list[dict]:
    """构造一个典型探索历史, 覆盖登录 → 首页 → 列表 → 详情。"""
    page_templates = [
        ("http://example.com/login", "登录页", [
            ("input", "用户名"), ("input", "密码"), ("button", "登录"),
        ]),
        ("http://example.com/home", "首页", [
            ("link", "采购管理"), ("link", "审批中心"), ("link", "系统设置"),
            ("link", "个人中心"), ("button", "新建"),
        ]),
        ("http://example.com/purchase", "采购列表页", [
            ("button", "新建采购"), ("link", "筛选"), ("link", "导出"),
            ("table", "采购单列表"),
        ]),
        ("http://example.com/purchase/new", "新建采购页", [
            ("input", "采购名称"), ("input", "采购金额"), ("textarea", "采购说明"),
            ("button", "提交"), ("button", "保存草稿"), ("button", "取消"),
        ]),
        ("http://example.com/approval", "审批中心", [
            ("link", "待审批"), ("link", "已审批"), ("link", "审批历史"),
        ]),
    ]
    history = []
    for i in range(num_pages):
        template = page_templates[i % len(page_templates)]
        url, title, base_elems = template
        # 用 base 元素补足 elements_per_page
        elems = list(base_elems) + [("elem", f"元素{j}") for j in range(elements_per_page - len(base_elems))]
        history.append({
            "url": url,
            "title": title,
            "interactive_elements": [
                {"id": f"#{i*100+j+1}", "role": r, "name": n, "text": n}
                for j, (r, n) in enumerate(elems[:elements_per_page])
            ],
            "error_messages": [],
        })
    return history


# ---------- 采样参数测试 (V1.6.3 核心改动) ----------

def test_v163_sampling_defaults_to_20_30():
    """V1.6.3: 默认采样 20 页 / 30 元素 (was 10/15)。"""
    from core.skills.system_mapper import DEFAULT_MAX_PAGES, DEFAULT_MAX_ELEMENTS_PER_PAGE

    assert DEFAULT_MAX_PAGES == 20, f"V1.6.3 默认页数应为 20, got {DEFAULT_MAX_PAGES}"
    assert DEFAULT_MAX_ELEMENTS_PER_PAGE == 30, f"V1.6.3 默认每页元素数应为 30, got {DEFAULT_MAX_ELEMENTS_PER_PAGE}"


def test_v163_sampling_env_overrides():
    """V1.6.3: 采样参数可被 env 覆盖 (降级用)。"""
    with patch.dict(os.environ, {"SYSTEM_MAP_MAX_PAGES": "5", "SYSTEM_MAP_MAX_ELEMENTS_PER_PAGE": "10"}):
        # 重新导入以应用 env
        import importlib
        import core.skills.system_mapper as sm_mod
        importlib.reload(sm_mod)
        assert sm_mod.DEFAULT_MAX_PAGES == 5
        assert sm_mod.DEFAULT_MAX_ELEMENTS_PER_PAGE == 10
        # 恢复
        importlib.reload(sm_mod)


def test_v163_summarize_history_respects_max_pages():
    """V1.6.3: _summarize_history 在 max_pages=3 时只摘要最近 3 页。"""
    from core.skills.system_mapper import _summarize_history

    history = make_sample_history(num_pages=10)
    summary = _summarize_history(history, max_pages=3, max_elements_per_page=30)

    # 应出现 "Page 1/2/3" 但不出现 "Page 8/9/10"
    assert "Page 1" in summary
    assert "Page 3" in summary
    assert "Page 8" not in summary
    assert "Page 10" not in summary


def test_v163_summarize_history_respects_max_elements():
    """V1.6.3: _summarize_history 在 max_elements=2 时每页只列 2 个元素。"""
    from core.skills.system_mapper import _summarize_history

    history = make_sample_history(num_pages=2, elements_per_page=10)
    summary = _summarize_history(history, max_pages=10, max_elements_per_page=2)

    # 每页摘要里应该只列 2 个元素 (login 页: 用户名, 密码)
    login_block = summary.split("Page 1:")[1].split("Page 2:")[0]
    # 元素以逗号分隔, 2 个元素 = 1 个逗号
    elem_lines = [l for l in login_block.split("\n") if "Elements:" in l]
    assert len(elem_lines) == 1
    # 检查元素数: 逗号数 + 1 = 元素数
    assert elem_lines[0].count(",") == 1, f"expected 2 elements (1 comma), got: {elem_lines[0]}"


def test_v163_summarize_history_handles_empty():
    """V1.6.3: 空 history 返回 '无探索历史', 不崩。"""
    from core.skills.system_mapper import _summarize_history

    assert _summarize_history([]) == "无探索历史"
    assert _summarize_history(None) == "无探索历史"


def test_v163_summarize_history_token_safety():
    """V1.6.3: 25 页 × 35 元素的最大输入, 摘要 token < 25K (防 65K 溢出)。"""
    from core.skills.system_mapper import _summarize_history

    history = make_sample_history(num_pages=25, elements_per_page=35)
    summary = _summarize_history(history, max_pages=20, max_elements_per_page=30)

    # 粗估: 1 字符 ≈ 0.5-1 token (中英文混合), 50K 字符 ≈ 25K-50K token
    # 安全阈值: 30K 字符 (覆盖 LLM 输入)
    assert len(summary) < 30_000, f"summary too large: {len(summary)} chars (potential token explosion)"


# ---------- Prompt 5 段 XML 测试 ----------

def test_v163_prompt_v16_xml_structure():
    """V1.6.3: generate_system_map 的 prompt 必须有 V1.6 5 段 XML。"""
    # 我们通过看 prompt 字符串来断言
    from core.skills.system_mapper import extract_system_map_structured
    import inspect
    source = inspect.getsource(extract_system_map_structured)
    for tag in ("<role>", "<context>", "<task>", "<rules>", "<examples>", "<output_contract>"):
        assert tag in source, f"V1.6.3 system_mapper prompt missing {tag}"


def test_v163_prompt_output_contract_specifies_three_fields():
    """V1.6.3: output_contract 必须显式声明 pages/actions/forms 三个字段。"""
    from core.skills.system_mapper import extract_system_map_structured
    import inspect
    source = inspect.getsource(extract_system_map_structured)
    assert "pages" in source
    assert "actions" in source
    assert "forms" in source
    # 不许编造原则
    assert "不编造" in source or "不写" in source or "未知值用空数组" in source


# ---------- Schema / Inter-node 契约测试 ----------

def test_v163_system_map_schema_valid():
    """V1.6.3: SystemMap pydantic schema 三个字段类型正确。"""
    from core.skills.system_mapper import SystemMap

    sm = SystemMap(pages=["登录页"], actions=["点击登录"], forms=["登录表单"])
    assert sm.pages == ["登录页"]
    assert sm.actions == ["点击登录"]
    assert sm.forms == ["登录表单"]

    sm_empty = SystemMap()
    assert sm_empty.pages == []
    assert sm_empty.actions == []
    assert sm_empty.forms == []


@pytest.mark.asyncio
async def test_v163_extract_returns_empty_on_no_history():
    """V1.6.3: 空 history 不调 LLM, 直接返回空 SystemMap。"""
    from core.skills.system_mapper import extract_system_map_structured

    sm = await extract_system_map_structured([])
    assert sm.pages == []
    assert sm.actions == []
    assert sm.forms == []


@pytest.mark.asyncio
async def test_v163_extract_returns_empty_on_llm_failure():
    """V1.6.3: LLM 失败时返回空 SystemMap, 不抛异常。"""
    from core.skills.system_mapper import extract_system_map_structured
    import core.skills.system_mapper as sm_mod

    # mock safe_structured_invoke 返回 None (外层 fallback)
    with patch.object(sm_mod, "safe_structured_invoke", new=AsyncMock(return_value=None)):
        sm = await extract_system_map_structured(make_sample_history())
    assert sm.pages == []
    assert sm.actions == []
    assert sm.forms == []


@pytest.mark.asyncio
async def test_v163_extract_uses_safe_structured_invoke():
    """V1.6.3: extract_system_map_structured 走 safe_structured_invoke (内层 fallback)。"""
    from core.skills.system_mapper import extract_system_map_structured, SystemMap
    import core.skills.system_mapper as sm_mod

    mock_smi = AsyncMock(return_value=SystemMap(pages=["p1"], actions=["a1"], forms=["f1"]))
    with patch.object(sm_mod, "safe_structured_invoke", new=mock_smi):
        sm = await extract_system_map_structured(make_sample_history())
    mock_smi.assert_called_once()
    assert sm.pages == ["p1"]
    assert sm.actions == ["a1"]
    assert sm.forms == ["f1"]


@pytest.mark.asyncio
async def test_v163_generate_system_map_returns_dict():
    """V1.6.3: generate_system_map (兼容层) 返回 dict, 供 planning_graph.py 用。"""
    from core.skills.system_mapper import generate_system_map
    import core.skills.system_mapper as sm_mod

    with patch.object(sm_mod, "safe_structured_invoke", new=AsyncMock(return_value=sm_mod.SystemMap(pages=["p"], actions=["a"], forms=["f"]))):
        result = await generate_system_map(make_sample_history())
    assert isinstance(result, dict)
    assert "pages" in result
    assert "actions" in result
    assert "forms" in result


# ---------- Inter-node 契约 (与 scenario_extractor 联动) ----------

def test_v163_system_map_consumed_by_scenario_extractor():
    """V1.6.3: SystemMap dict 形态与 scenario_extractor 期望一致。

    实际 consumer 在 agents/ui/planning_graph.py:308-314
    接受 {pages, actions, forms} 三个字段, 验证 schema 兼容。
    """
    from core.skills.system_mapper import generate_system_map

    # 同步测试: 验证返回 dict 有正确 keys (不调 LLM)
    import asyncio
    import core.skills.system_mapper as sm_mod

    async def _run():
        with patch.object(sm_mod, "safe_structured_invoke", new=AsyncMock(return_value=None)):
            return await generate_system_map(make_sample_history())
    result = asyncio.run(_run())

    # 必须是 dict 且三个字段都在
    assert isinstance(result, dict)
    assert set(result.keys()) == {"pages", "actions", "forms"}
    # 字段必须是 list[str]
    assert isinstance(result["pages"], list)
    assert isinstance(result["actions"], list)
    assert isinstance(result["forms"], list)


# ---------- Optional: live L1 test (costs tokens) ----------

@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv("SYSTEM_MAP_LIVE"), reason="set SYSTEM_MAP_LIVE=1 to run with real LLM")
async def test_system_mapper_live():
    """Live test. Skipped by default. Set SYSTEM_MAP_LIVE=1 to enable."""
    from core.skills.system_mapper import extract_system_map_structured

    history = make_sample_history(num_pages=20, elements_per_page=30)
    sm = await extract_system_map_structured(history)

    # Invariant: 3 字段 schema 有效
    assert isinstance(sm.pages, list)
    assert isinstance(sm.actions, list)
    assert isinstance(sm.forms, list)
    print(f"\n[live] pages={len(sm.pages)} actions={len(sm.actions)} forms={len(sm.forms)}")
