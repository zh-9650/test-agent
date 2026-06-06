# Development Guide

Last verified against the working tree: 2026-06-06.

## Required Reading

Read in this order:

1. `CONTEXT.md` for current architecture, implemented capabilities, and known
   defects.
2. `docs/PRD.md` for product behavior and acceptance expectations.
3. `docs/master-roadmap.md` for active priority.
4. The relevant contract document:
   `docs/prompt-engineering.md` or `docs/business_workflow.md`.

Do not search historical handoffs or daily devlogs. They were removed because
they duplicated stale state. Use `git log`, `git show`, and `git blame` when
historical context is required.

## Repository Map

| Path | Responsibility |
|---|---|
| `main.py` | Unified local backend/frontend launcher |
| `api/` | FastAPI routes, schemas, WebSocket management |
| `core/interfaces.py` | Shared Pydantic models and public contracts |
| `core/runtime.py` | Planning/execution orchestration, retry, report lifecycle |
| `core/skills/` | Knowledge, use-case, model, scenario, risk, and coverage skills |
| `agents/ui/planning_graph.py` | Goal-driven exploration and plan generation |
| `agents/ui/execution_graph.py` | Per-case observe/decide/execute/assert/record graph |
| `agents/ui/tools.py` | Browser tools and task marker tools |
| `core/page_semantic.py` | Semantic page extraction |
| `core/execution_logger.py` | PostgreSQL task/step persistence |
| `core/diag_logger.py` | Optional per-stage diagnostic artifacts |
| `core/report_builder.py` | HTML report generation |
| `database/` | SQLAlchemy connection and models |
| `frontend/` | React/Vite application |
| `tests/` | Core, API, UI-agent, and benchmark tests |
| `data/fixtures/` | Versioned reproducible test inputs |

## Environment

Required:

- Python 3.11+
- Node.js 18+
- PostgreSQL 14+
- Playwright Chromium
- Alibaba Cloud Bailian Anthropic-compatible credentials

Common `.env` variables:

```dotenv
ANTHROPIC_AUTH_TOKEN=
ANTHROPIC_BASE_URL=
ANTHROPIC_MODEL=
ANTHROPIC_DEFAULT_HAIKU_MODEL=
ANTHROPIC_DEFAULT_SONNET_MODEL=
ANTHROPIC_DEFAULT_OPUS_MODEL=
DATABASE_URL=postgresql://postgres:password@localhost:5432/smart_test

BACKEND_PORT=8000
FRONTEND_PORT=5173
START_FRONTEND=true

MAX_STEPS_PER_CASE=15
MAX_CONSECUTIVE_FAILURES=3
MAX_TEST_CASE_RETRIES=2
MAX_EXPLORE_PAGES=20
MAX_EXPLORE_MINUTES=5

L2_USE_CDP=0
L2_PARALLEL_TOOLS=0
DIAG_ENABLED=false
DIAG_FULL=false
```

The deployed `.env` may intentionally point all model variables at one test
model. Never copy its secret values into documentation or fixtures.

## Setup And Start

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
Set-Location frontend
npm install
Set-Location ..
python main.py
```

Set `START_FRONTEND=false` to run only FastAPI through `main.py`.

## Verification Matrix

Use the smallest relevant checks during implementation, then broaden before
completion.

Backend syntax:

```powershell
python -m compileall main.py api core agents database tests -q
```

Focused backend tests:

```powershell
python -m pytest tests/core/test_runtime.py tests/core/test_runtime_retry.py tests/api/test_app.py -q
```

Full backend suite:

```powershell
python -m pytest -q
```

Frontend:

```powershell
Set-Location frontend
npm run build
npm run lint
```

End-to-end changes affecting runtime, API, WebSocket, browser tools, or UI also
require:

1. start the real application;
2. create a task with representative rich inputs;
3. observe WebSocket progress;
4. inspect PostgreSQL task and step records;
5. inspect the generated report;
6. compare planned cases, terminal results, counters, and report totals.

Keep real target URLs and credentials outside Git.

## Diagnostic Workflow

When investigating quality or lifecycle failures:

1. enable `DIAG_ENABLED=true`;
2. run one fixed task;
3. inspect `data/diag/{task_id}/index.json`;
4. compare stages in order;
5. identify the first stage that differs from an explicit human oracle;
6. fix one layer at a time.

Diagnostic output is runtime data and must not be committed.

## Documentation Update Rules

Update documentation in the same commit as the behavior it describes.

| Change | Required documentation |
|---|---|
| Product behavior, input, output, or acceptance criteria | `docs/PRD.md` |
| Architecture, lifecycle, module ownership, known limitation | `CONTEXT.md` |
| Development command, environment variable, verification process | `docs/DEVELOPMENT.md` |
| Priority or sequencing decision | `docs/master-roadmap.md` |
| Prompt schema or inter-node contract | `docs/prompt-engineering.md` |
| Business process semantics | `docs/business_workflow.md` |
| Fixture added or changed | `data/fixtures/README.md` |
| Frontend-specific setup | `frontend/README.md` |

Do not add:

- session handoff files;
- daily progress logs;
- completed phase plans;
- generated benchmark reports;
- screenshots or browser snapshots;
- one-off scripts with fixed task IDs, URLs, or credentials.

Use commit history for implementation history. Add a retained benchmark or
research document only when it contains reproducible methodology and a
decision that remains relevant.

## Current Development Focus

Start with P0 in `docs/master-roadmap.md`: authoritative case results and task
lifecycle consistency. Do not tune multiple prompt layers until that path is
observable and reliable.
