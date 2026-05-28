# AI Native Testing Platform — 开发进度

> 由 Lead 维护，记录全局进度和关键决策时间线。

## 全局进度

| 步骤 | 模块 | 状态 | 队友 | 开始 | 完成 | DevLog |
|------|------|------|------|------|------|--------|
| 0 | Agent 定义 + 接口定义 | ✅ | Lead | 2026-05-28 | 2026-05-28 | - |
| 1 | 项目骨架 | ⏳ | core-dev | - | - | 01-scaffolding.md |
| 2 | 接口定义 | ⏳ | core-dev | - | - | 02-interfaces.md |
| 2b | 数据库 models | ⏳ | api-dev | - | - | 02b-database.md |
| 3 | Page Semantic Layer | ⏳ | core-dev | - | - | 03-page-semantic.md |
| 4 | LLM Client | ⏳ | core-dev | - | - | 04-llm-client.md |
| 5 | Playwright 工具函数 | ⏳ | graph-dev | - | - | 05-tools.md |
| 6 | Change Detector | ⏳ | core-dev | - | - | 06-change-detector.md |
| 7 | 执行子图 | ⏳ | graph-dev | - | - | 07-execution-graph.md |
| 8 | 规划子图 | ⏳ | graph-dev | - | - | 08-planning-graph.md |
| 9 | 完整 Runtime | ⏳ | graph-dev | - | - | 09-runtime.md |
| 10 | ExecutionLogger + ReportBuilder | ⏳ | core-dev | - | - | 10-logger-report.md |
| 11 | FastAPI 后端 | ⏳ | api-dev | - | - | 11-fastapi.md |
| 12 | WebSocket | ⏳ | api-dev | - | - | 12-websocket.md |
| 13 | React 前端 | ⏳ | frontend-dev | - | - | 13-frontend.md |

## 队友分配

| 队友 | 模型 | 负责文件 | 任务 |
|------|------|---------|------|
| core-dev | kimi-k2.6 (sonnet) | core/ | 步骤 1, 2, 3, 4, 6, 10 |
| graph-dev | glm-5.1 (opus) | agents/ | 步骤 5, 7, 8, 9 |
| api-dev | kimi-k2.6 (sonnet) | api/ + database/ + main.py | 步骤 2b, 11, 12 |
| frontend-dev | deepseek-v4-flash (haiku) | frontend/ | 步骤 13 |

## 全局决策时间线

| 时间 | 决策 |
|------|------|
| 2026-05-28 前置 | Agent Teams 配置设计完成（14 个决策已记录到 CONTEXT.md） |
| 2026-05-28 | Lead 完成 3 项前置：4 个 agent 定义 + core/interfaces.py + devlog 目录 |

## 依赖关系

```
步骤 1 (骨架, core-dev)
  ├── 步骤 2 (interfaces.py, core-dev)
  │     ├── 步骤 3 (Page Semantic, core-dev)
  │     ├── 步骤 4 (LLM Client, core-dev)
  │     ├── 步骤 5 (工具函数, graph-dev)
  │     └── 步骤 6 (Change Detector, core-dev)
  │           └── 步骤 7 (执行子图, graph-dev) ← 依赖 3,4,5,6
  │                 └── 步骤 8 (规划子图, graph-dev)
  │                       └── 步骤 9 (Runtime, graph-dev)
  │                             └── 步骤 11 (FastAPI, api-dev)
  │                                   └── 步骤 12 (WebSocket, api-dev)
  │                                         └── 步骤 13 (前端, frontend-dev)
  └── 步骤 2b (DB models, api-dev)
        └── 步骤 11 (FastAPI, api-dev)
```

## 备注

- 步骤 10 (ExecutionLogger + ReportBuilder) 可与步骤 7-9 并行
- 步骤 2b (DB models) 只依赖步骤 1，可与步骤 2-6 并行
