# Prompt Engineering 最佳实践（项目内化版）

> 调研日期：2026-06-01  
> 范围：Layer 1（5 个 skill）所有 LLM prompt  
> 目标：把"通用 LLM 编程最佳实践"沉淀到本项目的 L1 prompt 模板上

---

## 1. 来源与可信度

| 来源 | 关键论点 | 本项目采纳度 |
|---|---|---|
| [Anthropic 官方 prompt engineering](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview) | 清晰直接、multishot、CoT、XML 标签、chaining | ⭐⭐⭐⭐⭐ 全采纳 |
| [Anthropic context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | 不要 hardcode 复杂逻辑；找到"具体 vs 灵活"的平衡点 | ⭐⭐⭐⭐⭐ |
| [Arunabh: Prompt Engineering for Structured JSON](https://arunabh.me/blog/prompt-engineering-structured-json) | "Output Contract" 模式 + 三层 JSON 提取级联 | ⭐⭐⭐⭐⭐ |
| [AppScale: Structured Output Engineering 2026](https://appscale.blog/en/blog/structured-output-engineering-reliable-json-from-llms-2026) | `additionalProperties: false` + `maxLength`/`maxItems` | ⭐⭐⭐⭐ |
| [Build5Nines](https://build5nines.cloud/blog/how-to-write-ai-prompts-that-output-valid-json-data) | "Models are very good at copying structure—give it something to copy" | ⭐⭐⭐⭐⭐（few-shot） |
| [Prompt Builder: Claude Best Practices 2026](https://promptbuilder.cc/blog/claude-prompt-engineering-best-practices-2026) | 内置 evaluator checklist（自检 block） | ⭐⭐⭐⭐ |
| [Mr. Hotfix: Multi-Step Pipelines](https://medium.com/@mrhotfix/multi-step-llm-pipelines-why-your-single-prompt-approach-fails-at-scale-870b215d3325) | 单个 mega-prompt 在生产必败；需要 contracts、observability、failure isolation | ⭐⭐⭐⭐⭐（指导 L1↔L2 契约） |
| [Codebridge: Multi-Agent Orchestration](https://www.codebridge.tech/articles/mastering-multi-agent-orchestration-coordination-is-the-new-scale-frontier) | **Agent Specification Manifest**（每个 agent 必须有 role/goal/tools/prompt constraints） | ⭐⭐⭐⭐⭐（直接催生 L1 契约文档） |
| [DevToolKit 2026: Structured Output](https://devtoolkit.cloud/blog/structured-output-with-2026-llms-reliable-json) | JSON mode vs schema mode vs function calling 三选一 | ⭐⭐⭐ |

---

## 2. L1 5 个 prompt 通用模板

经过研究汇总，本项目 L1 统一采用以下结构（XML 标签 + Output Contract）：

```text
<role>
你是一个 [单一明确身份]。你的唯一职责是 [一句话职责]。
</role>

<context>
本任务在 L1 认知初始化流水线中的位置：
- 上游输入：[来自哪里、什么形状]
- 下游消费者：[谁用、用什么字段、判定标准]
- 本节点的成功定义：[下游能直接消费本次输出 = 成功]
</context>

<task>
[具体任务，1-2 句话]
</task>

<rules>
1. [硬约束 1]
2. [硬约束 2]
3. ...
</rules>

<examples>
[1-2 个 JSON 输入输出示例。复杂分类用 2-3 个；简单 Q&A 可以 0 个]
</examples>

<output_contract>
Return ONLY the following JSON object. No markdown. No explanation. No preamble.
- 严格使用字段：field1, field2, ...
- 严格使用枚举值：field_x ∈ {a, b, c}
- 数组长度限制：array_field 长度 ≤ N
- 未知值用 null，不编造
</output_contract>
```

### 为什么用这套

| 实践 | 来源 | 解决的问题 |
|---|---|---|
| `<role>` 标签 | Anthropic 官方 | 模型风格定调、避免多头身份 |
| `<context>` 含上下游 | Codebridge Manifest | L1 是流水线，必须有 inter-node 契约 |
| `<rules>` 编号列表 | Anthropic + Mr. Hotfix | 模型在长 prompt 中会"忘"约束 #7，编号可缓解 |
| `<examples>` few-shot | Anthropic + Build5Nines | "give it something to copy" |
| `<output_contract>` 末尾块 | Arunabh | "frame as contract, not suggestion"；防 markdown fence |
| `additionalProperties: false` (pydantic) | AppScale | 防模型发明新字段 |
| `maxLength` / `maxItems` (pydantic) | AppScale | 防 runaway output |

---

## 3. L1 节点间契约（新增 — 之前缺失）

> 这是 L1 作为流水线**必须的 schema 契约**，每个 prompt 在 `<context>` 块里都引用本表。

| 节点 | 上游输入 | 本节点输出（schema） | 下游消费 | 硬约束 |
|---|---|---|---|---|
| **N1 KnowledgeExtractor** | PRD 文本 + Swagger 文本 + Changelog 文本 | `KnowledgeBase { business_rules[], roles[], entities[], constraints[], raw_facts[] }`，每项带 `text/source/quote/confidence` | N1.5 读全部、N2 读 entities+roles、N3 间接、L3 读 rules | `source ∈ {prd, swagger, changelog, inferred}`；`confidence ∈ [0,1]`；**`quote` 不可追溯时写 "N/A" 并把 confidence 降到 ≤0.5** |
| **N1.5 UseCaseModeler** | N1 输出的 `KnowledgeBase` | `UseCaseModel { use_cases[] }`，每项 `name/actor/trigger/outcome/related_rules[]` | N1.7 自检 + N3 直接映射 | `actor` 必须在 `knowledge.roles` 列表中（不在则报 "unknown actor"）；`related_rules` 文本应能在 `knowledge.business_rules[].text` 中找到（字面包含或语义相同） |
| **N1.7 UseCaseCoverage** | N1 + N1.5 | `(refined UseCaseModel, CoverageReport { covered_rules[], missing_rules[], added_use_cases[] })` | N2 读 refined UCM、HTML 报告 L1 卡片读 CoverageReport | `covered_rules + missing_rules` 应等于 N1 输出的所有 `business_rules`（不漏不增）；`added_use_cases` 由程序计算增量，**LLM 不填** |
| **N2 SystemModeler** | N1 + N1.5 (refined) | `SystemModel { system_name, modules[], entities[], roles[], flows[] }`，每 flow 含 `name/nodes[]/transitions[]`，每 transition `from_state/action/to_state` | N3 读 modules/entities 命名空间 | `nodes` 必须是 **2-6 字汉字名词短语**（无前缀、无后缀、无标点）；同一 node 在不同 flow 中拼写必须一致；`action` 必须等于某 `use_case.name` |
| **N3 GoalExtractor** | N1.5 (refined) | `ExplorationGoalList { goals[] }`，每项 `goal/priority` | Layer 2 Explorer 顺序执行 | `priority ∈ {high, medium, low}`，判定标准见 N3 prompt；同一 `use_case.name` 最多产生 1 个 goal |

---

## 4. 各节点改造细节

### 4.1 N1 KnowledgeExtractor

**改造前**（旧 prompt 缺失）：
- ❌ 无 XML 结构
- ❌ 无 few-shot
- ❌ 无上下文契约
- ❌ `quote` 在 adversarial 输入下大面积空字符串，无 fallback
- ❌ 无 CoT 引导

**改造后**（`knowledge_extractor.py` 全部重写）：
- ✅ XML 5 段结构
- ✅ 在 `<rules>` 明确 quote fallback：`if 原文不可精确引用 → quote="N/A" + confidence ≤ 0.5`
- ✅ 1 个 good example + 1 个 bad example
- ✅ `<context>` 写明下游 N1.5 怎么消费
- ✅ `<output_contract>` 用 "Return ONLY" 开头

### 4.2 N1.5 UseCaseModeler

**改造前**：
- ❌ 无 XML 结构
- ❌ `actor` 字段未约束到 N1.roles，可能产生幻觉角色
- ❌ 无覆盖率要求

**改造后**：
- ✅ XML 5 段结构
- ✅ `<rules>` 加 actor 约束：`actor 必须在 knowledge.roles 内，否则填 "unknown_actor_<原始输入>"`
- ✅ `<rules>` 加覆盖率要求：`每条 business_rule 应至少被一个 use_case.related_rules 引用（覆盖率目标 ≥ 85%）`

### 4.3 N1.7 UseCaseCoverage

**改造前**（V1.5 hardening 已加 fast-path 90%）：
- ⚠️ fast-path 在 substring 匹配，但 prompt 让 LLM 做"语义判断"，**两者矛盾**
- ❌ LLM 路径在真实流量里几乎不触发（实测 100% 命中），属于"纸面 LLM"
- ❌ prompt 没说明判定标准

**改造后**（3 选 1，**选方案 B**）：
- **方案 A**（推荐长期）：删 LLM 路径，fast-path 直接当唯一路径
- **方案 B**（已实施）：保留 LLM 路径，但 prompt 显式说"semantic match — a rule is covered iff its core predicate is referenced in some use_case.related_rules"
- **方案 C**：fast-path 用语义嵌入（embedding similarity）而非子串

**当前选择 B**，理由：
- 不改架构
- prompt 与 code 判定标准对齐
- 加 CoT 引导让 LLM 真的"审查"而不是抄

### 4.4 N2 SystemModeler

**改造前**：
- ❌ `nodes` 拼写可能不一致（"草稿" / "申请单-草稿" / "draft"）
- ❌ `action` 可能与 `use_case.name` 不对应
- ❌ 无 XML

**改造后**：
- ✅ XML 结构
- ✅ `<rules>` 加 nodes 归一化：`每个 node 是 2-6 字汉字名词短语；同一节点在不同 flow 中拼写必须一致；禁止带前缀（如"申请单-草稿"）`
- ✅ `<rules>` 加 action 约束：`transitions[].action 必须等于某 use_case.name`

### 4.5 N3 GoalExtractor

**改造前**：
- ❌ `priority` 判定标准模糊（"合理"）
- ❌ 同一 use_case 可能产生多个 goal

**改造后**：
- ✅ XML 结构
- ✅ `<rules>` 加 priority 标准：
  - `high` = 核心业务流（登录、支付、主 CRUD、删除/恢复等不可逆操作）
  - `medium` = 支撑功能（修改密码、个人资料、查询列表）
  - `low` = 边角功能（UI 偏好、关于我们）
- ✅ `<rules>` 加唯一性：`同一 use_case.name 最多产生 1 个 goal`

---

## 5. 反模式（项目内禁止）

| 反模式 | 来源 | 禁止理由 |
|---|---|---|
| 在 prompt 里 hardcode "if/else" 决策树 | Anthropic context engineering | 脆弱、维护难 |
| "请尽量 JSON 输出" | Arunabh | 不够强，要用 "Return ONLY" |
| 期待模型 "自己思考 priority" | Codebridge Manifest | 必须给判定标准 |
| 不写 `<output_contract>` 就期望结构化 | AppScale 2026 | 必有兜底提取 |
| 多个 use_case 名字拼写变体 | 本项目实测 | 必加归一化 |
| 期望子串匹配 = 语义覆盖 | 本项目 N1.7 教训 | prompt 与 code 必须同步 |

---

## 6. 自动化守护

- **回归测试** `tests/core/test_l1_prompts.py`：
  - 用 4 个 fixture（`prd_aitalk / prd_purchase / prd_minimal / prd_adversarial`）跑 5 个 skill
  - 断言 schema 通过 + inter-node 契约成立（如 N3 goals.length == N1.5 use_cases.length）
  - CI 失败 → 提示词回退
- **不变量**（应在每个 fixture 上验证）：
  1. N1 输出的 `business_rules` 非空（除非 fixture 本身无业务规则）
  2. N1.5 输出的 `actor` ⊆ N1 输出的 `roles`
  3. N1.7 的 `covered ∪ missing == N1.business_rules`（无遗漏、无凭空增加）
  4. N2 输出的 `nodes` 全部 2-6 字汉字且无重复前缀
  5. N3 输出的 `goals` 数量 ≤ N1.5 的 `use_cases` 数量（唯一性）

---

## 7. 后续可演进（Phase 2+）

- **Embedding-based coverage**（替代 substring 匹配）
- **Auto-prompt-tuning**（用 few-shot sample 自动找最优示例）
- **Prompt 单元测试的 LLM-as-judge**（用 haiku 模型判定 N1 输出是否"足够好"）
- **L1↔L2 契约机器校验**（从 pydantic schema 自动生成 L1↔L2 不变量测试）

---

## 8. L2 模板草案（待 V2.0 B 阶段实施）

> **本节为草案**，实际 L2 prompt 实施在 V2.0 Phase B 完成（2026-06-01 落盘计划）。详细计划见 `docs/layer2-v2.0-plan.md` §3.2 与 devlog 21。

### 8.1 L2 通用模板

L2 3 个 prompt（decide / assert / step）都遵循 V1.6 5 段 XML 结构，与 L1 一致：

```text
<role>
你是一个 [单一明确身份: Web 测试执行智能体 / 断言评估智能体 / 步骤执行智能体]。
</role>

<context>
本任务在 L2 决策流水线中的位置：
- 上游输入：[observe 节点的 page_info / 上轮 assert 的 change_report / 上轮 LLM 的 tool_call]
- 下游消费者：[execute_node 调工具 / record_node 写 StepResult / ReportBuilder 渲染]
- 本节点的成功定义：[下游能直接消费本次输出 = 成功]
- L1 业务模型上下文：<prd_rules>...</prd_rules> + <focus_areas>...</focus_areas> + <scenarios>...</scenarios> + <risk_points>...</risk_points>
</context>

<task>
[具体任务，1-2 句话]
</task>

<rules>
1. [硬约束 1 - 如: status 必填 ∈ {PASS, FAIL, INCONCLUSIVE}]
2. [硬约束 2 - 如: 必须调一个工具（含 mark_task_*）或显式 stop]
3. ...
</rules>

<examples>
<example type="good">[JSON 输入输出示例]</example>
<example type="bad">[反例: 说明常见错误模式]</example>
</examples>

<output_contract>
Return ONLY the following JSON object. No markdown. No explanation. No preamble.
- 严格使用字段: field1, field2, ...
- 严格使用枚举值: field_x ∈ {a, b, c}
- 数组长度限制: array_field 长度 ≤ N
- 未知值用 null，不编造
</output_contract>
```

### 8.2 L2 节点间契约（新增 - 之前缺失）

| 节点 | 上游输入 | 本节点输出（schema） | 下游消费 | 硬约束 |
|---|---|---|---|---|
| **L2.observe** | task_id | `page_info: dict` (url/title/interactive_elements/...) | L2.decide | 不调 LLM，纯 Playwright + browser-use |
| **L2.decide** | page_info + 上轮 assertion + change_report + L1 context | `AIMessage` 带 `tool_calls`（必填）或 `tool_calls=[]`（用例完成） | L2.execute 或 L2.record | **必填 tool_call**（含 mark_task_*）；如意图结束用例，调 `mark_task_complete` / `mark_task_failed` / `mark_task_skipped` |
| **L2.execute** | 最后 AIMessage 的 tool_calls | `ToolMessage[]` + `state_after` + `screenshot_after` | L2.assert | 工具失败计入 `consecutive_failures`；不抛异常（返回 "执行失败" 字符串） |
| **L2.assert** | state_before/after + tool_calls + expected | `AssertionResult { status, reasoning, confidence }` (pydantic) | L2.record | `status ∈ {PASS, FAIL, INCONCLUSIVE}`;`reasoning ≤ 200 字`;`confidence ∈ {high, medium, low}` |
| **L2.record** | assertion + tool_results | `StepResult` 累积到 `_collected_steps` | runtime.py → ReportBuilder | 失败时**优先**走 change_detector 规则（L0 → L1 → L2 分层） |

### 8.3 L2 ↔ L1 业务模型契约（新增 - CLAUDE.md Rule 3 落地）

L2 `<context>` 段必须显式消费以下 L1/Phase 1.5 输出：

| 来源 | 字段 | 注入位置 | 数据形态 |
|---|---|---|---|
| L1 (knowledge_extractor) | `task_config.rules`（PRD 提取的硬约束） | `<prd_rules>` | `list[str]` |
| L1 (system_modeler) | `task_config.focus_areas`（优先级目标） | `<focus_areas>` | `list[ExplorationGoal]` |
| Phase 1.5 (scenario_extractor) | `task_config._scenarios`（业务场景） | `<scenarios>` | `list[Scenario]` |
| Phase 1.5 (risk_analyzer) | `task_config._risk_points`（风险点） | `<risk_points>` | `list[RiskPoint]` |

**注入策略**：每类字段前 5 条，超出截断并在 doc 里标注。

### 8.4 L2 反模式（项目内禁止 - V2.0 B 阶段生效）

| 反模式 | 修复 |
|---|---|
| decide 用 `##` Markdown 段落 | 改 V1.6 5 段 XML |
| decide 不知道下游是 assert | 加 inter-node 契约 |
| assert 手剥 JSON 3 层 fallback | 改 `safe_structured_invoke` + pydantic |
| assert system prompt 英文硬编码 | 中文化 + V1.6 风格 |
| assert 不区分上游 change_detector 已判过的错误 | 加 inter-node 契约 |
| 账号密码进 system_prompt 明文 | 改成 `<account>` 占位，工具自己读 task_config |
| context 按"条"截断 | 改 token 估算截断 |
| 工具失败不计入 consecutive_failures | 改 execute_node 错误时 +1 |
