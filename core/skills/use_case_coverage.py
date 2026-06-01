import json
import re
from typing import Any
from pydantic import BaseModel, Field
from core.llm_client import get_llm_client, safe_structured_invoke
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

    Returns (covered, missing, coverage_rate). A rule is covered when its
    normalized form is a substring of (or contains) any normalized related rule.
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
    """
    Node 1.7: Use Case Coverage Self-Check (One-shot Refinement).
    Checks if the generated UseCaseModel covers all business rules in the KnowledgeBase.
    If not, it outputs an updated UseCaseModel and a report.
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

    llm = get_llm_client("default")

    prompt = f"""
你是一个严格的 QA 审查员。你的任务是检查"用例脚手架 (UseCaseModel)"是否完全覆盖了"知识库 (KnowledgeBase)"中的所有业务规则。

### 已提取的用例模型 (UseCaseModel)
```json
{use_case_model.model_dump_json(indent=2)}
```

### 原始业务规则 (Business Rules)
```json
{[rule.model_dump() for rule in knowledge.business_rules]}
```

请仔细对比：
是否有任何业务规则在用例模型中被遗漏了？

如果发现遗漏：
请在原有的 UseCaseModel 基础上补充缺失的 UseCase，或者修改现有的 UseCase 补充其 related_rules。
然后输出一个 CoverageResponse，包含完整的更新后的 use_case_model，以及详细的 report（说明覆盖了哪些，漏了哪些）。

如果没有遗漏：
请直接原样输出传入的 use_case_model，并在 report 中说明。

注意：不要在 report 中填写 added_use_cases 字段，我们会本地计算增量。

只返回 JSON。键名必须严格使用: use_case_model (内含 use_cases 数组), report (内含 covered_rules, missing_rules 数组)。
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
