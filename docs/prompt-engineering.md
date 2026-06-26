# Prompt And Node Contracts

Candidate case prompts emit structured `preconditions` with explicit type,
description, role when applicable, agent satisfiability, and failure policy.
`input_data` is a list of typed data descriptors. Adapters do not guess roles
or precondition types from Chinese or English keywords.

Last reconciled with code: 2026-06-18.

Prompts are implementation contracts between graph nodes. They are written in
Chinese because the configured models perform best for this project in
Chinese.

## Standard Structure

Use the following sections where applicable:

```xml
<role>单一职责和身份</role>
<context>上游输入、下游消费者、当前任务上下文</context>
<task>本次必须完成的工作</task>
<rules>硬约束和禁止行为</rules>
<examples>少量正反例</examples>
<output_contract>结构、字段、枚举和停止条件</output_contract>
```

Do not use a large free-form prompt when a typed downstream contract exists.

## Structured Output

- Prefer `safe_structured_invoke()` with a Pydantic model.
- Treat provider-native structured output as an optimization, not an
  assumption.
- If provider parsing returns `None`, validate native tool-call arguments and
  native JSON text against the Pydantic model before issuing a second request.
- Decode JSON-encoded container fields only when the target schema declares
  the field as a list or object.
- Tolerate unescaped control characters only after strict JSON parsing fails.
- Keep manual JSON extraction as a compatibility fallback.
- Unknown values must remain unknown; do not invent placeholders that look
  factual.
- When `CandidateTestCase.preconditions[*].type == "account_role"` is missing
  `required_role`, recovery may reuse one already-declared unique
  `required_roles` value, but otherwise must downgrade the unresolved
  requirement to a review-only non-agent precondition instead of inventing a
  role from prose.
- When `CoverageItem.coverage_dimension` is emitted as `e2e`, recovery must
  move that label back to `branch_type` and rewrite the dimension to a valid
  coverage category instead of dropping the whole batch.
- Prompt output fields must match the actual downstream Pydantic model.

## L1 And Planning Contracts

### Requirement Fact Extraction

Input: requirements, API documentation, changelog, prototype, and rules.
Output: `RequirementFact` set.

Rules:

- preserve source and quote evidence wherever available;
- split compound statements into atomic facts;
- surface ambiguities, conflicts, and inferred facts explicitly;
- do not collapse facts into use cases.
- do not impose a minimum fact count; an input with no product requirement
  returns an empty fact set;
- exclude document purpose, test instructions, examples, prompt text,
  acceptance methods, and agent execution constraints from product facts;
- long inputs are split on Markdown headings and paragraph boundaries;
- chunks are analyzed with bounded concurrency, then fact IDs and conflict
  references are normalized globally;
- a missing chunk result fails analysis instead of silently reducing source
  coverage.

### Requirement Assertion Derivation

Input: `RequirementFact` set.
Output: `RequirementAssertion` set.

Rules:

- assertions are verifiable statements, not prose summaries;
- do not infer inverse behavior that the source does not state;
- do not turn testing metadata or execution constraints into product behavior;
- zero assertions is valid when the facts do not support a product obligation;
- every high-risk assertion must be reviewable by a human;
- assertions may be auto-generated, but human confirmation gates high-risk
  items before downstream design;
- keep facts and assertions separate so evidence remains auditable.
- large fact sets are grouped by source and processed in bounded batches;
- merged assertions receive globally unique IDs and retain only valid fact
  references.

### Exploration Goal Generation

Input: assertions that require live evidence.
Output: exploration goals.

Rules:

- goals describe evidence to find, not assumed navigation paths;
- priorities distinguish core, supporting, and peripheral behavior;
- one goal may support multiple assertions when the evidence overlaps.
- exploration is bounded across the whole session by `MAX_EXPLORE_PAGES` and
  `MAX_EXPLORE_MINUTES`, not only by a per-goal step limit.

### Live Exploration Evidence

Input: exploration goals.
Output: `SystemMap` and page/action/form/navigation evidence.

Rules:

- exploration fills gaps in document evidence before planning is finalized;
- record evidence about pages, actions, fields, navigation, and errors;
- `explore_decide` receives a bounded semantic snapshot with real element IDs,
  labels, roles, links, options, forms, frames, shadow roots, and tabs; it must
  ground selectors in that snapshot instead of guessing UI paths;
- omit input values from the exploration decision snapshot so passwords and
  business data are not copied into prompts;
- exploration output should be concrete enough for later test design, but not
  hardcode execution scripts.

### Test Analysis And Design

Input: requirement assertions plus live system evidence.
Output: `CoverageBlueprint`, `TestCondition`, `TestDesignTechnique`, `CoverageItem`, and
`CandidateTestCase` sets.

Rules:

- test conditions answer what to test;
- the coverage blueprint identifies only evidence-backed modules, flows, and dependencies;
- design techniques answer how to cover it;
- coverage items answer what obligation each case satisfies;
- candidate cases must stay traceable to their upstream facts and assertions;
- candidate cases must not hardcode UI click paths when the execution layer is
  expected to discover the path dynamically.

### Test Condition Analysis

Input: `RequirementAssertion` set + optional `SystemMapEvid`.
Output: `TestCondition` set.

Rules:

- conditions answer "what to verify in what scenario";
- each assertion may split into multiple conditions;
- every condition must have a concrete oracle type and measurability label;
- leverage live `SystemMapEvid` when available to ground conditions in real UI evidence;
- preserve business nouns exactly as stated in the upstream assertion for label
  names, card names, field names, and statuses; if the assertion does not
  enumerate a concrete label set, do not invent or rename one in the
  condition;
- read-only or display-only wording means "no business write action"; do not
  expand it into "no dropdowns, navigation buttons, filters, role switchers, or
  view switchers";
- every core business flow needs at least one `branch_type="e2e"` condition;
  deterministic recovery may add that condition from the best matching positive
  flow condition when the model omits it.

### Test Design Technique Selection

Input: `TestCondition` set.
Output: `TestDesignTechnique` set (deterministic or LLM-assisted).

Rules:

- every condition needs at least one primary technique;
- high-risk conditions may combine primary + supplementary techniques;
- record rationale, not just labels.

### Coverage Analysis

Input: `TestCondition` + `TestDesignTechnique`.
Output: `CoverageItem` set.

Rules:

- coverage items are obligations, not counts;
- preserve every evidence-backed variant with a stable `variant_key`;
- extra boundary, negative, exception, or recovery dimensions require explicit
  support from the source or test condition;
- do not invent network, JavaScript, third-party, or rapid-interaction fault
  injection when the source does not require it;
- each item must explain the specific risk or branch it covers.

### Candidate Case Generation

Input: `CoverageItem` set.
Output: `CandidateTestCase` set.

Rules:

- do not hardcode brittle UI step sequences;
- keep execution hints lightweight and discovery-friendly;
- preserve exact domain nouns from `CoverageItem` for labels, cards, fields,
  and statuses instead of paraphrasing them into a different naming scheme;
- for read-only/display-only coverage, expected results should reject business
  create/edit/delete/save/submit/modify actions while allowing non-write
  navigation, filtering, role switching, and view switching controls;
- browser-console JavaScript, direct POST/PUT requests, illegal API-call
  integrity checks, and write-operation API probes require HTTP/devtools
  tooling; keep them in the package but do not present them as browser-UI
  auto-executable cases;
- department plan scope checks, progress formulas based on hidden
  completion/total counts, and empty/unique participation data-state scenarios
  require reference data or setup controls; keep them as deferred assets when
  the browser executor can only inspect the UI;
- progress-bar percentage formula checks and 0%/100% boundary states must also
  be deferred unless the browser-visible evidence includes the source
  completion and total-count values;
- department-vs-global dataset comparisons and progress data-source isolation
  checks require reference data; do not present them as browser-UI
  auto-executable cases;
- zero-data dashboard states require data setup, selected-project scope checks
  require reference data, and grid/chart rendering or `九宫格形式` checks need
  visual review unless a stronger visual oracle is available;
- displayed-count comparisons against underlying inventory data require a
  reference dataset; unfinished/all-complete progress boundaries require
  explicit data setup;
- dashboard formula cases must keep source card names: use `明星/核心人才` for
  the combined card, not separate invented `明星人才卡片` or `核心人才卡片`;
- each case must remain traceable to its upstream coverage items.

### Traceability And Packaging

Output: `TraceabilityMatrix` and `TestAssetPackage`.

Rules:

- every fact, assertion, condition, coverage item, and candidate case must be
  traceable;
- ambiguities, conflicts, and manual-review items must remain visible;
- `TraceabilityMatrix` is built deterministically (no LLM call) from upstream
  ID relationships;
- `TestAssetPackage` is assembled deterministically from all pipeline outputs;
- high-risk `auto_generated` assertions are automatically surfaced as
  `manual_review_items` in the package.

## Planning Graph Contracts

The planning flow is:

`extract_goals -> explore_observe -> explore_decide -> explore_execute`

then:

`generate_system_map -> extract_scenarios -> generate_plan`

`explore_decide` must either issue a valid tool call or explicitly stop.
Exploration actions must respect the navigation firewall and configured safety
limits. `generate_plan` must use both document-derived context and observed
`SystemMap` evidence.

## Execution Graph Contracts

The execution flow is:

`observe -> decide -> execute -> assert -> record`

### Decide

Input includes the current case, current natural-language step, semantic page
information, relevant rich inputs, prior failures, action history, and safety
warnings.

Output is a registered tool call or an explicit task marker. Tool names and
argument names must exactly match the registered schemas.

### Execute

Tool failures return structured failure data. They must not disappear as plain
text that downstream nodes cannot interpret.

### Assert

Use deterministic evidence first. Invoke semantic judgment only when rules are
insufficient. Output uses `AssertionResult` and one of:

- `pass`
- `fail`
- `inconclusive`

An exception is diagnostic evidence, not proof of success.
When headings, `visible_texts`, tables, URL, or deterministic DOM checks
already provide sufficient page evidence, semantic judgment may conclude a
final pass or a final fail directly from that evidence; contradictory page
evidence must not be forced into repeated `scroll`/`wait` loops first.
Formula-style assertions must not pass only because a quoted label is visible;
when the runtime recognizes a count formula, deterministic success requires
numeric evidence for the target and its source labels.

### Record

Persist the action, arguments, result, screenshot reference, change report,
assertion, reasoning chain, token count, and duration where available.

## Tool Schema Discipline

When adding or changing a tool:

1. update the function schema;
2. update prompt examples using that tool;
3. add a schema/behavior test;
4. verify invalid arguments produce actionable structured feedback;
5. update `docs/DEVELOPMENT.md` only if the developer workflow changes.

Known schema mismatches such as omitted required arguments or renamed argument
keys must be fixed at the contract boundary, not patched through prompt
guessing alone.

Runtime browser prompts must use `core/runtime_tool_contract.py` for tool names
and examples. Regression tests must compare that shared contract with the
`BrowserAction` schema so adding, removing, or renaming a runtime tool cannot
silently leave stale prompt text behind.

## Context Management

- Keep structured plan/results outside conversational messages.
- Preserve the system message and the most recent actionable context.
- Use token-aware trimming.
- Redact passwords and tokens before prompt construction.
- Keep failure context bounded and evidence-oriented.

## Regression Tests

Relevant suites include:

- `tests/core/test_runtime.py`
- `tests/core/test_l2_new_pipeline.py`
- `tests/core/test_system_mapper.py`
- `tests/core/test_l2_new_pipeline.py` — new L2 pipeline schema and invariant tests
- `tests/core/test_fact_extractor.py` — RequirementFact extraction
- `tests/core/test_assertion_deriver.py` — RequirementAssertion derivation
- `tests/core/test_traceability_builder.py` — deterministic traceability logic

Tests should validate schemas, invariants, and observable behavior. Avoid tests
that merely freeze complete prompt wording.
