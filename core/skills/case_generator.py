"""Generate structured, traceable CandidateTestCase assets."""

import asyncio
import os

from pydantic import BaseModel, Field

from core.diag_logger import get_diag_auto
from core.interfaces import CandidateTestCase, CoverageItem
from core.llm_client import get_last_raw, safe_structured_invoke


class CaseGenerationResult(BaseModel):
    cases: list[CandidateTestCase] = Field(description="候选用例列表")


async def generate_cases(
    coverage_items: list[CoverageItem],
) -> list[CandidateTestCase]:
    if not coverage_items:
        return []

    batch_size = max(1, int(os.getenv("L2_CASE_BATCH_SIZE", "20")))
    batches = [coverage_items[index:index + batch_size] for index in range(0, len(coverage_items), batch_size)]
    results = await asyncio.gather(*(_generate_case_batch(batch) for batch in batches))
    if any(not result for result in results):
        raise RuntimeError("case_generation_batch_failed")
    cases = [case for result in results for case in result]
    coverage_by_id = {item.id: item for item in coverage_items}
    normalized = []
    for index, case in enumerate(cases, start=1):
        source = next(
            (coverage_by_id[ref] for ref in case.trace_references if ref in coverage_by_id),
            None,
        )
        if source is None:
            continue
        normalized.append(case.model_copy(update={
            "id": f"TC-CAND-{index:03d}",
            "module_ids": source.module_ids,
            "business_flow_ids": source.business_flow_ids,
            "dependency_ids": source.dependency_ids,
            "branch_type": source.branch_type,
        }))
    return normalized


async def _generate_case_batch(
    coverage_items: list[CoverageItem],
) -> list[CandidateTestCase]:
    prompt = f"""<role>
你是测试分析师。请把 CoverageItem 转换为可执行但不包含固定 UI 点击步骤的 CandidateTestCase。
</role>

<rules>
1. 每个覆盖项生成一个用例，trace_references 必须包含对应 CoverageItem.id。
2. priority 继承 risk_level。
3. preconditions 必须是结构化对象，不得让执行层通过文本猜测角色或失败策略。
4. account_role 前置条件必须显式填写 required_role，并同步到 required_roles。
5. 当前目标页面可访问、页面已部署、可观察页面内容、可通过浏览器导航等环境条件，
   satisfiable_by_agent 必须为 true；只有确实需要外部人工、额外环境或不可获得数据时才为 false。
6. input_data 不得包含真实凭据；secret 数据只能填写 placeholder，value 必须为 null。
7. execution_hint 只提供轻量导航建议，不得生成固定步骤。
8. module_ids、business_flow_ids、dependency_ids、branch_type 必须原样继承覆盖项。
9. estimated_cost 只能是 low、medium、high；边界输入必须写入结构化 input_data。
10. 涉及标签名、卡片名、字段名、状态名等业务术语时，必须保留 CoverageItem 中的原词；如果覆盖项没有枚举具体名称，不要自行补出另一套命名。
11. 覆盖项表达“只读”“仅展示”“不可在线编辑”时，expected_result 应聚焦“无业务写入入口”；不要写成“无任何下拉框、导航按钮、筛选控件或视图切换控件”。
</rules>

<output_contract>
只返回 JSON：
{{
  "cases": [
    {{
      "id": "TC-CAND-001",
      "title": "用例标题",
      "goal": "业务验证目标",
      "description": "说明",
      "preconditions": [
        {{
          "type": "account_role | business_state | environment | data",
          "description": "前置条件",
          "required_role": null,
          "satisfiable_by_agent": true,
          "failure_policy": "skipped | incomplete | failed | human_review_required"
        }}
      ],
      "input_data": [
        {{
          "name": "字段名",
          "value": null,
          "placeholder": "测试数据占位符",
          "source": "generated",
          "sensitivity": "public | internal | secret",
          "generation_strategy": "生成方式",
          "boundary_category": "normal | boundary | negative"
        }}
      ],
      "expected_result": "预期结果",
      "priority": "high | medium | low",
      "category": "functional",
      "trace_references": ["COV-..."],
      "execution_hint": "轻量提示",
      "required_roles": []
      "module_ids": [],
      "business_flow_ids": [],
      "dependency_ids": [],
      "branch_type": "positive",
      "estimated_cost": "low | medium | high"
    }}
  ]
}}
</output_contract>

输入 CoverageItem：
{[item.model_dump() for item in coverage_items]}
"""
    result = await safe_structured_invoke(
        prompt,
        CaseGenerationResult,
        model_type="haiku",
    )
    if result is None or not result.cases:
        get_diag_auto().dump(
            "06_l2_case",
            node="N35_case_generator",
            output=[],
            status="empty_fallback",
            raw_content=get_last_raw(),
        )
        return []
    get_diag_auto().dump(
        "06_l2_case",
        node="N35_case_generator",
        output=result,
        status="ok",
        cases_count=len(result.cases),
        raw_content=get_last_raw(),
    )
    return result.cases
