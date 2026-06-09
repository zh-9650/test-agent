# Master Roadmap

Last updated: 2026-06-08.

This file contains active priorities only. Completed implementation history
belongs in Git commits, not duplicated phase documents.

## P0: Trustworthy Lifecycle And Results

1. M1: unify Review Gate semantics across Phase 1 and Phase 2, introduce strict
   exploration goals, and add deterministic L1 quality gates.
2. M2: split Runtime into explicit explore/execute phases and make
   `CandidateTestCase` the authoritative execution input.
3. M3: add durable `ExecutionRun` / `CaseResult` authority, preserve retry
   attempts, and derive counters from persisted terminal results.
4. Make `TestResult` or its successor a view of the authoritative case outcome.
5. Ensure every authoritative candidate case receives exactly one terminal
   result per execution run.
6. Treat empty execution, graph crashes, assertion exceptions, and analysis
   failures explicitly.
7. Align retry eligibility for `failed`, `incomplete`, and execution errors.
8. Derive final task lifecycle status separately from test outcome summary.
9. Align database counters, WebSocket final payload, and HTML report totals.
10. Add regression tests for partial execution and premature completion.
11. Reproduce one real task with diagnostic artifacts and identify the first
   divergence from a human oracle.

Exit criteria:

- planned count equals terminal result count;
- persisted totals equal report and WebSocket totals;
- no incomplete task is marked `completed`;
- regression tests cover the original failure shape.

## P1: Fast Health Checks And Frontend Contracts

1. Define a fast backend test subset for routine development.
2. Isolate database-backed test modules so the full pytest suite can run in
   one process without global engine or event-loop contamination.
3. Remove remaining debug prints from runtime hot paths.
4. Document and verify stop/resume semantics.

Exit criteria:

- `npm run build` and `npm run lint` pass;
- the documented fast pytest command completes predictably;
- diagnostics can be enabled without changing runtime behavior.

## P2: Execution Quality

1. Compare tool schemas with prompt examples automatically.
2. Improve invalid tool-call recovery.
3. Measure locator/CDP failure rates before changing the default backend.
4. Improve final-evidence validation for completion markers.
5. Add fixtures for iframe, shadow DOM, multi-tab, file upload, and complex
   form interaction.

## P3: Planning And Model Quality

1. Establish human-oracle fixtures for requirement facts, assertions,
   exploration evidence, and plan quality.
2. Improve exploration evidence quality based on real failure data.
3. *(Completed)* Test asset coverage and executability evaluation is tracked
   through `TestAssetPackage.manual_review_items` and `TraceabilityMatrix` status.
4. *(Completed)* Automated traceability from requirement fact to candidate case
   is implemented in `core/skills/traceability_builder.py`.

## P4: Platform Growth

- Persistent LangGraph PostgreSQL checkpointer.
- Cross-task memory retrieval improvements.
- Independent API testing agent.
- Multi-agent execution.
- Additional report formats and trend analysis.
- Production deployment and security hardening.

## Decision Gates

- Make CDP the default only after benchmarked locator failure data supports it.
- Add reflection loops only after a stable case-result baseline exists.
- Expand agent count only after single-agent lifecycle accuracy is reliable.
- Add abstractions only when current modules demonstrate real duplication or
  ownership ambiguity.
