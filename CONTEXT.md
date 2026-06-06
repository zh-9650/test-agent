# Project Context

Last verified against the working tree: 2026-06-06.

## Product Position

Smart Test Agent is an AI-native web testing platform. The model acts as the
tester at runtime: it reads requirements, explores the target application,
creates a structured plan, operates the browser through tools, evaluates
outcomes, persists evidence, and generates a report.

The product does not generate Playwright scripts for later maintenance.

## Current Runtime

The production path is:

1. `api/app.py` accepts a rich `task_config`.
2. Layer 1 extracts a `KnowledgeBase`, builds a `UseCaseModel`, checks rule
   coverage, and derives a lightweight `SystemModel`.
3. `agents/ui/planning_graph.py` converts the model into exploration goals,
   explores the live site, builds a `SystemMap`, extracts scenarios, and
   generates the test plan.
4. `core/runtime.py` executes each case through
   `observe -> decide -> execute -> assert -> record`.
5. `core/execution_logger.py` persists tasks and steps to PostgreSQL.
6. `core/report_builder.py` writes the HTML report.
7. FastAPI streams node and case events to React over WebSocket.

Core state and interface models live in `core/interfaces.py`. There is no
`core/state.py`.

## Implemented Capabilities

- FastAPI task, report, diagnostic, memory, stop, resume, and document helper
  endpoints.
- React pages for task creation, monitoring, reports, history, and memory.
- PostgreSQL persistence with startup table creation.
- Rich inputs: accounts, requirements, API docs, prototype URL, architecture
  docs, changelog, rules, and focus areas.
- Layer 1 knowledge and use-case modeling with structured-output fallback.
- Goal-driven exploration and live `SystemMap` generation.
- Playwright/browser-use page semantics with optional CDP resolution.
- Structured browser tools, hierarchical assertions, retry context, safety
  limits, session summaries, reports, and diagnostic JSON artifacts.
- Pytest suites for core, API, UI-agent behavior, and WebVoyager benchmarks.

## Experimental Or Conditional Features

- CDP element resolution is feature-gated.
- Parallel tool execution is disabled by default.
- Diagnostic logging is environment-controlled.
- Browser screenshots can be captured on demand.
- Browser-use alignment benchmarks are evaluation tooling, not release gates.

## Known High-Priority Problems

The current working tree is under active diagnosis. Do not describe the full
pipeline as production-stable until these are fixed and reverified:

1. `Runtime.run_stream()` and API task finalization do not yet share one
   authoritative lifecycle result.
2. A case with no reliable terminal evidence can be classified too
   optimistically.
3. Plan status, persisted counters, WebSocket completion data, and report
   totals can diverge.
4. Assertion exceptions may be converted to `inconclusive`, obscuring their
   original cause.
5. Focused runtime tests still depend on a live database and can fail with
   missing-task or closed-event-loop errors instead of remaining isolated.
6. The frontend production build succeeds, but `npm run lint` still reports
   existing explicit `any`, effect state-update, and unused-binding errors.

The next development priority is lifecycle/result accounting and diagnostic
reproduction, not broad prompt tuning.

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
