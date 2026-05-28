# CLAUDE.md

This file provides guidance to Claude Code when working with this project.

## Project Overview

**AI Native Testing Platform** — an LLM-driven system that autonomously tests web applications. The LLM acts as the tester in real time: it observes pages via Playwright, decides actions via tool calling, executes them, and judges results semantically. It does NOT generate test scripts for humans to maintain.

## Key Documentation

- **`CONTEXT.md`** (root) — All confirmed design decisions (44), glossary, agent breakdown, shared modules. **Read this first before writing any code.**
- **`docs/PRD.md`** — Full product requirements: 44 user stories, implementation decisions, database schema, project structure, testing strategy.
- **`old/`** — Outdated architecture docs from before the current design. **Ignore this directory.**

## Tech Stack

- **Backend**: FastAPI + LangGraph + LangChain (Python 3.11+)
- **LLM**: Alibaba Cloud Bailian Anthropic-compatible API (Anthropic SDK)
  - Models: qwen3.7-max (planning), kimi-k2.6 (execution), deepseek-v4-flash (simple), glm-5.1 (complex)
- **Browser**: Playwright
- **Database**: PostgreSQL (all environments)
- **Frontend**: React + Vite + TypeScript
- **Real-time**: LangGraph `.astream()` → FastAPI WebSocket → React

## Architecture Summary

**Two-phase execution (LangGraph subgraphs):**
1. Planning subgraph: AI explores target system → generates structured test plan
2. Execution subgraph: iterates test cases → observe → decide → execute → assert → record → next

**Execution loop per test case:**
- `observe`: Page Semantic Layer extracts interactive elements + screenshot
- `decide`: LLM decides action via tool_call (or no tool_call = test case complete)
- `execute`: dispatch to @tool function
- `assert`: Change Detector (facts) + LLM (semantic judgment)
- `record`: persist to database + emit WebSocket message

**Safety valves:** max 15 steps per case, 3 consecutive failures → skip. Both configurable.

## Environment Setup

Required before development:
- Python 3.11+
- Node.js 18+
- PostgreSQL 14+
- Alibaba Cloud Bailian API key (DashScope Anthropic-compatible endpoint)

```bash
# Create .env with:
ANTHROPIC_AUTH_TOKEN=sk-sp-D.HLDPR.Bceb.MEUCIQDZuqlaQtuRGK8jWnOyyn4mWtnyLtYpZVBFZhdeBeWgfQIgHpdGiX/er6z3TnVfhyhOE+HFRJwSzeKTSH2Zf5yQV78=
ANTHROPIC_BASE_URL=https://token-plan.cn-beijing.maas.aliyuncs.com/apps/anthropic
ANTHROPIC_MODEL=qwen3.7-max
ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash
ANTHROPIC_DEFAULT_SONNET_MODEL=kimi-k2.6
ANTHROPIC_DEFAULT_OPUS_MODEL=glm-5.1
DATABASE_URL=postgresql://postgres:123456@localhost:5432/smart_test
MAX_STEPS_PER_CASE=15
MAX_CONSECUTIVE_FAILURES=3
MAX_EXPLORE_PAGES=20
MAX_EXPLORE_MINUTES=5
BACKEND_PORT=8000
FRONTEND_PORT=5173

# Test target (for development validation):
# URL: http://192.168.31.155/login?redirect=/ai-talk/index
# Username: test_c  Password: 123456
```

**Important:** On first run, `main.py` must auto-create the `smart_test` database and all tables (using `SQLAlchemy create_all()`). Do NOT use Alembic migrations in Phase 1.

## Project Structure (target)

```
smart-test-agent/
├── main.py
├── .env
├── core/                  # 7 shared modules
│   ├── runtime.py         # LangGraph StateGraph, checkpointing
│   ├── state.py           # TestState, TestCase, TestResult, Setup models
│   ├── llm_client.py      # Anthropic SDK init, retry, token tracking
│   ├── execution_logger.py
│   ├── report_builder.py
│   ├── page_semantic.py   # Playwright locator extraction + screenshot
│   └── change_detector.py
├── agents/
│   ├── base.py            # AgentBase lifecycle
│   └── ui/                # Phase 1
│       ├── tools.py       # @tool Playwright operations
│       ├── planning_graph.py
│       ├── execution_graph.py
│       ├── prompts.py
│       └── setup_manager.py
├── api/                   # FastAPI + WebSocket
├── frontend/              # React + Vite (4 pages: TaskCreate, Monitor, Report, TaskHistory)
├── database/              # SQLAlchemy (create_all, no Alembic in Phase 1)
│   └── models.py          # task, task_step, report tables
├── data/                  # Runtime files (screenshots, traces, reports)
└── tests/
```

## Design Principles

- **Intent-based, not code generation** — LLM outputs tool_calls, not Playwright scripts
- **LLM decides everything** — no hardcoded login functions, no fixed test flows
- **Documents define WHAT and WHY; code defines HOW** — don't over-specify formats in docs
- **Safety valves over hard limits** — configurable thresholds, not fixed numbers
- **Continuous validation** — verify each module as it's built, not at the end
- **Prompts in Chinese** — all LLM prompts written in Chinese for best model performance
