# Smart Test Agent

AI-native web testing with FastAPI, LangGraph, LangChain, Playwright/browser-use,
PostgreSQL, and React.

The system reads product context, explores a live web application, generates a
test plan, executes cases through browser tool calls, evaluates outcomes, and
produces persisted evidence and an HTML report.

## Start Here

- Development and verification: `docs/DEVELOPMENT.md`
- Current architecture and known problems: `CONTEXT.md`
- Product requirements: `docs/PRD.md`
- Active priorities: `docs/master-roadmap.md`
- Prompt contracts: `docs/prompt-engineering.md`

## Local Start

1. Install Python and frontend dependencies.
2. Create `.env` from the variable list in `docs/DEVELOPMENT.md`.
3. Ensure PostgreSQL is available.
4. Install Playwright Chromium.
5. Run:

```powershell
python main.py
```

`main.py` starts FastAPI and, unless disabled, the Vite development server.
The backend code default is port `8000`; the frontend default is `5173`.

Do not commit credentials, runtime reports, screenshots, traces, diagnostic
artifacts, or benchmark output.
