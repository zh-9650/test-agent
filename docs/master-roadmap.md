# Master Roadmap

Last updated: 2026-06-06.

This file contains active priorities only. Completed implementation history
belongs in Git commits, not duplicated phase documents.

## P0: Trustworthy Lifecycle And Results

1. Make `TestResult` the authoritative case outcome.
2. Ensure every planned case receives exactly one terminal result.
3. Treat empty execution, graph crashes, and assertion exceptions explicitly.
4. Align retry eligibility for `failed`, `incomplete`, and execution errors.
5. Derive final task status from authoritative results.
6. Align database counters, WebSocket final payload, and HTML report totals.
7. Add regression tests for partial execution and premature completion.
8. Reproduce one real task with diagnostic artifacts and identify the first
   divergence from a human oracle.

Exit criteria:

- planned count equals terminal result count;
- persisted totals equal report and WebSocket totals;
- no incomplete task is marked `completed`;
- regression tests cover the original failure shape.

## P1: Fast Health Checks And Frontend Contracts

1. Fix current frontend lint and type-quality errors, including explicit
   `any`, effect state updates, and unused bindings.
2. Define a fast backend test subset for routine development.
3. Add focused tests for diagnostic logger flush/redaction behavior.
4. Remove remaining debug prints from runtime hot paths.
5. Document and verify stop/resume semantics.

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

1. Establish human-oracle fixtures for Layer 1 and plan quality.
2. Add SystemModel versus SystemMap gap analysis only after evidence shows it
   is a material source of failure.
3. Evaluate plan size and executability together, not plan breadth alone.
4. Add automated traceability from input rule to planned and executed case.

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
