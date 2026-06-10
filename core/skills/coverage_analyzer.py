"""core/skills/coverage_analyzer.py — N3 (New): CoverageItem Generator.

L1 Pipeline Position:
  上游: N2.5 technique_selector (TestDesignTechnique) + conditions
  下游: N3.5 case_generator
  本节点职责: 从条件和技术创建具体的覆盖义务项
"""
from pydantic import BaseModel, Field
from core.llm_client import safe_structured_invoke, get_last_raw
from core.interfaces import TestCondition, TestDesignTechnique, CoverageItem
from core.diag_logger import get_diag_auto


class CoverageResult(BaseModel):
    items: list[CoverageItem] = Field(description="覆盖项列表")


async def analyze_coverage(
    conditions: list[TestCondition],
    techniques: list[TestDesignTechnique],
) -> list[CoverageItem]:
    """N3 (New): 从条件+技术生成具体的覆盖义务项。"""
    if not conditions or not techniques:
        return []

    prompt = f"""<role>
你是一个测试覆盖率分析师。你的唯一职责是从"测试条件+设计技术"的组合中，
生成具体、可追溯的覆盖义务项 (CoverageItem)。每个覆盖项回答了"这条条件用这个技术覆盖哪个维度"。
</role>

<context>
你在 L2 分析流水线的中游。
- 上游: condition_analyzer + technique_selector
- 下游: case_generator 用覆盖项实例化测试用例
</context>

<task>
基于以下 TestCondition 和 TestDesignTechnique 列表，为每个 (条件, 技术) 对生成具体的覆盖项。
覆盖项是义务，不是计数——每个项应该解释它覆盖的具体风险或分支。
</task>

<rules>
1. **每个条件 + 技术可能产生多个覆盖项**（正常值、边界值、异常值等）
2. **coverage_dimension 准确选择**：
   - normal: 正常流程
   - boundary: 边界值
   - negative: 异常输入
   - permission: 权限场景
   - state: 状态覆盖
   - exception: 异常处理
   - recovery: 恢复场景
   - compatibility: 兼容性
   - security: 安全
3. **每个覆盖项应有明确的目标和风险等级**
4. **不要合并不同维度的覆盖**：normal 和 boundary 应拆为不同覆盖项
5. **覆盖项不是测试用例**：它描述义务，不描述具体执行步骤
</rules>

<output_contract>
Return ONLY the following JSON object. No markdown fences. No explanation. No preamble.

{{
  "items": [
    {{
      "id": str,
      "condition_id": str,
      "technique_id": str,
      "coverage_dimension": "normal" | "boundary" | "negative" | "permission" | "state" | "exception" | "recovery" | "compatibility" | "security",
      "goal": str,
      "risk_level": "high" | "medium" | "low"
    }}
  ]
}}

字段约束:
- id 格式 "COV-001", "COV-002" ...
- condition_id 和 technique_id 必须引用存在的 ID
</output_contract>

### 输入: TestCondition 列表
```json
{{
  "conditions": {[c.model_dump() for c in conditions]}
}}
```

### 输入: TestDesignTechnique 列表
```json
{{
  "techniques": {[t.model_dump() for t in techniques]}
}}
```
"""
    result = await safe_structured_invoke(prompt, CoverageResult, model_type="haiku")
    if result is None or not result.items:
        print("[CoverageAnalyzer] LLM returned no usable coverage items, using empty list")
        get_diag_auto().dump("05_l2_coverage", node="N3_coverage_analyzer", output=[], status="empty_fallback", raw_content=get_last_raw())
        return []
    get_diag_auto().dump("05_l2_coverage", node="N3_coverage_analyzer",
                          output=result, status="ok",
                          items_count=len(result.items),
                          raw_content=get_last_raw())
    return result.items
