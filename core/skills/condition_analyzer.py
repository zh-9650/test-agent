"""core/skills/condition_analyzer.py — N2 (New): TestCondition Generator.

L1 Pipeline Position:
  上游: N1.5 assertion_deriver (RequirementAssertion) + live exploration SystemMap evidence
  下游: N2.5 technique_selector
  本节点职责: 从断言 + 系统证据，生成可测试的条件
"""
from pydantic import BaseModel, Field
from core.llm_client import safe_structured_invoke, get_last_raw
from core.interfaces import RequirementAssertion, SystemMapEvid, TestCondition
from core.diag_logger import get_diag_auto


class ConditionResult(BaseModel):
    conditions: list[TestCondition] = Field(description="生成的条件列表")


async def analyze_conditions(
    assertions: list[RequirementAssertion],
    system_map: SystemMapEvid | None = None,
) -> list[TestCondition]:
    """N2 (New): 从断言 + 系统证据生成 TestCondition。"""
    if not assertions:
        return []

    assertions_json = [a.model_dump() for a in assertions]
    system_map_json = system_map.model_dump() if system_map else {}

    prompt = f"""<role>
你是一个测试条件分析师。你的唯一职责是把"需要验证什么"(断言)转化为精确的"可测试条件"(TestCondition)。
条件回答的是"具体在什么场景下、用什么预期来验证"。
</role>

<context>
你在新的 L1 分析流水线的中游。
- 上游: assertion_deriver 输出的断言 + 探索器带回的系统证据
- 下游: technique_selector 选择设计技术
- 本节点的成功定义: 每条条件都有明确的 oracle 类型和可测量性
</context>

<task>
基于以下断言列表（和可选的系统探索证据），为每条断言生成 1 到多条 TestCondition。
每条条件回答"这个断言具体在什么条件下如何验证"。
</task>

<rules>
1. **条件不是断言**：断言是"系统必须...", 条件是"在 X 状态下，执行 Y，预期 Z"
2. **每个断言可能拆分多条条件**：一条断言可能对应多个分支场景
3. **oracle_type 必须明确**：不能为空，从枚举中选择最合适的
   - ui_state: UI 元素状态/文本/可见性
   - api_response: 接口返回值
   - database: 数据库记录
   - business_rule: 业务规则检查
   - network: 网络请求/响应
   - document: 文档比对
   - human_review: 必须人工判断
4. **measurability 诚实标注**：不确定能否自动化验证时标注 human_review
5. **利用系统证据**：如果提供了 SystemMap，用它来使条件更具体
   （例如断言"用户能创建订单" + SystemMap 有"创建订单按钮" → 条件更精确）
6. **condition_type 选择准确**：
   - functional: 功能是否正确
   - validation: 输入校验
   - boundary: 边界值
   - permission: 权限控制
   - state_transition: 状态流转
   - error_handling: 错误处理
   - data_rule: 数据规则
   - risk_case: 风险场景
</rules>

<output_contract>
Return ONLY the following JSON object. No markdown fences. No explanation. No preamble.

{{
  "conditions": [
    {{
      "id": str,
      "assertion_ref": str,
      "condition_type": "functional" | "validation" | "boundary" | "permission" | "state_transition" | "error_handling" | "data_rule" | "risk_case",
      "statement": str,
      "precondition": str,
      "trigger": str,
      "oracle": str,
      "oracle_type": "ui_state" | "api_response" | "database" | "business_rule" | "network" | "document" | "human_review",
      "risk_level": "high" | "medium" | "low",
      "measurability": "measurable" | "partially_measurable" | "human_review",
      "source_references": [str]
    }}
  ]
}}

字段约束:
- id 格式 "COND-001", "COND-002" ...
- assertion_ref 必须引用存在的断言 ID
- oracle_type 不能为空
- 未知值不编造
</output_contract>

### 输入: RequirementAssertion 列表 (共 {len(assertions)} 条)
```json
{{
  "assertions": {assertions_json}
}}
```

### 系统证据 (SystemMap) - 可能为空
```json
{system_map_json}
```
"""
    result = await safe_structured_invoke(prompt, ConditionResult, model_type="default")
    if result is None or not result.conditions:
        print("[ConditionAnalyzer] LLM returned no usable conditions, using empty list")
        get_diag_auto().dump("03_l2_condition", node="N2_condition_analyzer", output=[], status="empty_fallback", raw_content=get_last_raw())
        return []
    get_diag_auto().dump("03_l2_condition", node="N2_condition_analyzer",
                          output=result, status="ok",
                          conditions_count=len(result.conditions),
                          raw_content=get_last_raw())
    return result.conditions
