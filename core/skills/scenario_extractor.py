"""core/skills/scenario_extractor.py — Scenario Extractor (Phase 1.5).

Pipeline Position:
  上游: PRD + Changelog + focus_areas + SystemMap
  下游: planning_graph.generate_plan_node (scenarios 注入 Planner)
  本节点职责: 从 PRD 提取"用户视角的端到端业务场景",用于 Goal-Driven 探索
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from core.llm_client import safe_structured_invoke


class Scenario(BaseModel):
    id: str = Field(description="场景编号,如 'S-001'")
    name: str = Field(description="场景名称,如 '用户下单流程'")
    entry_hint: str = Field(description="在页面上如何找到这个流程的入口(如 '寻找购物车或下单按钮')")
    priority: str = Field(description="'high' | 'medium' | 'low'")


class ScenarioList(BaseModel):
    scenarios: list[Scenario] = Field(default_factory=list, description="业务场景列表")


GOOD_EXAMPLE = """
INPUT (excerpt, PRD 摘要):
"采购员提交采购申请,5000 元以下由部门经理审批;5000-10000 元由总监审批;10000 元以上需要 VP 审批。
采购员可在采购列表查看历史记录,经理/总监/VP 在审批中心处理待办。"

EXPECTED OUTPUT:
{
  "scenarios": [
    {
      "id": "S-001",
      "name": "采购员提交采购申请",
      "entry_hint": "寻找'新建采购申请'或'提交申请'按钮,通常在采购列表页",
      "priority": "high"
    },
    {
      "id": "S-002",
      "name": "部门经理审批 5000 元以下采购单",
      "entry_hint": "进入'审批中心'或'待办列表',筛选金额 < 5000 的单子",
      "priority": "high"
    },
    {
      "id": "S-003",
      "name": "采购员查看历史采购记录",
      "entry_hint": "进入'采购列表'或'历史记录'页",
      "priority": "medium"
    }
  ]
}
"""

BAD_EXAMPLE = """
INPUT (excerpt): "系统要支持工作流。"

WRONG OUTPUT (anti-pattern): 把"工作流"硬造一个 scenario。
RIGHT OUTPUT:
{
  "scenarios": []
}
Reason: 描述太抽象,没有具体业务动作可作为测试场景。
"""


async def extract_scenarios(
    prd: str,
    changelog: str = "",
    focus_areas: str = "",
    system_map: dict | None = None,
) -> list[dict]:
    """从 PRD 提取业务场景列表,用于 Goal-Driven 探索。

    流水线位置: SystemMap 完成后 → Planner 生成用例前。
    ScenarioExtractor 拆的是"用户视角的端到端业务流程"。

    Args:
        prd: PRD 文档文本
        changelog: 变更日志(可选)
        focus_areas: 用户指定的重点关注领域(可选)
        system_map: 系统地图(可选,作为补充上下文)

    Returns:
        场景列表,每项包含 id, name, entry_hint, priority。
        返回空列表 = "PRD 不足以提取场景",不是错误。
    """
    if not prd and not changelog:
        return []

    context = ""
    if prd:
        context += f"## PRD 内容\n{prd[:3000]}\n\n"
    if changelog:
        context += f"## 变更日志\n{changelog[:1000]}\n\n"
    if focus_areas:
        context += f"## 重点区域\n{focus_areas}\n\n"
    if system_map:
        context += f"## 系统地图 (高优先级参考)\n{json.dumps(system_map, ensure_ascii=False, indent=2)[:2500]}\n\n"

    prompt = f"""<role>
你是一个资深测试分析师。你的唯一职责是从 PRD 中提取"用户视角的端到端业务场景",每个场景代表用户能完成的一个完整业务流程。
</role>

<context>
你在测试平台的"规划阶段"流水线中。
- 上游: PRD + Changelog + focus_areas(可选,作为补充认知)
- 下游: generate_plan_node 会把你的 scenarios 注入 Planner,Planner 优先为 high 场景生成用例
- 你的成功定义: Planner 能直接用 scenarios 列表驱动 Goal-Driven 探索,零回填
</context>

<task>
基于以下产品文档,提取所有可识别的端到端业务场景。
</task>

<rules>
1. **粒度标准**: 一个场景 = 用户视角的一个完整流程(如"用户下单流程"包含浏览→加购→结算→支付)。
   - 粗到能站成 1 个 end-to-end 用例
   - **禁止**细到"用户点击搜索按钮"(那是 step,不是 scenario)
   - **禁止**粗到"系统能处理订单"(太抽象,没入口)
2. **entry_hint 必须可执行** (重要): 要给 Planner 在 UI 里"具体去哪里找"的具体提示。
   - 好: "进入'审批中心'或'待办列表'"
   - 坏: "在系统中查找"(太抽象)、"通过 API 调用"(错,这是 UI 测试)
3. **priority 判定标准**:
   - `high`: 主业务流(下单、支付、登录、注册、提交审批)
   - `medium`: 支撑功能(查询列表、修改资料、修改密码)
   - `low`: 边角功能(UI 偏好、帮助文档、关于我们)
4. **id 格式**: `S-NNN`(3 位数字,从 001 开始递增)
5. **没有就返回空**: PRD 内容不足以提取场景时,返回 `{{"scenarios": []}}`,**不要**硬造。
6. **去重**: 同一业务流不要在多个场景里重复。
7. **最多 12 个**: PRD 真正能拆出的端到端场景有限,超过 12 个说明拆得太细。
8. **跨输入融合**: 当 PRD + Changelog 都给定时,跨文档出现的同一流程合并成 1 个 scenario。
</rules>

<examples>
<example title="good: 粒度合适 + entry_hint 可执行">
{GOOD_EXAMPLE}
</example>
<example title="bad-to-good: 描述太抽象时不硬造">
{BAD_EXAMPLE}
</example>
</examples>

<output_contract>
Return ONLY the following JSON object. No markdown fences. No explanation. No preamble.

{{
  "scenarios": [
    {{
      "id": str,                  // "S-001" 格式,3 位数字递增
      "name": str,                // 场景名,简洁(< 30 字)
      "entry_hint": str,          // UI 寻路提示,具体可执行(< 60 字)
      "priority": "high" | "medium" | "low"
    }}
  ]
}}

字段约束:
- `id` 格式: "S-NNN",NNN 3 位数字从 001 递增
- `priority` ∈ {{"high", "medium", "low"}}
- `scenarios` 长度 0-12
- `name` 长度 ≤ 30 字
- `entry_hint` 长度 ≤ 60 字
- 未知/不充分时 `scenarios` 填 `[]`
</output_contract>

{context}
"""
    try:
        response = await safe_structured_invoke(prompt, ScenarioList, model_type="haiku")

        if response is None:
            print("[ScenarioExtractor] LLM returned no usable scenarios")
            return []

        scenarios = [s.model_dump() for s in response.scenarios]
        print(f"[ScenarioExtractor] Extracted {len(scenarios)} scenarios: {[s.get('name', '') for s in scenarios]}")
        return scenarios
    except Exception as e:
        print(f"[ScenarioExtractor] Failed: {e}")
        return []
