"""RequirementAssertion derivation for the Layer 1 analysis pipeline."""

import asyncio
import os

from pydantic import BaseModel, Field

from core.diag_logger import get_diag_auto
from core.interfaces import RequirementAssertion, RequirementFact
from core.llm_client import get_last_raw, safe_structured_invoke


class AssertionDerivationResult(BaseModel):
    assertions: list[RequirementAssertion] = Field(description="推导的断言列表")


def _assertion_prompt(facts: list[RequirementFact]) -> str:
    facts_json = [fact.model_dump() for fact in facts]
    return f"""<role>
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
3. **跨事实关联断言**：
   - 优先关联当前批次内 2-3 个存在依赖、约束或组合关系的 facts
   - 不要为了数量强行关联无关 facts
4. **风险分级**：
   - high = 涉及金额、权限、安全、数据完整性的断言
   - medium = 核心功能逻辑
   - low = UI 展示、边缘功能
5. **断言类型准确**：functional / validation / security / performance / compatibility / data_rule / state_transition / error_handling
6. **高风险的断言**必须标记 review_status=auto_generated，留给下游做人工确认门禁
7. **保持断言与事实分离**：事实是证据，断言是验证义务
8. **禁止反向脑补**：原文只说明已登录用户可访问时，不得自动推导未登录用户必须返回 401、403 或重定向
9. **禁止元信息产品化**：文档目的、测试策略、示例、提示词、执行安全约束不得转写成被测系统功能
10. **允许零断言**：事实不足以支持产品义务时不要凑数，返回空数组
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
- fact_ids 至少包含 1 个当前批次内的有效事实 ID
- review_status 默认 "auto_generated"，高风险的保持 auto_generated
- 未知值不编造
</output_contract>

### 输入: RequirementFact 列表 (共 {len(facts)} 条)
{facts_json}
"""


def _fact_batches(facts: list[RequirementFact], batch_size: int) -> list[list[RequirementFact]]:
    grouped: dict[str, list[RequirementFact]] = {}
    for fact in facts:
        reference = fact.source_reference.split(" > ", 1)[0]
        grouped.setdefault(reference, []).append(fact)

    batches: list[list[RequirementFact]] = []
    for group in grouped.values():
        for start in range(0, len(group), batch_size):
            batches.append(group[start:start + batch_size])
    return batches


def _normalize_assertion_ids(
    batch_results: list[list[RequirementAssertion]],
    valid_fact_ids: set[str],
) -> list[RequirementAssertion]:
    normalized: list[RequirementAssertion] = []
    seen: set[tuple[tuple[str, ...], str, str]] = set()
    for assertions in batch_results:
        for assertion in assertions:
            fact_ids = [fact_id for fact_id in assertion.fact_ids if fact_id in valid_fact_ids]
            if not fact_ids:
                continue
            key = (
                tuple(sorted(fact_ids)),
                assertion.assertion_text.strip().casefold(),
                assertion.assertion_type,
            )
            if key in seen:
                continue
            seen.add(key)
            normalized.append(assertion.model_copy(update={
                "id": f"ASSERT-{len(normalized) + 1:03d}",
                "fact_ids": fact_ids,
            }))
    return normalized


async def derive_assertions(facts: list[RequirementFact]) -> list[RequirementAssertion]:
    """Derive assertions in bounded batches grouped by source."""
    if not facts:
        return []

    batch_size = max(5, int(os.getenv("L1_ASSERTION_BATCH_SIZE", "24")))
    batches = _fact_batches(facts, batch_size)
    semaphore = asyncio.Semaphore(max(1, int(os.getenv("L1_MAX_CONCURRENCY", "3"))))

    async def derive_batch(batch: list[RequirementFact]) -> list[RequirementAssertion]:
        async with semaphore:
            result = await safe_structured_invoke(
                _assertion_prompt(batch),
                AssertionDerivationResult,
                model_type="default",
            )
        return result.assertions if result and result.assertions else []

    batch_results = await asyncio.gather(*(derive_batch(batch) for batch in batches))
    nonempty_results = [assertions for assertions in batch_results if assertions]
    if not nonempty_results:
        print("[AssertionDeriver] LLM returned no usable assertions, using empty list")
        get_diag_auto().dump(
            "02_l2_assertion",
            node="N15_assertion_deriver",
            output=[],
            status="empty_fallback",
            raw_content=get_last_raw(),
        )
        return []
    if len(nonempty_results) != len(batches):
        failed = len(batches) - len(nonempty_results)
        raise RuntimeError(f"assertion_derivation_incomplete: {failed}/{len(batches)} batches failed")

    assertions = _normalize_assertion_ids(
        batch_results,
        {fact.id for fact in facts},
    )
    get_diag_auto().dump(
        "02_l2_assertion",
        node="N15_assertion_deriver",
        output={"assertions": [item.model_dump() for item in assertions]},
        status="ok",
        assertions_count=len(assertions),
        batches_count=len(batches),
        raw_content=get_last_raw(),
    )
    return assertions
