# L1 质量标准与 Runtime 执行契约重构设计

状态：Draft，等待用户评审  
日期：2026-06-09  
范围：L1/L1.5/L2 分析链路、Runtime 执行契约、执行结果持久化、Golden Dataset 与质量门  
非范围：本文件不直接实现代码，不提交真实人力资源需求原文，不实现完整 HITL 恢复闭环

---

## 1. 背景

当前项目已经形成 `RequirementFact -> RequirementAssertion -> ExplorationGoal -> SystemMapEvid -> TestCondition -> CoverageItem -> CandidateTestCase -> TraceabilityMatrix -> TestAssetPackage` 的分析链路，但仍存在几个会导致“分析包评分变高，真实执行仍不可用”的系统性风险：

1. Phase 1 与 Phase 2 Review Gate 规则不一致，可能静默丢失部分已通过的高风险功能断言。
2. `CandidateTestCase` 当前主要作为事后分析包产物，尚未成为 Runtime 的权威执行输入。
3. Runtime 当前仍偏向旧 `TestCase.steps` 的逐步骤执行模型，而新链路需要目标驱动执行。
4. 数据库缺少权威 `ExecutionRun` / `CaseResult` 持久化模型，任务计数依赖递增维护，无法保证幂等和恢复。
5. 重试会清理历史步骤，破坏 audit trail 和复现要求。
6. `task.status` 同时承载生命周期和阶段，导致前端、WebSocket、报告与数据库语义容易分叉。
7. L1 质量标准仍偏传统需求工程，缺少 agentic evaluation 所需的 groundedness、source quality、reproducibility、grader calibration 和 dataset health。

因此，本设计不以“先提升局部指标分数”为目标，而以“先锁定端到端契约，再逐步优化质量”为原则。

---

## 2. 设计原则

1. **链路可用性优先于局部质量分数**：先保证 CandidateCase 能成为 Runtime 权威输入，再优化多事实断言、Goal 文本等指标。
2. **单一权威源**：测试意图以 `CandidateTestCase` 为权威；执行结果以 `CaseResult` 为权威；探索证据以 `SystemMapEvid` 为权威。
3. **无损适配，不二次生成语义**：`RuntimeExecutableCase` 只能协议适配，不能生成固定步骤或改写测试目标。
4. **目标驱动执行**：执行图以目标、预期结果、页面观察和终态证据驱动，而不是逐条消费固定步骤。
5. **幂等持久化**：计数从权威结果集合聚合，不能通过 `+= 1` 维护。
6. **审计链完整**：重试不得删除历史步骤；每个 attempt、step、case result 都必须可追溯。
7. **失败语义确定化**：每种失败只有一个明确归类，不保留“failed 或 incomplete”式实现选择题。
8. **质量指标可计算**：每个质量门必须定义分母、分子、匹配规则和 oracle 来源。
9. **真实数据不污染仓库**：人力资源真实文档用于 E2E 校准，但仓库只保存脱敏 oracle、哈希、运行方法和摘要。
10. **Evidence 与 Oracle 分离**：Evidence Collection 负责收集截图、DOM、URL、网络、工具结果等证据；Oracle Evaluation 负责基于 `TestCondition.oracle_type` 与 terminal assertion 判断目标是否满足。第一轮先保持逻辑分离，物理模块拆分延后到 M2/M3 细化。

---

## 3. 目标端到端链路

锁定目标架构：

```text
StrictExplorationGoal
    -> Runtime.explore()
    -> ExplorationResult(SystemMapEvid, GoalResult[])
    -> run_l2_pipeline(SystemMapEvid)
    -> TestAssetPackage(CandidateTestCase[])
    -> adapt_executable_cases()  # 无损协议适配
    -> Runtime.execute(RuntimeExecutableCase[])
    -> TestResult[] / CaseResult[]
    -> ExecutionMapping
    -> Report / DB / WebSocket
```

关键约束：

```text
CandidateTestCase.id
  = RuntimeExecutableCase.id
  = TestResult.test_case_id
  = CaseResult.candidate_case_id
  = TaskStep.test_case_id
  = WebSocket case ID
  = Report case ID
```

重试不得产生第二个逻辑用例 ID。每个权威 `CandidateTestCase.id` 在一个 `ExecutionRun` 内最终只能有一个 terminal `CaseResult`。

---

## 4. 里程碑拆分

本设计实际包含四个大型项目，必须拆成四个可验收增量。

### M1：统一 Review Gate + 严格 Goal + 确定性质量门

目标：修复 L1/L2 分析链路的确定性契约，不做 Runtime 大重构。

范围：

- Phase 1 / Phase 2 使用同一个 Review Gate 函数。
- 引入严格 `StrictExplorationGoal`。
- 引入 `schema_version`。
- 设计 Source Registry。
- 引入内容寻址稳定 ID。
- blocked assertion 不从覆盖分母消失，进入 `human_review`。
- traceability 悬空引用检测。
- deterministic unsupported claim 硬门。
- 修订 `docs/L1质量标准.md`。

验收：

- Phase 1 / Phase 2 Review Gate 结果一致。
- Goal 必有 `id`、`assertion_refs`、`expected_evidence`、`stop_condition`、`priority`。
- 所有引用 ID 有效。
- blocked assertion 进入 manual review 和 traceability，而不是消失。
- deterministic unsupported 结构错误为 0。
- 旧数据只能通过显式 adapter 进入，不在核心模型内部用空字符串静默兼容。

### M2：Runtime explore/execute 拆分 + CandidateCase 目标驱动执行

目标：让 `CandidateTestCase` 成为 Runtime 的权威输入。

范围：

- Runtime 拆为 `explore()` 与 `execute(candidate_cases)`。
- `RuntimeExecutableCase` 只做无损适配。
- 执行图改为目标驱动，并在逻辑上区分 Evidence Collection 与 Oracle Evaluation：

```text
observe -> decide next action -> execute -> evaluate progress
        -> terminal assert -> record
```

- 不再依赖 `TestCase.steps` 判定用例进度。
- 引入 terminal assertion：

```text
objective_satisfied
expected_result_supported
terminal_evidence_sufficient
```

- 前置条件结构化。
- 账号角色必须显式声明，禁止通过 assertion 类型猜账号。
- 浏览器状态策略锁定。
- 探索失败、分析失败、无 CandidateCase 的策略唯一化。
- `SystemMapEvid` 成为唯一权威探索证据模型。
- 每个 Goal 产出 `GoalResult`。

验收：

- `CandidateTestCase.id` 进入 Runtime 并传递到所有执行产物。
- `execution_hint` 只辅助决策，不被当成固定步骤列表。
- 用例通过只能来自 terminal assertion。
- 探索完全失败不生成虚假案例。
- L2 分析失败不得回退旧 TestCase。

### M3：CaseResult/ExecutionRun 持久化 + 状态、计数、报告一致性

目标：解决执行生命周期和结果可信度 P0。

范围：

- 新增权威持久化模型 `ExecutionRun` 和 `CaseResult`。
- 持久化 `ExecutionMapping`。
- `TaskStep` 增加 `run_id`、`attempt_no`、`step_index`。
- 重试保留历史 attempt，不删除旧步骤。
- 计数从 `CaseResult` 聚合，禁止递增维护。
- 拆分 `task.status` 与 `task.phase`。
- 明确 completed / failed 语义。
- 取消覆盖 analyzing、exploring、designing、executing、reporting。
- 定义 WebSocket 事件契约。
- `report_status` 独立于 task lifecycle。

验收：

- 重复记录不会重复计数。
- retry 不删除历史证据。
- candidate case 数 = terminal CaseResult 数。
- DB / WebSocket / Report 使用同一 case ID 和结果集合。
- final WebSocket event 恰好一次。
- 报告失败不篡改执行结果。

### M4：Golden Dataset + 语义 grader + 真实 E2E 校准

目标：验证 L1 是否真实达标，而不是单次自评好看。

范围：

- 建立小型可提交 fixtures：正常完整需求、条件/边界/状态迁移、权限/高风险、文档冲突、模糊/证据不足、对抗性输入。
- Golden Dataset 版本治理。
- Oracle 修改记录原因。
- 每个指标定义分母、分子、语义匹配方法和抽样方法。
- 语义指标引入人工校准。
- 人力资源真实 E2E 只保存脱敏 oracle、文件哈希、运行方法、评分摘要和环境信息。

验收：

- deterministic checks 可自动化。
- semantic checks 有人工校准样本。
- grader-human agreement 达到阈值后才能作为质量门依据。
- 3-5 次运行输出 set stability、worst-run recall、critical-item miss rate。
- 真实 E2E 不作为长期唯一基线。

---

## 5. 数据模型决策

### 5.1 StrictExplorationGoal

核心链路使用严格模型，不允许默认空字段静默兼容。

```text
schema_version: str
id: str
assertion_refs: list[str]
goal: str
expected_evidence: list[str]
stop_condition: str
priority: high | medium | low
source_refs: list[str]
```

规则：

- `id` 由后处理生成，不信任 LLM ID。
- `assertion_refs` 必须有效。
- `expected_evidence` 至少 1 项。
- `stop_condition` 必填。
- 旧 `_goals` 只能通过显式 adapter 转换，并标记 `legacy/degraded`，不计入严格质量门。

### 5.2 GoalResult

每个探索目标必须产出可计算结果：

```text
schema_version: str
goal_id: str
status: found | not_found | blocked | insufficient
evidence_refs: list[str]
stop_reason: str
observed_at: datetime
```

进入设计规则：

- 全部 `not_found/blocked/insufficient` = 探索完全失败，task failed。
- 部分 `found` = 允许进入设计，但未找到目标的相关下游项标记 `evidence_gap`。

### 5.3 Source Registry

`source_reference + quote` 不足以稳定 groundedness 验证。新增 Source Registry：

```text
schema_version: str
source_id: str
source_type: prd | swagger | changelog | prototype | architecture | rule | inferred
content_hash: str
path_or_url: str
section: str | null
start_offset: int | null
end_offset: int | null
quote: str
quote_hash: str
```

规则：

- 非 inferred fact 必须指向有效 source anchor。
- inferred 不等于 unsupported，但必须写明推断依据并降低 confidence。
- 真实敏感材料不入仓，仓库只保存 hash、脱敏 oracle 和运行方法。

### 5.4 SystemMapEvid

`SystemMapEvid` 是唯一权威探索证据模型。Page、Action、Form、Navigation 项应带证据出处：

```text
evidence_refs: list[str]
observed_at: datetime
url: str
screenshot_ref: str | null
```

旧 `core/skills/system_mapper.py` 的字符串列表结构只作为边界适配，不继续作为核心模型传播。

### 5.5 CandidateTestCase

`CandidateTestCase` 是权威测试意图。需要增强：

```text
schema_version: str
id: str
title: str
goal: str
expected_result: str
execution_hint: str
preconditions: list[StructuredPrecondition]
input_data: list[TestInputDatum]
trace_references: list[str]
priority: high | medium | low
category: str
required_roles: list[str]
```

`input_data` 不应继续只是 `dict[str, str]`，至少支持：

```text
name
value | placeholder
source
sensitivity: public | internal | secret
generation_strategy
boundary_category
```

禁止把真实凭据写入分析包。

### 5.6 StructuredPrecondition

替代自然语言 `list[str]`：

```text
type: account_role | business_state | environment | data
description: str
required_role: str | null
satisfiable_by_agent: bool
failure_policy: skipped | incomplete | failed | human_review_required
```

规则：

- 账号角色必须显式声明，不能由 assertion 类型猜测。
- 无法解析角色时，case `incomplete`，reason=`account_role_unresolved`。
- 前置条件本身不生成独立 `CaseResult`，但必须生成 `TaskStep` 证据。

### 5.7 RuntimeExecutableCase

只做无损协议适配，不生成新语义：

```text
id = CandidateTestCase.id
objective = CandidateTestCase.goal
expected = CandidateTestCase.expected_result
hints = CandidateTestCase.execution_hint
preconditions = CandidateTestCase.preconditions
trace_references = CandidateTestCase.trace_references
priority = CandidateTestCase.priority
required_roles = CandidateTestCase.required_roles
```

禁止：

- 生成固定步骤。
- 改写 goal / expected_result。
- 重新分配 ID。
- 生成第二套权威测试意图。

### 5.8 ExecutionRun

新增权威运行模型：

```text
run_id: str
task_id: int
schema_version: str
status: running | completed | failed | cancelled
started_at: datetime
completed_at: datetime | null
candidate_case_ids: list[str]
summary: dict
```

### 5.9 CaseResult

新增权威用例结果模型：

```text
run_id: str
candidate_case_id: str
terminal_status: passed | failed | skipped | incomplete | human_review_required
attempt_count: int
started_at: datetime
completed_at: datetime
summary: str
evidence_refs: list[str]
failure_reason: str | null
```

规则：

- 一个 `run_id + candidate_case_id` 只能有一个 terminal CaseResult。
- retry 更新同一 CaseResult 的 attempt_count 和最终状态，不创建第二个逻辑结果。
- 历史 attempt 由 TaskStep 保留。

### 5.10 TaskStep

增加运行和尝试维度：

```text
run_id: str
attempt_no: int
step_index: int
test_case_id: str  # 等于 CandidateTestCase.id
```

规则：

- retry 不删除旧步骤。
- step_index 在 attempt 内递增。
- audit trail 通过 `run_id + candidate_case_id + attempt_no + step_index` 重建。

### 5.11 ExecutionMapping

不要污染静态 TraceabilityMatrix。新增运行映射：

```text
task_id -> run_id -> candidate_case_id -> attempt_no
```

ExecutionMapping 记录：

- CaseResult；
- TaskStep refs；
- evidence refs；
- report section；
- WebSocket event refs。

### 5.12 TraceabilityMatrix

TraceabilityMatrix 只表达分析设计关系，不记录运行状态：

```text
Fact -> Assertion -> TestCondition -> CoverageItem -> CandidateTestCase
```

关系类型必须显式：

```text
derived_from
verifies
covers
instantiated_as
blocked_by_review
```

blocked assertion 仍计入覆盖分母，并标记 `human_review`。

---

## 6. Runtime 生命周期设计

### 6.1 Context manager 资源所有权

Runtime 两阶段化必须有明确资源所有权：

```python
async with RuntimeSession(task_config) as runtime:
    exploration = await runtime.explore(strict_goals)
    package = await run_l2_pipeline(system_map=exploration.system_map)
    executable_cases = adapt_executable_cases(package.candidate_cases)
    results = await runtime.execute(executable_cases)
```

规则：

- RuntimeSession 持有浏览器实例。
- explore 后外部 L2 分析期间浏览器仍由 RuntimeSession 管理。
- 超时、异常、取消时 RuntimeSession 负责清理浏览器并回写状态。
- 不允许裸露浏览器资源由 `api/app.py` 临时管理。

### 6.2 阶段划分

```text
pending
running + analyzing
running + exploring
running + designing
running + executing
running + reporting
completed
failed
cancelled
```

`task.status`：

```text
pending | running | completed | failed | cancelled
```

`task.phase`：

```text
analyzing | exploring | designing | executing | reporting | null
```

语义：

- `task.failed` = 管线失败。
- `case failed` = 产品行为不符合预期，不等于 task failed。
- `task.completed` 可包含 failed case，只要所有权威 case 都有终态结果。

### 6.3 目标驱动执行图

新执行图：

```text
observe
  -> decide next action
  -> execute
  -> evaluate progress
  -> terminal assert
  -> record
```

中间步骤的局部 assertion 只用于进度和安全判断，不能直接判定整条 case passed。

终态判定需要：

```text
objective_satisfied: bool
expected_result_supported: bool
terminal_evidence_sufficient: bool
```

只有三者均满足，case 才能 `passed`。

Oracle 分类归属规则：不在 `RequirementAssertion` 上增加 `oracle_type`。`RequirementAssertion` 表达验证义务；`TestCondition.oracle_type` 表达验证媒介和判定方式。同一 assertion 可拆成多个 condition，不同 condition 可能使用不同 oracle，因此 Runtime terminal assertion 必须回溯到相关 `TestCondition.oracle_type`，而不是从 assertion 层推断 oracle。

L4 逻辑分层：

```text
EvidenceCollection
    -> OracleEvaluation
    -> AssertionResult / terminal CaseResult
```

Evidence Collection 收集截图、DOM/AXTree、URL、网络、页面状态、工具结果和变化报告。Oracle Evaluation 基于 `TestCondition.oracle_type`、`expected_result`、terminal evidence 和业务规则判定目标是否满足。M2 先通过接口和数据结构保持二者可分；是否抽成独立 Module 延后到 M3 结合持久化模型决定。

### 6.4 浏览器状态策略

第一版锁定单一默认策略：

```text
每个 case 默认从 target_url 或 case entry hint 重新 observe；
同一角色复用登录态；
跨角色清理 Cookie/storage 并重新登录；
不做全局业务数据回滚。
```

规则：

- execute 前必须重新 observe，不能直接信任探索阶段页面状态。
- `SystemMapEvid` 是 exploration evidence，不等同于 case execution evidence。
- 若业务状态需要重置但 agent 无法完成，则相关 case `incomplete` 或 `skipped`，按 precondition.failure_policy 决定。

### 6.5 前置条件失败策略

| 场景 | CaseResult |
|---|---|
| 前置条件明确无法满足且与产品缺陷无关 | skipped |
| 前置条件尝试后状态未知 | incomplete |
| 前置条件失败暴露产品缺陷 | failed |
| 前置需要人工数据准备 | human_review_required 或 incomplete，由 precondition.failure_policy 决定 |
| 账号角色无法解析 | incomplete |

前置失败必须记录 TaskStep 证据。

---

## 7. 失败策略

失败策略必须唯一化。

| 场景 | 结果 |
|---|---|
| 探索完全失败 | task failed |
| 探索部分成功 | 继续 designing，相关设计项 evidence_gap |
| L2 分析异常 | task failed |
| 无 CandidateCase | task failed |
| 分析失败后是否回退旧 TestCase | 禁止 |
| 产品行为不符合预期 | case failed，task 可 completed |
| 所有 case 因环境不可执行 | task completed，case incomplete |
| 报告生成失败 | task 可 completed，report_status=failed |
| 用户取消 analyzing/exploring/designing | task cancelled，保留已有分析产物 |
| 用户取消 executing | 当前 case incomplete(reason=cancelled)，未开始 case 按 run policy 生成 skipped/cancelled 或不生成结果，M3 中锁定实现 |
| 用户取消 reporting | task cancelled 或 completed+report_status=cancelled，M3 中锁定实现 |

M3 实现前，所有取消策略必须在计划中进一步收敛成数据库可执行规则。

---

## 8. WebSocket 事件契约

最小事件：

```text
phase_started
phase_completed
case_started
case_attempt_started
case_step
case_completed
session_completed
session_failed
```

规则：

- final event 恰好一次。
- 事件顺序固定：phase events 包围 case events。
- `case_started/case_completed` 使用 `CandidateTestCase.id`。
- 断线后前端通过 REST 获取 task、ExecutionRun、CaseResult、TaskStep 当前状态。
- WebSocket 不作为权威存储，只是状态流。

---

## 9. 报告契约

报告使用 `ExecutionRun + CaseResult + TaskStep + TestAssetPackage` 生成。

规则：

- report case ID = `CandidateTestCase.id`。
- 报告失败不改写执行结果。
- 执行完成但报告失败：

```text
task.status = completed
report_status = failed
```

- API 应明确返回报告不可用，而不是把任务标记 failed。

---

## 10. ID 策略

禁止使用 LLM 输出 ID 作为最终权威 ID，也禁止使用 `stable_index`。

采用内容寻址 ID：

```text
FACT-{short_hash(normalization_version + source_anchor + normalized_claim)}
ASSERT-{short_hash(normalization_version + sorted_fact_ids + normalized_assertion)}
GOAL-{short_hash(normalization_version + sorted_assertion_refs + normalized_goal)}
COND-{short_hash(normalization_version + assertion_ref + normalized_condition)}
COV-{short_hash(normalization_version + condition_id + coverage_dimension + normalized_goal)}
TC-{short_hash(normalization_version + sorted_coverage_refs + normalized_goal + normalized_expected)}
```

设计规则：

- hash 输入必须记录 normalization_version。
- 冲突时追加短 suffix 并记录 collision note。
- 相同语义但不同来源：默认不同 Fact ID；可通过 relation 标记 duplicate/equivalent。
- 文档更新导致 source anchor 或 claim 改变时生成新 ID。
- 语义等价匹配用于稳定性评估，不用于强行复用 ID。

---

## 11. Review Gate 语义

第一轮不实现完整 HITL 恢复闭环。

当前语义：

```text
Review Gate = 自动阻断 + manual_review_items
```

不是：

```text
Review Gate = 暂停任务 + 人工确认 + 恢复执行
```

规则：

- blocked assertion 不进入自动设计/执行。
- blocked assertion 进入 TestAssetPackage.manual_review_items。
- blocked assertion 在 Traceability 中标记 `human_review`，仍计入覆盖分母。
- `human_confirmed` 只作为外部输入状态，不由当前系统闭环修改。
- 后续若实现 HITL，需要单独设计谁修改状态、如何持久化、从哪个阶段恢复。

---

## 12. L1 质量门

### 12.1 确定性质量门

可自动判定，M1/M3 优先实现。

| 指标 | 门槛 |
|---|---|
| Schema 合法率 | 100% |
| 引用 ID 有效率 | 100% |
| Traceability 悬空引用 | 0 |
| Review Gate Phase 1 / Phase 2 一致率 | 100% |
| Strict Goal 必填字段完整率 | 100% |
| deterministic unsupported fact/assertion | 0 |
| blocked assertion 分母保留率 | 100% |
| CandidateCase 可追溯到 Fact | 100% |
| Execution ID 传递一致性 | 100% |
| CaseResult 幂等聚合 | 100% |

### 12.2 语义质量指标

不能只靠另一个 LLM 自动判定，必须有人工校准样本。

| 指标 | 说明 |
|---|---|
| groundedness | 输出 claim 是否被 source 或有效 fact 支撑 |
| human-sampled unsupported | 人工抽样发现的 unsupported claim 占比 |
| critical Fact recall | 关键需求事实召回 |
| assertion verifiability | assertion 是否可观察/可测 |
| wrong aggregation rate | 多事实断言错误聚合率 |
| gate decision quality | Review Gate 决策是否符合风险 |
| evidence sufficiency | Goal expected evidence 是否真实可观察 |
| semantic stability | 多次运行语义集合稳定性 |

### 12.3 unsupported claim 分类

```text
1. deterministic unsupported：硬门 0%
2. human-sampled unsupported：目标阈值
3. grader-estimated unsupported：监控指标
```

不能承诺自动语义 unsupported 为 0%。

### 12.4 稳定性指标

不使用文本完全一致或 ID 完全一致作为唯一标准。先做语义对齐，再计算：

- run success rate；
- set stability；
- worst-run recall；
- critical-item miss rate；
- gate decision agreement；
- risk classification agreement；
- traceability edge agreement。

`pass@1/pass^k` 不作为主指标，只可作为可选观察项。

---

## 13. Golden Dataset 设计

### 13.1 可提交 fixtures

至少六类：

1. 正常完整需求；
2. 条件、边界和状态迁移；
3. 权限与高风险规则；
4. 文档冲突；
5. 模糊或证据不足；
6. 对抗性输入。

### 13.2 Oracle 版本治理

每次 oracle 修改必须记录：

- 修改人；
- 修改时间；
- 修改原因；
- 影响指标；
- 是需求变化、标注错误，还是评测规则修正。

禁止为了当前模型通过而调整 oracle。

### 13.3 真实人力资源 E2E

测试数据：

```text
原型地址：http://127.0.0.1:5174/
需求目录：C:\Users\17381\Desktop\项目文件\人力资源\人才盘点一期功能需求清单文档
```

仓库不保存原始材料，只保存：

- 脱敏 oracle；
- 文件哈希；
- 运行方法；
- 评分摘要；
- 原型版本 / 数据快照 / 账号配置；
- 运行时间；
- 已知不稳定项。

真实 E2E 不作为长期唯一质量基线，因为原型数据、账号和环境会变化。

---

## 14. 文档与标准更新

需要更新：

- `docs/L1质量标准.md`：补充 agentic quality、质量门、指标分母、Golden Dataset、稳定性和 groundedness。
- `docs/business_workflow.md`：替换当前单段 run_stream 叙述，补充 explore/design/execute/reporting 阶段。
- `docs/ai-development-guide.md`：更新数据模型定义，加入 StrictGoal、SourceRegistry、ExecutionRun、CaseResult、ExecutionMapping。
- `docs/PRD.md`：补充 Runtime 两阶段、权威结果、报告状态和取消语义。
- `docs/master-roadmap.md`：将 M1-M4 映射到 P0/P1/P3。

---

## 15. 非目标

以下不在 M1-M4 第一轮全部完成：

- `CapabilityModel` 独立 Module。未来可作为 `SystemMapEvid` 的高层业务能力投影，用于把“支持用户认证”细化为“用户名登录 / 手机号登录 / 邮箱登录 / 扫码登录”等能力节点；在 CandidateCase 能进入 Runtime 且执行结果持久化稳定前，不引入该中间层。
- 完整 HITL 人工确认后恢复执行。
- 业务数据自动回滚平台。
- 多浏览器并发执行。
- 长期评测平台 UI。
- 将所有历史任务自动迁移为新模型。
- 删除旧 `TestCase`；旧结构保留为 legacy view，逐步退场。

---

## 16. 风险与回滚

| 风险 | 缓解 |
|---|---|
| Runtime 重构范围过大 | 拆分 M2/M3，先 M1 固化契约 |
| 新模型破坏旧任务读取 | 显式 legacy adapter，不在核心模型静默兼容 |
| 内容寻址 ID 误合并 | 默认相同语义不同来源仍保留不同 Fact ID，另建 relation |
| 语义 grader 不可靠 | 必须人工校准，低 agreement 不作为硬门 |
| 真实 E2E 不稳定 | 记录环境版本、数据快照、运行时间和不稳定项 |
| 计数迁移破坏前端 | M3 提供兼容 API 字段，但来源改为 CaseResult 聚合 |

---

## 17. 实施顺序

1. 写并确认本设计。
2. M1 实现计划：Review Gate 一致性、Strict Goal、确定性质量门、标准文档修订。
3. M1 TDD 实现和验证。
4. M2 设计细化和实现计划：Runtime explore/execute、目标驱动执行。
5. M3 设计细化和实现计划：ExecutionRun/CaseResult、幂等计数、attempt 保留。
6. M4 设计细化和实现计划：Golden Dataset、语义 grader、人力资源 E2E。

---

## 18. 参考依据

- [ISO/IEC/IEEE 29148:2018](https://www.iso.org/standard/72089.html)
- [IEEE/ISO/IEC 29148-2018](https://standards.ieee.org/standard/29148-2018.html)
- [ISTQB CTFL v4.0.1 Syllabus](https://istqb.org/wp-content/uploads/2024/11/ISTQB_CTFL_Syllabus_v4.0.1.pdf)
- [NIST Building Evaluation Probes into Agentic AI](https://www.nist.gov/programs-projects/building-evaluation-probes-agentic-ai)
- [Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- [OpenAI: Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices)
- [OpenAI: Evaluate agent workflows](https://developers.openai.com/api/docs/guides/agent-evals)
- [RAGChecker](https://arxiv.org/abs/2408.08067)
- [HaluEval](https://arxiv.org/abs/2305.11747)
- [Groundedness in Retrieval-augmented Long-form Generation](https://arxiv.org/abs/2404.07060)

---

## 19. 自审结果

- Placeholder scan：无 TBD/TODO。
- 一致性检查：本文将 CandidateTestCase 定义为权威测试意图，将 CaseResult 定义为权威执行结果，未混用 TestCase 权威语义。
- 范围检查：拆分为 M1-M4，避免单批次实现四个大型项目。
- 歧义检查：失败策略、status/phase、浏览器策略、Review Gate 语义、unsupported claim 分类均给出明确决策。
