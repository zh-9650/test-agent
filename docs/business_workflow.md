# Business Workflow

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

## 3. Cognitive Modeling

Layer 1 executes:

1. knowledge extraction;
2. use-case modeling;
3. use-case coverage checking;
4. system state modeling.

The resulting knowledge, coverage report, and system model are retained in
`task_config` for downstream planning and reporting.

## 4. Live Exploration And Planning

The planning graph:

1. extracts exploration goals;
2. observes the target;
3. chooses and executes exploration actions;
4. stops at configured page/time limits;
5. builds a `SystemMap` from observed evidence;
6. extracts business scenarios;
7. generates a structured test plan and reusable setups.

Planning must combine document intent with actual UI evidence. It must not
invent an executable path only because the PRD describes one.

## 5. Case Execution

For each planned case, Runtime:

1. resets browser state when required;
2. executes preconditions;
3. observes page semantics;
4. asks the model for one or more tool calls;
5. executes tools;
6. records deterministic changes;
7. performs hierarchical assertion;
8. persists the step;
9. continues or stops through safety rules.

Failed attempts may be retried with captured context. After retry exhaustion,
the case requires human review.

## 6. Completion Contract

Every planned case must produce exactly one terminal result:

- passed;
- failed;
- skipped;
- incomplete;
- human review required.

Task status, persisted counters, WebSocket completion data, and report totals
must all be derived from the same result set.

This contract is not fully satisfied by the current implementation and is the
active P0 roadmap item.

## 7. Reporting And Memory

The report combines case outcomes, steps, screenshots, assertions, coverage,
and an AI summary. Domain-scoped memory may retain useful interaction
knowledge for later tasks.

Report generation must not turn missing execution evidence into a successful
outcome.
