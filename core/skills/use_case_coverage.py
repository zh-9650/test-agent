"""core/skills/use_case_coverage.py — Node 1.7: Use Case Coverage Self-Check.

L1 Pipeline Position:
  上游: N1 KnowledgeBase + N1.5 UseCaseModel
  下游: N2 SystemModeler (用 refined UCM) + HTML 报告 (用 CoverageReport)
  本节点职责: 检查 UseCaseModel 是否覆盖了所有 business_rules,缺失时调用 LLM 补全
"""
import json
import re
from typing import Any
from pydantic import BaseModel, Field
from core.llm_client import safe_structured_invoke
from core.interfaces import KnowledgeBase, UseCaseModel


_FAST_PATH_COVERAGE_THRESHOLD = 0.9


def _normalize_for_match(s: str) -> str:
    """Strip whitespace + lowercase for fuzzy substring matching."""
    return re.sub(r"\s+", "", s).lower()


def _compute_coverage(
    rule_texts: list[str],
    related_texts: set[str],
) -> tuple[list[str], list[str], float]:
    """Pair every business rule with the closest related rule via substring match.

    A rule is covered when its normalized form is a substring of (or contains) any
    normalized related rule. Returns (covered, missing, coverage_rate).
    """
    if not rule_texts:
        return [], [], 1.0
    covered: list[str] = []
    missing: list[str] = []
    for rule in rule_texts:
        norm = _normalize_for_match(rule)
        hit = any(norm in ref or ref in norm for ref in related_texts)
        (covered if hit else missing).append(rule)
    return covered, missing, len(covered) / len(rule_texts)


def _compute_local_diff(
    before: UseCaseModel, after: UseCaseModel
) -> list[str]:
    """Compute use-case names added or modified locally (no LLM needed)."""
    original_by_name = {uc.name: uc for uc in before.use_cases}
    diff_names: list[str] = []
    for uc in after.use_cases:
        if uc.name not in original_by_name:
            diff_names.append(uc.name)
            continue
        old_uc = original_by_name[uc.name]
        if set(old_uc.related_rules) != set(uc.related_rules):
            diff_names.append(uc.name)
    return diff_names


class CoverageReport(BaseModel):
    covered_rules: list[str] = Field(default_factory=list, description="已覆盖的规则内容")
    missing_rules: list[str] = Field(default_factory=list, description="未覆盖或遗漏的规则内容")
    added_use_cases: list[str] = Field(default_factory=list, description="本次自检补全或修改的用例名称")


class CoverageResponse(BaseModel):
    use_case_model: UseCaseModel
    report: CoverageReport


async def check_use_case_coverage(knowledge: KnowledgeBase, use_case_model: UseCaseModel) -> tuple[UseCaseModel, CoverageReport]:
    """Node 1.7: Use Case Coverage Self-Check (One-shot Refinement).

    Strategy:
    1. Run fast-path substring coverage check (deterministic, no LLM cost)
    2. If ≥90% covered OR 100% covered → skip LLM, return local verdict
    3. Otherwise invoke LLM to (a) review semantically + (b) propose additions/modifications
       LLM prompt uses SEMANTIC coverage criterion (not substring) to align with human review.
    """
    if not knowledge.business_rules:
        return use_case_model, CoverageReport()

    related_texts = {
        _normalize_for_match(r)
        for uc in use_case_model.use_cases
        for r in uc.related_rules
    }
    all_rule_texts = [r.text for r in knowledge.business_rules]

    covered, missing, rate = _compute_coverage(all_rule_texts, related_texts)
    if not missing and covered:
        print(f"[UseCaseCoverage] Fast path: 100% coverage detected ({len(covered)} rules), skipping LLM check.")
        return use_case_model, CoverageReport(covered_rules=covered)
    if rate >= _FAST_PATH_COVERAGE_THRESHOLD:
        print(
            f"[UseCaseCoverage] Near-complete fast path: {rate:.0%} coverage "
            f"({len(missing)} potential gaps), skipping LLM check."
        )
        return use_case_model, CoverageReport(covered_rules=covered, missing_rules=missing)

    prompt = f"""<role>
你是一个严格的 QA 审查员。你的唯一职责是审查"用例脚手架 (UseCaseModel)"是否完整覆盖了"知识库 (KnowledgeBase)"中的所有业务规则,缺失时给出**精确**的补全方案。
</role>

<context>
你在 L1 流水线的自检位。fast-path 子串覆盖率 < 90% 才调用你(罕见情况)。
- 上游: N1 KnowledgeBase + N1.5 UseCaseModel
- 下游: N2 用你的 refined UseCaseModel 建状态机;HTML 报告 L1 卡片读你的 CoverageReport
- 你的成功定义: (1) covered ∪ missing == 所有 N1.business_rules(不漏不增);(2) refined UCM 仍满足 N1.5 的 actor / related_rules 约束
</context>

<task>
对比 UseCaseModel 与 KnowledgeBase.business_rules,**逐条**判定每条 business_rule 是否被某个 use_case.related_rules **语义覆盖**。
</task>

<rules>
1. **覆盖判定标准 (语义, 非子串)**: 一条 rule R 被 use_case UC 覆盖 = UC.related_rules 列表中存在某条文本,其**核心谓词**(主语+谓语+关键约束)与 R 语义相同。例如:
   - R: "采购金额超过 5000 元需要部门经理审批" 覆盖了"金额超过 5000 元需经理审批"(同核心谓词)
   - R: "登录失败 3 次锁定账号" 不被 "登录失败显示错误提示" 覆盖(锁定 vs 错误提示是不同动作)
2. **缺则补**: 对 missing 的 rules,新增 use_case(必须满足 N1.5 的 actor 约束:actor ∈ knowledge.roles),或把 rule 加入现有 use_case.related_rules。
3. **不要在 report 中填 `added_use_cases`**: 本字段由程序在调用方基于 name diff 自动计算,你填了会被覆盖。
4. **不要修改已有 use_case 的 name**: 程序按 name 做增量,改名会导致 diff 失效。
5. **CoT 步骤** (在 JSON 之前内部推理): 先列"哪些 rule 被覆盖、哪些没被",再列"补全方案",最后输出 JSON。
</rules>

<output_contract>
Return ONLY the following JSON object. No markdown fences. No explanation. No preamble.

{{
  "use_case_model": {{
    "use_cases": [
      {{
        "name": str,
        "actor": str,             // MUST be in knowledge.roles[].text
        "trigger": str,
        "outcome": str,
        "related_rules": [str]
      }}
    ]
  }},
  "report": {{
    "covered_rules": [str],        // 全部已覆盖 rule.text
    "missing_rules": [str]          // 全部未覆盖 rule.text(应为空数组当 100% 覆盖)
  }}
}}

字段约束:
- `covered_rules ∪ missing_rules` 应等于所有 N1.business_rules 的 text
- `use_case_model.use_cases` 数组长度 = 原始 ∪ 补全
- 不要输出 `added_use_cases`,由程序计算
</output_contract>

### UseCaseModel (待审查)
```json
{use_case_model.model_dump_json(indent=2)}
```

### KnowledgeBase.business_rules (覆盖目标)
```json
{[rule.model_dump() for rule in knowledge.business_rules]}
```
"""
    result = await safe_structured_invoke(prompt, CoverageResponse, model_type="default")
    if result is None:
        print("[UseCaseCoverage] LLM returned no usable refinement, using original model")
        return use_case_model, CoverageReport(covered_rules=covered, missing_rules=missing)
    try:
        refined = _coerce_use_case_model(result.use_case_model)
    except Exception as e:
        print(f"[UseCaseCoverage] Could not coerce refined use_case_model: {e}")
        return use_case_model, CoverageReport(covered_rules=covered, missing_rules=missing)
    diff_names = _compute_local_diff(use_case_model, refined)
    if diff_names:
        result.report.added_use_cases = diff_names
    return refined, result.report


def _coerce_use_case_model(raw: Any) -> UseCaseModel:
    """Defensive: some models serialize nested objects as JSON strings."""
    if isinstance(raw, UseCaseModel):
        return raw
    if isinstance(raw, str):
        try:
            return UseCaseModel.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[UseCaseCoverage] Could not parse string use_case_model: {e}")
    if isinstance(raw, dict):
        return UseCaseModel.model_validate(raw)
    raise ValueError(f"Unsupported use_case_model payload type: {type(raw).__name__}")
