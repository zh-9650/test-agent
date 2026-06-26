# AI Development Guide

Runtime consumes structured `CandidateTestCase.preconditions` and must not
infer roles or precondition types from natural-language keywords. Each retry
appends attempt-scoped `TaskStep` rows and updates the single run/case
`CaseResult`.

Last updated: 2026-06-16.

This document is the implementation guide for agents that will build and
verify the next-stage test-analysis pipeline for Smart Test Agent. It is meant
to be actionable by another AI without requiring conversation history.

## 0. Purpose

The product is not a test-case generator. It is an AI-native runtime testing
platform that:

1. understands business intent from source documents;
2. explores the live target before final planning;
3. converts evidence into test conditions and candidate cases;
4. executes cases adaptively through browser tools;
5. records evidence and produces a report.

The development target in this guide is the analysis-and-planning pipeline
that feeds runtime execution.

## 1. Required Reading Order

Before editing code for this area, read in this order:

1. `CONTEXT.md`
2. `docs/PRD.md`
3. `docs/business_workflow.md`
4. `docs/prompt-engineering.md`
5. `docs/master-roadmap.md`
6. `docs/DEVELOPMENT.md`

If you are changing prompt schema or node contracts, update
`docs/prompt-engineering.md` in the same change.

## 2. Current Target Architecture

The current target architecture is:

```text
Document Understanding
  -> RequirementFact
  -> RequirementAssertion
  -> ExplorationGoal
  -> Live Exploration
  -> SystemMap / PageMap / ActionMap / FormMap / NavigationMap
  -> CoverageBlueprint
  -> TestCondition
  -> TestDesignTechnique
  -> CoverageItem
  -> CandidateTestCase
  -> TraceabilityMatrix
  -> TestAssetPackage
```

## 3. Domain Terms

### 3.1 RequirementFact

An atomic, evidence-backed statement derived from PRD, Swagger, rule sets,
prototype materials, architecture documents, or changelogs.

Required properties:

- stable ID;
- source type;
- source reference;
- verbatim source quote;
- normalized subject/action/object/condition/outcome;
- confidence;
- status;
- conflict references.

Rules:

- split compound statements into atomic facts;
- preserve source evidence;
- do not collapse facts into use cases;
- do not resolve conflicts silently.

### 3.2 RequirementAssertion

A verifiable statement derived from one or more requirement facts.

Required properties:

- stable ID;
- fact reference;
- assertion text;
- assertion type;
- risk level;
- review status;
- source references.

Rules:

- assertions are what the system must verify;
- auto-generation is allowed;
- high-risk assertions require human confirmation before they feed downstream
  design;
- keep assertions separate from facts so evidence remains auditable.

### 3.3 StrictExplorationGoal

A focused request to discover evidence from the live system. The core analysis
chain uses the strict form; legacy goal dictionaries must be converted only at
explicit adapter boundaries.

Required properties:

- schema version;
- stable content-addressed ID;
- assertion references;
- goal text;
- priority;
- expected evidence;
- stop condition;
- source references.

Rules:

- goals describe evidence to find, not a route to follow;
- one goal may support multiple assertions if the evidence overlaps;
- expected evidence and stop condition are mandatory in the strict chain;
- do not silently default missing strict fields to empty strings.

### 3.4 SystemMap

The canonical live-system evidence model produced by exploration.

Required substructures:

- `PageMap`;
- `ActionMap`;
- `FormMap`;
- `NavigationMap`.

Rules:

- record visible pages, actions, fields, transitions, errors, and constraints;
- keep meaningful page evidence from every observed live page, not only from
  exploration goals that end in `found`;
- do not turn exploration into hardcoded execution scripts;
- keep the evidence concrete enough for test design.

### 3.5 TestCondition

The thing that answers: "what do we need to verify?"

Required properties:

- stable ID;
- assertion reference;
- condition type;
- statement;
- precondition;
- trigger;
- oracle;
- oracle type;
- risk level;
- measurability;
- source references.

Recommended condition types:

- `functional`
- `validation`
- `boundary`
- `permission`
- `state_transition`
- `error_handling`
- `data_rule`
- `risk_case`

Recommended oracle types:

- `ui_state`
- `api_response`
- `database`
- `business_rule`
- `network`
- `document`
- `human_review`

Rules:

- conditions are not cases;
- each assertion may split into many conditions;
- `e2e` belongs to `branch_type`, not `condition_type`; end-to-end coverage
  must still use a valid condition category such as `functional`;
- the oracle type must be explicit;
- if the oracle is not knowable yet, the condition should remain open or
  require human review.
- module, flow, dependency, and branch metadata comes from the coverage
  blueprint and is inherited by coverage items and candidate cases.

### 3.6 TestDesignTechnique

The method chosen to obtain coverage for a condition.

Recommended primary techniques:

- `equivalence_partitioning`
- `boundary_value_analysis`
- `decision_table`
- `state_transition`
- `pairwise`
- `error_guessing`
- `exploratory`
- `risk_based`

Rules:

- every condition needs at least one primary technique;
- high-risk conditions may combine techniques;
- record rationale, not just labels.

### 3.7 CoverageItem

A coverage obligation created from a condition and technique.

Recommended coverage dimensions:

- `normal`
- `boundary`
- `negative`
- `permission`
- `state`
- `exception`
- `recovery`
- `compatibility`
- `security`

Rules:

- coverage items are obligations, not counts;
- one condition may produce multiple coverage items;
- `e2e` belongs to `branch_type`, not `coverage_dimension`; end-to-end
  coverage must still use a valid dimension such as `normal`;
- each item should explain the specific risk or branch it covers.

### 3.8 CandidateTestCase

A test asset instance derived from one or more coverage items.

Required properties:

- stable ID;
- title;
- goal;
- description;
- preconditions;
- input data;
- expected result;
- priority;
- category;
- trace references;
- execution hint.

Rules:

- do not hardcode brittle UI step sequences unless the case genuinely depends
  on a known fixed path;
- keep execution hints lightweight and discovery-friendly;
- cases that require browser devtools, page-source inspection, unsupported
  pointer gestures, direct HTTP-request tooling, broad reference-dataset
  audits, or non-agent-satisfiable preconditions must remain in the package
  but be deferred from automatic execution;
- browser-console JavaScript, direct POST/PUT requests, illegal API-call
  integrity checks, and write-operation API probes are not browser-UI cases;
  defer them unless the active executor can issue those requests and inspect
  their responses directly;
- cases whose oracle depends on `九宫格` region-to-label mapping,
  calibrated-score source comparison, or other unavailable upstream/reference
  datasets must also be deferred until that oracle is available to the agent;
- department plan scope checks, progress formulas based on hidden
  completion/total counts, and empty/unique participation data-state scenarios
  also require reference data or setup controls; keep them deferred from
  browser-UI automation until that evidence exists;
- progress-bar percentage formula checks and 0%/100% boundary states follow
  the same rule when source completion and total-count evidence is not exposed
  to the browser executor;
- department-vs-global dataset comparisons and progress data-source isolation
  checks are reference-dataset audits and should not be selected as browser-UI
  automation;
- zero-data dashboard states require data setup, selected-project scope checks
  require reference data, and grid/chart rendering or `九宫格形式` checks need
  visual review unless a stronger visual oracle is available;
- displayed-count comparisons against underlying inventory data require a
  reference dataset; unfinished/all-complete progress boundaries require
  explicit data setup;
- if a provider emits an `account_role` precondition without
  `required_role`, recovery may only reuse an already-declared single
  `required_roles` entry; otherwise the unresolved role requirement must be
  downgraded to a non-agent-satisfiable review gate instead of inventing a
  role from free text;
- preserve exact business nouns from the upstream coverage item for labels,
  cards, fields, and statuses; if recovery applies a known low-risk alias
  normalization, it must move the text back toward the source vocabulary
  rather than inventing a new naming scheme;
- for dashboard formula cases, `明星人才卡片` and `核心人才卡片` are drifted
  aliases and should normalize back to the combined `明星/核心人才` card;
- the case must remain traceable to its upstream facts and assertions.

### 3.9 TraceabilityMatrix

A reviewable map from source facts to candidate cases.

Required row fields:

- fact ID;
- assertion ID;
- condition IDs;
- technique IDs;
- coverage item IDs;
- candidate case IDs;
- status;
- notes.

Rules:

- every upstream artifact must remain traceable;
- expose gaps, ambiguities, and conflicts;
- do not collapse partial coverage into a full pass.

### 3.10 TestAssetPackage

The final L1/L1.5/L2 delivery object.

It should include:

- facts;
- assertions;
- exploration goals;
- exploration evidence;
- system map;
- test conditions;
- test design techniques;
- coverage items;
- candidate cases;
- traceability matrix;
- ambiguities;
- conflicts;
- manual review items;
- runtime hints.

## 4. Pipeline Responsibilities

### 4.1 L1 Business Understanding

Input:

- PRD;
- Swagger/OpenAPI;
- rules;
- prototype notes;
- changelog;
- architecture notes.

Output:

- `RequirementFact`;
- `RequirementAssertion`;
- `ExplorationGoal`.

Rules:

- preserve source quotes;
- split atomic facts;
- derive assertions automatically;
- retain ambiguity and conflict states.

### 4.2 L1.5 Live Exploration

Input:

- `ExplorationGoal`.

Output:

- `SystemMap`;
- `PageMap`;
- `ActionMap`;
- `FormMap`;
- `NavigationMap`;
- exploration evidence.

Rules:

- exploration happens before final planning;
- exploration should fill evidence gaps from the documents;
- convert observed controls and forms deterministically into `ActionMap` and
  `FormMap`; do not require a second model call to rediscover page structure;
- add a `NavigationMap` only after a successful grounded action is followed by
  an observed canonical route change;
- retain source-page and evidence references on page, action, form, and
  navigation entries so the system map remains auditable;
- canonical page identity ignores query strings and fragments and normalizes
  numeric, UUID, and long hexadecimal record IDs;
- exploration decisions receive real semantic element IDs and control
  metadata, but no input values;
- persist the partial `system_map` back to the task package immediately after
  exploration so failed or partial runs remain diagnosable;
- persist every `GoalResult` plus measured surface/evidence counts in
  `TestAssetPackage.exploration_evidence`, and carry it through final design;
- if strict goal verdicts are inconclusive but real page evidence was captured,
  downstream design may still consume that evidence instead of treating the
  exploration as empty;
- exploration is not execution.

### 4.3 L2 Test Analysis And Design

Input:

- `RequirementAssertion`;
- `SystemMap`.

Output:

- `TestCondition`;
- `TestDesignTechnique`;
- `CoverageItem`;
- `CandidateTestCase`;
- `TraceabilityMatrix`.

Rules:

- use the live system evidence to avoid guessing;
- convert assertions into measurable conditions;
- expand conditions into coverage obligations;
- instantiate candidate cases from coverage obligations;
- if a non-rejected, non-review-blocked assertion comes back without any
  positive condition, deterministically backfill one positive `TestCondition`
  before quality gates run;
- if the coverage blueprint marks a business flow as core and the model emits
  no `branch_type="e2e"` condition for that flow, deterministically backfill
  one from the best matching positive flow condition before technique
  selection;
- for read-only or non-editable assertions, prefer measurable `ui_state`
  oracles for that deterministic positive supplement;
- for read-only/display-only assertions, scope the oracle to business write
  operations. Navigation, filtering, role switching, and view switching are
  non-write controls and should not be treated as violations by themselves;
- preserve source terminology for domain nouns such as dashboard labels, card
  names, field names, and statuses; when a known source-defined canonical set
  exists, deterministic normalization may rewrite drifted condition wording
  back to that canonical vocabulary before quality gates run;
- if the model emits candidate-case `input_data` text-like fields as arrays,
  numbers, or dicts, normalize them into strings during parsing instead of
  failing the entire batch on schema shape alone;
- keep all artifacts traceable.

### 4.4 L3 Autonomous Execution

Input:

- `CandidateTestCase`.

Output:

- execution events;
- step records;
- terminal case result.

Rules:

- follow the existing `observe -> decide -> execute -> assert -> record`
  contract;
- do not mutate candidate case semantics during execution;
- prefer structured control-specific actions such as `select_option` for real
  `<select>` widgets; if the model points at a concrete `<option>` with a
  click, execution may rewrite that to the parent select control;
- if current headings, read-only `visible_texts`, tables, URL, or stable DOM
  evidence already suffice to verify the case, do not spend additional turns
  on repeated `scroll` or `wait` actions;
- formula-style assertions need numeric evidence, not only label presence,
  before deterministic success;
- use runtime hints only as guidance.

### 4.5 L4 Evidence And Oracle

L4 is logically split into Evidence Collection and Oracle Evaluation. The first
collects what happened; the second decides whether the collected evidence
supports the expected result.

Input:

- UI state;
- DOM/AXTree evidence;
- URL state;
- network evidence;
- page changes;
- execution results;
- `TestCondition.oracle_type`;
- candidate case expected result.

Output:

- evidence records;
- oracle evaluation verdicts;
- assertion verdicts;
- step-level diagnostics.

Rules:

- do not add `oracle_type` to `RequirementAssertion`; the oracle belongs to
  `TestCondition` because one assertion can split into multiple conditions with
  different verification media;
- compatibility wording for automated checks: do not add oracle_type to
  RequirementAssertion;
- terminal case success must be based on sufficient evidence, not a passing
  intermediate step assertion;
- deterministic terminal matches must be retained in `CaseResult.evidence_refs`,
  not only used transiently for the verdict;
- locator/CDP observability must be retained in terminal case evidence:
  attempts, success strategy, failure reasons, failure rate, and semantic
  extraction source. Use this measured baseline before changing locator backend
  defaults;
- page semantics should retain compact visible read-only text evidence in
  addition to headings and interactive controls, so card-heavy dashboards can
  be evaluated without requiring every target string to be clickable;
- page semantics should expose bounded summaries for child frames, open shadow
  roots, and all tabs, plus structured metadata for complex form controls;
- preserve file inputs in the Playwright fallback even when the native control
  is visually hidden behind a custom upload button, because `set_input_files`
  can still operate on that control;
- deterministic formula checks should compare target-card numbers with their
  source-label numbers when the formula is recognized; if the numbers are
  missing, fall through to semantic judgment instead of passing on label text;
- if a case explicitly depends on DOM attribute state such as
  `contenteditable`, prefer a deterministic Playwright-side DOM inspection over
  asking the LLM to invent browser-console steps;
- terminal evaluation may conclude either pass or fail when current page
  evidence is already sufficient; contradictory page evidence should produce a
  direct failed outcome instead of waiting for the global case timeout;
- physical module splitting can wait until Runtime execution and result
  persistence seams are stable.

Rules:

- deterministic evidence first;
- semantic judgment only when evidence is insufficient;
- an exception is diagnostic evidence, not proof of success.

### 4.6 L5 Traceability And Reporting

Input:

- traceability matrix;
- execution results;
- evidence;
- coverage records.

Output:

- report data;
- gaps;
- conflicts;
- human-review items.

Rules:

- keep result counts aligned with authoritative terminal results;
- do not collapse categories;
- do not convert missing evidence into success.

## 5. Database And Persistence Guidance

The package should be persisted as a task-level analysis artifact.

Recommended persistence shape:

- task record first stores facts, assertions, source anchors, and exploration
  goals as a partial `TestAssetPackage`, then replaces it with the complete
  package after design and quality gates;
- after exploration, refresh the same task package with the latest partial
  `system_map` before deciding whether exploration produced enough evidence to
  continue;
- facts, assertions, conditions, coverage items, and candidate cases are stored
  in structured JSONB subdocuments initially;
- do not force premature normalization into many tables unless a query pattern
  requires it.

Persistence rules:

- preserve evidence hashes and source references;
- store review status and conflict status;
- keep the current live exploration evidence tied to the same task ID;
- do not store runtime-only secrets or browser snapshots as raw artifacts in
  Git.

## 6. Review Gates

Before a `TestAssetPackage` can be treated as ready:

1. every fact must have a source quote;
2. every high-risk assertion must be human confirmed;
3. every condition must have an oracle type;
4. every coverage item must have a coverage dimension and goal;
5. every candidate case must be traceable upstream;
6. conflicts and ambiguities must remain visible;
7. an empty or weak evidence set must not be promoted to a full pass;
8. the package must make it obvious what still needs human review.

## 7. Implementation Order

When building or refactoring this pipeline, implement in this order:

1. `RequirementFact`;
2. `RequirementAssertion`;
3. `ExplorationGoal`;
4. `SystemMap` evidence model;
5. `TestCondition`;
6. `TestDesignTechnique`;
7. `CoverageItem`;
8. `CandidateTestCase`;
9. `TraceabilityMatrix`;
10. `TestAssetPackage` persistence.

Do not add new abstractions before the upstream structure is stable.

## 8. Human-Oracle Evaluation

Semantic quality is calibrated against versioned fixtures under
`data/fixtures/oracles/`. Each oracle records source SHA-256 hashes,
annotation provenance, affected metrics, required semantic term groups,
forbidden claims, and plan-contract expectations.

Evaluation rules:

- compare normalized semantic terms, not exact generated wording or IDs;
- use one-to-one expectation matching so one aggregated fact or assertion
  cannot satisfy several atomic obligations;
- treat critical misses and forbidden claims as failures;
- evaluate live `SystemMapEvid` pages, actions, forms, and navigations
  separately from document facts;
- evaluate candidate-case intent, required branch types, traceability, and the
  deterministic quality-gate result;
- reject stale oracles when a source hash changes;
- change an oracle only for a source change, annotation correction, or
  evaluation-rule correction, never to accommodate the current model.

## 9. What To Avoid

- Do not hardcode UI click paths in the analysis layer.
- Do not treat coverage-as-string-match as semantic coverage.
- Do not merge facts, assertions, and conditions into one blob.
- Do not let exploration results overwrite document evidence.
- Do not move straight to report generation without a traceability matrix.

## 10. Verification Targets

The new pipeline should be considered healthy only when the following are
demonstrably true:

- facts can be traced back to source evidence;
- assertions are reviewable and do not silently absorb conflicts;
- exploration goals lead to real evidence gaps being filled;
- conditions and coverage items expand coverage beyond happy-path use cases;
- candidate cases are traceable and not brittle UI scripts;
- traceability can explain why each case exists;
- the persisted package can be consumed by later planning and runtime logic.

This document is intentionally specific enough for another AI to use as a
build guide without needing to reconstruct the product intent from chat
history.
