# Frontend

React 19 + TypeScript + Vite frontend for Smart Test Agent.

## Pages

- `TaskCreate`: rich task input and submission
- `Monitor`: WebSocket lifecycle stream
- `Report`: generated report and execution details
- `TaskHistory`: historical task list
- `MemoryManager`: global/domain memory CRUD

## Commands

```powershell
npm install
npm run dev
npm run build
npm run lint
```

The default development port is `5173`. API and WebSocket contracts are shared
through `src/api/client.ts`, `src/hooks/useWebSocket.ts`, and `src/types/index.ts`.

When those contracts change, update the backend producer and frontend consumer
in the same change, then run `npm run build` and `npm run lint`.
