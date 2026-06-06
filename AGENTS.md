# Repository Instructions

## Before Editing

Read:

1. `docs/DEVELOPMENT.md`
2. `CONTEXT.md`
3. relevant sections of `docs/PRD.md`
4. `docs/master-roadmap.md`

For prompt or workflow changes, also read the corresponding contract document.

## Engineering Rules

- Preserve the intent-based architecture. The model emits tool calls; it does
  not generate maintained test scripts.
- Do not hardcode product-specific login or navigation flows.
- Keep rich `task_config` inputs available to planning and execution.
- Keep prompts in Chinese.
- Prefer existing project patterns and narrowly scoped changes.
- Do not add Alembic in the current phase; startup creates tables.
- Never commit secrets or real credentials.
- Do not commit runtime data, diagnostic output, generated reports, browser
  snapshots, or one-off scripts.
- Work with existing uncommitted changes; never revert unrelated user work.

## Verification

Follow the verification matrix in `docs/DEVELOPMENT.md`.

Any change affecting runtime, API, WebSocket, frontend, browser behavior, or
reports requires real end-to-end validation in addition to focused tests.

## Documentation

Update the authoritative document in the same commit as the behavior change.
The mapping is defined in `docs/DEVELOPMENT.md`.

Do not create handoff/devlog/phase-completion documents in this repository.
Use Git history for historical implementation details.
