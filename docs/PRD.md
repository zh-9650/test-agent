# AI Native Testing Platform PRD

The execution contract is run-scoped: `CandidateTestCase` is the sole
maintained input and each planned case receives one terminal `CaseResult`.
Task, REST, WebSocket, frontend, and report summaries use that same result set.
Cancellation fills the denominator before completion, resume creates a new run
for non-passed cases, and report failure does not modify execution outcomes.

Status: active development
Last reconciled with code: 2026-06-18

## Problem

Traditional web automation produces scripts that teams must continuously
repair. This project instead lets an LLM test a site directly: understand the
requested behavior, inspect the live application, choose actions, evaluate the
result, and retain evidence.

## Product Goal

Given a target URL and optional product context, the platform should:

1. understand the system and its business rules as traceable facts and
   assertions;
2. explore the live UI before planning;
3. create a reviewable test asset package and test plan;
4. execute cases adaptively through browser tools;
5. stream progress and evidence;
6. persist trustworthy case outcomes;
7. generate a shareable report.

## Inputs

`target_url` is required. `task_config` may also contain:

- accounts with role, username, and password;
- PRD or requirements text and uploaded document content;
- Swagger/OpenAPI text or URL;
- UI prototype URL;
- technical architecture documentation;
- changelog or release notes;
- test rules and exclusions;
- focus areas.

Text-bearing task-config inputs may arrive as direct strings, parsed upload
payloads, or wrapper objects that carry extracted text. The backend must
normalize those values into plain text before planning and execution.

When `focus_areas` or a route-specific `target_url` is supplied, requirement
extraction, planning, exploration, and candidate-case generation must scope
themselves to the relevant module/page instead of silently expanding back to
unrelated product areas.

Planning and execution must consume relevant supplied inputs. A feature that
accepts an input but silently ignores it is incomplete.

## Current User Surfaces

The React application contains:

- task creation;
- live task monitoring;
- HTML report viewing;
- task history;
- agent memory management.

The FastAPI application currently exposes task CRUD/lifecycle, step lookup,
report lookup, diagnostic artifact lookup, memory CRUD,
document parsing, URL fetching, and task WebSocket streaming.

## Functional Requirements

### Planning

- Extract atomic requirement facts from PRD, Swagger, rules, prototype,
  architecture docs, and changelog with source evidence.
- Normalize facts into requirement assertions and keep ambiguities or
  conflicts explicit instead of silently resolving them.
- Derive exploration goals for assertions that require live evidence.
- Explore the actual target within configurable page/time limits before
  finalizing planning.
- Build a `SystemMap` and related page/action/navigation evidence from live
  exploration.
- Derive structured action and form entries from observed semantic controls,
  and derive navigation edges only from a successful grounded action followed
  by an observed canonical route change.
- Retain compact evidence references on every page, action, form, and
  navigation entry. Canonical route identity ignores query/fragment noise and
  normalizes record IDs while preserving the observed URL in evidence.
- Persist the partial task asset package before exploration and refresh it with
  the latest partial `system_map` immediately after exploration so incomplete
  exploration remains diagnosable.
- Persist goal-level exploration verdicts and measured page/action/form/
  navigation/evidence counts in the final `TestAssetPackage`, including after
  the design phase replaces the partial package.
- Convert assertions plus system evidence into test conditions, test design
  techniques, coverage items, and candidate test cases.
- Build a grounded coverage blueprint of modules, core business flows, and
  module dependencies before condition design.
- Preserve the complete candidate asset pool, then deterministically select a
  risk-driven automatic execution set from the auto-executable subset using
  `smoke`, `balanced`, or `full`. Non-auto-executable assets remain deferred
  with explicit reasons.
- Defer browser-console JavaScript, direct POST/PUT-style requests, illegal
  API-call integrity checks, and write-operation API probes when the active
  executor only supports browser UI actions.
- Defer cases whose oracle requires unavailable upstream/reference datasets,
  including `九宫格` region-to-label mapping or calibrated-score source
  comparison, instead of executing them as browser-only cases.
- Defer department plan scope checks, progress formulas based on hidden
  completion/total counts, and empty/unique participation data-state scenarios
  unless the executor can access the required reference dataset or create the
  required state.
- Treat progress-bar percentage formula checks and 0%/100% boundary states as
  reference/setup-dependent when the browser page does not expose the source
  completion and total-count evidence.
- Treat department-vs-global dataset comparisons and progress data-source
  isolation checks as reference-dataset audits, not browser-UI automation.
- Defer zero-data dashboard states without data setup, selected-project scope
  checks without reference data, and grid/chart rendering or `九宫格形式`
  checks without a stronger visual oracle.
- Defer displayed-count comparisons against underlying inventory data, and
  unfinished/all-complete progress boundaries without explicit data setup.
- Produce a traceability matrix that links facts, assertions, conditions,
  coverage items, candidate cases, and manual review items.
- Continue to support URL-only smoke testing.

### Execution

- Observe the current page before each decision.
- Send compact semantic page information rather than raw DOM.
- Express actions through registered tools.
- Resolve semantic element IDs by unique role/text before XPath fallback.
- Treat tag-prefixed semantic references such as `button#3` or `select#13` as
  agent-facing element IDs when they exist in the current semantic page map.
- Support structured select-control interaction through `select_option`, and
  allow execution to rewrite a mistaken click on a concrete `<option>` into a
  parent-select choice when that is the grounded control.
- Detect URL, element, error, network, modal, and page-state changes.
- Use deterministic URL/title/heading/modal/error evidence before semantic LLM
  assertion, and persist the matched terminal reason in report evidence.
- Persist locator observability in case evidence, including locator success and
  failure counts, failure reasons, and semantic extraction source, so backend
  changes such as CDP defaults are driven by measured data.
- Preserve compact semantic evidence for child frames, open shadow roots, and
  all tabs in the active browser context.
- Preserve actionable complex-form metadata for textarea, select, checkbox,
  radio, and file-upload controls. File inputs must remain discoverable when a
  custom upload UI hides the native input but browser automation can still set
  its files directly.
- Use deterministic DOM attribute inspection for assertions that explicitly
  depend on editability or `contenteditable` state, instead of requiring the
  LLM to drive browser-console workflows.
- For formula-style dashboard assertions, label visibility alone is not enough
  for deterministic success; the runtime must compare numeric target and source
  values when those values are available, and fail deterministically on a
  mismatch.
- Treat read-only dashboard assertions as prohibiting business write actions,
  not ordinary navigation, filtering, role switching, or view switching
  controls.
- Enforce runtime action guardrails for navigation, selector scope, and wait
  duration so unsupported browser-chrome or cross-origin actions fail fast.
- Enforce configurable step and failure safety limits.
- Enforce exploration page/time limits across the complete exploration session.
- Ground exploration actions in a bounded semantic page snapshot with actual
  element IDs; omit input values from that decision context.
- Preserve meaningful page evidence from exploration even when no strict
  exploration goal reaches `found`, and only treat exploration as failed when
  no usable live page evidence was captured.
- Retry failed cases with captured failure context, including blocked actions,
  selector ambiguity, and attempt-level timeouts.
- Reset browser state between cases/retries when required.
- Produce exactly one terminal result per planned case.
- Treat execution targets as soft limits: mandatory core-flow, critical
  dependency, core-module, high-risk, and permission obligations may exceed a
  balanced target. Smoke is capped at 30; full executes the complete
  auto-executable pool.

Terminal case states are:

- `passed`
- `failed`
- `skipped`
- `incomplete`
- `human_review_required`

### Monitoring

- Stream page, reasoning, action, assertion, retry, warning, progress, and
  completion events over WebSocket.
- Keep event payloads consistent with persisted and reported state.
- Allow a running task to be stopped.

### Persistence And Reports

- Persist tasks, steps, reports, and domain-scoped memory in PostgreSQL.
- Create the database/tables during startup for this phase; no migration
  workflow is required yet.
- Store screenshots as files rather than large database blobs.
- Report planned, executed, passed, failed, incomplete, skipped, and
  human-review counts without collapsing categories.
- Show the complete asset-pool count separately from the run's planned count.
- Include execution evidence and AI summary in HTML reports.

### Diagnostics

- Write per-task stage artifacts under `data/diag/{task_id}/` when enabled.
- Redact credentials, tokens, cookies, and authorization values.
- Flush pending writes before task shutdown.
- Store screenshot paths or metadata, not base64 images.

## Architecture Constraints

- LangGraph owns planning and execution flow.
- LangChain model and tool abstractions are used inside nodes.
- Playwright/browser-use owns browser interaction.
- PostgreSQL is used in all environments.
- Prompts are Chinese and their contracts are documented in
  `docs/prompt-engineering.md`.
- Shared interfaces remain in `core/interfaces.py`.
- UI-specific browser behavior stays under `agents/ui/`.

## Quality Requirements

- External behavior matters more than internal implementation details.
- Unit tests cover deterministic modules and contracts.
- Integration tests cover graph/runtime/API interactions.
- Versioned human-oracle fixtures evaluate semantic fact recall, assertion
  obligations, exploration evidence, and plan intent without requiring exact
  model wording or generated IDs.
- Human-oracle fixtures retain source hashes and annotation provenance; stale
  source snapshots must fail evaluation instead of silently reusing outdated
  labels.
- Feature completion requires the verification matrix in
  `docs/DEVELOPMENT.md`.
- Real target verification must use credentials supplied outside Git.

## Lifecycle Acceptance

Planned cases, terminal results, REST summaries, WebSocket final data, frontend
counts, and report statistics are derived from the same run-scoped
`CaseResult` collection.

## Deferred Scope

- Independent API testing agent.
- Multi-agent parallel test teams.
- Persistent LangGraph PostgreSQL checkpointer.
- Database assertions and server-log analysis.
- Mobile and native desktop testing.
- Generated Playwright/Selenium test scripts.
- Production deployment packaging.
