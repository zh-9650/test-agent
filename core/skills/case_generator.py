"""core/skills/case_generator.py — N3.5 (New): CandidateTestCase Generator.

L1 Pipeline Position:
  上游: N3 coverage_analyzer (CoverageItem)
  下游: N4 traceability_builder
  本节点职责: 从覆盖项实例化可执行的候选测试用例
"""
from pydantic import BaseModel, Field
from core.llm_client import safe_structured_invoke, get_last_raw
from core.interfaces import CoverageItem, CandidateTestCase
from core.diag_logger import get_diag_auto


class CaseGenerationResult(BaseModel):
    cases: list[CandidateTestCase] = Field(description="候选用例列表")


async def generate_cases(
    coverage_items: list[CoverageItem],
) -> list[CandidateTestCase]:
    """N3.5 (New): 从覆盖项实例化候选测试用例。"""
    if not coverage_items:
        return []

    prompt = f"""<role>
你是一个测试用例设计师。你的唯一职责是从覆盖义务项(CoverageItem)实例化出可执行的候选测试用例(CandidateTestCase)。
用例不需要写死 UI 步骤，但必须清晰地描述"测什么、前置条件、输入、预期"。
</role>

<context>
你在 L2 分析流水线的下游。
- 上游: coverage_analyzer 输出的覆盖项
- 下游: traceability_builder 构建追溯矩阵
- 本节点成功定义: 每条用例可追溯到上游覆盖项，且表达清晰
</context>

<task>
基于以下 CoverageItem 列表，为每个覆盖项生成 1 个候选测试用例。
</task>

<rules>
1. **不写死 UI 步骤**：用例描述的是"验证什么"而非"点击哪里"。执行提示留轻量级建议
2. **可追溯**：每条用例的 trace_references 必须包含覆盖项 ID
3. **优先级对齐**：继承覆盖项的 risk_level → priority 映射：high→high, medium→medium, low→low
4. **input_data 精确**：用 dict {{字段名: 示例值}} 的格式描述输入数据
5. **execution_hint 是轻量建议**：如"可能需要先登录"，而非"第1步点击登录按钮"
6. **一条覆盖项对应一条用例**：不要合并
</rules>

<output_contract>
Return ONLY the following JSON object. No markdown fences. No explanation. No preamble.

{{
  "cases": [
    {{
      "id": str,
      "title": str,
      "goal": str,
      "description": str,
      "preconditions": [str],
      "input_data": {{str: str}},
      "expected_result": str,
      "priority": "high" | "medium" | "low",
      "category": str,
      "trace_references": [str],
      "execution_hint": str
    }}
  ]
}}

字段约束:
- id 格式 "TC-CAND-001", "TC-CAND-002" ...
- trace_references 至少包含 1 个覆盖项 ID
- preconditions 和 trace_references 未知时用空数组
</output_contract>

### 输入: CoverageItem 列表 (共 {len(coverage_items)} 条)
```json
{{
  "coverage_items": {[c.model_dump() for c in coverage_items]}
}}
```
"""
    result = await safe_structured_invoke(prompt, CaseGenerationResult, model_type="haiku")
    if result is None or not result.cases:
        print("[CaseGenerator] LLM returned no usable cases, using empty list")
        get_diag_auto().dump("06_l2_case", node="N35_case_generator", output=[], status="empty_fallback", raw_content=get_last_raw())
        return []
    get_diag_auto().dump("06_l2_case", node="N35_case_generator",
                          output=result, status="ok",
                          cases_count=len(result.cases),
                          raw_content=get_last_raw())
    return result.cases
