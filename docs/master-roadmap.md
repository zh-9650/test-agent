# Master Roadmap

P0 authoritative lifecycle/results and P1 frontend/test-contract work are no
longer active roadmap items. Current feature work starts at P2.

Last updated: 2026-06-18.

This file contains active priorities only. Completed implementation history
belongs in Git commits, not duplicated phase documents.

## P2: Execution Quality

1. *(Completed)* Runtime tool schemas, prompt tool lists, and prompt examples
   are compared automatically through the shared runtime tool contract.
2. *(Completed)* Invalid or empty action decisions are persisted explicitly,
   and structured action recovery uses the shared structured-output path.
3. *(Completed)* Locator/CDP failure-rate measurement is retained in case
   evidence before changing the default backend.
4. *(Completed)* Final evidence checks use deterministic stable page evidence
   before semantic judgment and retain the matched reason in case evidence.
5. *(Completed)* Real Chromium fixtures cover iframe, open shadow DOM,
   multi-tab, file upload, and complex-form semantics across CDP and
   Playwright fallback paths.

## P3: Planning And Model Quality

1. *(Completed)* Versioned human-oracle fixtures and a deterministic evaluator
   cover requirement facts, assertions, exploration evidence, and plan quality
   with source-hash and provenance checks.
2. *(Completed)* Real failure data showed page-only system maps and ungrounded
   exploration decisions. Exploration now persists evidence-backed
   page/action/form/navigation maps, goal-result summaries, canonical routes,
   and bounded value-redacted semantic decision context.
3. *(Completed)* Test asset coverage and executability evaluation is tracked
   through `TestAssetPackage.manual_review_items` and `TraceabilityMatrix` status.
4. *(Completed)* Automated traceability from requirement fact to candidate case
   is implemented in `core/skills/traceability_builder.py`.
5. *(Completed)* Planning now preserves a complete grounded candidate asset
   pool and selects deterministic smoke, balanced, or full execution sets.

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
