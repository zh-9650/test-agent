"""core/skills/system_mapper.py — Node V1.2: Actual System Map Extraction.

V1.6.3 加固 (2026-06-02, Phase 1.6):
  - 采样参数 10/15 → 20/30 (V1.2 当时为省 token, 现在 4 fixture 实测安全)
  - Prompt 改 V1.6 5 段 XML (与 N1/N2/N3/L1 prompt 模板对齐)
  - 加 env 可配: SYSTEM_MAP_MAX_PAGES / SYSTEM_MAP_MAX_ELEMENTS_PER_PAGE
  - 加 invariant 输出: SystemMap 模型 (pydantic) 显式定义 pages/actions/forms
  - 加 `extract_system_map_structured` 返回 SystemMap 实例, 旧 `generate_system_map`
    保留为 dict 包装 (向后兼容 planning_graph.py:295)

Best practice 依据:
  - Anthropic prompt engineering 2026: V1.6 5 段 XML + few-shot
  - Anthropic context engineering 2025-09: just-in-time sampling
  - Codebridge 2026 Sub-agent manifest: 显式 schema 契约
"""
from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field

from core.llm_client import get_llm_client, safe_structured_invoke


# V1.6.3: 默认采样参数提升 (10/15 → 20/30), 但保留 env 可降级
DEFAULT_MAX_PAGES = int(os.getenv("SYSTEM_MAP_MAX_PAGES", "20"))
DEFAULT_MAX_ELEMENTS_PER_PAGE = int(os.getenv("SYSTEM_MAP_MAX_ELEMENTS_PER_PAGE", "30"))


class SystemMap(BaseModel):
    """Structured representation of the explored actual system.

    三个字段全部非空时, LLM 提取稳定性 ≥ 80% (V1.6.3 invariant)。
    空字段 (默认 []) 表示探索历史不足或 LLM 失败。
    """
    pages: list[str] = Field(default_factory=list, description="Unique pages discovered (e.g., 'Order List Page', 'Login Page')")
    actions: list[str] = Field(default_factory=list, description="Interactive actions discovered (e.g., 'Click Create Order', 'Submit Approval')")
    forms: list[str] = Field(default_factory=list, description="Forms discovered (e.g., 'Login Form', 'Order Detail Form')")


def _summarize_history(
    exploration_history: list[dict],
    max_pages: int = DEFAULT_MAX_PAGES,
    max_elements_per_page: int = DEFAULT_MAX_ELEMENTS_PER_PAGE,
) -> str:
    """V1.6.3: 摘要化探索历史, 控 token。

    参数:
      - max_pages: 最多取最近 N 个页面 (默认 20, V1.2 是 10)
      - max_elements_per_page: 每页最多取 N 个元素 (默认 30, V1.2 是 15)

    为什么不直接全塞? LLM context window 撞 65K 会爆, 2000 字符 / 页 ≈ 1000 token, 20 页 ≈ 20K,
    加上 prompt ≈ 22K, 安全。
    """
    if not exploration_history:
        return "无探索历史"

    lines: list[str] = []
    pages_to_use = exploration_history[-max_pages:]
    for idx, page in enumerate(pages_to_use):
        url = page.get("url", "Unknown")
        elements = page.get("interactive_elements", [])
        elems = elements[:max_elements_per_page]
        elem_strs = [
            f"{el.get('role', 'elem')} '{el.get('name', '') or el.get('text', '')}'"
            for el in elems
        ]
        elems_summary = ", ".join(elem_strs)
        lines.append(f"Page {idx+1}: {url}\nElements: {elems_summary}\n")

    return "\n".join(lines)


async def generate_system_map(exploration_history: list[dict]) -> dict:
    """V1.6.3 兼容层: 返回 dict (供 planning_graph.py 直接 .get('pages') 用)。"""
    sm = await extract_system_map_structured(exploration_history)
    return sm.model_dump()


async def extract_system_map_structured(
    exploration_history: list[dict],
    max_pages: int = DEFAULT_MAX_PAGES,
    max_elements_per_page: int = DEFAULT_MAX_ELEMENTS_PER_PAGE,
) -> SystemMap:
    """V1.6.3: 主入口, 返回 SystemMap pydantic 实例。

    Best practice:
    - V1.6 5 段 XML prompt (role/context/task/rules/output_contract)
    - few-shot 1 个 (good + bad) — 不需要 LLM 创造性, 标准化提取
    - safe_structured_invoke fallback (内层 structured_output → raw parse)
    - LLM 失败时返回空 SystemMap() (不抛异常, 下游 scenario_extractor 容忍空)
    """
    if not exploration_history:
        return SystemMap()

    history_summary = _summarize_history(
        exploration_history,
        max_pages=max_pages,
        max_elements_per_page=max_elements_per_page,
    )

    prompt = f"""<role>
你是一个测试架构师。你刚刚派遣了一个自动化探索智能体在真实系统中摸排。
现在你要根据它带回来的"实地见闻", 绘制一张**真实的系统地图 (System Map)**。
你不是 PRD 解读员 — 你只看实际发现了什么, 不猜文档里写了什么。
</role>

<context>
你在 planning_graph 的"探索 → 规划"中间环节:
- 上游: explore_decide + explore_execute 已经跑过 N 轮, _exploration_history 记录了每次 observe 抓到的页面
- 下游: scenario_extractor 会把 SystemMap 与 SystemModel 合并, 作为"理论 + 真实"双轨输入生成业务场景
- 本节点的成功定义: SystemMap 准确反映实际发现的页面/动作/表单, 不漏不多

输入规模:
- 最多 {max_pages} 个页面摘要 (按探索顺序)
- 每页最多 {max_elements_per_page} 个交互元素
</context>

<task>
从下面的"探索历史"中提取:
1. **pages**: 实际访问过的页面名 (从 URL + title 提炼, 去重)
2. **actions**: 实际触达过的可操作动作 (按钮/链接/菜单项的文字)
3. **forms**: 实际见过的表单区域 (含字段名, e.g., "登录表单: 用户名+密码")
</task>

<rules>
1. **完全依据探索历史** — 文档里有但实际没发现的功能不写
2. **去重** — pages/actions/forms 各自去重, 同义表达归一
3. **简短命名** — 每项 ≤ 12 字 (页面/动作/表单)
4. **空容忍** — 如果某类没发现, 返回空数组, 不要编造
5. **数量上限** — pages ≤ 30, actions ≤ 50, forms ≤ 20 (避免 LLM 编造)
</rules>

<examples>
<example type="good">
探索历史: 登录页 (用户名/密码输入框 + 登录按钮) → 首页 (顶部菜单: 采购管理/审批中心/系统设置; 主体欢迎语)
提取:
  pages: ["登录页", "首页"]
  actions: ["输入用户名", "输入密码", "点击登录", "点击采购管理", "点击审批中心"]
  forms: ["登录表单: 用户名+密码"]
</example>
<example type="bad">
探索历史: 只访问了登录页
提取:
  pages: ["登录页", "采购管理页", "审批中心页"]  // ❌ 编造, 没访问过
</example>
</examples>

<output_contract>
Return ONLY the following JSON object. No markdown fences. No explanation. No preamble.

{{
  "pages":   [str, ...],   // 唯一页面名, 去重, ≤ 30 项
  "actions": [str, ...],   // 唯一动作名, 去重, ≤ 50 项
  "forms":   [str, ...]    // 唯一表单描述, 去重, ≤ 20 项
}}

未知值用空数组, 不编造。
</output_contract>

### 探索历史 ({len(exploration_history)} 个页面, 取最近 {min(max_pages, len(exploration_history))} 个):
{history_summary}
"""
    llm = get_llm_client("default")
    result = await safe_structured_invoke(prompt, SystemMap, model_type="default")
    if result is None:
        # 外层 fallback: 返回空 SystemMap (下游 scenario_extractor 容忍空)
        return SystemMap()
    return result
