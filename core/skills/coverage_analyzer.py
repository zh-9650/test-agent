"""core/skills/coverage_analyzer.py — N3 (New): CoverageItem Generator.

L1 Pipeline Position:
  上游: N2.5 technique_selector (TestDesignTechnique) + conditions
  下游: N3.5 case_generator
  本节点职责: 从条件和技术创建具体的覆盖义务项
"""
import asyncio
import os

from pydantic import BaseModel, Field
from core.llm_client import safe_structured_invoke, get_last_raw
from core.interfaces import TestCondition, TestDesignTechnique, CoverageItem
from core.diag_logger import get_diag_auto


class CoverageResult(BaseModel):
    items: list[CoverageItem] = Field(description="覆盖项列表")


_DIMENSION_BY_CONDITION = {
    "functional": "normal",
    "validation": "negative",
    "boundary": "boundary",
    "permission": "permission",
    "state_transition": "state",
    "error_handling": "exception",
    "data_rule": "normal",
    "risk_case": "security",
}


def fallback_coverage(
    conditions: list[TestCondition],
    techniques: list[TestDesignTechnique],
) -> list[CoverageItem]:
    technique_by_condition = {
        technique.condition_id: technique for technique in techniques
    }
    items: list[CoverageItem] = []
    for index, condition in enumerate(conditions, start=1):
        technique = technique_by_condition.get(condition.id)
        if technique is None:
            continue
        items.append(CoverageItem(
            id=f"COV-{index:03d}",
            condition_id=condition.id,
            technique_id=technique.id,
            coverage_dimension=_DIMENSION_BY_CONDITION[condition.condition_type],
            goal=condition.statement,
            risk_level=condition.risk_level,
            source_references=condition.source_references,
            module_ids=condition.module_ids,
            business_flow_ids=condition.business_flow_ids,
            dependency_ids=condition.dependency_ids,
            branch_type=condition.branch_type,
        ))
    return items


def normalize_coverage(
    conditions: list[TestCondition],
    techniques: list[TestDesignTechnique],
    items: list[CoverageItem],
) -> list[CoverageItem]:
    """Keep all grounded variants and deduplicate exact obligations."""
    condition_by_id = {condition.id: condition for condition in conditions}
    technique_by_ref: dict[str, TestDesignTechnique] = {}
    for technique in techniques:
        technique_by_ref[technique.id] = technique
        technique_by_ref[
            f"{technique.condition_id}:{technique.primary_technique}"
        ] = technique
    normalized: list[CoverageItem] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        technique = technique_by_ref.get(item.technique_id)
        if item.condition_id not in condition_by_id or technique is None:
            continue
        if technique.condition_id != item.condition_id:
            continue
        condition = condition_by_id[item.condition_id]
        key = (item.condition_id, item.coverage_dimension, item.variant_key)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            item.model_copy(update={
                "technique_id": technique.id,
                "source_references": item.source_references or condition.source_references,
                "module_ids": item.module_ids or condition.module_ids,
                "business_flow_ids": item.business_flow_ids or condition.business_flow_ids,
                "dependency_ids": item.dependency_ids or condition.dependency_ids,
                "branch_type": item.branch_type if item.branch_type != "positive" else condition.branch_type,
            })
        )
    return normalized


async def analyze_coverage(
    conditions: list[TestCondition],
    techniques: list[TestDesignTechnique],
) -> list[CoverageItem]:
    """N3 (New): 从条件+技术生成具体的覆盖义务项。"""
    if not conditions or not techniques:
        return []

    batch_size = max(1, int(os.getenv("L2_COVERAGE_BATCH_SIZE", "30")))
    batches = [conditions[index:index + batch_size] for index in range(0, len(conditions), batch_size)]
    technique_by_condition = {item.condition_id: item for item in techniques}

    async def analyze_batch(batch: list[TestCondition]) -> list[CoverageItem]:
        batch_techniques = [
            technique_by_condition[item.id] for item in batch if item.id in technique_by_condition
        ]
        return await _analyze_coverage_batch(batch, batch_techniques)

    results = await asyncio.gather(*(analyze_batch(batch) for batch in batches))
    if any(not result for result in results):
        raise RuntimeError("coverage_analysis_batch_failed")
    return normalize_coverage(conditions, techniques, [item for result in results for item in result])


async def _analyze_coverage_batch(
    conditions: list[TestCondition],
    techniques: list[TestDesignTechnique],
) -> list[CoverageItem]:
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
1. 为条件生成所有有来源依据的覆盖变体，不设 1/2 个维度上限
2. **禁止臆造故障注入**：来源和 TestCondition 未明确要求时，不得增加网络错误、JavaScript 异常、第三方脚本、快速连点等场景
3. **coverage_dimension 准确选择**：
   - normal: 正常流程
   - boundary: 边界值
   - negative: 异常输入
   - permission: 权限场景
   - state: 状态覆盖
   - exception: 异常处理
   - recovery: 恢复场景
   - compatibility: 兼容性
   - security: 安全
4. **每个覆盖项应有明确的目标和风险等级**
5. **额外维度必须可追溯**：只有 TestCondition 或来源明确包含该边界、异常、权限或恢复义务时才可增加
6. **覆盖项不是测试用例**：它描述义务，不描述具体执行步骤
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
      "variant_key": str,
      "source_references": [str],
      "module_ids": [str],
      "business_flow_ids": [str],
      "dependency_ids": [str],
      "branch_type": "positive" | "negative" | "boundary" | "permission" | "state" | "exception" | "recovery" | "e2e"
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
        items = fallback_coverage(conditions, techniques)
        get_diag_auto().dump(
            "05_l2_coverage",
            node="N3_coverage_analyzer",
            output=items,
            status="deterministic_fallback",
            raw_content=get_last_raw(),
        )
        return items
    items = result.items
    get_diag_auto().dump("05_l2_coverage", node="N3_coverage_analyzer",
                          output=items, status="ok",
                          items_count=len(items),
                          raw_content=get_last_raw())
    return items
