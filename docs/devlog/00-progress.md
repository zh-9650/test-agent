# AI Native Testing Platform — 开发进度

> 由 Lead 维护，记录全局进度和关键决策时间线。

## 全局进度

| 步骤 | 模块 | 状态 | 队友 | 开始 | 完成 | DevLog |
|------|------|------|------|------|------|--------|
| 0 | Agent 定义 + 接口定义 | ✅ | Lead | 2026-05-28 | 2026-05-28 | - |
| 1 | 项目骨架 | ✅ | core-dev | 2026-05-28 | 2026-05-28 | 01-scaffolding.md |
| 2 | 接口定义 | ✅ | Lead (pre-launch) | 2026-05-28 | 2026-05-28 | 02-interfaces.md |
| 2b | 数据库 models | ✅ | api-dev | 2026-05-28 | 2026-05-28 | 02b-database.md |
| 3 | Page Semantic Layer | ✅ | core-dev | 2026-05-28 | 2026-05-28 | 03-page-semantic.md |
| 4 | LLM Client | ✅ | core-dev | 2026-05-28 | 2026-05-28 | 04-llm-client.md |
| 5 | Playwright 工具函数 | ✅ | graph-dev | 2026-05-28 | 2026-05-28 | 05-tools.md |
| 6 | Change Detector | ✅ | core-dev | 2026-05-28 | 2026-05-28 | 06-change-detector.md |
| 7 | 执行子图 | ✅ | graph-dev | 2026-05-28 | 2026-05-28 | 07-execution-graph.md |
| 8 | 规划子图 | ✅ | graph-dev | 2026-05-28 | 2026-05-28 | 08-planning-graph.md |
| 9 | 完整 Runtime | ✅ | graph-dev | 2026-05-28 | 2026-05-28 | 09-runtime.md |
| 10 | ExecutionLogger + ReportBuilder | ✅ | core-dev | 2026-05-28 | 2026-05-28 | 10-logger-report.md |
| 11 | FastAPI 后端 | ✅ | api-dev | 2026-05-28 | 2026-05-28 | 11-fastapi.md |
| 12 | WebSocket | ✅ | api-dev | 2026-05-28 | 2026-05-28 | 12-websocket.md |
| 13 | React 前端 | ✅ | frontend-dev | 2026-05-28 | 2026-05-28 | 13-frontend.md |
| 14 | Phase 1.5 修复与测试 | ✅ | Lead | 2026-05-30 | 2026-05-30 | 14-phase15-fixes.md |
| 15 | [Phase 2] V1: System Modeling Agent | ✅ | core-dev | 2026-05-31 | 2026-05-31 | 15-phase2-v1-system-modeler.md |
| 16 | [Phase 2] V1.1/V1.2: Goal-Driven Graph | ✅ | Lead | 2026-05-31 | 2026-05-31 | 16-phase2-v1.1-v1.2-graph-refactor.md |
| 17 | [Phase 2] V1.3: Knowledge Extraction IR | ✅ | Lead | 2026-06-01 | 2026-06-01 | 17-layer1-knowledge-extraction.md |
| 18 | [Phase 2] V1.4: Use Case Scaffold | ✅ | Lead | 2026-06-01 | 2026-06-01 | 18-layer1-usecase-scaffold.md |
| 19 | [Phase 2] V1.5: Layer 1 鲁棒性 + 报告可观测性 | ✅ | Lead | 2026-06-01 | 2026-06-01 | 19-layer1-hardening.md |
| 20 | [Phase 2] V1.6+V1.7: L1+Phase 1.5 prompt 全面加固 + 盲点修复 + L1 收尾 | ✅ | Lead | 2026-06-01 | 2026-06-01 | 20-layer1-prompt-engineering-v17.md |
| 21 | [Phase 2] V2.0 v1: L2 全面加固计划 (A+B+C+D, 4 阶段, 4 commit) | 📋 Plan v1 → v2 | Lead | 2026-06-01 | 2026-06-01 | 21-layer2-v2.0-plan.md + `docs/layer2-v2.0-plan.md` |
| 22 | [Phase 2] **Phase 1.6**: N2+explore+SystemMap 三件套加固 (插在 V2.0 A 之前) | 📋 Plan | Lead | 2026-06-01 | 待执行 | 21-layer2-v2.0-plan.md §3.0 |

## 队友分配

| 队友 | 模型 | 负责文件 | 任务 |
|------|------|---------|------|
| core-dev | kimi-k2.6 (sonnet) | core/ | 步骤 1, 2, 3, 4, 6, 10, 15 |
| graph-dev | glm-5.1 (opus) | agents/ | 步骤 5, 7, 8, 9 |
| api-dev | kimi-k2.6 (sonnet) | api/ + database/ + main.py | 步骤 2b, 11, 12 |
| frontend-dev | deepseek-v4-flash (haiku) | frontend/ | 步骤 13 |
| Lead | Claude | 全局 | 步骤 14 (Phase 1.5 修复) |

## 全局决策时间线

| 时间 | 决策 |
|------|------|
| 2026-05-28 前置 | Agent Teams 配置设计完成（14 个决策已记录到 CONTEXT.md） |
| 2026-05-28 | Lead 完成 3 项前置：4 个 agent 定义 + core/interfaces.py + devlog 目录 |
| 2026-05-28 | Phase 1 全部 13 步完成。14 commits, 41 Python files, 70 files changed, 8706 lines added |
| 2026-05-28 | 115/116 tests passing (1 test isolation issue, passes in isolation) |
| 2026-05-28 | 执行方式：Subagent-Driven Development (sequential dispatch with model selection) |
| 2026-05-29 | **核心架构升级 (Scheme 2)**：页面语义提取（Page Semantic Layer）从原生的 Playwright CSS Locator 彻底替换为 `browser-use` 库的 Accessibility Tree 提取方案，同时使用 CDP (Chrome DevTools Protocol) 桥接实现了与 Playwright 框架的无缝兼容。提升了复杂DOM的交互准确率（如解决登录框提取失败的问题），并完美保留了 Playwright 原有的 trace 与录屏功能。 |
| 2026-05-30 | **Phase 1.5 修复**：修复 Risk Analyzer 字段名不一致、Scenario Extractor 集成、SessionSummary 列表响应处理、环境变量覆盖、ReportBuilder AI Summary 等 8 个问题。端到端测试验证通过。 |
| 2026-05-31 | **Phase 2 - V1 重构**：引入 `System Modeling Agent`，强行解析 PRD 提炼系统的状态流转与业务链路，并作为上下文注入 Scenario Extractor，彻底解决了生成脱离实际的“幽灵用例”问题。 |
| 2026-05-31 | **Phase 2 - V1.1/V1.2 重构**：完成 `Goal Extractor` 与 `System Mapper`，改造 `planning_graph` 拓扑为目标驱动流水线 (`extract_goals` -> `explore` -> `generate_map` -> `extract_scenarios`)，实现了认知-探索-规划闭环。 |
| 2026-06-01 | **Phase 2 - V1.3 重构**：重构认知提取架构为中间表达层 (IR)，新增 `KnowledgeBase` 事实库提炼，并将 `SystemModel` 升级为严谨的“轻量级状态机 (State Machine)”表达，通过优先级目标进一步优化探索 Agent 规划。 |
| 2026-06-01 | **Phase 2 - V1.4 改进**：在知识提取后加入 `UseCaseModel` (Node 1.5)，作为状态机生成的坚实脚手架。同时为知识事实引入了 `quote` 追溯指针，最大程度削减模型幻觉。 |
| 2026-06-01 | **Phase 2 - V1.5 加固**：针对 Qwen 等 Anthropic 兼容端点对 `with_structured_output` 支持不完整的问题，在 `core/llm_client.py` 统一了 `safe_structured_invoke` 入口（原生结构化 + 手动 JSON 解析双轨）。同时把 Node 1.7 覆盖率自检报告接入 HTML 报告，前端 `testLayer1` 增加 SSE `progress: "error"` 抛错识别。`scratch/test_layer1.py` 端到端验证通过。 |
| 2026-06-01 | **Phase 2 - V1.6 加固**:5 个 L1 skill 的 prompt 全部重构为 `<role>`/`<context>`/`<task>`/`<rules>`/`<examples>`/`<output_contract>` 5 段 XML 结构,沉淀 L1↔L2 节点契约(`docs/prompt-engineering.md`)。引入 `tests/core/test_l1_prompts.py` 回归测试(4 fixtures × 7 不变量 = 28 用例),修复 6 个设计漏洞。 |
| 2026-06-01 | **Phase 2 - V1.7 收尾**:把 V1.6 模式扩展到 Phase 1.5 三个 skill (`risk_analyzer` / `scenario_extractor` / `session_summary`),同时把 `scenario_extractor` / `session_summary` 从裸 `llm.ainvoke().content` 切换到 `safe_structured_invoke`。修复 L1 验证报告盲点 B (`unknown_actor` 显式化,CoverageReport 新增 `unknown_actor_count` + HTML 报告展示) 和盲点 C (fast-path 90% 阈值加 8 行 docstring)。盲点 A 确认非盲点。新增 24 个 Phase 1.5 回归测试。**L1 + Phase 1.5 全部 prompt 加固完成,53 mock + 8 live skip 全过,L1 收尾。** 下一步: V1.6 模式迁移到 L2 `execution_graph.py`(prompt 调用 hot path,每步 1 次)。 |

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
