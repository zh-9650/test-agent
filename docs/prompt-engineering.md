# Prompt And Node Contracts

Last reconciled with code: 2026-06-06.

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
- Keep manual JSON extraction as a compatibility fallback.
- Unknown values must remain unknown; do not invent placeholders that look
  factual.
- Prompt output fields must match the actual downstream Pydantic model.

## Layer 1 Contracts

### Knowledge Extraction

Input: requirements, API documentation, changelog.
Output: `KnowledgeBase`.

Rules:

- preserve source and quote evidence where available;
- separate roles, entities, business rules, constraints, and raw facts;
- lower confidence when evidence is inferred rather than quoted.

### Use-Case Modeling

Input: `KnowledgeBase`.
Output: `UseCaseModel`.

Rules:

- actor must come from known roles or be explicitly marked unknown;
- use cases describe business actions, not UI clicks;
- trigger and outcome use domain language;
- related rules support coverage tracing.

### Coverage Review

Input: knowledge and use cases.
Output: refined model plus `CoverageReport`.

Rules:

- coverage is semantic, not merely substring equality;
- covered and missing rules account for the full input rule set;
- refinements must retain valid actors and stable use-case names.

### System Modeling

Input: knowledge and refined use cases.
Output: `SystemModel`.

Rules:

- transition action equals an existing use-case name;
- states are short normalized business states;
- transition endpoints exist in the containing flow;
- duplicate `(from_state, action)` transitions are removed.

### Goal Extraction

Input: use cases and system model.
Output: exploration goals.

Rules:

- one use case maps to at most one goal;
- priorities distinguish core, supporting, and peripheral behavior;
- goals describe evidence to find, not assumed navigation paths.

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

## Context Management

- Keep structured plan/results outside conversational messages.
- Preserve the system message and the most recent actionable context.
- Use token-aware trimming.
- Redact passwords and tokens before prompt construction.
- Keep failure context bounded and evidence-oriented.

## Regression Tests

Relevant suites include:

- `tests/core/test_l1_prompts.py`
- `tests/core/test_l2_prompts.py`
- `tests/agents/ui/test_planning_graph.py`
- `tests/agents/ui/test_execution_graph.py`
- `tests/core/test_system_mapper.py`

Tests should validate schemas, invariants, and observable behavior. Avoid tests
that merely freeze complete prompt wording.
