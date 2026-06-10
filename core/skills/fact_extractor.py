"""core/skills/fact_extractor.py — N1: RequirementFact Extraction.

Pipeline Position:
  上游: 用户输入的 PRD / Swagger / Changelog / 规则 / 原型 / 架构文档
  下游: N1.5 assertion_deriver
  本节点职责: 把源文档提纯为原子化的 RequirementFact，保持可追溯性
"""
import re
from pydantic import BaseModel, Field
from core.llm_client import safe_structured_invoke, get_last_raw
from core.interfaces import RequirementFact
from core.diag_logger import get_diag_auto


class FactExtractionResult(BaseModel):
    facts: list[RequirementFact] = Field(description="提取的需求事实列表")


# ---------------------------------------------------------------------------
# Confidence Calibration (post-processing)
# ---------------------------------------------------------------------------
# 基于业界最佳实践：LLM 自评 confidence 不可靠，需用证据质量后处理校准。
# 参考: Evidence-based Requirement Analysis, Confidence-Aware RE (ACM 2020),
#       Conformal Prediction for structured extraction.

# Source type 基线 confidence
_SOURCE_BASELINE: dict[str, float] = {
    "prd": 0.95,
    "swagger": 0.90,
    "architecture": 0.85,
    "changelog": 0.80,
    "prototype": 0.75,
    "rule": 0.85,
    "inferred": 0.60,
}


def _calibrate_confidence(fact: RequirementFact) -> float:
    """基于证据质量后处理校准单条 fact 的 confidence。

    校准因子:
    1. Source type 基线 — 不同来源可靠性不同
    2. Quote 质量 — 有精准原文引用 > 无引用
    3. Fact 完整度 — 有 condition+outcome > 只有 subject-action
    4. 原子性 — 短 subject 更可能为原子事实
    """
    # 1. Source type baseline
    base = _SOURCE_BASELINE.get(fact.source_type, 0.70)

    # 2. Quote quality adjustment
    quote = (fact.quote or "").strip()
    if not quote or quote == "N/A":
        base -= 0.20  # 无引用，显著降低
    elif len(quote) < 10:
        base -= 0.10  # 引用过短，可能不精确
    elif len(quote) > 50:
        base += 0.02  # 长引用，略微加分

    # 3. Fact completeness (condition + outcome)
    has_condition = bool(fact.condition and fact.condition.strip())
    has_outcome = bool(fact.outcome and fact.outcome.strip())
    if has_condition and has_outcome:
        base += 0.03  # 完整的事实描述
    elif not has_condition and not has_outcome:
        base -= 0.05  # 只有 subject-action，信息量较少

    # 4. Atomicity — short subject tends to be more atomic
    subject_len = len(fact.subject or "")
    if subject_len > 30:
        base -= 0.05  # subject 过长，可能未充分拆分
    elif subject_len < 10:
        base += 0.02  # 短 subject，更原子化

    # Clamp to [0.3, 1.0]
    return max(0.3, min(1.0, round(base, 2)))


def calibrate_facts(facts: list[RequirementFact]) -> list[RequirementFact]:
    """后处理校准所有 facts 的 confidence。

    不覆盖 LLM 的 1.0 判断（如果 LLM 给 1.0 且校准后也高，则保持），
    但会将 LLM 给 1.0 但证据质量不足的 facts 降低。
    """
    for fact in facts:
        calibrated = _calibrate_confidence(fact)
        # 取 LLM 原始值和校准值的较低者（保守策略）
        fact.confidence = min(fact.confidence, calibrated)
    return facts


async def extract_facts(
    prd_content: str = "",
    api_doc_content: str = "",
    changelog_content: str = "",
    prototype_notes: str = "",
    architecture_notes: str = "",
    rules: str = "",
) -> list[RequirementFact]:
    """N1 (New): 从多份源文档中提取原子化的 RequirementFact。"""
    prompt = f"""<role>
你是一个极其严谨的"可追溯事实提取器"。你的唯一职责是从输入文档中精确提取原子化事实，
每条事实必须包含规范化 subject/action/object/condition/outcome 和原文引用。
</role>

<context>
你在 L2 分析流水线的最上游。
- 你的输出直接喂给下游 assertion_deriver (RequirementAssertion 推导)
- 每条事实应该是不可再分的原子陈述
</context>

<task>
从以下输入文档中提取所有可追溯的原子化需求事实 (RequirementFact)。
</task>

<rules>
1. **原子化**：复合陈述必须拆分为多条事实。例如"金额>5000需经理审批且需总监复核"
   应拆为"金额>5000需经理审批"和"金额>5000需总监复核"两条。
2. **source_type 准确**：prd / swagger / changelog / prototype / architecture / rule / inferred
3. **subject/action/object 规范化**：提取核心主体、动作、客体，用简洁的业务术语
4. **condition/outcome 优雅处理**：有条件则填，无条件则 null；不编造
5. **quote 精准**：必须能从原文 Ctrl+F 定位；不可追溯时填 "N/A" 且 confidence ≤ 0.5
6. **冲突标记**：如果发现两条事实语义冲突（如 PRD 和 Swagger 说法不同），
   在各自 conflict_references 中互填对方 ID，status 设为 "conflicted"
7. **不要合并事实到 use case 一级**：保持细粒度
8. **confidence 置信度分级**（严格执行，不允许全部为 1.0）：
   - 1.0 = 原文有明确、无歧义的直接陈述
   - 0.8-0.9 = 原文有陈述但存在少量解读空间
   - 0.6-0.7 = 从多个事实间接推导，或原文描述较模糊
   - 0.4-0.5 = 高度依赖推断，原文仅有暗示
   - 约束: 至少 30% 的 facts confidence 应 < 1.0；如果全部为 1.0 则视为提取失败
9. **总量控制**（关键要求）：
   - 总体控制在 80-120 条 facts
   - 单个模块 facts 不应超过总 Facts 的 35%（防止过度集中）
   - 如果某模块事实明显少于其他模块（<5条），在 source_reference 中标注"[需补充]"
</rules>

<output_contract>
Return ONLY the following JSON object. No markdown fences. No explanation. No preamble.

{{
  "facts": [
    {{
      "id": str,
      "source_type": "prd" | "swagger" | "changelog" | "prototype" | "architecture" | "rule" | "inferred",
      "source_reference": str,
      "quote": str,
      "subject": str,
      "action": str,
      "object": str,
      "condition": str | null,
      "outcome": str | null,
      "confidence": number,
      "status": "draft" | "confirmed" | "conflicted" | "superseded",
      "conflict_references": [str]
    }}
  ]
}}

字段约束:
- id 格式 "FACT-001", "FACT-002" ...
- confidence ∈ [0.0, 1.0]
- 如果未发现冲突，conflict_references 为空数组 []
- 未知值用空数组或 null，不编造
</output_contract>

### 产品需求文档 (PRD)
{prd_content or "未提供"}

### 接口文档 / Swagger
{api_doc_content or "未提供"}

### 变更日志 (Changelog)
{changelog_content or "未提供"}

### 原型说明
{prototype_notes or "未提供"}

### 架构文档
{architecture_notes or "未提供"}

### 规则/约束
{rules or "未提供"}
"""
    result = await safe_structured_invoke(prompt, FactExtractionResult, model_type="default")
    if result is None or not result.facts:
        print("[FactExtractor] LLM returned no usable facts, using empty list")
        get_diag_auto().dump("01_l2_fact_extraction", node="N1_fact_extractor", output=[], status="empty_fallback", raw_content=get_last_raw())
        return []

    # 后处理: 基于证据质量校准 confidence (解决 LLM 过度自信问题)
    result.facts = calibrate_facts(result.facts)

    get_diag_auto().dump("01_l2_fact_extraction", node="N1_fact_extractor",
                          output=result, status="ok",
                          facts_count=len(result.facts),
                          raw_content=get_last_raw())
    return result.facts
