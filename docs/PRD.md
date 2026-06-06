# AI Native Testing Platform PRD

Status: active development
Last reconciled with code: 2026-06-06

## Problem

Traditional web automation produces scripts that teams must continuously
repair. This project instead lets an LLM test a site directly: understand the
requested behavior, inspect the live application, choose actions, evaluate the
result, and retain evidence.

## Product Goal

Given a target URL and optional product context, the platform should:

1. understand the system and its business rules;
2. explore the live UI before planning;
3. create a reviewable test plan;
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
report lookup, diagnostic artifact lookup, Layer 1 testing, memory CRUD,
document parsing, URL fetching, and task WebSocket streaming.

## Functional Requirements

### Planning

- Extract business knowledge with source evidence where available.
- Build atomic use cases and check business-rule coverage.
- Derive a lightweight system state model.
- Explore the actual target within configurable page/time limits.
- Generate cases with ID, title, description, steps, expected result,
  priority, category, and preconditions.
- Continue to support URL-only smoke testing.

### Execution

- Observe the current page before each decision.
- Send compact semantic page information rather than raw DOM.
- Express actions through registered tools.
- Detect URL, element, error, network, modal, and page-state changes.
- Use deterministic rules before semantic LLM assertion where possible.
- Enforce configurable step and failure safety limits.
- Retry failed cases with captured failure context.
- Reset browser state between cases/retries when required.
- Produce exactly one terminal result per planned case.

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
- Feature completion requires the verification matrix in
  `docs/DEVELOPMENT.md`.
- Real target verification must use credentials supplied outside Git.

## Current Acceptance Gap

The repository does not currently meet the lifecycle consistency requirement.
Known evidence shows that planned count, executed results, persisted counters,
final task status, and report statistics can disagree. This is the current P0
product defect and must be resolved before claiming reliable end-to-end task
completion.

## Deferred Scope

- Independent API testing agent.
- Multi-agent parallel test teams.
- Persistent LangGraph PostgreSQL checkpointer.
- Database assertions and server-log analysis.
- Mobile and native desktop testing.
- Generated Playwright/Selenium test scripts.
- Production deployment packaging.
