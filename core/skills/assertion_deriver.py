"""core/skills/assertion_deriver.py — N1.5 (New): RequirementAssertion Derivation.

L1 Pipeline Position:
  上游: N1 fact_extractor (RequirementFact 列表)
  下游: ExplorationGoal 生成 + TestCondition 分析
  本节点职责: 从原子事实推导可验证的断言
"""
from pydantic import BaseModel, Field
from core.llm_client import safe_structured_invoke, get_last_raw
from core.interfaces import RequirementFact, RequirementAssertion
from core.diag_logger import get_diag_auto


class AssertionDerivationResult(BaseModel):
    assertions: list[RequirementAssertion] = Field(description="推导的断言列表")


async def derive_assertions(facts: list[RequirementFact]) -> list[RequirementAssertion]:
    """N1.5 (New): 从原子事实推导可验证的断言。"""
    if not facts:
        return []

    facts_json = [f.model_dump() for f in facts]
    prompt = f"""<role>
你是一个专业的测试分析师。你的唯一职责是从原子化的需求事实推导出可验证的断言 (RequirementAssertion)。
断言是"系统必须验证什么"的精确陈述，不是对需求的重新描述。
</role>

<context>
你在新的 L1 流水线的第二步。
- 上游: N1 fact_extractor 输出的 RequirementFact 列表
- 下游: 探索目标生成器 / 测试条件分析器
- 本节点的成功定义: 每条断言都是可验证的、与事实可追溯的
</context>

<task>
从以下 RequirementFact 列表推导出系统必须验证的断言。
一条事实可能产生 0 到多条断言；多条事实可能合并为一条断言。
</task>

<rules>
1. **可验证性**：断言必须是"系统应该..."或"系统必须..."的格式，能够通过观察/测量验证
2. **追溯性**：每条断言必须引用其来源事实 ID (fact_ids)
3. **跨事实关联断言**（关键要求）：
   - 至少 25% 的断言应引用 2-3 个相关 facts，形成交叉验证
   - 例如：如果 FACT-A 说"绩效权重之和=100%"，FACT-B 说"有4个绩效维度"，
     则应生成一条关联断言："系统应确保4个绩效维度的权重之和严格等于100%"
   - 识别 facts 之间的逻辑关系（依赖、约束、组合），生成复合验证断言
4. **风险分级**：
   - high = 涉及金额、权限、安全、数据完整性的断言
   - medium = 核心功能逻辑
   - low = UI 展示、边缘功能
5. **断言类型准确**：functional / validation / security / performance / compatibility / data_rule / state_transition / error_handling
6. **高风险的断言**必须标记 review_status=auto_generated，留给下游做人工确认门禁
7. **保持断言与事实分离**：事实是证据，断言是验证义务
</rules>

<output_contract>
Return ONLY the following JSON object. No markdown fences. No explanation. No preamble.

{{
  "assertions": [
    {{
      "id": str,
      "fact_ids": [str],
      "assertion_text": str,
      "assertion_type": "functional" | "validation" | "security" | "performance" | "compatibility" | "data_rule" | "state_transition" | "error_handling",
      "risk_level": "high" | "medium" | "low",
      "review_status": "auto_generated" | "human_confirmed" | "rejected",
      "source_references": [str]
    }}
  ]
}}

字段约束:
- id 格式 "ASSERT-001", "ASSERT-002" ...
- fact_ids 至少包含 1 个有效事实 ID
- review_status 默认 "auto_generated"，高风险的保持 auto_generated
- 未知值不编造
</output_contract>

### 输入: RequirementFact 列表 (共 {len(facts)} 条)
```json
{{
  "facts": {facts_json}
}}
```
"""
    result = await safe_structured_invoke(prompt, AssertionDerivationResult, model_type="default")
    if result is None or not result.assertions:
        print("[AssertionDeriver] LLM returned no usable assertions, using empty list")
        get_diag_auto().dump("02_l2_assertion", node="N15_assertion_deriver", output=[], status="empty_fallback", raw_content=get_last_raw())
        return []
    get_diag_auto().dump("02_l2_assertion", node="N15_assertion_deriver",
                          output=result, status="ok",
                          assertions_count=len(result.assertions),
                          raw_content=get_last_raw())
    return result.assertions
