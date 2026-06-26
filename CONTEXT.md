# Project Context

## Authoritative Runtime

The production lifecycle is `analyzing -> exploring -> designing -> executing
-> reporting`. `RuntimeSession` owns browser resources, `CandidateTestCase` is
the only maintained execution input, and `CaseResult` is the only maintained
terminal result.

`ExecutionRun`, `CaseResult`, and attempt-aware `TaskStep` records are
persisted by `core/execution_store.py`. REST, WebSocket, React, and
`core/run_report.py` derive summaries from that same run-scoped result set.
Retry appends steps and updates one result. Cancellation fills missing results;
resume creates a new run containing only prior non-passed cases. Report failure
sets `report_status=failed` without changing execution outcomes.

The former `TestCase`, `TestResult`, `run()`, `run_stream()`, planning graph,
execution graph, incremented task counters, and retry-time step deletion have
been removed.

Last verified against the working tree: 2026-06-18.

## Product Position

Smart Test Agent is an AI-native web testing platform. The model acts as the
tester at runtime: it reads requirements, explores the target application,
creates a structured plan, operates the browser through tools, evaluates
outcomes, persists evidence, and generates a report.

The product does not generate Playwright scripts for later maintenance.

The primary analysis contract is `RequirementFact` → `RequirementAssertion`
→ `ExplorationGoal` → `SystemMapEvid` → `CoverageBlueprint` → `TestCondition` → `TestDesignTechnique`
→ `CoverageItem` → `CandidateTestCase` → `TraceabilityMatrix` → `TestAssetPackage`.

`TestAssetPackage.candidate_cases` is the complete grounded asset pool.
Execution uses a deterministic `smoke`, `balanced`, or `full` selector over
the auto-executable subset and stores the selected/deferred decision plus
deferral reasons in `runtime_hints.execution_selection`. Cases that require
unsupported browser capabilities remain in the package but do not enter the
automatic execution run.
`ExecutionRun.candidate_case_ids` contains only the cases actually planned for
that run. Resume retries only non-passed cases from the prior run.

## Current Runtime

The production path is:

1. `api/app.py` accepts a rich `task_config` and schedules
   `core/task_lifecycle.py`.
2. `TaskLifecycleService` enriches inputs and owns phase transitions.
3. Layer 1 derives facts, assertions, and strict exploration goals.
4. `RuntimeSession.explore()` collects live `SystemMapEvid`.
5. Layer 2 designs and quality-gates `CandidateTestCase[]`.
6. `RuntimeSession.execute()` runs selected cases inside an `ExecutionRun`.
7. `core/execution_store.py` persists one `CaseResult` per run/case and keeps
   all attempt-aware steps.
8. `core/run_report.py` builds the run-scoped report from persisted authority.
9. FastAPI sends phase, case, step, and one final session event to React.

Core state and interface models live in `core/interfaces.py`. There is no
`core/state.py`.

## Implemented Capabilities

- FastAPI task, report, diagnostic, memory, stop, resume, and document helper
  endpoints.
- React pages for task creation, monitoring, reports, history, and memory.
- PostgreSQL persistence with startup table creation.
- Rich inputs: accounts, requirements, API docs, prototype URL, architecture
  docs, changelog, rules, and focus areas.
- Primary Layer 2 pipeline: `RequirementFact` → `RequirementAssertion` →
  `ExplorationGoal` → test conditions → coverage → candidate cases →
  `TraceabilityMatrix` → `TestAssetPackage` with review gate for high-risk
  assertions;
- Goal-driven exploration and live `SystemMap` generation.
- Long requirement documents are split at Markdown headings, optionally
  narrowed by `focus_areas`/route terms before fact extraction, and processed
  in bounded concurrent fact/assertion batches. Merged IDs and references are
  normalized globally; partial batch failures fail analysis.
- Fact extraction has no minimum output quota and excludes document purpose,
  test instructions, examples, and agent execution constraints from product
  requirements. Assertion derivation may return zero and must not invent
  inverse behavior.
- Playwright/browser-use page semantics with optional CDP resolution.
- Structured browser tools, hierarchical assertions, retry context, safety
  limits, session summaries, reports, and diagnostic JSON artifacts.
- Runtime resolves semantic element IDs by unique role/text before XPath and
  checks stable URL/title/heading/modal/error evidence before invoking semantic
  terminal judgment.
- Runtime browser tool names and prompt examples are generated from
  `core/runtime_tool_contract.py`; tests compare that contract with the
  `BrowserAction` schema so prompt/tool drift is caught automatically.
- Runtime records locator/CDP observability in terminal case evidence:
  locator attempts, success strategy, failure reason, failure rate, and semantic
  extraction source (`cdp`, browser session, or Playwright fallback). This gives
  a measured baseline before changing the default locator backend.
- Page semantics also extracts compact read-only `visible_texts` from visible
  non-interactive content, so dashboards and card-heavy pages expose evidence
  even when the target text is not part of a clickable control.
- Page semantics exposes compact iframe and open-shadow-root summaries,
  multi-tab state, textarea controls, file inputs, and structured form-field
  metadata. Real Chromium fixtures cover both the CDP path and the Playwright
  fallback so difficult browser surfaces remain observable without
  product-specific navigation logic.
- `core/human_oracle.py` evaluates persisted test asset packages against
  versioned human semantic expectations for facts, assertions, exploration
  evidence, and candidate-plan intent. Oracle source hashes prevent stale
  labels, and one-to-one matching prevents one aggregated artifact from
  satisfying multiple atomic expectations.
- Runtime can deterministically inspect DOM editability for
  `contenteditable`-style assertions on the target route, so attribute-boundary
  cases no longer need to fail just because the LLM lacks a browser-console
  tool.
- Structured LLM recovery tolerates provider-emitted JSON-ish list fields,
  including stringified, partially truncated, or partially malformed item
  lists, so one broken list item is less likely to fail the whole analysis
  chunk.
- Candidate-case recovery also normalizes non-string `input_data` text fields
  such as `placeholder`, `value`, and related metadata when a model emits
  lists or numbers, so one malformed placeholder does not fail the entire case
  generation batch. The same recovery path now reuses an already-declared
  single `required_roles` entry for malformed `account_role` preconditions,
  and otherwise downgrades the unresolved role requirement into a
  non-agent-satisfiable review gate instead of failing the whole batch.
- Condition recovery rewrites misplaced `condition_type="e2e"` outputs into
  `branch_type="e2e"` plus a valid functional condition type, and condition
  analysis deterministically backfills one positive condition for any
  non-blocked assertion that would otherwise fail the quality gate.
- Condition analysis also deterministically backfills one `branch_type="e2e"`
  condition for each core business flow in the coverage blueprint when the
  model omits it, preserving the quality gate requirement without weakening the
  gate.
- Coverage recovery applies the same alias rule when a provider emits
  `coverage_dimension="e2e"`: keep `e2e` in `branch_type`, rewrite the
  dimension to a valid executable category, and preserve the batch instead of
  dropping those obligations.
- Runtime defers candidate cases that require browser devtools, page-source
  inspection, network-panel inspection, unsupported pointer gestures, direct
  HTTP-request tooling, broad reference-dataset audits, or
  non-agent-satisfiable preconditions instead of forcing them into automatic
  execution.
- Browser-console JavaScript, direct POST/PUT requests, illegal API-call
  integrity checks, and write-operation API probes are classified as requiring
  devtools or HTTP-request tooling. Browser-only execution must defer them
  rather than infer success from an unchanged UI snapshot.
- Cases that require `九宫格` region-to-label reference mapping, calibrated-score
  source comparison, or similar upstream dataset interpretation are treated as
  reference-dataset audits and deferred from automatic browser execution until
  the required oracle is available.
- Department plan scope checks, progress formulas based on hidden
  completion/total counts, and empty/unique participation data-state scenarios
  are also deferred unless those reference datasets or setup controls are
  available to the agent.
- Progress-bar percentage formula checks and 0%/100% boundary states are part
  of the same rule when the completion and total-count evidence is not exposed
  to the browser executor.
- Department-vs-global dataset comparisons and progress data-source isolation
  checks are reference-dataset audits, not browser-UI automation.
- Zero-data dashboard states require data setup; selected-project scope checks
  require reference data; grid/chart rendering and `九宫格形式` checks are
  visual review unless the executor has a stronger visual oracle.
- Assertions that compare displayed counts with underlying inventory data are
  reference-dataset audits; unfinished/all-complete progress boundaries require
  explicit data state setup.
- Runtime terminal evaluation may now finish with either pass or fail from page
  evidence alone when headings, `visible_texts`, tables, URL, or DOM checks are
  already sufficient; contradictory read-only evidence no longer needs to
  exhaust the case timeout before producing a failed result.
- Runtime no longer treats a quoted dashboard label as sufficient evidence for
  formula-style assertions. Known dashboard count formulas require numeric
  evidence for the target card and its source labels before deterministic pass;
  mismatched sums produce deterministic failure.
- Runtime now supports structured select controls through `select_option`, and
  a mistaken click on a concrete `<option>` may be rewritten to a parent
  `<select>` choice before the attempt burns through repeated visibility
  timeouts.
- Runtime resolves semantic element IDs even when the model prefixes them with
  a tag name such as `button#3` or `select#13`, avoiding invalid CSS-selector
  failures for agent-facing element references.
- Runtime blocks `view-source:` and browser-chrome navigation, blocks generic
  container selectors such as `body/html/document`, clamps waits, and fails
  fast on ambiguous or missing locators before repeating the same bad action.
- Runtime observation will attempt one browser-state reset when the underlying
  page/context/browser is unexpectedly closed during exploration or execution,
  reducing session-stop failures that previously aborted the phase immediately.
- Exploration now retains page-map evidence from every meaningful live page
  observation, not only from goals that reach `found`, and the task-level
  `analysis_package` is refreshed with that partial `system_map` immediately
  after exploration. Design may continue when live page evidence exists even if
  the strict goal verdicts remain `insufficient` or `not_found`.
- Exploration deterministically promotes observed controls and forms into
  `ActionMap` and `FormMap`, and records `NavigationMap` edges when a successful
  grounded action changes the canonical page route. Every page, action, form,
  and navigation entry retains compact evidence references; query strings,
  fragments, numeric IDs, and UUID path segments do not multiply one route
  into duplicate pages.
- Exploration decisions receive a bounded, value-redacted semantic snapshot
  containing real element IDs, labels, roles, links, options, forms, frames,
  shadow roots, and tabs. The final package retains all `GoalResult` records
  and measured page/action/form/navigation/evidence counts in
  `exploration_evidence`.
- Condition and candidate-case generation now preserve source business nouns
  for labels, cards, fields, and statuses instead of silently inventing a new
  naming scheme; standard dashboard talent-label assertions are normalized back
  to the source-defined canonical label set before quality gates and execution.
- Dashboard formula case recovery normalizes drifted `明星人才卡片` and
  `核心人才卡片` wording back to the source-defined `明星/核心人才` card.
- Read-only dashboard semantics are scoped to business write operations:
  navigation, filtering, role switching, and view switching are allowed as
  non-write controls, while create/edit/delete/save/submit/modify-style
  business actions remain violations.
- Coverage keeps distinct grounded variants using
  `condition_id + coverage_dimension + variant_key`; unsupported fault
  injection scenarios do not enter the automatic candidate set.
- Pytest suites for core, API, and UI-agent behavior. Network benchmarks are
  excluded from default collection.

## Experimental Or Conditional Features

- CDP element resolution is feature-gated.
- Parallel tool execution is disabled by default.
- Diagnostic logging is environment-controlled.
- Browser screenshots can be captured on demand.
- Exploration enforces configured page and time budgets across the whole
  session, so an inflated goal set cannot multiply the per-goal limit without
  bound.
- Browser-use alignment benchmarks are evaluation tooling, not release gates.

## Current Development Focus

The P0/P1 lifecycle migration and active P2/P3 roadmap work are complete in the
maintained architecture. Current work proceeds to P4 platform growth without
weakening the single-agent lifecycle baseline.

## L1 Pipeline Improvements (2026-06-09)

Three issues identified during L1 quality analysis have been fixed:

1. **Goals priority layering**: `_goals_from_confirmed_assertions()` now maps
   assertion types to priority levels (security/data_rule/state_transition →
   high, functional/medium → medium, functional/low → low). Previously all
   goals were medium because the review gate blocked high-risk assertions.
2. **Facts confidence calibration**: Two-layer approach:
   - Prompt-level: fact_extractor.py prompt enforces confidence grading rules
   - Post-processing: `_calibrate_confidence()` adjusts confidence based on
     evidence quality (source type, quote quality, fact completeness, atomicity).
     Result: confidence<1.0 ratio improved from 0% to 74%.
3. **Review Gate optimization**: `_split_by_review_gate()` now only blocks
   security/data_rule high+auto_generated assertions (reduced拦截率 from
   ~32% to ~11%). Functional high-risk assertions pass through directly.

Tests: `tests/core/test_l2_new_pipeline.py` (17 tests, all passing).

## Confirmed Design Rules

- Read `docs/DEVELOPMENT.md` before changing code.
- Requirements define what and why; code defines how.
- Prompts are written in Chinese.
- Browser actions are tool calls, not generated scripts.
- No hardcoded product-specific login flow.
- Limits and retries are configurable safety valves.
- Secrets must never be written to source, fixtures, diagnostic output, or
  documentation.
- Feature work is incomplete without backend, frontend, WebSocket, and real
  target verification when those surfaces are affected.

## Configuration Defaults

Source-of-truth defaults come from code and `.env`, not this document.
Important variables include:

- `BACKEND_PORT` (code default: `8000`)
- `FRONTEND_PORT` (code default: `5173`)
- `START_FRONTEND`
- `DATABASE_URL`
- `ANTHROPIC_AUTH_TOKEN`
- `ANTHROPIC_BASE_URL`
- model selection variables
- `MAX_STEPS_PER_CASE`
- `MAX_CONSECUTIVE_FAILURES`
- `MAX_TEST_CASE_RETRIES`
- `MAX_CASE_ATTEMPT_SECONDS`
- `LLM_REQUEST_TIMEOUT_SECONDS`
- `LLM_MAX_RETRIES`
- phase timeout variables documented in `docs/DEVELOPMENT.md`
- `MAX_EXPLORE_PAGES`
- `MAX_EXPLORE_MINUTES`
- `L2_USE_CDP`
- `L2_PARALLEL_TOOLS`
- diagnostic logging variables documented in `docs/DEVELOPMENT.md`

## Documentation Authority

- `README.md`: project entry point.
- `docs/DEVELOPMENT.md`: developer workflow, architecture map, verification,
  and documentation maintenance policy.
- `docs/PRD.md`: product scope and acceptance expectations.
- `docs/master-roadmap.md`: current priorities only.
- `docs/prompt-engineering.md`: prompt and inter-node contracts.
- `docs/business_workflow.md`: business workflow reference.
- `docs/benchmark/`: retained benchmark evidence.

Historical handoffs, daily devlogs, and completed phase plans are intentionally
not kept in the repository. Git history is the archive.
