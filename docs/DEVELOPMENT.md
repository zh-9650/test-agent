# Development Guide

Last verified against the working tree: 2026-06-15.

## Required Reading

Read in this order:

1. `CONTEXT.md` for current architecture, implemented capabilities, and known
   defects.
2. `docs/PRD.md` for product behavior and acceptance expectations.
3. `docs/master-roadmap.md` for active priority.
4. The relevant contract document:
   `docs/prompt-engineering.md`, `docs/business_workflow.md`, or
   `docs/ai-development-guide.md`.

Do not search historical handoffs or daily devlogs. They were removed because
they duplicated stale state. Use `git log`, `git show`, and `git blame` when
historical context is required.

## Repository Map

| Path | Responsibility |
|---|---|
| `main.py` | Unified local backend/frontend launcher |
| `api/` | FastAPI routes, schemas, WebSocket management |
| `core/interfaces.py` | Shared Pydantic models and public contracts |
| `core/task_lifecycle.py` | Authoritative task lifecycle orchestration service |
| `core/runtime.py` | Browser exploration and one candidate-case attempt |
| `core/runtime_session.py` | Browser ownership and retry lifecycle |
| `core/execution_store.py` | Run, result, step, and summary persistence |
| `core/skills/` | Requirement analysis, test design, quality gates, case adaptation, traceability, and asset packaging |
| `agents/ui/tools.py` | Browser tools and task marker tools |
| `core/page_semantic.py` | Semantic page extraction |
| `core/diag_logger.py` | Optional per-stage diagnostic artifacts |
| `core/run_report.py` | Run-scoped HTML report generation |
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
MAX_CASE_ATTEMPT_SECONDS=120
LLM_REQUEST_TIMEOUT_SECONDS=180
LLM_MAX_RETRIES=2
ANALYZING_PHASE_TIMEOUT_SECONDS=900
EXPLORING_PHASE_TIMEOUT_SECONDS=300
DESIGNING_PHASE_TIMEOUT_SECONDS=900
EXECUTING_PHASE_TIMEOUT_SECONDS=1800
L1_CHUNK_MAX_CHARS=12000
L1_ASSERTION_BATCH_SIZE=24
L1_MAX_CONCURRENCY=3
L1_MAX_FACTS=120
L1_MAX_FAILED_CHUNKS=0
L2_CONDITION_BATCH_SIZE=20
L2_COVERAGE_BATCH_SIZE=30
L2_CASE_BATCH_SIZE=20
L2_DESIGN_MAX_CONCURRENCY=3
MAX_EXPLORE_PAGES=20
MAX_EXPLORE_MINUTES=5
BROWSER_HEADED=false
BROWSER_RECORD_VIDEO=false

L2_USE_CDP=0
L2_PARALLEL_TOOLS=0
DIAG_ENABLED=false
DIAG_FULL=false
```

Process environment variables take precedence over local `.env` defaults.
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
python -m pytest tests/core/test_runtime.py tests/api/test_database.py tests/api/test_app.py tests/api/test_websocket.py tests/core/test_l2_new_pipeline.py -q
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

Evaluate a serialized `TestAssetPackage` against a versioned human oracle:

```powershell
python -m core.human_oracle `
  path\to\package.json `
  data\fixtures\oracles\purchase_approval.v1.json `
  --source-root data\fixtures
```

The command prints machine-readable metric results and exits non-zero when
critical expectations, forbidden-claim checks, exploration evidence, or plan
contracts fail.

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
| AI implementation guide for the test-analysis pipeline | `docs/ai-development-guide.md` |
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

P2 and P3 are complete. Start with a scoped P4 item in
`docs/master-roadmap.md`, preserving the authoritative single-agent lifecycle
and its existing quality baselines.
