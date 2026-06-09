# M1 L1 Contract Quality Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement M1: unify Review Gate semantics, introduce strict exploration goals, add source registry/deterministic quality gates, and update authoritative documentation.

**Architecture:** M1 stays inside the analysis pipeline and does not refactor Runtime execution. It adds strict, validated contracts around existing L1/L2 outputs while preserving legacy adapters at the boundary. Deterministic quality gates run on `TestAssetPackage` artifacts and catch invalid references, missing strict goal fields, unsupported source anchors, and Review Gate drift.

**Tech Stack:** Python 3.11, Pydantic, pytest, FastAPI project conventions, existing `core/interfaces.py`, `core/skills/l2_pipeline.py`, `core/skills/traceability_builder.py`.

---

## File Structure

- Modify: `core/interfaces.py`
  - Add `SourceAnchor`, strict `ExplorationGoal` fields, `QualityGateFinding`, `QualityGateReport`.
  - Keep legacy compatibility explicit through optional fields and adapter functions in pipeline, not silent core assumptions.
- Modify: `core/skills/l2_pipeline.py`
  - Make Phase 1 and Phase 2 call the same `_split_by_review_gate()`.
  - Generate strict exploration goals with IDs, assertion refs, expected evidence, stop condition, and source refs.
- Create: `core/skills/quality_gates.py`
  - Deterministic validation for references, strict goals, source anchors, blocked assertions, and traceability dangling refs.
- Modify: `core/skills/asset_packager.py`
  - Run deterministic quality gates when assembling a package and persist the report in `runtime_hints`.
- Modify: `core/skills/traceability_builder.py`
  - Ensure blocked high-risk assertions can remain visible as `human_review` rows instead of disappearing from coverage denominator.
- Modify: `tests/core/test_l2_new_pipeline.py`
  - Add Review Gate consistency and strict goal generation tests.
- Create: `tests/core/test_quality_gates.py`
  - Unit tests for deterministic quality gates.
- Modify: `tests/core/test_traceability_builder.py`
  - Add blocked assertion visibility test.
- Modify docs:
  - `docs/L1质量标准.md`
  - `docs/business_workflow.md`
  - `docs/ai-development-guide.md`
  - `docs/master-roadmap.md`
  - Design spec already updated: `docs/superpowers/specs/2026-06-09-l1-quality-runtime-contract-design.md`

---

### Task 1: Add Strict ExplorationGoal Contract

**Files:**
- Modify: `core/interfaces.py`
- Test: `tests/core/test_l2_new_pipeline.py`

- [ ] **Step 1: Write failing tests for strict goal fields**

Add to `tests/core/test_l2_new_pipeline.py`:

```python
def test_goals_from_confirmed_assertions_are_strict():
    from core.skills.l2_pipeline import _goals_from_confirmed_assertions

    assertions = [
        RequirementAssertion(
            id="ASSERT-LOGIN",
            fact_ids=["FACT-LOGIN"],
            assertion_text="用户必须能够使用有效账号登录系统",
            assertion_type="functional",
            risk_level="high",
            source_references=["FACT-LOGIN"],
        )
    ]

    goals = _goals_from_confirmed_assertions(assertions)

    assert len(goals) == 1
    goal = goals[0]
    assert goal.id.startswith("GOAL-")
    assert goal.assertion_refs == ["ASSERT-LOGIN"]
    assert goal.expected_evidence
    assert goal.stop_condition
    assert goal.source_refs == ["FACT-LOGIN"]
    assert goal.priority == "high"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m pytest tests/core/test_l2_new_pipeline.py::test_goals_from_confirmed_assertions_are_strict -q
```

Expected: FAIL because `ExplorationGoal` has no `id`, `assertion_refs`, `expected_evidence`, `stop_condition`, or `source_refs`.

- [ ] **Step 3: Extend `ExplorationGoal` model minimally**

In `core/interfaces.py`, replace the current `ExplorationGoal` class with:

```python
class ExplorationGoal(BaseModel):
    """严格探索目标。

    核心 L1/L1.5 链路要求所有字段完整。旧数据只能在读取边界通过
    adapter 显式降级，不能在核心模型内部静默生成空字符串。
    """
    schema_version: str = Field(default="exploration_goal.v2", description="Schema 版本")
    id: str = Field(description="稳定 Goal ID，如 GOAL-abc12345")
    assertion_refs: list[str] = Field(min_length=1, description="来源断言 ID 列表")
    goal: str = Field(description="要探索的业务证据目标")
    expected_evidence: list[str] = Field(min_length=1, description="期望在真实系统中观察到的证据")
    stop_condition: str = Field(description="达到何种证据即可停止探索")
    priority: Literal["high", "medium", "low"] = Field(description="探索优先级")
    source_refs: list[str] = Field(default_factory=list, description="来源 fact/source 引用")
```

- [ ] **Step 4: Update `_goals_from_confirmed_assertions()` minimal implementation**

In `core/skills/l2_pipeline.py`, update the goal append block to:

```python
        import hashlib
        normalized = f"{a.id}|{a.assertion_text}".strip().lower()
        goal_id = "GOAL-" + hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
        expected = f"页面或系统状态能证明：{a.assertion_text}"
        goals.append(ExplorationGoal(
            id=goal_id,
            assertion_refs=[a.id],
            goal=f"验证: {a.assertion_text[:80]}",
            expected_evidence=[expected],
            stop_condition=f"已观察到支持断言 {a.id} 的证据，或达到探索限制后标记 evidence_gap",
            priority=priority,
            source_refs=list(a.source_references or a.fact_ids),
        ))
```

- [ ] **Step 5: Run the focused test**

Run:

```powershell
python -m pytest tests/core/test_l2_new_pipeline.py::test_goals_from_confirmed_assertions_are_strict -q
```

Expected: PASS.

- [ ] **Step 6: Run nearby pipeline tests**

Run:

```powershell
python -m pytest tests/core/test_l2_new_pipeline.py -q
```

Expected: existing tests may fail where helper-created goals are missing required fields. Update test fixtures to provide strict fields rather than weakening the model.

---

### Task 2: Unify Review Gate in Phase 1 and Phase 2

**Files:**
- Modify: `core/skills/l2_pipeline.py`
- Test: `tests/core/test_l2_new_pipeline.py`

- [ ] **Step 1: Write failing test for precomputed Phase 2 Review Gate consistency**

Add to `tests/core/test_l2_new_pipeline.py`:

```python
@pytest.mark.asyncio
async def test_phase2_precomputed_review_gate_matches_phase1_for_functional_high():
    from core.skills.l2_pipeline import run_l2_pipeline
    from core.interfaces import TestAssetPackage

    facts = _make_sample_facts()
    assertions = [
        RequirementAssertion(
            id="ASSERT-FUNC-HIGH",
            fact_ids=["FACT-001"],
            assertion_text="用户必须能够创建采购申请单",
            assertion_type="functional",
            risk_level="high",
            review_status="auto_generated",
            source_references=["FACT-001"],
        ),
        RequirementAssertion(
            id="ASSERT-SEC-HIGH",
            fact_ids=["FACT-002"],
            assertion_text="系统必须保护审批数据权限",
            assertion_type="security",
            risk_level="high",
            review_status="auto_generated",
            source_references=["FACT-002"],
        ),
    ]

    captured_assertions = []

    async def fake_analyze_conditions(confirmed_assertions, system_map=None):
        captured_assertions.extend(confirmed_assertions)
        return []

    with patch("core.skills.condition_analyzer.analyze_conditions", new=fake_analyze_conditions):
        package = await run_l2_pipeline(
            precomputed_facts=facts,
            precomputed_assertions=assertions,
            precomputed_goals=[],
            precomputed_review_items=[],
        )

    assert isinstance(package, TestAssetPackage)
    assert [a.id for a in captured_assertions] == ["ASSERT-FUNC-HIGH"]
    assert any("ASSERT-SEC-HIGH" in item for item in package.manual_review_items)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/core/test_l2_new_pipeline.py::test_phase2_precomputed_review_gate_matches_phase1_for_functional_high -q
```

Expected: FAIL because current Phase 2 precomputed path blocks all high auto-generated assertions and does not recompute manual review items consistently.

- [ ] **Step 3: Replace Phase 2 inline gate with `_split_by_review_gate()`**

In `core/skills/l2_pipeline.py`, replace:

```python
    if precomputed_facts is not None:
        confirmed_assertions = [
            a for a in assertions
            if not (a.risk_level == "high" and a.review_status == "auto_generated")
            and a.review_status != "rejected"
        ]
    else:
        confirmed_assertions, blocked_assertions = _split_by_review_gate(assertions)
        manual_review_items = [
            f"[高风险需人工确认] {a.id}: {a.assertion_text} (源自事实: {', '.join(a.fact_ids)})"
            for a in blocked_assertions
        ]
```

with:

```python
    confirmed_assertions, blocked_assertions = _split_by_review_gate(assertions)
    manual_review_items = list(manual_review_items or [])
    existing_review_text = "\n".join(manual_review_items)
    for a in blocked_assertions:
        if a.id not in existing_review_text:
            manual_review_items.append(
                f"[高风险需人工确认] {a.id}: {a.assertion_text} (源自事实: {', '.join(a.fact_ids)})"
            )
```

- [ ] **Step 4: Run focused test**

Run:

```powershell
python -m pytest tests/core/test_l2_new_pipeline.py::test_phase2_precomputed_review_gate_matches_phase1_for_functional_high -q
```

Expected: PASS.

- [ ] **Step 5: Run full pipeline unit file**

Run:

```powershell
python -m pytest tests/core/test_l2_new_pipeline.py -q
```

Expected: PASS after strict goal fixture updates.

---

### Task 3: Add Source Registry Models

**Files:**
- Modify: `core/interfaces.py`
- Test: `tests/core/test_quality_gates.py`

- [ ] **Step 1: Create failing model test**

Create `tests/core/test_quality_gates.py` with:

```python
from __future__ import annotations

from core.interfaces import RequirementFact, RequirementAssertion, ExplorationGoal, TestAssetPackage


def test_source_anchor_model_supports_grounding_fields():
    from core.interfaces import SourceAnchor

    anchor = SourceAnchor(
        source_id="SRC-001",
        source_type="prd",
        content_hash="abc123",
        path_or_url="requirements.md",
        start_offset=10,
        end_offset=20,
        quote="用户可以登录",
        quote_hash="def456",
    )

    assert anchor.schema_version == "source_anchor.v1"
    assert anchor.source_id == "SRC-001"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/core/test_quality_gates.py::test_source_anchor_model_supports_grounding_fields -q
```

Expected: FAIL because `SourceAnchor` does not exist.

- [ ] **Step 3: Add `SourceAnchor` to interfaces**

In `core/interfaces.py`, before `RequirementFact`, add:

```python
class SourceAnchor(BaseModel):
    """可审计来源锚点，用于 groundedness 和 Source Registry。"""
    schema_version: str = Field(default="source_anchor.v1", description="Schema 版本")
    source_id: str = Field(description="来源 ID，如 SRC-001")
    source_type: Literal["prd", "swagger", "changelog", "prototype", "architecture", "rule", "inferred"] = Field(description="来源类型")
    content_hash: str = Field(description="来源内容 hash")
    path_or_url: str = Field(default="", description="来源路径或 URL")
    section: str | None = Field(default=None, description="章节、页码或段落")
    start_offset: int | None = Field(default=None, description="quote 在来源内容中的起始 offset")
    end_offset: int | None = Field(default=None, description="quote 在来源内容中的结束 offset")
    quote: str = Field(default="", description="原文引用")
    quote_hash: str = Field(default="", description="quote hash")
```

Then add to `TestAssetPackage`:

```python
    source_registry: list[SourceAnchor] = Field(default_factory=list)
```

- [ ] **Step 4: Run source model test**

Run:

```powershell
python -m pytest tests/core/test_quality_gates.py::test_source_anchor_model_supports_grounding_fields -q
```

Expected: PASS.

---

### Task 4: Implement Deterministic Quality Gates

**Files:**
- Create: `core/skills/quality_gates.py`
- Modify: `core/interfaces.py`
- Test: `tests/core/test_quality_gates.py`

- [ ] **Step 1: Add failing quality gate tests**

Append to `tests/core/test_quality_gates.py`:

```python
def _strict_goal() -> ExplorationGoal:
    return ExplorationGoal(
        id="GOAL-1",
        assertion_refs=["ASSERT-1"],
        goal="验证登录",
        expected_evidence=["看到首页"],
        stop_condition="看到首页后停止",
        priority="high",
        source_refs=["FACT-1"],
    )


def test_quality_gate_detects_invalid_goal_assertion_ref():
    from core.skills.quality_gates import run_quality_gates

    package = TestAssetPackage(
        facts=[RequirementFact(
            id="FACT-1", source_type="prd", source_reference="SRC-1",
            quote="用户可以登录", subject="用户", action="登录", confidence=1.0,
        )],
        assertions=[],
        exploration_goals=[_strict_goal()],
    )

    report = run_quality_gates(package)

    assert not report.passed
    assert any(f.code == "dangling_goal_assertion_ref" for f in report.findings)


def test_quality_gate_passes_valid_minimal_package():
    from core.interfaces import SourceAnchor
    from core.skills.quality_gates import run_quality_gates

    package = TestAssetPackage(
        source_registry=[SourceAnchor(
            source_id="SRC-1", source_type="prd", content_hash="hash",
            path_or_url="requirements.md", quote="用户可以登录", quote_hash="qh",
        )],
        facts=[RequirementFact(
            id="FACT-1", source_type="prd", source_reference="SRC-1",
            quote="用户可以登录", subject="用户", action="登录", confidence=1.0,
        )],
        assertions=[RequirementAssertion(
            id="ASSERT-1", fact_ids=["FACT-1"], assertion_text="用户必须可以登录",
            assertion_type="functional", risk_level="high", source_references=["FACT-1"],
        )],
        exploration_goals=[_strict_goal()],
    )

    report = run_quality_gates(package)

    assert report.passed
    assert report.findings == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/core/test_quality_gates.py -q
```

Expected: FAIL because `QualityGateReport` and `run_quality_gates` do not exist.

- [ ] **Step 3: Add quality gate report models**

In `core/interfaces.py`, before `TestAssetPackage`, add:

```python
class QualityGateFinding(BaseModel):
    """确定性质量门发现。"""
    code: str = Field(description="机器可读问题代码")
    severity: Literal["error", "warning"] = Field(default="error", description="严重程度")
    message: str = Field(description="可读说明")
    artifact_type: str = Field(default="", description="产物类型")
    artifact_id: str = Field(default="", description="产物 ID")


class QualityGateReport(BaseModel):
    """确定性质量门报告。"""
    schema_version: str = Field(default="quality_gate_report.v1", description="Schema 版本")
    passed: bool = Field(description="是否通过所有 error 级质量门")
    findings: list[QualityGateFinding] = Field(default_factory=list)
```

Add to `TestAssetPackage`:

```python
    quality_gate_report: QualityGateReport | None = Field(default=None)
```

- [ ] **Step 4: Create `quality_gates.py`**

Create `core/skills/quality_gates.py`:

```python
"""Deterministic quality gates for L1/L2 analysis artifacts."""
from __future__ import annotations

from core.interfaces import QualityGateFinding, QualityGateReport, TestAssetPackage


def _finding(code: str, message: str, artifact_type: str = "", artifact_id: str = "") -> QualityGateFinding:
    return QualityGateFinding(
        code=code,
        severity="error",
        message=message,
        artifact_type=artifact_type,
        artifact_id=artifact_id,
    )


def run_quality_gates(package: TestAssetPackage) -> QualityGateReport:
    """Run deterministic, non-LLM quality gates on a TestAssetPackage."""
    findings: list[QualityGateFinding] = []

    fact_ids = {f.id for f in package.facts}
    assertion_ids = {a.id for a in package.assertions}
    source_ids = {s.source_id for s in package.source_registry}

    for fact in package.facts:
        if fact.source_type != "inferred" and fact.source_reference and source_ids:
            if fact.source_reference not in source_ids:
                findings.append(_finding(
                    "invalid_fact_source_reference",
                    f"Fact {fact.id} references missing source {fact.source_reference}",
                    "RequirementFact",
                    fact.id,
                ))
        if fact.source_type != "inferred" and not fact.quote:
            findings.append(_finding(
                "missing_fact_quote",
                f"Fact {fact.id} has no quote",
                "RequirementFact",
                fact.id,
            ))

    for assertion in package.assertions:
        for fid in assertion.fact_ids:
            if fid not in fact_ids:
                findings.append(_finding(
                    "dangling_assertion_fact_ref",
                    f"Assertion {assertion.id} references missing fact {fid}",
                    "RequirementAssertion",
                    assertion.id,
                ))

    for goal in package.exploration_goals:
        if not goal.id:
            findings.append(_finding("missing_goal_id", "Goal has no id", "ExplorationGoal"))
        if not goal.expected_evidence:
            findings.append(_finding(
                "missing_goal_expected_evidence",
                f"Goal {goal.id} has no expected_evidence",
                "ExplorationGoal",
                goal.id,
            ))
        if not goal.stop_condition:
            findings.append(_finding(
                "missing_goal_stop_condition",
                f"Goal {goal.id} has no stop_condition",
                "ExplorationGoal",
                goal.id,
            ))
        for aid in goal.assertion_refs:
            if aid not in assertion_ids:
                findings.append(_finding(
                    "dangling_goal_assertion_ref",
                    f"Goal {goal.id} references missing assertion {aid}",
                    "ExplorationGoal",
                    goal.id,
                ))

    passed = not any(f.severity == "error" for f in findings)
    return QualityGateReport(passed=passed, findings=findings)
```

- [ ] **Step 5: Run quality gate tests**

Run:

```powershell
python -m pytest tests/core/test_quality_gates.py -q
```

Expected: PASS.

---

### Task 5: Attach Quality Gate Report During Packaging

**Files:**
- Modify: `core/skills/asset_packager.py`
- Test: `tests/core/test_quality_gates.py`

- [ ] **Step 1: Inspect package assembly function**

Open `core/skills/asset_packager.py` and locate `assemble_package(...)`. The implementation should return `TestAssetPackage(...)`.

- [ ] **Step 2: Add failing test**

Append to `tests/core/test_quality_gates.py`:

```python
def test_asset_packager_attaches_quality_gate_report():
    from core.skills.asset_packager import assemble_package

    package = assemble_package(
        facts=[RequirementFact(
            id="FACT-1", source_type="prd", source_reference="",
            quote="用户可以登录", subject="用户", action="登录", confidence=1.0,
        )],
        assertions=[RequirementAssertion(
            id="ASSERT-1", fact_ids=["FACT-1"], assertion_text="用户必须可以登录",
            assertion_type="functional", risk_level="high",
        )],
        exploration_goals=[_strict_goal()],
    )

    assert package.quality_gate_report is not None
    assert package.quality_gate_report.passed
    assert package.runtime_hints["quality_gate_passed"] is True
```

- [ ] **Step 3: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/core/test_quality_gates.py::test_asset_packager_attaches_quality_gate_report -q
```

Expected: FAIL because package does not attach a quality gate report.

- [ ] **Step 4: Update `assemble_package`**

In `core/skills/asset_packager.py`, before returning the package, do:

```python
    from core.skills.quality_gates import run_quality_gates

    package = TestAssetPackage(
        facts=facts,
        assertions=assertions,
        exploration_goals=exploration_goals,
        exploration_evidence=exploration_evidence,
        system_map=system_map,
        test_conditions=test_conditions,
        test_design_techniques=test_design_techniques,
        coverage_items=coverage_items,
        candidate_cases=candidate_cases,
        traceability_matrix=traceability_matrix,
        ambiguities=ambiguities,
        conflicts=conflicts,
        manual_review_items=manual_review_items,
        runtime_hints=dict(runtime_hints or {}),
    )
    report = run_quality_gates(package)
    package.quality_gate_report = report
    package.runtime_hints["quality_gate_passed"] = report.passed
    package.runtime_hints["quality_gate_error_count"] = sum(1 for f in report.findings if f.severity == "error")
    return package
```

Keep existing arguments and defaults from the current function; only change the return construction.

- [ ] **Step 5: Run quality gate tests**

Run:

```powershell
python -m pytest tests/core/test_quality_gates.py -q
```

Expected: PASS.

---

### Task 6: Keep Blocked Assertions Visible in Traceability

**Files:**
- Modify: `core/skills/traceability_builder.py`
- Test: `tests/core/test_traceability_builder.py`

- [ ] **Step 1: Add failing test**

Append to `tests/core/test_traceability_builder.py`:

```python
    def test_blocked_high_risk_assertion_is_human_review_not_removed(self):
        facts = [_make_fact("FACT-001")]
        assertions = [RequirementAssertion(
            id="ASSERT-SEC-001",
            fact_ids=["FACT-001"],
            assertion_text="系统必须限制未授权访问",
            assertion_type="security",
            risk_level="high",
            review_status="auto_generated",
        )]

        matrix = build_traceability(facts, assertions, [], [], [], [])

        assert len(matrix.rows) == 1
        assert matrix.rows[0].status == "human_review"
        assert matrix.rows[0].assertion_ids == ["ASSERT-SEC-001"]
```

- [ ] **Step 2: Run test**

Run:

```powershell
python -m pytest tests/core/test_traceability_builder.py::TestBuildTraceability::test_blocked_high_risk_assertion_is_human_review_not_removed -q
```

Expected: The current implementation likely already passes for high-risk assertions. If it passes, keep it as regression coverage.

- [ ] **Step 3: If failing, update status logic**

In `core/skills/traceability_builder.py`, ensure status selection keeps high-risk assertions as `human_review` before partial/covered logic:

```python
        if not related_assertions:
            status = "gap"
        elif has_high_risk:
            status = "human_review"
        elif branches_with_cases >= branches_covered:
            status = "covered"
        elif branches_with_cases > 0:
            status = "partial"
        else:
            status = "partial"
```

- [ ] **Step 4: Run traceability tests**

Run:

```powershell
python -m pytest tests/core/test_traceability_builder.py -q
```

Expected: PASS.

---

### Task 7: Update Documentation Baseline

**Files:**
- Modify: `docs/L1质量标准.md`
- Modify: `docs/business_workflow.md`
- Modify: `docs/ai-development-guide.md`
- Modify: `docs/master-roadmap.md`
- Modify: `docs/superpowers/specs/2026-06-09-l1-quality-runtime-contract-design.md`

- [ ] **Step 1: Confirm docs include M1 scope**

Check these statements exist:

- `docs/L1质量标准.md`: L1 Agentic 质量补充原则 table.
- `docs/business_workflow.md`: CandidateTestCase is target authority and not UI click scripts.
- `docs/ai-development-guide.md`: StrictExplorationGoal and L4 Evidence And Oracle.
- `docs/master-roadmap.md`: M1/M2/M3 roadmap items.
- Design spec: CapabilityModel Future Work and oracle_type stays on TestCondition.

- [ ] **Step 2: Run markdown grep checks**

Run:

```powershell
python - <<'PY'
from pathlib import Path
checks = {
    'docs/L1质量标准.md': ['L1 Agentic 质量补充原则', 'Review Gate 一致性', 'Strict Goal'],
    'docs/business_workflow.md': ['CandidateTestCase is the target authority', 'goal-driven loop'],
    'docs/ai-development-guide.md': ['StrictExplorationGoal', 'L4 Evidence And Oracle', 'do not add `oracle_type`'],
    'docs/master-roadmap.md': ['M1: unify Review Gate', 'M2: split Runtime', 'M3: add durable'],
    'docs/superpowers/specs/2026-06-09-l1-quality-runtime-contract-design.md': ['CapabilityModel', 'TestCondition.oracle_type', 'EvidenceCollection'],
}
for file, needles in checks.items():
    text = Path(file).read_text(encoding='utf-8')
    missing = [n for n in needles if n not in text]
    if missing:
        raise SystemExit(f'{file} missing {missing}')
print('docs checks passed')
PY
```

Expected: `docs checks passed`.

If PowerShell heredoc fails, use:

```powershell
python -c "from pathlib import Path; checks={'docs/L1质量标准.md':['L1 Agentic 质量补充原则','Review Gate 一致性','Strict Goal'],'docs/business_workflow.md':['CandidateTestCase is the target authority','goal-driven loop'],'docs/ai-development-guide.md':['StrictExplorationGoal','L4 Evidence And Oracle','do not add `oracle_type`'],'docs/master-roadmap.md':['M1: unify Review Gate','M2: split Runtime','M3: add durable'],'docs/superpowers/specs/2026-06-09-l1-quality-runtime-contract-design.md':['CapabilityModel','TestCondition.oracle_type','EvidenceCollection']};\n[(__import__('sys').exit(f'{f} missing {[n for n in ns if n not in Path(f).read_text(encoding=\'utf-8\')]}') if [n for n in ns if n not in Path(f).read_text(encoding='utf-8')] else None) for f,ns in checks.items()]; print('docs checks passed')"
```

- [ ] **Step 3: Commit docs separately if requested by user**

Do not commit unless the user asks. If committing, include:

```text
docs: define M1 L1 contract quality gates

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

---

### Task 8: Run Focused Verification

**Files:**
- No source edits unless tests expose failures.

- [ ] **Step 1: Run focused test set**

Run:

```powershell
python -m pytest tests/core/test_l2_new_pipeline.py tests/core/test_traceability_builder.py tests/core/test_quality_gates.py -q
```

Expected: PASS.

- [ ] **Step 2: Run compile check**

Run:

```powershell
python -m compileall core tests -q
```

Expected: exit code 0.

- [ ] **Step 3: Record verification outcome in final response**

Report exact commands and whether they passed. Include warning output if any warnings are relevant.

---

## Self-Review

- Spec coverage: M1 implements Review Gate consistency, Strict Goal, Source Registry model, deterministic quality gates, traceability blocked assertion visibility, and documentation baseline. M2/M3/M4 are explicitly out of M1 and remain in the design spec.
- Placeholder scan: no TBD/TODO placeholders. Each task has concrete tests, implementation snippets, and commands.
- Type consistency: `ExplorationGoal`, `SourceAnchor`, `QualityGateFinding`, and `QualityGateReport` names are consistent across tasks.
