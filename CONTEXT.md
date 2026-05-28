# Context: AI 测试智能体平台

## Project Goal

构建一个 AI Native Testing Platform —— AI 自主理解系统、自主执行测试、自主分析风险、自主生成报告。

输入：URL、Swagger/OpenAPI、PRD文档、测试规则、测试账号、业务说明
输出：UI测试结果、API测试结果、探索式测试结果、执行日志、截图、测试报告、AI分析总结、禅道Bug记录

## Glossary

### Agent
负责理解与决策的 LLM 实体。Agent 不直接操作底层工具，而是输出结构化意图（intent）。

### Skill
负责执行能力的原子化模块。接收 Agent 的意图，执行具体操作（如点击、输入、HTTP请求）。

### Intent（意图）
Agent 输出的操作指令。在 tool calling 方案下，intent 就是 LLM 的 tool_call 输出（如 `click(target="登录按钮")`），不需要自定义 JSON 格式。

### Runtime
负责状态管理与流程控制的执行引擎（基于 LangGraph）。管理任务生命周期、上下文、Skill/Agent 调度、错误恢复。

### Page Semantic Layer（页面语义层）
禁止将完整 DOM 输入 LLM。页面需经过摘要提取，输出结构化语义（page_type、buttons、inputs、forms、tables）。

## Agents

| Agent | 职责 | 构建阶段 |
|-------|------|---------|
| UI Testing Agent | 页面理解、元素识别、UI操作、UI断言 | Phase 1 |
| Explorer Agent | 探索式测试、随机探索、主动风险发现 | Phase 2 |
| API Testing Agent | Swagger解析、接口测试、参数生成、异常测试（复用公共模块） | Phase 3 |
| Assertion Agent | 跨UI/API的统一断言逻辑（从Skill升级为独立Agent） | Phase 4 |
| Report Agent | 结果聚合、失败原因分析、AI总结、报告生成 | Phase 5 |
| Planner Agent | 顶层协调：理解测试目标、拆分任务、调度其他Agent | Phase 6 |

## Shared Modules (Phase 1)

所有 Agent 共用的基础设施，Phase 1 交付：

| 模块 | 作用 |
|------|------|
| **Runtime** | LangGraph 流程引擎，管理任务生命周期、状态、错误恢复 |
| **RuntimeState** | 统一任务状态模型（task_id、current_step、logs、errors 等） |
| **SkillRegistry** | Skill 注册与调度，Agent 声明需要哪些 Skill |
| **Tool Calling** | 用 LangChain `@tool` + `bind_tools()` 替代自定义 IntentProtocol，LLM 原生工具调用格式即为 intent |
| **LLM Client** | 统一模型连接（Anthropic SDK + 百炼 Anthropic 兼容接口），含重试、超时、token 统计。Prompt/Parser 由各自 Agent 定义 |
| **ExecutionLogger** | 步骤日志持久化 |
| **ReportBuilder** | 报告生成骨架，各 Agent 填充各自内容 |

## Key Decisions

- **Intent-based 而非代码生成型**：系统不走"AI生成Playwright脚本再执行"的路线。Agent 实时决策、实时执行、实时观察，每一步输出 intent 由 Skill 执行。（2026-05-27）
- **6个独立Agent，分阶段构建**：目标是完整的 Planner/UI/API/Explorer/Assertion/Report 六个独立 Agent，但按依赖顺序逐步交付，每个阶段都能独立运行。（2026-05-27）
- **Tool Calling 替代自定义 IntentProtocol**：不自己定义 intent JSON 格式，直接用 LangChain 的 @tool 装饰器定义工具 + bind_tools() 绑定到模型。LLM 输出的 tool_calls 就是 intent，tools_by_name 字典就是分发。各 Agent 各自定义自己的 @tool 函数。（2026-05-27）
- **规则约束引擎延后**：Phase 1 不建 Rule Engine，后续再加。（2026-05-27）
- **页面语义层采用 A+B 结合方案**：Playwright locator API 提取可交互元素（第1-3层：交互元素、页面结构、状态信息），截图给 LLM 做视觉理解（第4层）。提取脚本框架无关，不依赖特定前端框架。（2026-05-27）
- **页面语义层只定原则不定格式**：文档层面定义 5 条约束（①每个可交互元素必须有编号供 LLM 精确引用 ②三层信息：交互元素+页面结构+状态 ③单页提取结果不超过 2000 tokens ④框架无关 ⑤输出为 Python dict）。具体 JSON schema 在代码中用 Pydantic model 定义，开发时根据 LLM 实际效果迭代调整。（2026-05-27）
- **目标测试系统前端框架不确定**：平台需通用，不绑定特定 UI 框架（Ant Design/Element/自研等）。提取层基于 Playwright locator API，天然兼容 Shadow DOM、异步加载、iframe 等。（2026-05-27）
- **断言采用双层架构**：规则层只做"发生了什么"的事实检测（URL变化、元素增删、JS报错、网络错误、弹窗、错误提示），不做对错判断；LLM层结合intent+变化报告+截图做语义判断（"这个变化对不对"）。规则层不绑定任何业务逻辑。（2026-05-27）
- **先规划后执行（两阶段子图模式）**：Agent 先读取需求文档/规则生成测试计划（结构化用例列表），再按计划逐条执行。LangGraph 子图隔离规划与执行阶段的上下文。测试计划本身充当长期记忆，不占用 LLM 上下文窗口。（2026-05-27）
- **上下文管理策略**：①test_plan/results 为结构化数据不占上下文窗口 ②每个用例结束后清空 messages，只留一句话总结（如"TC-003 通过"）注入下一个用例 ③SystemMessage 每次重新注入，不依赖历史消息 ④当前用例步骤和预期每次都重新注入 ⑤单个用例内超过 5 步时，更早的步骤压缩为摘要，只保留最近 5 步完整对话（用 trim_messages 实现）。LangGraph Checkpoint 支持中断恢复。（2026-05-27）
- **前置条件由 Agent 智能执行**：规划阶段 AI 生成 setup（如"用 admin 账号登录"），执行阶段复用 observe→decide→execute 循环执行 setup，Agent 自己看懂页面、找到输入框、填写账号密码、点登录。不写死任何 login 函数，setup 就是一个迷你测试用例。（2026-05-27）
- **测试步骤用自然语言**：测试计划中的 steps 是给执行阶段 LLM 看的任务说明书，不需要结构化指令。LLM 结合页面语义摘要 + 自然语言步骤来实时决策。（2026-05-27）
- **规划阶段信息来源**：有什么用什么——URL、需求文档、Swagger、测试账号、测试规则均可。信息越多计划越完整，只有 URL 也能测。（2026-05-27）
- **前端实时监控**：Phase 1 包含前端执行监控面板（类 Cursor Agent），通过 WebSocket 实时推送 Agent 状态、AI思考过程、执行日志、截图。LangGraph astream() + FastAPI WebSocket。（2026-05-27）
- **模型选型**：阿里云百炼平台 Anthropic 兼容接口（token-plan.cn-beijing.maas.aliyuncs.com/apps/anthropic）。主模型 qwen3.7-max（规划/决策），轻量模型 deepseek-v4-flash（简单任务），中等模型 kimi-k2.6（执行），强力模型 glm-5.1（复杂推理）。LLM Client 使用 Anthropic SDK。Tool calling 已验证可用（Claude Code 本身即通过此接口运行，重度依赖 tool calling）。注意：百炼官方文档为 OpenAI 兼容接口，Anthropic 兼容接口为 token-plan 专用端点。（2026-05-27）
- **本地运行**：Phase 1 先本地跑（python main.py），不 Docker 化。（2026-05-27）
- **可扩展性原则**：所有设计必须考虑后续扩展，新增 Agent 不影响现有功能，公共模块只放所有 Agent 共用的东西。（2026-05-27）
- **Action Timeline 记录 AI 思考**：每步记录 thought + action + result + assertion。Phase 1 用 LLM 自然输出的 reasoning text（AIMessage.content），后续通过改 prompt 升级为结构化 JSON，不改代码。（2026-05-27）
- **Session Replay（Playwright Trace + 录屏）**：Phase 1 即加入。每个测试用例生成 trace.zip 和 video.webm，用于调试 Agent 行为和事后回放。实现成本极低（<10行代码）。（2026-05-27）
- **Error Taxonomy 延后**：错误分类（locator_error/timeout_error/assertion_error/business_error/js_error/network_error）Phase 1 不加，后续再做。（2026-05-27）
- **Confidence Score 延后**：需要结构化输出才有意义，与 Phase 1 自然输出的决定矛盾，后续加。（2026-05-27）
- **Test Strategy Layer 先用 prompt 实现**：Phase 1 在规划阶段的 prompt 中嵌入测试策略思维（风险分析、边界分析、业务流分析），不改架构。后续如果效果不好，可以把 prompt 中的各策略拆成独立模块（risk_analyzer、boundary_analyzer、flow_analyzer），各自调用 LLM 再汇总。（2026-05-27）
- **页面业务语义理解延后到 Phase 2**：Phase 1 的页面语义层只提取元素+结构+状态，不做"这个页面在业务上是什么"的判断。Phase 2 Explorer Agent 时再加（observe 节点中多一次 LLM 调用判断业务含义）。（2026-05-27）
- **Memory System 延后，数据先行**：Phase 1 不加 Memory 模块，但 task/task_step/report 表的设计已在为 Memory 做数据积累。后续加 Memory 时只需增加一个读取层，从历史数据中提炼知识供规划阶段参考。（2026-05-27）
- **Phase 1 前后端同步开发，过程中逐步验证**：不拆子阶段，后端和前端一起做。每完成一个模块就验证（建好 Page Semantic Layer 验证 observe，建好 tool calling 验证 decide+execute，建好断言验证完整循环）。（2026-05-27）
- **执行子图拓扑：LLM 自主判断 + 双安全阀**：decide 节点判断是否完成——有 tool_calls 则继续执行，无 tool_calls 则用例结束。两道安全阀兜底：①连续 3 次操作失败 → 标记 failed 跳下一个用例；②单用例达到 15 步上限 → 标记 incomplete 跳下一个用例。两个数字放配置文件，不改代码可调。（2026-05-27）
- **数据库统一用 PostgreSQL**：开发和生产都用 PostgreSQL，不用 SQLite。开发环境需本地安装 PostgreSQL。（2026-05-27）
- **Prompt 设计原则**：全部用中文。文档只定义每个 prompt 的意图和要点，不写完整文本（完整 prompt 在代码中迭代）。四个 prompt 场景：①规划 prompt（生成测试计划）②执行 prompt（每步决策，最频繁）③断言 prompt（操作后判断结果）④总结 prompt（全部结束后）。Prompt 中用表格编码决策逻辑（参考 .claude/skills/ 中的 auto-case-writer、playwright-explorer、test-reporting 的模式）。（2026-05-27）
- **规划阶段先探索再规划**：规划阶段用 observe→decide 循环让 AI 自主探索目标系统——AI 自己决定看哪些页面、点哪些导航，收集足够的页面信息后再生成测试计划。两道安全阀：①已探索页面数达到上限（默认 20）②探索时间超过上限（默认 5 分钟）。两个数字放配置文件。探索代码复用执行阶段的 observe→decide 循环和 Page Semantic Layer。（2026-05-27）
- **规划阶段输出用 tool calling 约束 JSON**：不依赖自然语言解析，用一个 create_test_plan tool 定义约束输出格式（参数为 TestCase schema），LLM "调用"这个 tool 即输出结构化测试计划，代码直接解析 tool_call 参数。（2026-05-27）
- **前端四个页面**：TaskCreate（创建任务表单）、Monitor（实时监控）、Report（测试报告）、TaskHistory（历史任务列表，独立页面）。Monitor 页面左侧显示 AI 思考+操作日志，右侧显示浏览器截图，每步更新一张（不做实时视频流）。TaskCreate 表单不限制用例数量，AI 规划多少跑多少。（2026-05-27）
- **测试账号方案**：支持多账号，每个账号含角色名/用户名/密码。规划阶段将账号信息注入 prompt，AI 自行决定哪些用例需要登录、用哪个账号，可规划出"不同角色测权限"的用例。密码 Phase 1 存明文在 task.config，代码预留加密接口。（2026-05-27）
- **配置文件用 .env**：Python 侧用 python-dotenv 加载。必须配置的：API Key、API 地址、数据库连接、三个模型名。可选的（有默认值）：MAX_STEPS_PER_CASE=15、MAX_CONSECUTIVE_FAILURES=3、BACKEND_PORT=8000、FRONTEND_PORT=5173。用户只需填 API Key 和数据库地址就能跑。（2026-05-27）
- **WebSocket 消息格式**：7 种消息类型——page_update（observe 后）、ai_thinking（decide 后）、action_result（execute 后）、assertion_result（assert 后）、setup_progress（setup 执行中）、test_case_complete（用例结束）、session_complete（全部结束）。每条消息统一格式：{type, test_case_id, step_index, data, timestamp}。通过 LangGraph .astream() 接收节点更新，转成消息格式推送。（2026-05-27）
- **截图和文件存文件系统**：截图、Trace、录屏、HTML 报告全部存磁盘，数据库只存相对路径。目录结构：data/screenshots/{task_id}/{test_case_id}/step_N.png，data/sessions/{task_id}/{test_case_id}/trace.zip 和 video.webm，data/reports/{task_id}/report.html。（2026-05-27）
- **后端 API 只定能力不定路由**：文档定义 7 项能力（创建任务、查看任务列表、查看任务详情、实时 WebSocket 推送、拉取历史步骤、查看/下载报告、停止任务），具体路由命名、请求/响应格式在代码中由 Claude Code 开发时确定。（2026-05-27）
- **Change Detector 内嵌在 assert 节点**：不单独设节点。assert 节点内先跑 Change Detector（纯 Python 函数对比 state_before/state_after 生成 ChangeReport），再调 LLM 做语义判断。（2026-05-27）
- **浏览器生命周期**：单个浏览器实例贯穿整个测试会话。Browser context 按需切换（不按用例切换）——登录状态有效就复用，失效才关旧建新。Trace 和录屏按用例粒度录制（用例开始→用例结束保存）。浏览器崩溃时捕获异常、重启浏览器、从当前用例恢复执行，已完成的结果不丢。（2026-05-27）
- **Playwright 工具只定原则**：每个工具是 @tool 装饰的 Python 函数，docstring 即 LLM 可见的说明。执行成功返回简短描述（"已点击 #3"），失败返回错误信息（不抛异常）。Phase 1 最小工具集：navigate、click、input_text、scroll、wait，其他按需添加。具体参数设计在代码中迭代。（2026-05-27）
- **数据库自动初始化**：main.py 启动时自动检测并创建 smart_test 数据库（SQLAlchemy create_all()），不用 Alembic 迁移。用户装好 PostgreSQL 就能直接 python main.py。（2026-05-27）
- **开发顺序（自底向上，每步验证）**：①项目骨架（目录/依赖/.env）→ ②数据库 models → ③Page Semantic Layer → ④LLM Client → ⑤工具函数 → ⑥Change Detector → ⑦执行子图 → ⑧规划子图 → ⑨完整 Runtime → ⑩Execution Logger + Report Builder → ⑪FastAPI 后端 → ⑫WebSocket → ⑬React 前端。开发验证用的测试目标：http://192.168.31.155/login?redirect=/ai-talk/index（账号 test_c / 123456）。（2026-05-27）
- **Phase 1 单任务串行**：同一时间只跑一个测试任务，新任务排队等当前任务完成后自动开始。后续支持并发时再改。（2026-05-27）
- **前端无登录**：Phase 1 本地运行，四个页面打开即用，不需要用户认证。（2026-05-27）
- **启动方式**：开发时前后端分别启动（后端 uvicorn + 前端 npm run dev）。python main.py 作为统一入口，自动启动两者。生产部署时前端 build 为静态文件由 FastAPI 托管。（2026-05-27）
- **需求文档支持格式**：Phase 1 支持 .txt 和 .md（纯文本直接读取）。PDF 支持用 pdfplumber 提取文本。（2026-05-27）
- **开发方式：Claude Code Agent Teams 全自动编排**：使用 Agent Teams 功能进行开发。Lead（主会话）全自动编排，按模块拆分给 4 个队友（core-dev / graph-dev / api-dev / frontend-dev），队友间可互相讨论接口细节。Lead 负责全局任务依赖图、分配、进度追踪。全程记录决策和编码过程：每个模块产出开发记录（docs/devlog/），Lead 维护全局进度和决策日志。不做人工阶段性审批，Lead 自主推进。（2026-05-28）
- **接口约定机制：接口先行 + 部分并行**：core-dev 先写 core/interfaces.py（Pydantic model + 函数签名，无实现），完成后 graph-dev 和 api-dev 立即并行开工（读真实接口写代码）。core-dev 继续填充实现但不改签名。frontend-dev 等 api-dev 出 API 接口后再开工。队友间发现接口问题时通过 SendMessage 协商，协商结果记录到 docs/devlog/。（2026-05-28）
- **开发记录格式（DevLog）**：每个模块一个文件（docs/devlog/NN-module-name.md），包含：①决策记录（选项对比 + 选择理由）②接口变更（改了什么 + 通知了谁）③编码要点（关键实现细节）④验证结果（跑了什么 + 结果如何）。Lead 维护 docs/devlog/00-progress.md 全局进度表 + 全局决策时间线。（2026-05-28）
- **Agent Teams 队友配置**：4 个队友按模块分区——core-dev（core/）、graph-dev（agents/）、api-dev（api/ + database/ + main.py）、frontend-dev（frontend/）。不限制工具集，靠 spawn prompt 约束文件写权限（可读任何文件，只写自己的）。模型分配：graph-dev 用 glm-5.1（Opus，最复杂），core-dev 和 api-dev 用 kimi-k2.6（Sonnet，中等），frontend-dev 用 deepseek-v4-flash（Haiku，最简单）。qwen3.7-max 留给 Lead 做全局编排。（2026-05-28）
- **13 步任务分配**：core-dev 负责步骤 1/2/3/4/6（骨架+接口+Page Semantic+LLM Client+Change Detector）；graph-dev 负责步骤 5/7/8/9（工具函数+执行子图+规划子图+Runtime）；api-dev 负责步骤 2b/11/12（数据库+FastAPI+WebSocket）；frontend-dev 负责步骤 13（React 前端）。并行节奏：core-dev 完成接口文件（步骤 2）后解锁 core-dev/graph-dev/api-dev 三线并行；frontend-dev 等 api-dev 完成后开工。（2026-05-28）
- **验证策略：TDD 全流程，Lead 不做代码验证**：每个队友遵循 TDD 循环（Red→Green→Refactor），先写测试再写实现。测试不只是单元测试，也包括用真实依赖的集成测试。每个模块完成后在测试目标（http://192.168.31.155/login）上做真实验证，结果记录到 devlog。上游未完成时用 interfaces.py 的接口 mock 依赖，上游完成后替换为真实依赖重跑测试。Lead 只负责调度和进度把控，不亲自跑代码验证。（2026-05-28）
- **Agent 定义文件放项目级**：4 个 agent 定义（core-dev.md / graph-dev.md / api-dev.md / frontend-dev.md）放在项目 .claude/agents/ 下，跟着项目走。定义为项目定制（prompt 包含具体模块路径、CONTEXT.md 引用、测试目标），不做通用模板。（2026-05-28）
- **Git 提交策略：每模块完成一次 commit**：每个模块完成并通过验证后提交一次，commit message 格式 `feat(模块区域): 描述`（如 `feat(core): page semantic layer`）。devlog 文件随对应模块一起提交。不做 squash，开发过程中不频繁 commit。（2026-05-28）
- **共享资源冲突处理：requirements.txt 一次写完**：core-dev 在项目骨架阶段（步骤 1）根据 PRD.md 一次性写完所有已知依赖（fastapi、langchain、langgraph、langchain-anthropic、playwright、sqlalchemy、psycopg2 等），其他队友不再修改此文件。后续如发现缺包，谁发现谁补一行。（2026-05-28）
- **错误处理：主动监控 + 3 次失败报告**：队友在 spawn prompt 中被要求"连续 3 次尝试同一问题失败时，必须通过 SendMessage 向 Lead 报告，停止重试"。Lead 收到后决定换方案、换队友或暂停等用户确认。Lead 定期审查 devlog 检查是否有越界文件修改。与测试平台"3 次连续失败跳过"的安全阀理念一致。（2026-05-28）
- **团队启动策略：全部同时创建**：4 个队友同时拉起。等待上游依赖完成的队友先读 CONTEXT.md、PRD.md 和测试目标熟悉项目，等接口文件出来后直接上手。不省等待期的 token，避免 Lead 分阶段创建的判断失误风险。（2026-05-28）
- **Skill 使用：全部开放**：队友可自由使用所有可用 skill（superpowers + 用户级 skill），包括 test-driven-development、verification-before-completion、brainstorming 等。不限制也不强制，队友按需自行调用。（2026-05-28）
- **启动方式：先写基础设施再启动团队**：在创建团队前，先由 Lead 完成 3 项前置工作：①写 4 个 .claude/agents/*.md 定义文件 ②写 core/interfaces.py 骨架（Pydantic model + 函数签名）③写 docs/devlog/ 目录结构。团队启动后所有队友直接对着接口干活，不用等。（2026-05-28）
