# Business Workflow

The authoritative task phases are `analyzing`, `exploring`, `designing`,
`executing`, and `reporting`. A run has one terminal `CaseResult` per planned
candidate case. Product assertion failures remain case failures while the task
may complete; analysis, exploration, design, and execution-system failures fail
the task.

Cancellation preserves completed cases, marks the active missing case
`incomplete`, marks later cases `skipped`, and only then marks the run and task
cancelled. Resume creates a new run for previous non-passed cases. Reports read
`ExecutionRun + CaseResult + TaskStep + TestAssetPackage`; report failure never
rewrites execution results.

This document describes the intended task lifecycle at a business level. For
implementation details and known deviations, see `CONTEXT.md`.

## 1. Task Creation

The user supplies a target URL and optional accounts, requirements, API docs,
prototype link, architecture notes, changelog, constraints, and focus areas.

FastAPI stores a pending `Task` and schedules one background execution. A
global lock currently serializes browser sessions.

## 2. Input Enrichment

`core/document_parser.py` resolves supported document links and produces an
enriched `task_config`. Original input meaning must be preserved and secrets
must not be copied into prompts or diagnostic artifacts unnecessarily.

## 3. Document Understanding & Assertion Derivation

Layer 1 runs as the primary pipeline:

1. extract atomic `RequirementFact` from PRD, Swagger, changelog, prototype,
   architecture docs, and rules — each fact preserves source type, quote,
   subject/action/object, and conflict references;
2. derive `RequirementAssertion` from facts — each assertion is a verifiable
   statement with risk level and review status;
3. generate `ExplorationGoal` from high/medium risk assertions;
4. run the **review gate**: high-risk `auto_generated` assertions are blocked
   from downstream design and flagged as `manual_review_items`.

The resulting facts, assertions, and goals are the primary inputs to all
downstream stages. This partial analysis package is persisted before live
exploration so a failed exploration remains diagnosable.

## 4. Live Exploration & System Evidence

`RuntimeSession.explore()`:

1. consumes exploration goals from the analysis pipeline;
2. observes the live target application;
3. chooses grounded actions from a bounded, value-redacted semantic snapshot
   containing real element IDs, then executes them;
4. stops at configured page/time limits;
5. builds a `SystemMap` with `PageMap`, `ActionMap`, `FormMap`, and
   `NavigationMap` evidence from the observed UI.

Observed controls and forms are promoted deterministically into structured map
entries. Navigation edges are added only when a successful grounded action is
followed by a canonical route change. Page, action, form, and navigation
entries retain compact evidence references and source-page context.

Exploration must retain page evidence from every meaningful observed page, even
when a strict goal remains `insufficient` or `not_found`; the system must not
drop usable live UI evidence just because no goal reached `found`.

Exploration output is written back into the task `analysis_package` as
`SystemMapEvid` before the exploration gate decides whether the task can
continue. Goal verdicts and measured surface/evidence counts are retained in
`TestAssetPackage.exploration_evidence` through final design. The task should
fail exploration only when there are no goal results or no usable live page
evidence at all.

## 5. Test Design & Packaging

After exploration, the pipeline continues deterministically:

1. `TestCondition` — what to verify in what scenario, leveraging both
   document assertions and live `SystemMapEvid` when available;
2. `CoverageBlueprint` — grounded modules, core flows, dependencies, and
   unresolved gaps;
3. `TestDesignTechnique` — equivalence partitioning, boundary value analysis,
   error guessing, etc.;
4. `CoverageItem` — coverage obligations across normal, boundary, negative,
   exception, and risk dimensions;
5. `CandidateTestCase` — lightweight, traceable test assets (not brittle UI
   click scripts);
6. `TraceabilityMatrix` — links every fact → assertion → condition → technique
   → coverage item → candidate case;
7. `TestAssetPackage` — the final deliverable, persisted to the database
   `analysis_package` JSONB column.

High-risk `auto_generated` assertions are surfaced in `manual_review_items`
and do not enter automatic test design or execution until a human reviews and
confirms them. Blocked assertions still count in traceability coverage as
`human_review`; they must not disappear from the denominator.

`CandidateTestCase` is the target authority for new execution work. It carries
business goal, expected result, preconditions, data hints, and trace references;
it must not contain fixed UI click steps. Runtime may adapt it into an internal
runtime view, but that adapter must be lossless and must not generate a second
source of test intent.

The package retains every grounded candidate case. Before first execution a
deterministic selector records selected and deferred IDs plus reasons, and
only the auto-executable subset may enter the first `ExecutionRun`. Cases that
depend on devtools, source view, unsupported pointer gestures, or non-agent
preconditions remain deferred assets instead of being forced into automatic
execution. Resume does not reconsider deferred assets; it retries only
non-passed cases from the previous run.

For compatibility with plan checks: CandidateTestCase is the target authority.

## 6. Case Execution

The target execution lifecycle is two-stage:

1. `Runtime.explore()` consumes strict exploration goals and produces
   `ExplorationResult(SystemMapEvid, GoalResult[])`.
2. L2 design turns `SystemMapEvid` into `TestAssetPackage` and
   `CandidateTestCase[]`.
3. `Runtime.execute(candidate_cases)` executes those candidate cases through a
   goal-driven loop.

For each candidate case, Runtime:

1. applies the browser/account state policy for the case;
2. resolves structured preconditions and role requirements;
3. observes page semantics;
4. decides the next action from the case objective, expected result, execution
   hint, and current evidence;
5. executes tools;
6. collects evidence before evaluating the oracle;
7. evaluates terminal progress independently from intermediate step assertions;
8. persists step evidence with run and attempt identity;
9. records exactly one terminal result for the candidate case.

Stable URL, page-title, heading, modal, and error evidence is evaluated
deterministically before semantic terminal judgment. Semantic element IDs are
resolved by unique role/text first and XPath only as a fallback. When a case
explicitly requires DOM editability checks such as `contenteditable`, Runtime
may perform a direct deterministic DOM inspection on the live page instead of
asking the LLM to improvise browser-console actions.
For real select controls, Runtime may use a structured `select_option` action;
if the model mistakenly targets a concrete `<option>` with a click, Runtime may
rewrite that action to the parent `<select>` before consuming more retry budget.

Failed attempts may be retried with captured context, but retries must preserve
previous attempt evidence. Retry must not delete prior steps.

## 7. Completion Contract

Every planned case must produce exactly one terminal result:

- passed;
- failed;
- skipped;
- incomplete;
- human review required.

Task status, persisted summaries, WebSocket completion data, and report totals
must all be derived from the same result set.

This is the maintained production contract.

## 8. Reporting And Memory

The report combines case outcomes, steps, screenshots, assertions, coverage,
and an AI summary. Domain-scoped memory may retain useful interaction
knowledge for later tasks.

Report generation must not turn missing execution evidence into a successful
outcome.
