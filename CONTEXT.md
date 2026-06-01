# Context: Smart Test Agent (AI 智能测试平台)

## 1. 项目定位与目标 (Project Goal)

构建一个重度 AI 参与的**探索与巡检测试工具** —— 这是一个典型的 **Agentic Manual（具身智能体）** 架构。
系统通过接收自然语言的目标指令或测试用例，利用 AI 主动分析网页结构（基于 Accessibility Tree），并自动规划和执行 Web 自动化交互操作，最终基于页面上下文自动对每一步的执行结果进行智能化双层断言，从而生成详尽的测试报告。

**主要输入**：URL、测试账号、配置参数、业务说明
**主要输出**：实时执行日志流（WebSocket）、执行截图、录屏/Trace、断言结果与 HTML 测试报告。

> **核心定位说明**：本项目不追求 CI/CD 中毫秒级的绝对确定性和低执行成本，而是定位于“极低维护成本、无需编写任何测试脚本”的智能巡检系统。执行慢、Token 消耗大是其定位带来的合理代价。

## 2. 核心架构与技术栈

整个测试任务的生命周期由 LangGraph 状态机驱动，分为两个阶段的异步执行子图：

*   **前端 (Frontend)**：`React` + `Vite`。包含任务创建、监控面板（左侧执行日志流，右侧实时截图）、测试报告页。
*   **后端 (Backend)**：`FastAPI`。提供 RESTful API，承载前后端的数据通信，并管理后台基于 `asyncio` 的异步测试任务流。
*   **核心引擎 (Core Engines)**：
    *   **编排框架**：基于 `LangGraph` 构建的 StateGraph。
    *   **交互底座**：原生 `Playwright` (支持 Trace 和视频) + `browser-use` 库（负责将复杂 DOM 提纯为扁平化的无障碍交互树）。
*   **持久化 (Database)**：采用 `PostgreSQL` + `SQLAlchemy` ORM。核心表：`Task`, `TaskStep`, `Report`, `AgentMemory`。

## 3. 架构层级演进蓝图 (Phased Design Roadmap)

根据最新的架构研讨，系统路线图调整为聚焦“高收益、低复杂度”的务实演进路线：

### [已完成] Phase 1: 基础闭环固化与端到端联调 (Foundation & MVP)
*   **当前状态**：基于 LangGraph 的编排入口、UI Agent、WebSocket 与 FastAPI 基础已成型。
*   **核心目标**：知识注入 -> 探索 -> 生成用例 -> 执行。
*   **已完成**：并发争抢（加锁串行化）与记忆污染（域名隔离）已解决，前端能稳定跑通主流程。

### [已完成] Phase 1.5: 高价值能力扩充 (Value Amplification)
*   **修复状态**：2026-05-30 完成 8 个问题修复，端到端测试验证通过。
*   **Risk Analyzer (风险分析器)**：探索页面后，自动识别高风险元素（金额、库存等），优先生成边界值/异常用例。
*   **Scenario Extractor (业务场景提取)**：从 PRD 提取具体的业务流程（如“发货流程”），实现 Goal Driven 探索，而非无目的的 Page Driven。
*   **Session Summary (任务级记忆压缩)**：Case 结束后压缩上下文，形成 Task 级别的局部记忆，同时大幅降低 Token 消耗。
*   **Coverage Tracking (覆盖率追踪)**：统计并报告“页面覆盖率”和“业务场景覆盖率”，提供直观的测试价值度量。
*   **断言分级 (Hierarchical Assertion)**：执行后优先走规则断言（URL/元素/接口状态），最后再走大模型判定，降低成本与误判率。

### [进行中] Phase 2: 高级系统架构 (Advanced Architecture) - 【当前焦点】
*   **V1~V1.4 架构升级 (已完成)**：引入 `KnowledgeExtractionLayer` (含追溯指针) 与 `UseCaseModel`，将 `SystemModelingAgent` 升级为基于脚手架的轻量级状态机，实现带优先级的 `Goal-Driven Explorer`。实现“认知 -> 脚手架 -> 建模 -> 探索 -> 验证 -> 规划”完整闭环，极大地削弱了大模型幻觉。
*   **后续焦点**：Business Graph 数据库、Reflection 自我反思循环、跨任务的长期 Memory 沉淀、多 Agent 协同。

### Phase 3: 自主测试团队 (Autonomous Testing Team)
*   完全自主接管产品迭代的回归测试。

## 4. 关键技术决策 (Key Decisions)

1.  **全面拥抱 browser-use 树**：抛弃极度不稳定的纯 CSS/XPath 抓取，利用 `browser-use` 提取页面 Accessibility Tree，大大提高了大模型对页面的理解能力。
2.  **动态上下文与记忆 (RAG)**：在执行测试前，通过 `retrieve_memories(target_url)` 向提示词中注入历史学习到的“测试经验”。
3.  **防 Token 爆炸的上下文管理**：单用例内超过 10 条交互记录时，丢弃中间信息，只保留最近的上下文，依赖 LangGraph Checkpoint 进行状态管理。
4.  **Action Timeline 设计**：不走“代码生成再跑”的老路，每一步都是“Thought + Action + Result + Assertion”的实时博弈。
5.  **Robust Retry 重试兜底**：在 AI 调用环节实现异步指数退避重试机制，以应对大模型 API 严格的 Rate Limit 429 报错。
6.  **配置文件与启动机制**：开发期由 `main.py` 统管，同时拉起 Uvicorn 和 Vite 进程。

## 5. 最近技术升级与架构演进 (Latest Upgrades - Phase 1.5+)

在端到端联调中，为了解决并发争抢、Token 爆炸与断言不准确等问题，系统已实际上线以下硬核架构升级：

### 1. 并发与资源隔离 (Concurrency & Database)
*   **全局串行锁与浏览器隔离**：在 API 调度层加入了严格的任务串行执行队列（或分布式锁），彻底解决多个任务抢占同一个 Playwright Browser Context 导致的串台问题。
*   **PostgreSQL 全面接管**：摒弃了初期的 SQLite 方案，现在全部状态持久化（Task, TaskStep, Report, AgentMemory）已平滑迁移至强类型的 PostgreSQL + SQLAlchemy 异步 ORM 架构，支持海量测试数据与并发连接。

### 2. 状态机流转与执行优化 (Execution Optimizations)
*   **Hierarchical Assertion (层次化规则断言)**：在 `assert_node` 中引入了“规则优先”的熔断机制。如果检测到明显的 JS Error、Network Error，或者中间步骤页面无任何变化，系统会立即使用规则判定（Pass/Fail/Inconclusive）并跳过 LLM。只有发生实质性页面变化时，才由 LLM 执行语义判定。此举大幅减少了“睁眼说瞎话”和 Token 浪费。
*   **Session Summary (跨 Case 记忆传递)**：在 `runtime.py` 的执行流中，每完成一个 TestCase，会调用轻量级 LLM 将执行过程压缩成百字以内的摘要（`session_summary.py`）。这个摘要会被注入到下一个 Case 的 `SystemMessage` 顶部。这使得大模型能像人类一样拥有“贯穿整个 Test Session 的记忆”，比如能记住“之前已经完成登录了，现在可以直接测业务”。

### 3. 高级探索与展示 (Exploration & Report)
*   **Knowledge Extraction (层级 1 知识提取)**：引入 `knowledge_extractor` 专门应对长篇复杂的 PRD。模型首先扮演无情的“规则阅读器”，将文本提纯为硬核的带有溯源指针 (quote) 的 `KnowledgeBase`（包括业务实体、角色、规则与约束条件）。这一层避免了后续由于幻觉导致的系统建模偏差（V1.3/V1.4升级）。
*   **UseCase Scaffold (用例脚手架)**：引入 `use_case_modeler` 在生成状态机前，先将零散知识聚合为带有 trigger 和 outcome 的原子级 `UseCaseModel`，填补了推断状态机的断层鸿沟（V1.4升级）。
*   **System Modeling Agent (状态机建模)**：强制根据提炼出的脚手架和事实库，推导系统的整体状态流转（Lightweight State Machine），而非松散的业务流文本（`SystemModel`），彻底解决了模型生成脱离实际的“幽灵用例”问题（V1.3/V1.4升级）。
*   **Goal-Driven Explorer (目标驱动探索)**：引入了 `Goal Extractor`，将状态机转化为带有明确优先级 (High/Medium/Low) 的业务级探索目标。现在大模型带着“作战任务”去页面里翻找入口，极大提升了图谱的导航效率（V1.1/V1.3升级）。
*   **System Mapper (实际页面地图提取)**：在带目标探索结束后，收集探索历史并输出包含页面真实控件分布的结构化 `SystemMap`。它与文档认知合并，作为 `Scenario Extractor` (场景提取器) 的双管齐下指导，保证了规划出的 Test Case 具备真实执行基础（V1.2升级）。
*   **Premium Web Report (高端数据看板)**：测试结果的 HTML 报告已抛弃原始模板，重构为现代暗黑极客风（Sleek Dark Mode + Glassmorphism）。不仅具备覆盖率实时进度条，还具备详细的 AI 总结呈现，显著提升产品高级感。

