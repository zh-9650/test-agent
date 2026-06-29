# Smart Test Agent 项目总览

本文档是当前仓库的单文件说明，目标是用一份文档覆盖项目定位、运行方式、核心架构、主要模块、接口边界、前端页面、运行数据、已知限制和后续方向。

最后更新：2026-06-26

## 1. 项目是什么

Smart Test Agent 是一个 AI-native Web 测试平台。

它不是“生成一堆 Playwright 脚本”的工具，而是让模型在运行时直接充当测试人员：

- 读取需求和上下文资料
- 探索真实网页
- 生成结构化测试资产
- 选择可自动执行的候选用例
- 通过浏览器工具执行操作
- 基于页面证据做结果判断
- 持久化运行过程和最终结果
- 生成 HTML 报告

项目当前是单智能体、单生命周期主线，不是多智能体编排系统。

## 2. 核心原则

- 测试意图的权威输入是 `CandidateTestCase`
- 执行结果的权威输出是 `CaseResult`
- 一次执行边界由 `ExecutionRun` 表示
- 运行时通过浏览器工具调用执行，不生成维护型测试脚本
- 需求、规划、执行、报告都围绕同一套持久化结果集展开
- 报告失败不会回写执行结果
- 恢复执行只重跑最近一次运行里未通过的用例

## 3. 生命周期

当前维护中的生产生命周期是：

`analyzing -> exploring -> designing -> executing -> reporting`

含义如下：

1. `analyzing`
   从 PRD、Swagger、规则、原型、架构说明、变更记录中抽取需求事实与断言，并生成探索目标。
2. `exploring`
   打开真实目标页面，做受限探索，收集 `SystemMapEvid`。
3. `designing`
   根据文档证据和真实页面证据生成覆盖蓝图、测试条件、设计技术、覆盖项、候选用例、追溯矩阵和最终分析包。
4. `executing`
   对候选资产池做确定性筛选，只执行当前执行器支持的子集。
5. `reporting`
   从持久化的运行数据生成 HTML 报告。

## 4. 关键数据模型

项目主链路的数据形态如下：

`RequirementFact -> RequirementAssertion -> ExplorationGoal -> SystemMapEvid -> CoverageBlueprint -> TestCondition -> TestDesignTechnique -> CoverageItem -> CandidateTestCase -> TraceabilityMatrix -> TestAssetPackage`

### RequirementFact

原子化需求事实，来自 PRD、Swagger、规则、原型、架构文档或变更记录，保留来源和引用。

### RequirementAssertion

从事实推导出的“需要验证的系统义务”，不是摘要，不是测试步骤。

### ExplorationGoal

为了补全真实系统证据而生成的探索目标，描述“要找到什么证据”，而不是“要点击哪条路径”。

### SystemMapEvid

探索阶段得到的真实页面证据，包含：

- `PageMap`
- `ActionMap`
- `FormMap`
- `NavigationMap`

### CoverageBlueprint

基于断言和页面证据提炼出的模块、核心业务流和依赖关系。

### TestCondition

回答“在什么场景下验证什么”。

### TestDesignTechnique

回答“用什么测试设计方法覆盖该条件”。

### CoverageItem

回答“某个具体覆盖义务是什么”。

### CandidateTestCase

当前项目中最重要的测试资产。它是运行前的权威测试意图，不包含脆弱的固定 UI 点击脚本。

### TraceabilityMatrix

把事实、断言、条件、覆盖项和候选用例串起来，说明每个用例为什么存在。

### TestAssetPackage

分析和设计阶段的最终打包产物，持久化在任务上。

### ExecutionRun

一次执行边界。记录这次到底计划执行了哪些 `CandidateTestCase`。

### CaseResult

某个候选用例在某次运行中的唯一终态结果。

### TaskStep

某次运行中某个候选用例某次尝试下的步骤明细。重试会追加，不会删旧步骤。

## 5. 运行时权威关系

当前项目的权威关系是：

- 规划资产权威：`TestAssetPackage`
- 执行输入权威：`CandidateTestCase`
- 运行边界权威：`ExecutionRun`
- 终态结果权威：`CaseResult`
- 报告权威来源：`ExecutionRun + CaseResult + TaskStep + TestAssetPackage`

前端、REST、WebSocket、报告必须与这套权威数据一致。

## 6. 自动执行选择规则

系统不会盲目执行所有候选用例。

设计阶段会保留完整候选资产池，然后通过确定性规则选择自动执行集：

- `smoke`
- `balanced`
- `full`

不能自动执行的候选用例不会被丢弃，而是被明确标记为延后资产，常见原因包括：

- 需要浏览器开发者工具
- 需要查看页面源码
- 需要网络面板或直接 HTTP 请求能力
- 需要不支持的指针手势
- 依赖外部参考数据集
- 前置条件无法由 agent 自动满足

这类资产仍然保留在 `TestAssetPackage` 中，只是不进入本次自动执行。

## 7. 执行阶段做什么

执行阶段遵循：

`observe -> decide -> execute -> assert -> record`

### observe

读取当前页面语义信息，而不是把完整 DOM 粗暴塞给模型。

### decide

模型根据当前用例目标、预期结果、页面证据、前序失败信息和安全约束，决定下一步工具调用。

### execute

调用浏览器工具，例如：

- `click`
- `input_text`
- `navigate`
- `scroll`
- `wait`
- `select_option`

### assert

优先使用确定性证据做判断，例如：

- URL
- 标题
- heading
- modal
- error
- visible texts
- 表格文本
- DOM 属性
- 数值公式

只有确定性规则不足时，才回退到语义判断。

### record

把步骤、结果、截图引用、变化信息、终态依据等持久化。

## 8. 终态结果

每个计划执行的候选用例必须且只能产生一个终态结果：

- `passed`
- `failed`
- `skipped`
- `incomplete`
- `human_review_required`

任务级别、前端统计、WebSocket 最终汇总、HTML 报告都要从同一批 `CaseResult` 推导。

## 9. 后端主要模块

### `main.py`

统一启动入口。负责加载环境、启动后端，并在启用时拉起前端开发服务器。

### `api/`

FastAPI API 层。

- `api/app.py`
  主应用与路由
- `api/schemas.py`
  REST 输入输出模型
- `api/websocket.py`
  WebSocket 连接和消息管理
- `api/utils.py`
  文档解析、URL 获取等辅助接口

### `core/task_lifecycle.py`

当前生产主线的生命周期编排器。

它负责：

- 输入预处理
- 阶段切换
- 调用探索和设计
- 创建 `ExecutionRun`
- 执行选中的候选用例
- 写报告

当前项目里，它是比 LangGraph 更直接的运行时权威。

### `core/runtime.py`

浏览器探索与单次用例尝试执行的核心逻辑。

### `core/runtime_session.py`

浏览器资源的生命周期包装层，负责：

- 打开浏览器
- 关闭浏览器
- 在一个会话内串起探索和执行
- 处理重试

### `core/execution_store.py`

执行数据持久化层，负责：

- 创建运行
- 写入/更新结果
- 追加步骤
- 汇总运行状态
- 处理取消和失败补全

### `core/run_report.py`

从持久化数据生成 HTML 报告。

### `core/page_semantic.py`

从页面中提取语义层信息，包括：

- 可交互元素
- headings
- visible_texts
- 表单控件
- iframe
- shadow root
- tabs

### `core/runtime_tool_contract.py`

运行时工具名称和 prompt 示例的共享契约，避免 prompt 与执行器脱节。

### `core/skills/`

分析与设计阶段的模块化能力，包括：

- `fact_extractor.py`
- `assertion_deriver.py`
- `coverage_planner.py`
- `condition_analyzer.py`
- `technique_selector.py`
- `coverage_analyzer.py`
- `case_generator.py`
- `traceability_builder.py`
- `asset_packager.py`
- `execution_selector.py`
- `quality_gates.py`
- `l2_pipeline.py`

### `database/`

数据库连接与 SQLAlchemy 模型定义。

## 10. 前端页面

前端位于 `frontend/`，使用 React 19 + TypeScript + Vite。

主要页面：

- `TaskCreate`
  创建任务，输入目标 URL、账号、规则、PRD、Swagger、架构说明、原型、变更记录、执行策略等。
- `Monitor`
  观察任务运行过程、阶段变化、WebSocket 消息和摘要。
- `Report`
  查看运行报告和步骤细节。
- `TaskHistory`
  查看历史任务、状态和最近一次运行摘要。
- `MemoryManager`
  管理全局或域级记忆数据。
- `AnalysisPackage`
  查看分析包、质量门、候选用例与延后资产等。

## 11. API 能力概览

当前主要 API 能力包括：

- 任务创建、查询、删除
- 步骤查询
- 运行查询
- 结果查询
- 报告查询
- 停止任务
- 恢复任务
- 诊断产物查询
- 记忆 CRUD
- 文档解析
- URL 内容抓取
- WebSocket 任务流

## 12. 数据库存储内容

当前 PostgreSQL 中主要存这些内容：

- `Task`
- `ExecutionRunRecord`
- `CaseResultRecord`
- `TaskStep`
- `Report`
- `AgentMemory`

这个阶段不使用 Alembic 迁移流程，启动时创建表。

## 13. 本地运行方式

### 环境要求

- Python 3.11+
- Node.js 18+
- PostgreSQL 14+
- Playwright Chromium
- 可用的模型访问凭据

### 安装

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
Set-Location frontend
npm install
Set-Location ..
```

### 启动

```powershell
python main.py
```

默认情况下：

- 后端端口：`8000`
- 前端端口：`5173`

如果设置 `START_FRONTEND=false`，则只启动后端。

## 14. 常用环境变量

关键环境变量包括：

- `ANTHROPIC_AUTH_TOKEN`
- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_MODEL`
- `DATABASE_URL`
- `BACKEND_PORT`
- `FRONTEND_PORT`
- `START_FRONTEND`
- `MAX_STEPS_PER_CASE`
- `MAX_CONSECUTIVE_FAILURES`
- `MAX_TEST_CASE_RETRIES`
- `MAX_CASE_ATTEMPT_SECONDS`
- `LLM_REQUEST_TIMEOUT_SECONDS`
- `LLM_MAX_RETRIES`
- `ANALYZING_PHASE_TIMEOUT_SECONDS`
- `EXPLORING_PHASE_TIMEOUT_SECONDS`
- `DESIGNING_PHASE_TIMEOUT_SECONDS`
- `EXECUTING_PHASE_TIMEOUT_SECONDS`
- `MAX_EXPLORE_PAGES`
- `MAX_EXPLORE_MINUTES`
- `BROWSER_HEADED`
- `BROWSER_RECORD_VIDEO`
- `L2_USE_CDP`
- `L2_PARALLEL_TOOLS`
- `DIAG_ENABLED`
- `DIAG_FULL`

## 15. 调试和诊断

项目支持诊断产物输出。

启用方式：

- 设置 `DIAG_ENABLED=true`

诊断文件写到：

- `data/diag/{task_id}/`

用于排查：

- 某个阶段的输入输出
- 规划与执行链路中的偏差
- 真实页面证据与最终结论不一致的问题

诊断数据属于运行时产物，不应提交到仓库。

## 16. 已知限制

当前已知限制包括：

- 生命周期层有全局锁，同一时刻有效执行是串行的
- memory 目前主要是存储和管理能力，还没有真正接入规划和执行主流程
- CDP 分辨率和并行工具执行仍然是 feature-gated
- 独立 API 执行能力尚未落地
- 多智能体执行尚未落地
- 生命周期检查点/恢复机制尚未完整实现

## 17. 当前维护边界

当前项目明确不做：

- 生成长期维护型 Playwright/Selenium 脚本
- 在仓库里保存测试夹具、benchmark、历史阶段文档、评估报告
- 把运行时诊断产物提交进 Git

## 18. 当前优先方向

当前 P4 方向是平台化增强，重点包括：

- 生命周期检查点与恢复
- 把 memory 从 CRUD 变成真实运行输入
- 独立 API 执行能力
- 更多报告格式和趋势分析
- 部署与安全加固

多智能体执行是后续项，但前提是单智能体基线继续稳定。

## 19. 修改这个项目时要遵守什么

- 改代码前先理解现有模式，不要引入无谓新抽象
- 保持提示词为中文
- 不要硬编码产品特定登录流
- 不要把浏览器操作写死成可维护脚本
- 变更影响 API、前端、运行时、WebSocket、报告时，要做真实端到端验证
- 不要提交凭据、运行数据、截图、诊断产物

## 20. 一句话总结

这是一个“让模型在真实浏览器里做测试，并把规划、执行、证据和报告统一到一条运行时主线”的 Web 测试平台；当前是单智能体、强约束、重证据、可追溯的架构形态。
