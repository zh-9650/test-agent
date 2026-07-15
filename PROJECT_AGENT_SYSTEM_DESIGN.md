# Smart Test Agent Agent 化系统设计说明

本文是 Smart Test Agent 的目标设计主文档。它不是代码改造记录，也不是学习笔记，
而是回答一个产品和架构问题：

```text
这个项目到底应该如何按 Agent 设计路线来设计，下一步开发应该照什么方向做？
```

结论先写在前面：Smart Test Agent 不应该被改造成一个完全自主 Agent，也不应该现在
改成 multi-agent 系统。它应该被设计成一个 **证据驱动的 Web 测试 agentic workflow**：

```text
确定性生命周期主干
+ 局部 Agent 决策循环
+ 受限工具合同
+ 结构化证据链
+ 可中断 HITL
+ Eval / Trace / Metrics
+ 渐进接入 Memory / RAG
```

最后更新：2026-07-03

## 1. 文档定位

本文是唯一保留的 Agent 化系统设计文档。前面按学习路线拆过阶段草稿，包括
Agent vs Workflow、Agent 基本构件、目标形态判断和工具设计；这些内容已经合并到本文。

后续开发、评审和任务拆分都以本文为入口，不再维护多份阶段性设计文档，避免结论分散和
版本漂移。

## 2. 总体判断：要不要 Agent

### 当前项目是什么

当前项目已经不是普通 workflow，也不是完全自主 Agent，而是强约束 agentic workflow。

生产主线是：

```text
analyzing -> exploring -> designing -> executing -> reporting
```

核心证据：

- `core/task_lifecycle.py` 的 `TaskLifecycleService.run_test_session()` 控制阶段顺序、
  阶段超时、失败补全、执行选择、运行完成和报告生成。
- `core/skills/l2_pipeline.py` 负责从需求事实到测试资产包的结构化设计管线。
- `core/runtime.py` 负责真实浏览器里的探索循环和单用例执行循环。
- `core/runtime_tool_contract.py` 定义生产工具合同。
- `core/runtime_action_policy.py` 对模型动作做确定性 guardrail。
- `core/interfaces.py` 定义 `CandidateTestCase`、`ExecutionRun`、`CaseResult`、
  `TaskStep`、`TestAssetPackage` 等权威协议对象。

### 是否应该做成完整 Agent

不应该。

原因：

- 测试平台的核心价值是可追溯、可审计、可复现和可信报告。
- 完全自主 Agent 会让阶段边界、预算、终态判断和报告事实来源变得不稳定。
- 当前 `ExecutionRun -> CaseResult -> TaskStep -> Report` 的权威链条是优点，不能削弱。
- Agent 自主性应该局部增强，而不是把整个生命周期交给模型。

### 是否应该做成 multi-agent

当前不应该。

multi-agent 可以作为后续扩展，但不是下一阶段目标。原因是当前更基础的能力还没稳：

- 工具返回还没有完整结构化。
- HITL 还不是暂停、审批、编辑、恢复的闭环。
- Eval 和 trajectory 指标还不完整。
- Memory 有 CRUD，但还没有进入规划和执行主链路。
- 生命周期仍有全局锁，平台化队列和资源治理还没完成。

在这些基础没稳之前，上 multi-agent 只会增加任务分配、冲突仲裁和失败归因成本。

## 3. 目标产品形态

目标形态：

```text
Evidence-driven Test Agentic Workflow
```

中文可以叫：

```text
证据驱动的测试 Agentic Workflow
```

它的含义是：

- 生命周期由代码编排，不由模型自由决定。
- LLM 只在需要语义判断、动态探索、测试设计生成或动作选择的位置出现。
- 所有 LLM 输出必须被 schema、工具合同、guardrail、质量门、HITL 或 eval 收口。
- 测试成功必须由证据证明，不能靠模型宣布。
- 报告必须来自持久化事实，不允许 LLM 重写事实。

## 4. 设计原则

### 原则 1：确定性主干保留

这些必须由代码决定：

- 阶段顺序。
- 阶段超时。
- 任务状态变化。
- 运行创建和完成。
- 失败、取消时补齐未终态结果。
- 质量门是否中止。
- 自动执行用例筛选。
- 报告生成。
- 工具权限和安全策略。

### 原则 2：局部 Agent，而不是全局 Agent

只有两个阶段应该有运行时 agent loop：

- `exploring`：为了在真实页面中动态找证据。
- `executing`：为了根据当前页面状态动态执行 `CandidateTestCase`。

其他阶段更适合 workflow / prompt chain：

- `analyzing`：结构化抽取事实和断言。
- `designing`：结构化生成测试资产。
- `reporting`：确定性渲染报告。

### 原则 3：权威对象先于模型输出

模型不能直接决定“系统真相”。系统真相必须落在权威对象上：

- `RequirementFact`：需求事实。
- `RequirementAssertion`：可验证断言。
- `ExplorationGoal`：探索目标。
- `SystemMapEvid`：真实页面证据。
- `CandidateTestCase`：执行前测试意图。
- `ExecutionRun`：一次执行边界。
- `TaskStep`：步骤证据。
- `CaseResult`：用例终态。
- `Report`：事实渲染结果。

### 原则 4：成功靠证据，不靠声明

执行阶段不应开放 `mark_task_complete` 给模型。这一点当前设计是正确的。

用例通过只能来自：

- 确定性页面证据。
- 或受限语义判断形成的 `TerminalAssertion`。
- 最终写入唯一 `CaseResult`。

### 原则 5：先评估，再扩自主性

任何新增自主能力都必须有 eval 回答：

- 成功率是否提高。
- 成本和延迟是否可接受。
- 失败是否更容易定位。
- 是否增加人工接管率。
- 是否降低报告可信度。

## 5. 按 Agent 设计路线的阶段结论

### 第 1 阶段：Agent vs Workflow

结论：保持 agentic workflow，不做完整自主 Agent。

当前固定 workflow：

```text
analyzing -> exploring -> designing -> executing -> reporting
```

LLM 决策点：

- 抽取事实。
- 推导断言。
- 判断探索证据是否足够。
- 选择探索动作。
- 生成测试条件、覆盖项和候选用例。
- 判断执行终态。
- 选择执行动作。

目标改造：

- 保留 `TaskLifecycleService` 的主干权威。
- 明确哪些节点允许 LLM 决策。
- 每个 LLM 决策都要有结构化输出或工具合同。

### 第 2 阶段：Agent 基本构件

结论：已有基本构件，但要统一协议。

已有能力：

- prompt chain 分布在 `core/skills/*.py`。
- 运行时 prompt 分布在 `core/runtime.py`。
- `safe_structured_invoke()` 提供结构化 LLM 调用和 JSON 恢复。
- `BrowserAction` 把运行时动作限制为 `{tool, args}`。
- `ActionResult` 已存在，但生产路径没有充分使用。

目标改造：

- 保持 Pydantic schema 作为协议层。
- 减少 prompt 和 schema 双写漂移。
- 运行时动作参数从自由 dict 逐步升级为 typed schema。
- 保留现有 `ActionResult` 给宽工具库使用，新增 `RuntimeToolResult` 作为生产工具合同结果。

### 第 3 阶段：工具设计

结论：生产工具合同要保持窄，但返回值必须结构化。

当前生产工具：

```text
click
navigate
scroll
input_text
select_option
wait
mark_task_complete
mark_task_failed
```

执行阶段开放：

```text
click
navigate
scroll
input_text
select_option
wait
mark_task_failed
```

目标改造：

- 建立 L0-L3 工具权限等级。
- 生产工具统一返回 `RuntimeToolResult`。
- blocked、failed、timeout、not_found 等状态有标准错误码。
- `TaskStep` 记录结构化工具结果。
- 报告展示工具失败原因。

### 第 4 阶段：编排模式

结论：短期继续使用当前自研生命周期编排，不急着引入 LangGraph。

当前编排：

```text
TaskLifecycleService
-> generate_exploration_goals
-> RuntimeSession.explore
-> run_l2_pipeline
-> select_execution_cases
-> create_execution_run
-> RuntimeSession.execute
-> finalize_execution_run
-> build_run_report
```

目标编排：

```text
Deterministic Orchestrator
+ Phase Contracts
+ Checkpoints
+ Resume Policy
+ Event Stream
+ Resource Budget
```

应该改：

- 把每个阶段的输入、输出、失败策略写成阶段合同。
- 把 resume 从“只重跑未通过用例”升级为检查点恢复策略。
- 区分 task 状态、phase 状态、run 状态、case 状态。
- 保留 WebSocket 事件流，但事件 payload 要更结构化。

暂不做：

- 不为了概念完整而引入复杂图编排框架。
- 不让模型动态决定跳过阶段或重排阶段。

### 第 5 阶段：记忆、知识库和上下文工程

结论：Memory 先只读接入，不自动写入。

当前状态：

- `AgentMemory` 数据表已存在。
- `api/app.py` 有 `/api/memory` CRUD。
- 前端有 `MemoryManager` 页面。
- 但 memory 没有进入 analyzing、designing、executing 主流程。

目标设计：

1. 只读召回。
   - 按 domain、target_url、scope_type 召回少量记忆。
   - 注入 analyzing/designing prompt。
   - 不覆盖需求事实，只作为上下文提示。

2. 执行辅助。
   - 注入常见页面术语、登录提示、业务概念。
   - 不注入 secret 原文。

3. provenance。
   - 标注哪些设计结论使用了 memory。
   - 报告中能显示 memory 引用。

4. 写入控制。
   - 初期禁止自动写 memory。
   - 后续写入必须经过人工确认或 eval 门槛。

暂不做：

- 不做无约束长期记忆。
- 不让旧 memory 覆盖新的 PRD / Swagger / rules。
- 不把失败轨迹直接写入长期记忆。

### 第 6 阶段：Human-in-the-loop 和安全边界

结论：当前只有人工审核标记，还没有完整 HITL 闭环。

已有能力：

- 高风险断言会进入 `manual_review_items`。
- `human_review_required` 是 `CaseResult` 的终态之一。
- `Report` 和 `Monitor` 能显示需人工数量。
- `agents/ui/tools.py` 有 `request_human_intervention()` 雏形，但生产路径未接入。

目标 HITL 闭环：

```text
pause
-> show evidence
-> user approve / edit / reject / provide input
-> resume
-> audit trail
-> report
```

触发场景：

- 高风险 security / data_rule 断言。
- L2/L3 工具请求。
- 需要验证码、MFA、人工登录。
- 连续定位失败。
- 终态证据冲突。
- retry exhausted。
- 需要 secret，但安全输入缺失。

安全边界：

- L0 只读工具默认可开放。
- L1 安全浏览器动作默认可开放。
- L2 特权检查默认关闭，HITL 后开放。
- L3 破坏性或跨边界动作默认禁止。

### 第 7 阶段：评估和可观测性

结论：这是当前最大缺口之一。

已有基础：

- `quality_gates.py` 对 `TestAssetPackage` 做确定性质量门。
- `diag_logger.py` 支持诊断产物。
- `ExecutionRun + CaseResult + TaskStep` 能还原部分执行轨迹。
- Playwright trace 写到 `data/sessions/{task_id}/trace.zip`。

目标 eval 分三层：

1. 资产 eval。
   - facts 是否有来源。
   - assertions 是否可验证。
   - cases 是否覆盖 trace references。
   - deferred 是否有原因。

2. 轨迹 eval。
   - 工具选择是否合理。
   - selector 失败率。
   - wait / scroll 是否空转。
   - terminal assertion 是否证据充分。

3. 产品 eval。
   - 报告能否解释结论。
   - 人工接管是否必要。
   - 成本、延迟、成功率是否可接受。

第一批 eval 样例至少 10 条，覆盖：

- 需求事实抽取。
- 冲突需求。
- 权限/安全断言。
- 表单流程。
- 列表/表格验证。
- 错误提示。
- 状态流转。
- 不可自动执行用例。
- 执行失败恢复。
- 报告可信度。

### 第 8 阶段：生产化

结论：生产化应该排在工具结构化、HITL、eval 之后。

当前限制：

- `TaskLifecycleService.execution_lock` 让有效执行串行化。
- `_running_tasks` 是进程内后台任务表。
- 没有队列、worker、租约、幂等检查点。
- 成本、延迟、模型调用、工具失败率没有统一指标面板。

目标生产化：

- 任务队列。
- worker 并发上限。
- browser session 池或资源配额。
- 同一 domain 的串行/并行策略。
- checkpoint 和 resume。
- 生命周期事件审计。
- 模型调用成本统计。
- 工具失败率统计。
- 人工接管率统计。

暂不做：

- 不在 eval 不稳前扩大并发。
- 不在 HITL 不完整前开放高权限工具。
- 不把诊断产物、截图、trace 提交进仓库。

## 6. 可开发协议

这一节把前面的方向性设计收敛成开发时必须遵守的协议。没有这些协议，HITL、Eval、
Memory 和工具结构化很容易再次散落到各个模块里。

### 6.1 RuntimeToolResult 决策

明确采用：

```text
ActionResult = 宽工具库结果模型
RuntimeToolResult = 生产运行时工具结果模型
```

原因：

- `ActionResult` 已被 `agents/ui/tools.py` 使用，适合保留为实验/候选工具结果。
- 生产路径需要更严格的阶段、权限、失败码、HITL 和 eval 字段。
- 新增 `RuntimeToolResult` 可以避免破坏宽工具库，同时让生产合同稳定。

`RuntimeToolResult` 最小字段：

```text
tool: string
phase: exploration | execution
permission_level: L0 | L1 | L2 | L3
status: success | blocked | failed | timeout | not_found | noop | completion_rejected
error_code: string
message: string
llm_feedback: string
args: object
normalized_args: object
before_url: string
after_url: string
url_changed: boolean
page_changed: boolean
changed_signals: object
selector_resolution: object
duration_ms: integer
evidence: object
hitl_required: boolean
hitl_reason: string
```

落库策略：

- 第一阶段不改表结构，`TaskStep.result` 保存 `message` 或 `llm_feedback`，
  `TaskStep.change_report` 保存 `changed_signals`，`TaskStep.action_args` 保存
  `normalized_args`。
- 第二阶段再新增 `tool_result JSONB` 和 `policy_decision JSONB`。

### 6.2 Phase Contract 模板

每个生命周期阶段必须有阶段合同。模板如下：

```text
phase:
owner:
input:
output:
authoritative_artifact:
llm_decision_points:
deterministic_rules:
timeout:
failure_policy:
checkpoint:
resume_policy:
events:
metrics:
```

当前阶段合同：

| Phase | Owner | Authoritative artifact | LLM 决策 | Failure policy | Resume policy |
|---|---|---|---|---|---|
| analyzing | `TaskLifecycleService` + `l2_pipeline` | facts / assertions / goals / partial package | facts、assertions、goals | 无 goals 则失败；高风险进入 manual review | 从已持久化 package 或重新分析恢复 |
| exploring | `RuntimeSession` + `Runtime` | `SystemMapEvid` / `GoalResult` | 证据是否足够、下一步动作 | 无页面证据或目标结果则失败；单 goal 可 insufficient | 可复用已发现 system map，按缺口 goal 继续 |
| designing | `l2_pipeline` | `TestAssetPackage` | conditions、techniques、coverage、cases | quality gate error 中止 | 从 facts/assertions/system map 重新生成 |
| executing | `RuntimeSession` + `Runtime` | `ExecutionRun` / `TaskStep` / `CaseResult` | 终态判断、下一步动作 | planned cases 必须补齐终态；retry exhausted 进入 human review | 创建 resumed run，仅重跑非 passed cases |
| reporting | `run_report` | `Report` | 无 | 报告失败不回写执行结果 | 可从持久化 run/results/steps/package 重建 |

### 6.3 HITL 状态机

HITL 不能只是 `human_review_required` 终态。目标状态机如下：

```text
running
-> paused_for_review
-> resumed
-> running
-> completed

running
-> paused_for_review
-> rejected
-> failed | cancelled

running
-> human_review_required
```

含义：

- `paused_for_review`：运行尚未结束，等待用户输入或审批。
- `resumed`：用户已处理，系统继续执行，可以复用当前 run 或创建 resumed run。
- `human_review_required`：当前 case 已经终态，需要人工后续处理，不再自动继续。

建议新增领域对象：

```text
HumanReviewRequest
- id
- task_id
- run_id
- candidate_case_id
- phase
- reason
- evidence_refs
- blocked_tool
- requested_at
- status: pending | approved | edited | rejected | expired

HumanReviewDecision
- request_id
- decision
- edited_inputs
- approved_tools
- comment
- decided_at
```

与现有不变量的关系：

- 如果执行暂停但尚未终态，不调用 `finalize_execution_run()`。
- 如果用户拒绝继续，未终态 case 仍必须通过 `fill_failed_results()` 或专门策略补齐。
- 如果用户选择恢复，优先创建 `resumed_from_run_id`，避免修改历史运行事实。

### 6.4 Eval Case Manifest

第一批 eval 不需要大平台，但需要固定格式。建议每条样例如下：

```json
{
  "id": "EVAL-001",
  "name": "登录表单错误提示",
  "target_url": "https://example.test/login",
  "inputs": {
    "prd": "...",
    "swagger": "",
    "rules": "...",
    "focus_areas": "登录校验"
  },
  "expected_assets": {
    "required_assertions": ["必须验证错误密码提示"],
    "required_case_titles": ["错误密码登录失败"],
    "deferred_allowed": true
  },
  "expected_execution": {
    "allowed_terminal_statuses": ["passed", "failed", "human_review_required"],
    "must_not_use_tools": ["evaluate_js"],
    "max_tool_failures": 3
  },
  "report_checks": {
    "must_explain_result": true,
    "must_include_traceability": true
  }
}
```

第一批 10 条样例至少覆盖：

- 需求事实抽取。
- 冲突需求。
- 权限/安全断言。
- 表单流程。
- 列表/表格验证。
- 错误提示。
- 状态流转。
- 不可自动执行用例。
- 执行失败恢复。
- 报告可信度。

### 6.5 MemoryContext 规则

Memory 先只读接入，不能覆盖需求事实。

建议上下文对象：

```text
MemoryContext
- scope_type
- scope_value
- memory_key
- memory_value
- source_domain
- confidence
- last_used_at
- provenance
```

召回规则：

- 每次最多注入 5 条。
- domain / target_url 精确匹配优先于 global。
- 明确过期、低置信或与当前 PRD/rules 冲突的 memory 不注入。
- memory 只能作为提示，不得生成新的 `RequirementFact` 来源。
- 报告中标注使用过的 memory key，便于审计。

## 7. 目标架构总图

```text
User / API / Frontend
        |
        v
TaskLifecycleService
  deterministic lifecycle owner
        |
        +-- analyzing
        |     LLM structured extraction
        |     RequirementFact / RequirementAssertion / ExplorationGoal
        |
        +-- exploring
        |     local agent loop
        |     observe -> assess evidence -> tool action -> SystemMapEvid
        |
        +-- designing
        |     structured L2 pipeline
        |     CoverageBlueprint / CandidateTestCase / TraceabilityMatrix
        |
        +-- execution selection
        |     deterministic routing
        |     ExecutionSelection
        |
        +-- executing
        |     local agent loop
        |     RuntimeExecutableCase -> TaskStep -> CaseResult
        |
        +-- reporting
              deterministic rendering
              Report from persisted facts
```

横向能力：

```text
Tool Contract
Action Policy
HITL
Memory
Eval
Trace / Metrics
Persistence
```

## 8. 模块职责边界

### API 层

位置：

- `api/app.py`
- `api/schemas.py`
- `api/websocket.py`

职责：

- 接收任务。
- 查询任务、运行、结果、报告。
- 停止和恢复任务。
- 管理 memory。
- 推送生命周期事件。

不应该承担：

- 阶段编排逻辑。
- 浏览器执行逻辑。
- 测试资产生成规则。

### 生命周期层

位置：

- `core/task_lifecycle.py`

职责：

- 阶段顺序。
- 任务状态。
- 运行创建。
- 阶段超时。
- 失败和取消补齐。
- 报告触发。

后续应该补：

- 阶段合同。
- checkpoint。
- 队列和资源策略。

### 设计管线层

位置：

- `core/skills/*.py`
- `core/skills/l2_pipeline.py`

职责：

- 事实抽取。
- 断言推导。
- review gate。
- 覆盖设计。
- 用例生成。
- 追溯矩阵。
- 质量门。

后续应该补：

- eval 指标。
- memory 只读上下文。
- 冲突事实更显式。

### 运行时层

位置：

- `core/runtime.py`
- `core/runtime_session.py`
- `core/page_semantic.py`

职责：

- 打开浏览器。
- 页面观察。
- 探索 loop。
- 执行 loop。
- 动作执行。
- 终态判断。
- 重试。

后续应该补：

- `RuntimeToolResult`。
- 工具轨迹记录。
- HITL pause/resume。
- selector failure metrics。

### 工具层

位置：

- `core/runtime_tool_contract.py`
- `core/runtime_action_policy.py`
- `agents/ui/tools.py`

职责：

- 生产工具合同。
- 工具权限。
- 动作策略。
- 宽工具候选池。

后续应该补：

- L0-L3 权限等级。
- 工具准入标准。
- 结构化失败码。
- 高权限工具 HITL 审批。

### 持久化层

位置：

- `database/models.py`
- `core/execution_store.py`

职责：

- `Task`。
- `ExecutionRunRecord`。
- `CaseResultRecord`。
- `TaskStep`。
- `Report`。
- `AgentMemory`。

后续应该补：

- `tool_result` JSONB。
- `human_review_request` / `human_review_decision`。
- eval run 或 eval artifact 存储策略。

### 报告层

位置：

- `core/run_report.py`
- `frontend/src/pages/Report.tsx`

职责：

- 展示事实链。
- 展示结果。
- 展示步骤。
- 支持恢复失败用例。

后续应该补：

- 需求事实 -> 断言 -> 用例 -> 步骤 -> 结果的证据链。
- 工具失败码统计。
- human review 记录。
- deferred 资产解释。

## 9. 阶段级目标设计

### analyzing

输入：

- PRD。
- Swagger / API doc。
- rules。
- focus areas。
- prototype。
- tech doc。
- changelog。
- memory 只读上下文，未来接入。

输出：

- `RequirementFact`。
- `RequirementAssertion`。
- `ExplorationGoal`。
- `manual_review_items`。

设计方式：

- prompt chain。
- Pydantic structured output。
- review gate。

不做：

- 不做 agent loop。
- 不让模型动态改变生命周期。

### exploring

输入：

- `ExplorationGoal`。
- 当前页面语义。
- 工具合同。
- 探索预算。

输出：

- `SystemMapEvid`。
- `GoalResult`。
- 探索轨迹。

设计方式：

- 局部 agent loop。
- observe -> evidence assessment -> action -> observe。
- 工具必须受 action policy 限制。

目标增强：

- `RuntimeToolResult`。
- L0 只读工具。
- trajectory eval。

### designing

输入：

- facts。
- assertions。
- system map。
- rules。
- focus areas。
- memory 只读上下文，未来接入。

输出：

- `CoverageBlueprint`。
- `TestCondition`。
- `TestDesignTechnique`。
- `CoverageItem`。
- `CandidateTestCase`。
- `TraceabilityMatrix`。
- `TestAssetPackage`。

设计方式：

- structured pipeline。
- deterministic fallback。
- quality gates。

目标增强：

- 明确 deferred 资产原因。
- 更强 traceability。
- 设计质量指标。

### executing

输入：

- `RuntimeExecutableCase`。
- 浏览器页面语义。
- 工具合同。
- 前序失败反馈。
- retry / timeout policy。

输出：

- `TaskStep`。
- `CaseResult`。
- 执行轨迹。

设计方式：

- 局部 agent loop。
- 成功由终态证据判断。
- 失败可由 `mark_task_failed` 收口。

目标增强：

- 工具结果结构化。
- HITL pause/resume。
- 终态判断 eval。
- selector failure 分类。

### reporting

输入：

- `ExecutionRunRecord`。
- `CaseResultRecord`。
- `TaskStep`。
- `TestAssetPackage`。

输出：

- HTML Report。
- 前端报告视图。

设计方式：

- deterministic rendering。
- 不由 LLM 改写事实。

目标增强：

- 证据链展示。
- 工具指标。
- human review 记录。
- deferred / incomplete 原因解释。

## 10. 数据权威链

主链路：

```text
RequirementFact
-> RequirementAssertion
-> ExplorationGoal
-> SystemMapEvid
-> CoverageBlueprint
-> TestCondition
-> TestDesignTechnique
-> CoverageItem
-> CandidateTestCase
-> TraceabilityMatrix
-> TestAssetPackage
-> ExecutionSelection
-> RuntimeExecutableCase
-> TaskStep
-> CaseResult
-> Report
```

关键不变量：

- 每个 `CandidateTestCase` 必须能追溯到覆盖项。
- 每个计划执行的 case 最终必须有一个 `CaseResult`。
- `ExecutionRun.summary.planned` 必须等于 planned case 数。
- `ExecutionRun.summary.terminal` 完成时必须等于 planned。
- 报告只从持久化数据生成。
- 取消和失败都不能丢分母。

## 11. 开发路线

### P0：先补证据和可控性

目标：让当前单 Agent workflow 变得可评估、可审计、可恢复。

任务：

1. 工具结果结构化。
   - 新增 `RuntimeToolResult`，保留 `ActionResult` 给宽工具库。
   - `_execute_browser_action()` 返回结构化结果。
   - `TaskStep` 兼容记录工具结果。

2. 工具失败码。
   - action policy 输出标准 error code。
   - selector / timeout / blocked / no change 等失败分类。

3. 报告展示工具失败。
   - failed / incomplete / human_review_required case 展示主要失败码。

4. Eval 种子集。
   - 先做 10 条任务样例。
   - 覆盖资产、执行、报告。

### P1：补 HITL 和 Memory 只读

目标：让系统知道什么时候需要人，并能安全使用已有知识。

任务：

1. `HumanReviewRequest` / `HumanReviewDecision`。
2. pause / review / resume 生命周期。
3. 高风险断言和高权限工具进入 HITL。
4. `AgentMemory` 只读召回。
5. memory provenance 进入分析包和报告。

### P2：补编排恢复和生产观测

目标：让系统能平台化运行。

任务：

1. 阶段 checkpoint。
2. resume policy 扩展。
3. 任务队列。
4. 浏览器资源配额。
5. 成本、延迟、模型调用、工具失败率指标。

### P3：谨慎扩展工具和执行能力

目标：扩大测试能力，但不破坏可信度。

任务：

1. L0 只读工具进入生产合同。
2. API 执行能力。
3. CDP / network inspection 作为 L2 工具，HITL 后开放。
4. screenshot_on_demand 带配额进入特定场景。

### P4：再评估 multi-agent

只有当前条件满足时才考虑：

- 单 Agent eval 稳定。
- 工具合同稳定。
- HITL 闭环可用。
- 轨迹可审计。
- memory 污染可控。
- 生产指标可观测。

可能拆分的角色：

- Planner：生成测试资产。
- Explorer：补系统证据。
- Executor：执行用例。
- Reviewer：评估证据和报告。

但这些角色必须通过明确协议通信，不能变成自由聊天式协作。

## 12. 明确不做

当前阶段不做：

- 完全自主 Agent。
- 默认 multi-agent。
- 长期维护型 Playwright/Selenium 脚本生成。
- 无权限等级的宽工具开放。
- 默认 `evaluate_js`。
- 默认跨域导航。
- 自动写长期 memory。
- 让 LLM 重写报告事实。
- 把运行时诊断、截图、trace 提交进 Git。

## 13. 验收标准

这份设计落地后，项目应该满足这些判断：

### 产品形态

- 能清楚说明自己是 agentic workflow，不是 full autonomous agent。
- 能说明每个阶段哪些是 deterministic，哪些由 LLM 决策。

### 数据可信

- 每个测试结论都有事实链。
- 每个自动执行 case 都有终态。
- 报告能解释为什么 passed / failed / skipped / incomplete / human_review_required。

### 工具可信

- 每个工具有权限等级。
- 每次工具调用有结构化结果。
- 工具失败可分类、可统计、可进入 HITL。

### 人工接管可信

- 系统知道什么时候该暂停。
- 用户能看到证据。
- 用户决策能恢复执行并进入报告。

### 评估可信

- 至少有 10 条固定 eval 样例。
- 有资产质量、执行轨迹、报告可信度三类指标。
- 新工具和新自主能力进入生产前必须过 eval。

### 生产可信

- 任务状态、运行状态、用例状态边界清楚。
- 取消和失败不丢分母。
- 并发和资源扩张不早于 eval / HITL / 工具结构化。

## 14. 下一步应该做什么

不要继续散写概念文档。下一步进入开发规划时，建议按这个顺序拆任务：

```text
1. RuntimeToolResult 生产化
2. action policy 结构化 error code
3. TaskStep 结构化工具结果记录
4. 报告展示工具失败码
5. 10 条 eval 种子集
6. HITL request / decision 协议
7. Memory 只读召回
8. 阶段 checkpoint 和 resume policy
```

这条路线的核心思想是：

```text
先让单 Agent 工作流可证明地可靠，再扩大自主性。
```
