"""Build a grounded business coverage blueprint before condition design."""

from pydantic import BaseModel, Field

from core.diag_logger import get_diag_auto
from core.interfaces import CoverageBlueprint, RequirementAssertion, SystemMapEvid
from core.llm_client import get_last_raw, safe_structured_invoke


class CoverageBlueprintResult(BaseModel):
    blueprint: CoverageBlueprint = Field(default_factory=CoverageBlueprint)


def fallback_blueprint(
    assertions: list[RequirementAssertion],
    system_map: SystemMapEvid | None,
) -> CoverageBlueprint:
    """Create modules only from explicit assertion subjects/pages; never invent flows."""
    modules = []
    for index, assertion in enumerate(assertions, start=1):
        modules.append({
            "id": f"MOD-{index:03d}",
            "name": assertion.assertion_text[:48],
            "assertion_ids": [assertion.id],
            "page_refs": [],
            "risk_tier": assertion.risk_level,
            "is_core": assertion.risk_level == "high",
        })
    gaps = []
    if system_map is None or not system_map.pages:
        gaps.append("缺少可用于识别业务页面与流程的探索证据")
    return CoverageBlueprint(modules=modules, gaps=gaps)


async def plan_coverage_blueprint(
    assertions: list[RequirementAssertion],
    system_map: SystemMapEvid | None,
    memory_context: str = "",
) -> CoverageBlueprint:
    if not assertions:
        return CoverageBlueprint()
    memory_context_section = (
        f"\n### MemoryContext (hint-only, never a RequirementFact source)\n"
        f"{memory_context}\n"
        if memory_context
        else ""
    )
    prompt = f"""<role>你是业务覆盖架构师。</role>
<task>只依据已确认断言和探索证据，识别业务模块、核心流程和模块依赖。</task>
<rules>
1. 不得补造输入中不存在的模块、流程、角色或依赖。
2. 模块和流程必须引用 assertion_ids；依赖必须给出 source_basis。
3. 无法可靠识别的内容写入 gaps，不要猜测。
4. 核心流程仅标记真实端到端业务结果；P0/P1 仅用于明确的关键依赖。
</rules>
<output_contract>只返回符合 CoverageBlueprintResult 的 JSON。</output_contract>
断言：{[a.model_dump() for a in assertions]}
探索证据：{system_map.model_dump() if system_map else {}}
{memory_context_section}
"""
    result = await safe_structured_invoke(
        prompt, CoverageBlueprintResult, model_type="default"
    )
    blueprint = result.blueprint if result is not None else fallback_blueprint(assertions, system_map)
    get_diag_auto().dump(
        "03_l2_blueprint",
        node="N2_coverage_planner",
        output=blueprint,
        status="ok" if result is not None else "deterministic_fallback",
        raw_content=get_last_raw(),
    )
    return blueprint
