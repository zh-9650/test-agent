# AI Native Testing Platform - Product Requirements Document

> **Phase 1: UI Testing Agent + Runtime Foundation**
> **Date:** 2026-05-27
> **Status:** Ready for implementation

---

## Problem Statement

Enterprise QA teams rely on manually written test scripts (Playwright, Selenium, etc.) to validate web applications. This approach is brittle — scripts break when UI changes, require constant maintenance, and cannot discover unexpected issues. Existing "AI-assisted" testing tools are essentially script generators: the AI writes a Playwright script, and the team still maintains it. There is no system that autonomously understands a web application, decides what to test, executes tests intelligently, and reports findings — the way a skilled human tester would.

## Solution

Build an AI Native Testing Platform where the LLM acts as the tester — not as a script generator. The system accepts a target URL (plus optional requirements docs, Swagger specs, test rules, credentials), autonomously plans what to test, navigates the application in real time, makes decisions at each step based on what it observes, asserts results semantically, and produces a comprehensive test report.

The platform is built on three pillars:
- **LangGraph** for flow orchestration, state management, and durable execution
- **LangChain** for LLM interaction (model calls, tool calling, message management)
- **Playwright** for browser automation

Phase 1 delivers the foundational runtime infrastructure plus a fully functional UI Testing Agent. The runtime is designed so that future agents (API, Explorer, Assertion, Report, Planner) can be added without modifying existing code — they inherit the same base patterns and share the same public modules.

---

## User Stories

### Task Creation & Configuration
1. As a QA engineer, I want to input a target URL and start a UI test session, so that I can quickly validate a web application without writing any test code
2. As a QA engineer, I want to provide test credentials (username/password), so that the system can authenticate and test protected areas of the application
3. As a QA engineer, I want to upload a requirements document (PDF/Markdown), so that the AI understands what the application is supposed to do and can generate more relevant test cases
4. As a QA engineer, I want to define test rules and constraints (e.g., "do not test the payment module"), so that the AI respects business boundaries during testing
5. As a QA engineer, I want to specify test focus areas (e.g., "focus on the user management module"), so that the AI prioritizes high-value areas
6. As a QA engineer, I want to set a maximum number of test steps, so that the session doesn't run indefinitely
7. As a QA engineer, I want to provide a Swagger/OpenAPI spec alongside the URL, so that the AI can cross-reference API endpoints with UI behavior

### Test Planning
8. As a QA engineer, I want the system to automatically generate a test plan before execution, so that I can review and understand what will be tested
9. As a QA engineer, I want the test plan to include test case IDs, titles, descriptions, steps, and expected results, so that it's traceable and auditable
10. As a QA engineer, I want the test plan to identify shared preconditions (e.g., "login as admin"), so that setup steps are not repeated for every test case
11. As a QA engineer, I want the test plan to categorize test cases by type (functional, security, boundary), so that I can understand coverage
12. As a QA engineer, I want the test plan to assign priority levels to test cases, so that high-priority cases are executed first
13. As a QA engineer, I want the system to work even if I only provide a URL with no documentation, so that I can do quick smoke tests on any web application

### Real-Time Monitoring
14. As a QA engineer, I want to see the agent's current step in real time, so that I know what it's doing at any moment
15. As a QA engineer, I want to see the AI's reasoning process (why it chose a particular action), so that I can understand and trust its decisions
16. As a QA engineer, I want to see live screenshots of the browser as the agent navigates, so that I can visually follow the test execution
17. As a QA engineer, I want to see execution logs streamed in real time, so that I can spot issues as they happen
18. As a QA engineer, I want to see the current test case being executed and overall progress (e.g., "5/20 test cases complete"), so that I know how far along the session is

### Test Execution
19. As the system, I want to observe each page before deciding what to do, so that my actions are based on the actual current state of the application
20. As the system, I want to extract a semantic summary of each page (interactive elements, structure, state), so that the LLM receives a manageable representation instead of raw DOM
21. As the system, I want to capture a screenshot of each page, so that the LLM can visually understand the page layout and business context
22. As the system, I want to use LangChain tool calling to express my intent (e.g., click, input_text, navigate), so that actions are structured and traceable
23. As the system, I want to detect state changes after each action (URL changes, new elements, removed elements, JS errors, network errors, modals, error messages), so that I can assert results based on facts
24. As the system, I want the LLM to judge whether each action's result matches the expected outcome, so that assertions are semantic rather than brittle
25. As the system, I want to automatically execute preconditions (e.g., login) before test cases that require them, so that each test case runs in a clean state
26. As the system, I want to clear conversation context between test cases, so that the LLM's context window stays manageable across 50+ test cases
27. As the system, I want to track which test cases have been completed and their results, so that I never lose progress
28. As the system, I want to checkpoint state after every step, so that I can resume from where I left off if the process crashes

### Test Reporting
29. As a QA engineer, I want a test report that lists all executed test cases with pass/fail status, so that I can see overall quality at a glance
30. As a QA engineer, I want the report to include screenshots at each step, so that I can visually verify what happened
31. As a QA engineer, I want the report to include an AI-generated summary of findings, so that I get a high-level quality assessment without reading every detail
32. As a QA engineer, I want the report to highlight risk areas and potential issues discovered during testing, so that I can prioritize follow-up
33. As a QA engineer, I want the report to include execution logs for each test case, so that I can debug failures
34. As a QA engineer, I want the report to be available as an HTML file, so that I can share it with stakeholders without requiring access to the platform

### Memory & Knowledge Base
35. As a QA engineer, I want the AI to remember how to interact with complex UI elements across sessions, so that it doesn't repeat the same mistakes
36. As a QA engineer, I want system-specific memories (e.g., login quirks) to be isolated by target URL, so that they don't pollute other test targets
37. As a QA engineer, I want to view, edit, and delete the AI's learned memories in a frontend UI, so that I can correct its knowledge base manually

### Extensibility & Future Agents
35. As a developer, I want to add an API Testing Agent in a future phase without modifying the UI Agent code, so that the system grows incrementally
36. As a developer, I want all agents to share the same runtime, state management, logging, and reporting infrastructure, so that I don't duplicate code
37. As a developer, I want to add new Playwright tools (e.g., drag-and-drop, file upload) by writing a single @tool-decorated function, so that extending capabilities is simple
38. As a developer, I want to swap the LLM provider (e.g., from Qwen to DeepSeek) by changing a single configuration parameter, so that I'm not locked into one vendor
39. As a developer, I want to add a Rule Engine in a future phase that intercepts tool calls before execution, so that dangerous actions can be blocked without changing agent logic
40. As a developer, I want the assertion system to be upgradeable from an inline skill to an independent Assertion Agent, so that cross-agent assertion logic can be centralized later

### Operations
41. As a DevOps engineer, I want the system to run locally with `python main.py`, so that development and debugging are straightforward
42. As a DevOps engineer, I want execution state to persist to a database, so that test sessions survive server restarts
43. As a DevOps engineer, I want to be able to resume a crashed test session from its last checkpoint, so that long-running sessions don't need to restart from scratch
44. As a QA lead, I want to query execution history (past test sessions, their results, durations), so that I can track quality trends over time

---

## Implementation Decisions

### 15. Memory System (Phase 1.5)

The system implements a dual-scoped Memory System using a Key-Value PostgreSQL table (`agent_memory`):
- **Scope**: Memories are categorized as either `global` (shared UI patterns) or `domain` (isolated to a specific target URL).
- **Reflection Timing**: Coarse-grained. At the end of a task (e.g., during report generation), a Reflection Node/Agent analyzes the logs and extracts reusable knowledge.
- **Retrieval**: Before generating test plans and during execution (e.g., upon failures), the agent queries the KV store to inject relevant memories into the prompt.
- **Human-in-the-loop**: The React frontend exposes a "Memory Management" page for humans to view, edit, and delete learned knowledge.

### 1. Architecture: Intent-Based Execution (Not Code Generation)

The system does NOT generate Playwright scripts. The LLM makes decisions in real time, at each step outputting a structured tool call (intent) that is executed by a Playwright tool function. This is fundamentally different from "AI writes a test script and then the script runs."

**Rationale:** Code generation creates a maintenance burden (the AI-written script breaks when the UI changes and needs to be re-generated). Intent-based execution is adaptive — the LLM sees the current page state and decides what to do, so it naturally handles UI changes.

### 2. Orchestration: LangGraph for Flow, LangChain for Components

LangGraph provides the execution graph (nodes, edges, state, checkpoints, subgraphs). LangChain provides the components used inside each node (ChatModel, message types, @tool decorator, bind_tools, PromptTemplate, OutputParser).

LangGraph's `StateGraph` defines the overall flow. Each node is a Python function that reads/writes shared state. Conditional edges control loops and branching. The compiled graph supports `.astream()` for real-time state streaming.

LangChain's `AgentExecutor` is NOT used — the agent loop is custom-built with LangGraph nodes to support the observe → decide → execute → assert → record cycle with context cleanup between test cases.

### 3. Two-Phase Execution: Plan Then Execute (Subgraph Isolation)

The test session is split into two LangGraph subgraphs:

**Planning Subgraph:**
- Reads all inputs (URL, requirements, rules, credentials, Swagger)
- AI explores the target system using the observe→decide loop (navigating pages, observing structure) to gather real page information before planning. Two safety valves: max 20 pages explored, max 5 minutes exploration time (configurable)
- LLM generates a structured test plan via tool calling (a `create_test_plan` tool constrains the output to match TestCase schema): list of test cases with IDs, titles, natural-language steps, expected results, priorities, categories
- LLM identifies shared preconditions (setups) and defines them once — setups are mini test cases executed by the same observe→decide→execute loop, no hardcoded login functions
- Output: `test_plan: list[TestCase]` and `setups: dict[str, list[Step]]`

**Execution Subgraph:**
- Iterates through `test_plan` using `current_index`
- For each test case: executes setup if needed → enters observe-decide-execute-assert loop → records result → clears conversation context → advances to next
- Uses conditional edges to loop within a test case and across test cases

**Rationale:** Subgraph isolation means the planning LLM conversation doesn't pollute the execution context. The test plan itself acts as long-term memory — structured data that doesn't consume LLM context window tokens.

### 4. State Design

The shared state schema (extending LangGraph's `MessagesState`):

```
TestState:
  # Planning output (structured, not in LLM context window)
  test_plan: list[TestCase]
  setups: dict[str, list[SetupStep]]

  # Execution tracking
  current_index: int              # which test case
  current_step: int               # which step within current test case
  results: list[TestResult]       # accumulated via operator.add reducer

  # Page information (refreshed each step)
  page_info: dict                 # semantic summary from Page Semantic Layer
  screenshot: str                 # base64 encoded screenshot

  # Change detection
  state_before: dict              # page state snapshot before action
  state_after: dict               # page state snapshot after action

  # LLM conversation (needs context management)
  messages: list[AnyMessage]      # auto-appended via add_messages reducer
```

Key design: `test_plan`, `results`, `setups` are structured data fields that don't enter the LLM's context window. Only `messages` (the current test case's conversation) needs context management.

### 5. Page Semantic Layer: Playwright Locator + Screenshot

Pages are never passed as raw DOM to the LLM. Instead, a two-part extraction runs at each observation step:

**Part A — Structured Extraction (Playwright locator API):**
- Layer 1: Interactive elements — inputs (label, type, placeholder, required), buttons (text, type, disabled), links (text, href), selects (label, options), checkboxes, radios, tables (headers, row_count, pagination)
- Layer 2: Page structure — URL, title, headings, breadcrumbs, navigation menu, forms, modals, alerts/toasts
- Layer 3: State information — loading state, error messages, validation errors, empty states, pagination info, active tabs

Uses Playwright's `locator()` API (not raw `document.querySelectorAll`) to naturally handle Shadow DOM, async loading, iframes, and lazy rendering. Framework-agnostic — works with React, Vue, Next.js, Angular, or plain HTML.

**Part B — Screenshot:**
- Full viewport screenshot captured as base64
- Provided to the LLM alongside the structured extraction for visual understanding

### 6. Tool Calling as Intent Protocol

LangChain's `@tool` decorator defines Playwright operations as callable tools:

```
@tool click(target: str, locator: str = "") -> str
@tool input_text(target: str, value: str) -> str
@tool navigate(url: str) -> str
@tool scroll(direction: str, amount: int) -> str
@tool screenshot() -> str
@tool hover(target: str) -> str
@tool select_option(target: str, value: str) -> str
@tool press_key(key: str) -> str
@tool wait(seconds: float) -> str
```

The LLM receives these tool definitions via `bind_tools()`. When the LLM decides to act, it produces a `tool_call` in its response. The execution node dispatches to the corresponding tool function via a `tools_by_name` dictionary lookup.

This replaces a custom intent JSON format — the LLM's native tool calling format IS the intent protocol.

### 7. Dual-Layer Assertion

**Layer 1 — Rule-Based Change Detection (facts, no judgment):**
After each action, a Python function compares `state_before` and `state_after` and produces a change report:

```
ChangeReport:
  url_changed: bool
  url_before: str
  url_after: str
  new_elements: list[str]        # elements that appeared
  gone_elements: list[str]       # elements that disappeared
  js_errors: list[str]           # browser console errors
  network_errors: list[str]      # failed network requests
  error_messages_visible: list[str]  # visible error/toast messages
  modal_appeared: bool
  page_loading: bool
  screenshot_after: str
```

This layer never judges pass/fail. It only reports what happened.

**Layer 2 — LLM Semantic Judgment:**
The LLM receives: the original intent (tool_call), the change report, the screenshot, and the test case's expected result. It decides whether the action's outcome matches expectations and returns a pass/fail judgment with reasoning.

**Rationale:** Rule-based assertion is fast and deterministic but can't judge business logic. LLM judgment is flexible but expensive. Combining them — rules for fast fact detection, LLM for semantic judgment — minimizes cost while maintaining accuracy.

### 8. Context Management

Across 50+ test cases, the LLM's context window would overflow if all conversation history were retained. The management strategy:

- **Test plan and results** are structured data stored in state fields, NOT in the messages list. They don't consume context window.
- **Messages** only contain the current test case's conversation (observe → decide → execute → assert).
- **Between test cases**, old messages are removed via LangGraph's `RemoveMessage`. A one-line summary is optionally prepended to the next test case's context.
- **Within a test case**, if the conversation grows too long (many steps), `trim_messages` keeps only the most recent messages.

LangGraph's `Checkpointer` (PostgresSaver for all environments) persists the full state at every step, enabling crash recovery.

### 9. Setup/Precondition Management

The planning phase produces both `test_plan` and `setups`:

```
TestCase:
  id: str
  title: str
  description: str
  preconditions: list[str]       # e.g., ["login_as_admin"]
  steps: list[str]               # natural language
  expected: str
  priority: str                  # high / medium / low
  category: str                  # functional / security / boundary

Setup:
  steps: list[dict]              # structured action steps
```

When the execution subgraph encounters a test case with preconditions, the Agent executes the setup using the same observe→decide→execute loop — the Agent sees the login page, finds input fields, fills credentials, and clicks login autonomously. No hardcoded login functions. A setup is essentially a mini test case. The browser context persists as long as login state is valid, so subsequent test cases sharing the same precondition skip re-login.

### 10. Shared Modules (Public Infrastructure)

Seven modules are shared across all current and future agents:

| Module | Responsibility |
|--------|---------------|
| **Runtime** | LangGraph StateGraph compilation, checkpointing, state management, subgraph orchestration |
| **RuntimeState** | Base state schema extending `MessagesState`, shared fields (task_id, logs, errors, results) |
| **LLM Client** | Unified model connection via Anthropic SDK (Bailian Anthropic-compatible endpoint), retry logic, timeout, token counting. Each agent provides its own prompt and parser. |
| **ExecutionLogger** | Step-by-step logging to database (task_id, step_index, action, target, result, screenshot, timestamp) |
| **ReportBuilder** | Report generation skeleton — HTML template with sections for summary, test results, screenshots, logs. Each agent fills its own content. |
| **Page Semantic Layer** | Playwright locator-based extraction + screenshot capture. Used by any agent that interacts with web pages. |
| **Change Detector** | Rule-based before/after comparison producing a ChangeReport. Used by any agent that needs to assert results. |

**Boundary rule:** A module is shared ONLY if every agent needs it. UI-specific logic (Playwright browser management, page extraction) stays in the UI Agent package. API-specific logic (Swagger parsing, HTTPX requests) stays in the API Agent package (Phase 3).

### 11. LLM Model Strategy

Using Alibaba Cloud Bailian Platform (DashScope) with OpenAI-compatible API. Confirmed tool calling support for:

| Model | Use Case | Rationale |
|-------|----------|-----------|
| qwen3.7-max | Planning (test plan generation) | Highest reasoning capability for complex analysis |
| kimi-k2.6 | Execution (per-step decisions, assertions) | Good balance for high-frequency calls |
| deepseek-v4-flash | Simple tasks (summarization, cleanup) | Cheapest, sufficient for straightforward tasks |
| glm-5.1 | Complex reasoning | Reserved for difficult inference tasks |

Model switching is done via environment variables (`ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_HAIKU_MODEL`, etc.) — changing config, no code changes. LLM Client uses the Anthropic SDK with the Bailian Anthropic-compatible endpoint.

### 12. Real-Time Monitoring

LangGraph's `.astream()` yields state updates as each node completes. FastAPI exposes a WebSocket endpoint that forwards these updates to the frontend:

```
WebSocket message types:
  - step_update: {step_index, action, status, timestamp}
  - ai_thinking: {reasoning, tool_call}
  - screenshot: {base64_image, page_url}
  - progress: {current_test_case, total, completed, passed, failed}
  - test_result: {test_case_id, status, summary}
  - session_complete: {report_url, summary_stats}
```

### 13. Project Structure

```
smart-test-agent/
├── main.py                        # Entry point
├── requirements.txt
├── .env
│
├── core/                          # Shared infrastructure (7 public modules)
│   ├── __init__.py
│   ├── runtime.py                 # LangGraph StateGraph, compilation, checkpointing
│   ├── state.py                   # TestState schema, TestCase/TestResult/Setup models
│   ├── llm_client.py              # Model initialization, retry, token tracking
│   ├── execution_logger.py        # Step logging to database
│   ├── report_builder.py          # HTML report generation skeleton
│   ├── page_semantic.py           # Playwright locator extraction + screenshot
│   └── change_detector.py         # Before/after comparison → ChangeReport
│
├── agents/                        # Agent implementations
│   ├── __init__.py
│   ├── base.py                    # AgentBase: shared lifecycle (observe→plan→execute→assert)
│   ├── ui/                        # UI Testing Agent (Phase 1)
│   │   ├── __init__.py
│   │   ├── tools.py               # @tool decorated Playwright operations
│   │   ├── planning_graph.py      # Planning subgraph
│   │   ├── execution_graph.py     # Execution subgraph (observe→decide→execute→assert loop)
│   │   ├── prompts.py             # UI Agent-specific system prompts
│   │   └── setup_manager.py       # Precondition execution
│   ├── api/                       # API Testing Agent (Phase 3, empty for now)
│   ├── explorer/                  # Explorer Agent (Phase 2, empty for now)
│   ├── assertion/                 # Assertion Agent (Phase 4, empty for now)
│   ├── report/                    # Report Agent (Phase 5, empty for now)
│   └── planner/                   # Planner Agent (Phase 6, empty for now)
│
├── api/                           # FastAPI application
│   ├── __init__.py
│   ├── app.py                     # FastAPI app, routes
│   ├── websocket.py               # WebSocket handler for real-time monitoring
│   └── schemas.py                 # Pydantic request/response models
│
├── frontend/                      # React frontend
│   ├── src/
│   │   ├── pages/
│   │   │   ├── TaskCreate.tsx     # Task creation form
│   │   │   ├── Monitor.tsx        # Real-time execution monitoring
│   │   │   └── Report.tsx         # Report viewing
│   │   ├── components/
│   │   ├── hooks/
│   │   └── App.tsx
│   ├── package.json
│   └── vite.config.ts
│
├── database/
│   ├── __init__.py
│   ├── models.py                  # SQLAlchemy models (task, task_step, report)
│   ├── connection.py              # Database connection setup
│   └── migrations/                # Alembic migrations
│
└── tests/
    ├── core/                      # Tests for shared modules
    ├── agents/ui/                 # Tests for UI Agent
    └── api/                       # Tests for FastAPI endpoints
```

### 14. Database Schema

```
task:
  id: bigint PK
  task_name: varchar
  target_url: text
  status: varchar (pending/running/completed/failed/cancelled)
  config: jsonb                    # test rules, credentials reference, focus areas
  test_plan: jsonb                 # generated test plan
  total_tests: int
  passed_tests: int
  failed_tests: int
  started_at: timestamp
  completed_at: timestamp
  created_at: timestamp

task_step:
  id: bigint PK
  task_id: bigint FK → task
  test_case_id: varchar            # TC-001, TC-002, etc.
  step_index: int
  action_type: varchar             # click, input_text, navigate, etc.
  action_target: text
  action_args: jsonb
  result: text
  screenshot_path: text
  change_report: jsonb             # ChangeReport from change detector
  assertion_result: jsonb          # {status: pass/fail, reasoning: str}
  created_at: timestamp

report:
  id: bigint PK
  task_id: bigint FK → task
  report_path: text
  summary: text                    # AI-generated summary
  created_at: timestamp

agent_memory:
  id: bigint PK
  scope_type: varchar              # 'global' or 'domain'
  scope_value: text                # '*' or specific domain like '192.168.31.155'
  memory_key: text                 # Short description of the memory
  memory_value: text               # Detailed knowledge/reflection
  created_at: timestamp
  updated_at: timestamp

---

## Testing Decisions

### What Makes a Good Test

Tests should verify external behavior, not internal implementation. A good test:
- Provides input and checks output
- Does not mock internal LangGraph state transitions
- Does not assert on prompt strings or message ordering
- Treats each module as a black box with a defined interface

### Which Modules Will Be Tested

| Module | Test Type | What to Test |
|--------|-----------|-------------|
| **Page Semantic Layer** | Unit | Extraction correctness on sample HTML pages (login form, data table, dashboard with modals). Test with Shadow DOM, iframe, async-loaded content. |
| **Change Detector** | Unit | Given before/after page state snapshots, verify the ChangeReport correctly identifies URL changes, element additions/removals, JS errors, network errors, modals, error messages. |
| **LLM Client** | Unit | Retry logic on transient failures, timeout handling, token counting accuracy. Mock the DashScope API. |
| **Execution Logger** | Unit | Correct persistence of step records, query by task_id, ordering by step_index. Use PostgreSQL test database for tests. |
| **Report Builder** | Unit | HTML report generation from sample test results. Verify all sections are present, screenshots are embedded, statistics are correct. |
| **Setup Manager** | Unit | Precondition resolution — given a test case with `preconditions: ["login_as_admin"]`, verify setup steps are retrieved and ordered correctly. |
| **State Models** | Unit | Pydantic validation of TestCase, TestResult, Setup, ChangeReport models. |
| **Planning Subgraph** | Integration | Given sample inputs (URL + mock requirements), verify the subgraph produces a valid test plan with correct structure. Mock the LLM. |
| **Execution Subgraph** | Integration | Given a test plan and mock Playwright, verify the observe→decide→execute→assert loop runs correctly, results accumulate, context is cleaned between test cases. |
| **FastAPI Endpoints** | Integration | POST /tasks (create), GET /tasks/{id} (status), WebSocket /ws/tasks/{id} (real-time). Use FastAPI TestClient. |
| **Frontend** | Manual/E2E | Task creation flow, real-time monitoring display, report rendering. |

### Prior Art

This is a greenfield project — no existing tests to reference. The testing approach follows standard Python patterns: `pytest` for backend, `vitest` for frontend.

---

## Out of Scope

### For Phase 1
- **API Testing Agent** — planned for Phase 3. The public modules are designed to support it, but no API-specific code is built in Phase 1.
- **Explorer Agent** — planned for Phase 2.
- **Assertion Agent** — planned for Phase 4. In Phase 1, assertion is an inline capability (dual-layer), not an independent agent.
- **Report Agent** — planned for Phase 5. In Phase 1, reporting is handled by the shared ReportBuilder module.
- **Planner Agent** — planned for Phase 6. In Phase 1, planning is a subgraph within the UI Agent, not a top-level coordinator.
- **Rule Engine** — constraint system for blocking dangerous actions. Deferred to a future phase.
- **Zentao/JIRA integration** — bug auto-reporting to third-party systems. Deferred.
- **DingTalk/Email notifications** — push notifications on test completion. Deferred.
- **Docker deployment** — Phase 1 runs locally with `python main.py`.
- **Performance testing** — Artillery.io integration. Deferred.
- **Test case CSV import/export** — deferred.
- **Historical learning** — learning from past test cases and bugs to improve future testing is now part of Phase 1.5 (Memory System).
- **Database assertions** — SQL-based data validation. Deferred.
- **Log analysis** — server-side error log analysis. Deferred.

### For the Entire Project
- **Mobile app testing** — the platform targets web applications only.
- **Native desktop app testing** — out of scope.
- **Test script generation** — the system is explicitly NOT a script generator. It does not output Playwright/Selenium scripts for humans to maintain.

---

## Further Notes

### LangGraph Version Compatibility
LangGraph's API has been evolving rapidly. The implementation should pin to a specific version and follow the latest `StateGraph`, `MessagesState`, and checkpointing patterns. The `add_messages` reducer from `langgraph.graph.message` is the correct way to accumulate messages — not `operator.add` on a plain list.

### LLM API Compatibility
The platform uses Alibaba Cloud Bailian's Anthropic-compatible endpoint (token-plan.cn-beijing.maas.aliyuncs.com/apps/anthropic). The LLM Client uses the Anthropic SDK. Tool calling has been verified as available (Claude Code itself runs through this endpoint and relies heavily on tool calling). Streaming behavior with tool calling should be tested during development.

### Playwright Browser Lifecycle
Each test session launches a single browser instance. Browser contexts are managed by need, not by test case — a context persists as long as the login state is valid. When login is detected as lost, the old context is closed and a new one is created with setup re-executed. Trace and video recording are per-test-case (start at case begin, save at case end). If the browser crashes, the system catches the exception, restarts the browser, and resumes from the current test case — completed results are not lost.

### Token Cost Management
With approximately 50+ LLM calls per test session (planning + exploration + 2-3 calls per test step × 20+ test cases), token costs can add up. The implementation should:
- Track token usage per session (LLM Client module)
- Use deepseek-v4-flash for simple tasks (summarization)
- Clear conversation context aggressively between test cases
- Cache page semantic extraction where possible (same page = same extraction)

### Future Extensibility Hooks
The following extension points are deliberately designed into Phase 1:
- `agents/base.py` defines `AgentBase` with a standard lifecycle that future agents inherit
- `core/state.py` defines `TestState` with fields that future agents extend (not replace)
- `agents/` directory has placeholder directories for all future agents
- Tool registration uses `bind_tools()` — adding new tools means adding new `@tool` functions, no architecture changes
- Model switching is a single parameter change in `core/llm_client.py`
