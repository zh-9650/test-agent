"""Generate structured, traceable CandidateTestCase assets."""

import asyncio
import os

from pydantic import BaseModel, Field

from core.diag_logger import get_diag_auto
from core.interfaces import CandidateTestCase, CoverageItem, StructuredPrecondition
from core.llm_client import get_last_raw, safe_structured_invoke


class CaseGenerationResult(BaseModel):
    cases: list[CandidateTestCase] = Field(description="候选用例列表")


def fallback_cases(coverage_items: list[CoverageItem]) -> list[CandidateTestCase]:
    cases: list[CandidateTestCase] = []
    for index, item in enumerate(coverage_items, start=1):
        title = item.goal[:60] or f"覆盖项 {item.id} 验证"
        lower_goal = item.goal.lower()
        expected_result = "页面呈现与覆盖目标一致的可观察结果。"
        execution_hint = "打开目标页面，按覆盖目标完成对应 UI 操作并观察结果。"
        if any(
            marker in lower_goal
            for marker in (
                "错误密码",
                "无效密码",
                "密码错误",
                "错误凭据",
                "错误输入",
                "错误提示",
                "错误流程",
                "拒绝登录",
                "wrong password",
                "invalid password",
                "invalid credential",
                "wrong credential",
            )
        ):
            expected_result = "提交后仍停留在登录页，并显示密码错误或登录失败提示。"
            execution_hint = "回到登录页，输入覆盖目标中的用户名和错误密码，点击立即登录。"
        elif any(marker in lower_goal for marker in ("一键填值", "quick fill", "quick-fill")):
            expected_result = "点击一键填值后，登录表单字段值符合覆盖目标。"
            execution_hint = "回到登录页，点击一键填值体验按钮并观察输入框值。"
        elif any(marker in lower_goal for marker in ("登录成功", "有效凭据", "dashboard", "控制台")):
            expected_result = "提交有效凭据后进入控制台，并显示登录后入口或账号身份。"
            execution_hint = "回到登录页，输入已配置的有效账号密码，点击立即登录。"

        cases.append(
            CandidateTestCase(
                id=f"TC-CAND-{index:03d}",
                title=title,
                goal=item.goal,
                description="由覆盖项生成的确定性候选用例。",
                preconditions=[
                    StructuredPrecondition(
                        type="environment",
                        description="目标页面已加载且可通过浏览器访问。",
                        satisfiable_by_agent=True,
                        failure_policy="incomplete",
                    )
                ],
                expected_result=expected_result,
                priority=item.risk_level,
                category="functional",
                trace_references=[item.id],
                execution_hint=execution_hint,
                module_ids=item.module_ids,
                business_flow_ids=item.business_flow_ids,
                dependency_ids=item.dependency_ids,
                branch_type=item.branch_type,
                estimated_cost="low",
            )
        )
    return cases


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
    timeout_seconds = float(os.getenv("L2_CASE_GENERATION_TIMEOUT_SECONDS", "90"))
    try:
        result = await asyncio.wait_for(
            safe_structured_invoke(
                prompt,
                CaseGenerationResult,
                model_type="haiku",
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        items = fallback_cases(coverage_items)
        get_diag_auto().dump(
            "06_l2_case",
            node="N35_case_generator",
            output=items,
            status="deterministic_fallback_timeout",
            timeout_seconds=timeout_seconds,
            raw_content=get_last_raw(),
        )
        return items
    if result is None or not result.cases:
        items = fallback_cases(coverage_items)
        get_diag_auto().dump(
            "06_l2_case",
            node="N35_case_generator",
            output=items,
            status="deterministic_fallback_empty",
            raw_content=get_last_raw(),
        )
        return items
    get_diag_auto().dump(
        "06_l2_case",
        node="N35_case_generator",
        output=result,
        status="ok",
        cases_count=len(result.cases),
        raw_content=get_last_raw(),
    )
    return result.cases
