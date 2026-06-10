"""core/skills/technique_selector.py — N2.5 (New): TestDesignTechnique Selector.

L1 Pipeline Position:
  上游: N2 condition_analyzer (TestCondition 列表)
  下游: N3 coverage_analyzer
  本节点职责: 为每个条件选择合适的设计技术
"""
from pydantic import BaseModel, Field
from core.llm_client import safe_structured_invoke, get_last_raw
from core.interfaces import TestCondition, TestDesignTechnique
from core.diag_logger import get_diag_auto


class TechniqueResult(BaseModel):
    techniques: list[TestDesignTechnique] = Field(description="设计技术列表")


async def select_techniques(conditions: list[TestCondition]) -> list[TestDesignTechnique]:
    """N2.5 (New): 为每个条件选择测试设计技术。"""
    if not conditions:
        return []

    prompt = f"""<role>
你是一个测试设计技术专家。你的唯一职责是为每个测试条件选择最合适的测试设计技术，
并说明选择理由。你不需要生成用例，只决定"用什么方法覆盖"。
</role>

<context>
你在新的 L2 分析流水线的上游。
- 上游: condition_analyzer 生成的 TestCondition
- 下游: coverage_analyzer 用你的技术选择来创建覆盖项
</context>

<task>
为以下每个 TestCondition 选择至少一种 primary 测试设计技术，
高风险的条件可组合多种 supplementary 技术。
</task>

<rules>
1. **每条件至少一种 primary 技术**
2. **条件类型对技术的建议映射**：
   - functional → equivalence_partitioning, boundary_value_analysis
   - validation → equivalence_partitioning, boundary_value_analysis, error_guessing
   - boundary → boundary_value_analysis
   - permission → decision_table, risk_based
   - state_transition → state_transition
   - error_handling → error_guessing, exploratory
   - data_rule → decision_table, pairwise
   - risk_case → risk_based, exploratory
3. **高风险条件**可组合多种技术（primary + supplementary）
4. **rationale 简洁有力**：说明为什么选这个技术，不写长段落
</rules>

<output_contract>
Return ONLY the following JSON object. No markdown fences. No explanation. No preamble.

{{
  "techniques": [
    {{
      "condition_id": str,
      "primary_technique": "equivalence_partitioning" | "boundary_value_analysis" | "decision_table" | "state_transition" | "pairwise" | "error_guessing" | "exploratory" | "risk_based",
      "supplementary_techniques": [str],
      "rationale": str
    }}
  ]
}}

字段约束:
- condition_id 必须引用存在的条件 ID
- supplementary_techniques 为空数组表示无补充
</output_contract>

### 输入: TestCondition 列表 (共 {len(conditions)} 条)
```json
{{
  "conditions": {[c.model_dump() for c in conditions]}
}}
```
"""
    result = await safe_structured_invoke(prompt, TechniqueResult, model_type="haiku")
    if result is None or not result.techniques:
        print("[TechniqueSelector] LLM returned no usable techniques, using empty list")
        get_diag_auto().dump("04_l2_technique", node="N25_technique_selector", output=[], status="empty_fallback", raw_content=get_last_raw())
        return []
    get_diag_auto().dump("04_l2_technique", node="N25_technique_selector",
                          output=result, status="ok",
                          techniques_count=len(result.techniques),
                          raw_content=get_last_raw())
    return result.techniques
