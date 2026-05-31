# 智能测试框架业务流程规范 (Business Workflow)

本文档基于最新版本的 `test_agent` 系统架构编写，全面梳理了从测试任务下发到最终报告产出的全链路闭环流程。

---

## 一、 系统架构概览

我们的测试框架是一个典型的 **“输入配置增强 -> 大模型智能规划 -> 大模型接管端到端执行 -> 智能聚合断言与报告”** 的闭环自动化平台。

整个系统的运行以 `Task` (任务) 为核心载体，流转于后端的调度引擎中，最终产生详细的 `TaskStep` (步骤执行记录) 和 `Report` (智能报告)。

---

## 二、 完整业务生命周期详解

### 1. 任务创建与文档动态提取阶段 (Input & Enrichment)

当用户通过外部接口（如通过前端表单触发，最终请求 `POST /api/tasks`）发起一项测试任务时，不仅支持传入基础的规则，还支持通过外链动态拉取研发需求文档。

1. **输入参数解析**：
   接收 `CreateTaskRequest` 请求，包含：
   - `target_url`: 测试主入口（如目标系统首页）
   - `config`: 测试配置。涵盖：
     - `credentials`: 用于自动登录的测试账号。
     - `rules`: 验收标准和业务规则。
     - `focus_areas`: 重点测试的页面或功能。
     - **增强字段**: `prd` (产品需求文档 URL)、`api_doc` (接口文档 URL)、`changelog` (变更日志 URL)。

2. **后台异步抢占调度**：
   任务以 `pending` 状态写入数据库，后台由 `core/runtime.py` 的轮询任务或者直接调起 `_run_test_session`，通过异步锁 (`_task_execution_lock`) 抢占执行权，将状态置为 `running`。

3. **动态文档解析 (Document Parser)**：
   在正式规划用例前，系统调用 `core/document_parser.py`。
   - 使用正则匹配 `config` 中的 PRD、API 文档 URL 链接。
   - 后台静默启动无头浏览器 (Playwright)，自动前往这几个 URL 并抓取其富文本内容 (`document.body.innerText`)。
   - 将抓取回来的长文本**拼接组装**，替换原有的简短配置，生成 `enriched_config`。
   > **意义**：这一步让底层 AI 摆脱了原始链接，拿到了真实的文档文本。

4. **系统认知建模 (System Modeling Agent) [Phase 2 - V1]**：
   - 提取出文档纯文本后，送入 `core/skills/system_modeler.py` 技能模块。
   - 强制 LLM 提炼出当前系统的四大维度地图：`modules` (模块), `roles` (角色), `business_flows` (业务流), `states` (状态)。
   - **意义**：这一步如同人类测试员在脑海中建立业务全景图，彻底消除了生成“不存在的虚假测试用例”的可能。认知地图随后被固化到数据库 `Task.config["_system_model"]`。

### 2. 测试用例智能规划阶段 (LLM Planning Graph)

系统将扩充了认知地图的 `enriched_config` 送入 `agents/planning/graph.py` 中的 LangGraph 规划流。在这个阶段，引擎不碰目标系统，而是纯调用大模型完成“大脑层”的推理。

1. **风险分析 (Risk Analyzer)**：
   使用长篇文档、目标 URL 和 `focus_areas`，利用大模型推断该系统潜在的脆弱点和测试优先级。
2. **场景提取 (Scenario Extractor)**：
   结合刚刚建立的认知模型地图 (`system_model`)，基于文档约束进一步发散，拆解出最符合真实业务的、高维度的测试场景（如：提交订单、审批驳回等）。
3. **测试计划生成 (Test Plan Generator)**：
   最终，将上述提取的场景下放，由大模型自动生成一份完全结构化的 **Test Plan**（如 `TC-001`, `TC-002`）。
   每个测试用例 (Test Case) 包含：
   - 用例 ID 和用例目标。
   - 前置条件 (`preconditions`)，如“必须处于已登录状态”。
   - 执行步骤与预期结果 (`expected_outcome`)。

规划完成后，Test Plan 将被持久化到数据库 `Task` 表。

### 3. 端到端智能执行与交互阶段 (UI Execution Graph)

这是系统最核心的“动作”环节。引擎遍历规划好的所有 Test Case，针对每一个用例启动 `agents/ui/execution_graph.py` 状态机（LangGraph）。

对于每个用例，循环执行以下链路：

1. **纯净环境加载**：
   - 彻底拦截上游缓存：引擎调用 `page.goto("about:blank")` 和 `localStorage.clear()`，彻底杜绝 Chromium 的历史表单回填机制与 Cookie 污染，确保每个测试环境的独立和纯净。
   - 重定向到用例专属的 `target_url`。
2. **前置条件处理 (Setup Sub-graph)**：
   - 如果用例需要已登录态，自动调起一个子流程（借用 `config.credentials`）处理登录交互。
3. **环境感知观察 (Observe Node)**：
   - 调用 `browser-use` 封装的DOM解析，结合 `core/page_semantic.py`。
   - 扫描当前页面的所有输入框、按钮、超链接等，为其打上交互标签（例如：`#308` 登录按钮）。
   - 调用 `take_screenshot` 捕获页面截图，留存证据。
4. **大模型决策引擎 (Decide Node)**：
   - 大模型看到“当前页面元素列表”、“历史已执行步骤”、“测试目标”，结合自身的判断力，推断下一步该进行何种动作（使用 `input_text`, `click`, `evaluate_js`, 或标记 `mark_task_complete` 终止）。
5. **行为映射与执行 (Execute Node)**：
   - 引擎调用 `agents/ui/tools.py` 解析模型的决策。
   - 针对 `click '#308'` 这样的指令，通过强悍的 `_resolve_element` 底层算法：不仅匹配 `placeholder`、`label`，更兼顾了通过 `value` 属性寻找诸如 `input[type="submit"]` 这种“隐身”交互按钮。
   - 使用 Playwright 引擎对真实浏览器元素发出点击、填充、执行 JS 等信号。
6. **动态分层断言 (Hierarchical Assert Node)**：
   - 操作完成后立刻评估。调用 `core/hierarchical_assert.py`，观察 DOM 是否有变。
   - 判断：当前步骤是继续（`inconclusive`），还是测试通过（`pass`，满足了预期结果），亦或是出现了明显业务错误/系统崩溃（`fail`）。
7. **执行快照保存 (Record Node)**：
   - 将这单步操作记录序列化写入 `TaskStep` 数据表，以便前台能够回放用户的每一步点击和对应的屏幕截图。

*此流程 (3~7) 会陷入循环，直至用例执行成功或抛出异常中断。*

### 4. 结果聚合与报告生成阶段 (Reporting)

当所有的测试用例执行完毕后，执行链路关闭，最后进行数据聚合。

1. **Session Summary (智能聚合总结)**：
   系统调用 `core/skills/session_summary.py`，将刚刚所有的交互步骤、断言结果“喂”给 LLM。
   大模型根据冰冷的日志，写出具有人类逻辑的“长难句总结”（例如：“本次测试主要验证登录模块，在输入了 xxx 之后跳转到了 xxx 页面，验证符合预期。”）。
2. **报告渲染 (Report Builder)**：
   调用 `core/report_builder.py`，组合生成的智能总结、执行耗时、成功率、甚至关键失败步骤的截图。
   最终生成一份结构化的 HTML `Report`。
3. **状态终结**：
   通过 WebSocket 发送测试结束广播，更新任务数据库的状态为 `completed`（或遇到系统级故障标记为 `failed`）。

---

## 三、 本次核心改进点 (Phase 1.5 总结)

系统在最近的迭代中针对自动化链路做了两项历史遗留“死角”攻坚：

1. **动态解析增强体系**：使得我们从传统的黑盒“盲猜测试”，升级为直接读取产研需求文档的“白盒感知测试”。
2. **全栈抗污染防御**：采用 `about:blank` 斩断原生浏览器跨刷新状态缓存，彻底杜绝 `React` 等 SPA 框架状态不同步的问题。
3. **表单解析算法强化**：精准识别 `type="input"` 且具有 `value` 的 `submit` 按钮事件拦截，大大提升了 Web 应用常规表单操作的通过率。

## 四、 Phase 2 核心进化 (V1.1 & V1.2)

1. **Goal Driven Explorer (V1.1 目标驱动探索)**：
   引入了 `Goal Extractor`，将 `system_model` 中的业务流转化为明确的导航目标。探索节点在 Prompt 中被强制注入这些目标，使得 Playwright 执行探索时“有的放矢”，大大提升了巡检效率。
2. **System Map 融合 (V1.2 实际系统地图)**：
   在带目标探索结束后，系统汇集所有的探索历史，输出包含页面真实控件分布的结构化 `System Map`。它与文档认知 (`system_model`) 合并，作为 `Scenario Extractor` 的双管齐下指导，彻底保证了 Test Case 的生成具备真实的 UI 入口和操作依据。
