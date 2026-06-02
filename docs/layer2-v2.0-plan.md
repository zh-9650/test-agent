# L2 全面加固 V2.0 — 完整计划（含 Phase 1.6 插入）

**日期**: 2026-06-01
**作者**: Lead
**前置**: V1.7 (b16ffe8) L1 + Phase 1.5 prompt 全面加固、L1 收尾 (c2e5a2f)、V2.0 计划 v1 (cb8c8ab)
**状态**: 修订后待执行
**范围**: Phase 1.6 + A + B + C + D（5 阶段，9-10 天，5 个独立 commit）
**本修订依据**: 2026-06-01 GPT 外部评审建议 + 项目内 V1.7 报告 P0 漏洞核对

---

## 0. TL;DR

L1 + Phase 1.5 8 个 skill 全部 V1.6 化完成 (V1.7)，L2 (execution_graph) 仍是 prompt 调用的 hot path 但工程标准远落后 L1。本计划**修订后**用 **5 阶段**让 L2 追平 L1 V1.7 同等工程标准：

| 阶段 | 名称 | 工时 | 关键产出 | Commit |
|---|---|---|---|---|
| **Phase 1.6** | N2/explore/SystemMap 三件套加固 | 1.5-2d | 修 N2 SystemModel fallback + explore prompt V1.6 化 + SystemMap 采样强化 + invariant 测试 | `fix(layer1): Phase 1.6 N2+explore+SystemMap 三件套加固` |
| **Phase A** | L2 安全网 + 测试基础设施 | 1.5d | 5 个 L2 P0 漏洞修复 + `test_l2_prompts.py` + e2e | `fix(layer1+layer2): L2 safety net + test infrastructure` |
| **Phase B** | L2 Prompt V1.6 化 | 2.5d | 3 个 L2 prompt 重写 + `safe_structured_invoke` + pydantic | `feat(layer2): L2 prompts V1.6 migration` |
| **Phase C** | 联动 L1 业务模型 | 1d | 4 字段 `<context>` 注入 + ReportBuilder L2 卡片 | `feat(layer2): L1→L2 business model linkage` |
| **Phase D** | L2 可观测性 | 1d | token 估算 + node 事件 + WebSocket 告警 | `feat(layer2): observability` |
| **合计** | | **9-10d** | **5 个独立 commit** | |

### 关键决策（已拍板）

1. **范围**：Phase 1.6 + A + B + C + D 全做（不做 Phase E Reflection）
2. **测试**：`test_l2_prompts.py` + `L2_LIVE` 开关 + `scratch/test_l2_e2e.py` 端到端集成测试
3. **evaluate_js 沙箱**：关键字黑名单（5 个：page.goto / page.evaluate / window.location / location.href / fetch(）
4. **合并**：阶段独立 commit（5 个）
5. **执行顺序**：**Phase 1.6 先于 V2.0 A**（V1.7 报告点名的 P0 漏洞在 1.6 修）
6. **Gap Analyzer**：推迟到 V2.1（GPT 新建议的真正价值所在）
7. **不做**：Business Graph / LangSmith / Multi-Agent / 改 tools.py 14 工具（除 evaluate_js）/ checkpointer 升级

### 本次修订（v1 → v2）变更

| 项 | v1 (cb8c8ab) | v2 (本次) | 理由 |
|---|---|---|---|
| 阶段数 | 4 (A/B/C/D) | 5 (1.6/A/B/C/D) | GPT 指出 N2 SystemModel + SystemMap 桥梁是真正瓶颈 |
| Phase 1.6 | 不存在 | **新增**：N2 fallback + explore prompt V1.6 化 + SystemMap 采样 | V1.7 报告点名 P0 + V1.7 未覆盖 planning_graph 盲点 |
| Gap Analyzer | 不存在 | V2.1 候选 | GPT 最有价值的新想法，但与 L2 加固正交 |
| 顺序 | A→B→C→D | **1.6→A→B→C→D** | 修理论模型不稳再搞执行层 |
| 工时 | 7-8d | 9-10d | +1.5-2d for Phase 1.6 |

---

## 1. 背景与现状

### 1.1 L2 定位

L2 (execution_graph) 是测试执行的引擎，对每条 test_case 跑 `observe → decide → execute → assert → record` 的 ReAct 循环。典型 5 步 case ≈ **6-10 次 LLM 调用**（每个 decide 1 次，assert 0-1 次），单 case 最多 76 个 node 调用。

**L2 是 prompt 调用的 hot path**，调用频次是 L1 + Phase 1.5 合计的 30-100 倍。

### 1.2 L2 vs L1 V1.7 现状对比

| 维度 | L1/Phase 1.5 (V1.7) | L2 (execution_graph) | Planning (explore) | SystemMap |
|---|---|---|---|---|
| Prompt 模式 | V1.6 5 段 XML + Output Contract | V1.5 之前 `##` 自由文本 | **V1.5 之前自由文本**（V1.7 漏） | `system_mapper.py` 自由文本 |
| `safe_structured_invoke` + pydantic | ✅ 全部 8 skill | ❌ assert_node 手剥 JSON 3 层 fallback | explore_decide 走 bind_tools | ✅ 已用 pydantic |
| Inter-node 契约 | ✅ L1↔L2 文档化 | ❌ 缺 | ❌ 缺 | ⚠️ 已被 scenario_extractor 消费 |
| 回归测试 | 53 mock + 8 live skip | 11 mock（无 L2 prompt 测试） | **无** | **无** |
| Live test 开关 | `L1_LIVE=1` | 无 | 无 | 无 |
| Context 管理 | 静态 | 按"条"截断 + base64 截图全塞 = 撞 65K token 风险 | 10 页 + 15 元素/页截断 | 受 explore 质量影响 |
| 异常恢复 | 2 safety valve | 工具失败**不**计入 consecutive_failures | — | — |
| 联动 L1 业务模型 | L1 → Phase 1.5 → ReportBuilder 完整 | L2 ↔ L1 业务模型**单向** | L1 → explore（via Goals） | explore → SystemMap → scenario_extractor |

### 1.3 已知设计漏洞（按 ROI 排序）

**P0 — Phase 1.6 + Phase A 修**：

| ID | 漏洞 | 位置 | 阶段 |
|---|---|---|---|
| V-1.6.1 | N2 SystemModel fallback 触发频繁（3/4 fixture） | `core/skills/system_modeler.py` | Phase 1.6 |
| V-1.6.2 | planning_graph explore_decide / explore_execute prompt 未 V1.6 化 | `agents/ui/planning_graph.py` | Phase 1.6 |
| V-1.6.3 | SystemMap 采样太薄（10 页 / 15 元素）+ 无 invariant 测试 | `core/skills/system_mapper.py` | Phase 1.6 |
| V8-V12 | L2 context 爆炸（按"条"截断 + base64 截图全塞） | `agents/ui/execution_graph.py:574-586` | Phase A |
| V13 | L2 工具失败不计入 consecutive_failures | `agents/ui/execution_graph.py:266-267` | Phase A |
| V17 | L2 assert JSON 解析失败无重试 | `agents/ui/execution_graph.py:502` | Phase A |
| V20 | L2 evaluate_js 任意 URL 跳转 | `agents/ui/tools.py:347-410` | Phase A |
| V10 | session_summary 被 decide 覆盖 | `agents/ui/execution_graph.py:180` | Phase A |

**P1 — 随 Phase B/C 解决**：

- V1-V7 L2 prompt 质量问题（XML 缺失 / 无 Output Contract / 无契约）
- V14 L2 assert system prompt 英文硬编码
- V15 L2 账号密码进 system prompt 明文
- V16 L2 `rules` / `focus_areas` 未消费
- V18 L2 assert 不区分上游已判过的错误

**P2 — V2.1+ backlog**：

- V19 L2 tools.py 14 工具缺陷（hover/wait_for_visible/OCR/截图对比）
- V21 `input_text` value 验证
- V22 没有截图对比工具
- V23 `mark_task_*` 无 LLM 自我验证
- **V2.1-N1 Gap Analyzer**（SystemModel vs SystemMap 比对，GPT 新建议）

---

## 2. 设计原则

| 原则 | 含义 | 借鉴来源 |
|---|---|---|
| **V1.6 模式一致性** | L2 + planning_graph 全部用 `<role>/<context>/<task>/<rules>/<examples>/<output_contract>` | 项目内部 L1 V1.7 沉淀 |
| **State-driven Agent** | L2 内部状态字段（current_step/consecutive_failures/last_assertion）显式化 | LangGraph 2026 best practice |
| **Token 预算硬约束** | 单 step 估算 < 30K tokens，超出走 compaction；按 token 不按条截断 | Anthropic Context Engineering 2025-09 |
| **ReAct + Hierarchical Assertion 沿用** | 不引入 Plan-and-Execute / Reflection（复杂度溢出 ROI） | 2026 三模式 |
| **联动 L1 业务模型** | `rules` / `focus_areas` / `scenarios` / `RiskPoint` / `SystemModel` / `SystemMap` 必须进相关 `<context>` | CLAUDE.md Rule 3 |
| **可测试优先** | 改动前先建回归测试 + live 开关 | L1 模板 |
| **schema 校验前移到 LLM 端** | assert 改用 pydantic `safe_structured_invoke`，不再手剥 | 已有 `llm_client.py` |
| **理论 + 真实双轨** | SystemModel（理论）+ SystemMap（真实）必须交叉验证（Gap Analyzer 后续） | GPT 2026-06-01 外部评审 |

---

## 3. 阶段拆解

### 3.0 Phase 1.6 — N2 + explore + SystemMap 三件套加固 (1.5-2 天, **先于 V2.0**)

> **本阶段是修订 v1 → v2 新增**。依据：V1.7 报告原文点名的 N2 SystemModel fallback P0 漏洞 + V1.7 漏掉的 planning_graph explore prompt 盲点 + SystemMap 采样薄。

| 任务 | 文件 | 修复漏洞 | 工时 |
|---|---|---|---|
| **1.6.1** 修 N2 SystemModel fallback 频繁触发 | `core/skills/system_modeler.py` | V-1.6.1 (3/4 fixture fallback) | 0.5d |
|  - 排查 4 fixture live test 中 N2 fallback 的具体原因 | | | |
|  - 加固 prompt：把"3 选 1 判定"明确化（"何时 fallback" 的硬规则写进 `<rules>`） | | | |
|  - 跑 4 fixture live 验证 fallback 触发率从 3/4 降到 ≤ 1/4 | | | |
| **1.6.2** planning_graph explore_decide / explore_execute prompt V1.6 化 | `agents/ui/planning_graph.py` | V-1.6.2 (V1.7 漏) | 0.5d |
|  - explore_decide 改 5 段 XML + Output Contract (返回 tool_call 必填) | | | |
|  - explore_execute 加 inter-node 契约（明确"失败时进 record 不抛异常"） | | | |
|  - `<context>` 注入 SystemModel + ExplorationHistory + Goals | | | |
| **1.6.3** 强化 SystemMap 采样 + 加 invariant 测试 | `core/skills/system_mapper.py`, `tests/core/test_system_mapper.py` | V-1.6.3 | 0.4d |
|  - 采样从 10 页 → 20 页，15 元素 → 30 元素 | | | |
|  - 加 `tests/core/test_system_mapper.py` (mock + live skip) | | | |
|  - Invariant: `pages` / `actions` / `forms` 三个字段非空时 LLM 提取稳定性 ≥ 80% | | | |
| **1.6.4** 文档：把 planning_graph explore + SystemMap 加进 `docs/prompt-engineering.md` §8 | `docs/prompt-engineering.md` | 文档同步 | 0.1d |

**Commit 1.6**：`fix(layer1): Phase 1.6 N2+explore+SystemMap 三件套加固`

**验收**：
- N2 SystemModel fallback 触发率从 3/4 → ≤ 1/4 fixture
- planning_graph explore_decide/execute 走 5 段 XML
- SystemMap 采样 20/30 + 4 fixture mock 全过
- V1.7 53 mock + 8 live skip 全过不退化
- L1 ↔ L2 集成 smoke test 通过

---

### 3.1 Phase A — L2 安全网 + 测试基础设施 (1.5 天)

> 不动 prompt，只补最严重的设计漏洞 + 建测试基础设施。

| 任务 | 文件 | 修复漏洞 | 工时 |
|---|---|---|---|
| **A1** 建 `tests/core/test_l2_prompts.py` + `L2_LIVE=1` 开关 | `tests/core/test_l2_prompts.py`, `tests/conftest.py` | 无回归测试 | 0.5d |
| **A2** `record_node` 改按 **token** 估算截断（不按条）+ 截图降采样到 800px | `agents/ui/execution_graph.py:574-586` | V8-V12 context 爆炸 | 0.3d |
| **A3** 修 `decide_node` 覆盖 session_summary 注入（runtime 注入首条 system；decide 不再 insert(0)） | `agents/ui/execution_graph.py:180` + `core/runtime.py:415-425` | V10 session_summary 被覆盖 | 0.2d |
| **A4** 工具失败计入 `consecutive_failures`（execute_node 错误 → +1） | `agents/ui/execution_graph.py:266-267` | V13 工具失败不终止 | 0.2d |
| **A5** evaluate_js 黑名单：检测 `page.goto` / `page.evaluate` / `window.location` / `location.href` / `fetch(` 关键字 → 拒绝执行并返回明确错误 | `agents/ui/tools.py:347-410` | V20 任意 URL 跳转 | 0.2d |
| **A6** assert JSON 解析失败 → `_fallback_assertion()` 走"INCONCLUSIVE + reasoning 解释原因"，不静默 | `agents/ui/execution_graph.py:502` | V17 解析失败无重试 | 0.1d |

**测试套配置**：
- `test_l2_prompts.py` 模板（4 fixture × N invariant = N 个 mock + 4 个 live skip）
- `L2_LIVE=1` 环境变量开关（默认 skip live 测试，CI 跑 mock 即可）
- **e2e 集成测试**：`scratch/test_l2_e2e.py`，跑 3 个真实 case（登录/表单/边界值），验证 record 落库 + ReportBuilder HTML 输出 + WebSocket 流正常

**Commit A**：`fix(layer1+layer2): L2 safety net + test infrastructure (V2.0-A)`

**验收**：
- `pytest tests/core/test_l2_prompts.py` 4 fixture mock 全过
- `pytest tests/agents/ui/test_execution_graph.py` 11 个原测试不退化
- `L2_LIVE=1 pytest tests/core/test_l2_prompts.py::test_l2_live_all_fixtures[prd_purchase]` PASSED
- e2e `python scratch/test_l2_e2e.py` 跑通 3 case

---

### 3.2 Phase B — L2 Prompt V1.6 化 (2.5 天)

> L2 3 个 prompt 全部重写为 5 段 XML + 走 `safe_structured_invoke` + pydantic

| 任务 | 改造点 | 工时 |
|---|---|---|
| **B1** `decide_prompt` 5 段 XML 重写 | `<role>` 单一身份;`<context>` 注入 `<prd_rules>` + `<focus_areas>` + `<scenarios>` + `<risk_points>` + 上轮 `<assertion>` + `<change_report>`;`<task>` 一句话;`<rules>` 编号 1-N;`<examples>` 1 good + 1 bad;`<output_contract>` "**必须调一个工具**（含 mark_task_*）或显式 stop" | 1.0d |
| **B2** `assert_prompt` 5 段 XML 重写 + 走 pydantic | 中文化;Output Contract 改用 `safe_structured_invoke` + `pydantic.AssertionResult(status ∈ {PASS, FAIL, INCONCLUSIVE}, reasoning ≤ 200 字, confidence ∈ {high, medium, low})`;inter-node 契约：上游 change_detector 已判过的别再判 | 0.8d |
| **B3** `step_prompt` 5 段 XML 重写（如果有） | 统一风格 | 0.2d |
| **B4** `_format_page_info` token-aware 截断 | 按 2000 token 上限截断；超长文本保留首 50 字符 + 截断标记 | 0.3d |
| **B5** 账号密码从 system_prompt 剥离 | 改成 `<account role="${role}">username: ${username}</account>` 占位（密码不进 prompt，工具自己读 task_config） | 0.2d |

**测试**：
- 4 fixture × N invariant（N=6-8 拟定）= 24-32 mock 测试
- inter-node 契约测试：decide 输出必带 tool_call，assert 输出必带 status 字段
- good/bad example 回归测试
- L2_LIVE=1 跑 1 fixture live

**Commit B**：`feat(layer2): L2 prompts V1.6 migration (XML + Output Contract + safe_structured_invoke)`

**验收**：
- 4 fixture live test 全过 + Phase A 11 原测试不退化
- assert JSON 解析失败率（v1.7 baseline < 5%，B 后 < 1%）
- `safe_structured_invoke` fallback 路径触发率 < 30%

---

### 3.3 Phase C — 联动 L1 业务模型 (1 天)

> 让 L2 真正消费 L1 + Phase 1.5 输出（CLAUDE.md Rule 3 落地）

| 任务 | 改造点 | 工时 |
|---|---|---|
| **C1** `decide_prompt` `<context>` 加 `<prd_rules>` 注入（来自 `task_config.rules`） | B1 已预留位，C1 只填数据 | 0.2d |
| **C2** 同上加 `<focus_areas>` 注入 | 同上 | 0.2d |
| **C3** 同上加 `<scenarios>` 注入（来自 `task_config._scenarios`） | 同上 | 0.2d |
| **C4** 同上加 `<risk_points>` 注入（来自 `task_config._risk_points`） | 同上 | 0.2d |
| **C5** L2 输出 `reasoning_chain: list[str]` 到 state，ReportBuilder HTML 报告 L2 卡片新增"AI 思考链"折叠区 | `record_node` 写 StepResult + `core/report_builder.py` 加卡片 | 0.2d |

**测试**：
- 端到端 e2e 在真实目标系统跑 1 case，prompt 里能 grep 到 `<prd_rules>` 标签（验证 C1-C4 真的进了 LLM 视野）
- HTML 报告 L2 卡片显示 AI 思考链（验证 C5）

**Commit C**：`feat(layer2): L1→L2 business model linkage (rules/focus_areas/scenarios/risk_points)`

**验收**：
- 4 fixture live 全过 + HTML 报告 L2 卡片显示 reasoning_chain
- e2e 在 http://192.168.31.155 跑过 1 case，prompt 截屏含 4 个 XML 标签

---

### 3.4 Phase D — L2 可观测性 (1 天)

> 让运维/调试有据可查

| 任务 | 改造点 | 工时 |
|---|---|---|
| **D1** 注入 token 估算（`tiktoken` 库在 decide/assert 前后调用，写 state） | `agents/ui/execution_graph.py` 头尾 | 0.2d |
| **D2** execution_logger 增加 `node_enter` / `node_exit` 事件 + 耗时 + token 字段 | `core/execution_logger.py` | 0.3d |
| **D3** ReportBuilder L2 卡片新增"Token 用量"折线图（每步 token 累加） + WebSocket 推 node_enter/exit 流 | `core/report_builder.py` + `api/websocket.py` | 0.3d |
| **D4** `consecutive_failures ≥ 2` 时的 early-warning log + WebSocket 推"告警"事件（限频：每 case 最多 1 次） | `agents/ui/execution_graph.py` + `api/websocket.py` | 0.2d |

**测试**：
- execution_logger 单元测试（mock 节点调用，验证事件序列）
- ReportBuilder HTML 输出含 token 折线（HTML 解析验证）
- WebSocket 流含 node_enter / node_exit / 告警事件（手工 e2e + 自动化测试）

**Commit D**：`feat(layer2): observability (token tracking + node events + early-warning)`

**验收**：
- ReportBuilder HTML 报告看到 token 折线 + node 时间线
- WebSocket 流能在监控页看到"即将失败"提示（验证 consecutive_failures ≥ 2 告警）
- 端到端 e2e 跑通 3 case，报告含全部新指标

---

## 4. 联动性 / 可扩展性 / 风险

### 4.1 联动性
- **L1 不变**：Phase B/C 的 L2 prompt 只**消费** L1 输出，**不修改** L1 任何文件
- **Phase 1.5 加深联动**：C3/C4 让 `scenario_extractor` / `risk_analyzer` 的输出真正被 L2 使用，反过来证明 V1.7 投资有价值
- **ReportBuilder 解耦**：C5 + D3 用 state 字段通讯，不引入新依赖
- **runtime.py 不变**：A3 修的是 execution_graph 内部行为，不动 runtime 调度
- **tools.py 最小改动**：A5 evaluate_js 黑名单是唯一改动，其他 14 工具保持不动
- **planning_graph 改动局部**：1.6.2 只改 explore_decide / explore_execute prompt，不动 graph 拓扑
- **system_mapper 改动局部**：1.6.3 只改采样参数 + 加测试，不动 `SystemMap` schema

### 4.2 可扩展性
- **B1-B2 的 V1.6 模板是通用工厂方法**——未来加 L3 Reflection、L4 Multi-Agent 都能直接套
- **A1 的 `test_l2_prompts.py` 是新测试基础设施**——4 fixture 模板可复用到 L3/L4
- **D2 的 execution_logger 扩展点不限于 L2**——所有子图的 node_enter/exit 都能用
- **A2 的 token 估算**可推广到所有 LLM 调用节点（N1-N3 + L2 + Phase 1.5）
- **1.6.3 的 SystemMap invariant 测试**可作为 Gap Analyzer (V2.1) 的输入契约

### 4.3 风险与缓解

| 风险 | 缓解 |
|---|---|
| 1.6.1 修 N2 fallback 可能引入新 bug | 1.6.1 跑 4 fixture live 对比前后 fallback 率 |
| B1 改 decide_prompt 触发"幻觉漂移" | A1 先建测试套，B1-B2 每改一版跑 4 fixture live 验证 |
| 工具面 (V19-V22) 暂不动 | 记入 V2.1 backlog |
| evaluate_js 沙箱化可能影响合法用例 | A5 只黑名单 5 个关键字 + 错误提示清晰 |
| token 估算不准（中文/工具描述） | D1 用 `tiktoken` 库，分中英文单独校准；偏差 > 30% 回退 |
| WebSocket 告警刷屏 | D4 限频（每 case 最多 1 次告警） |
| C3/C4 注入可能让 prompt 超过 token 上限 | C3/C4 注入时按"前 5 条"截断 |
| e2e 集成测试不稳定 | `scratch/test_l2_e2e.py` 允许部分 case 失败不阻塞主流程 |
| 1.6.3 SystemMap 采样加大可能撞 token 上限 | 1.6.3 跑 live test 验证不超过 30K tokens |

---

## 5. 不在 V2.0 范围（明确）

- ❌ **Phase E Reflection**：需 50 case 数据评估 ROI
- ❌ **Gap Analyzer**（SystemModel vs SystemMap 比对，GPT 新建议）：**V2.1 候选**，本计划只负责"理论 + 真实"双轨的输入端（Phase 1.6），不做比对
- ❌ **Business Graph 数据库选型**：V2.5+ 路线
- ❌ **LangSmith/Langfuse 集成**：运维基建
- ❌ **Multi-Agent 协同**：V3 路线
- ❌ **改 tools.py 14 工具**（除 evaluate_js 黑名单）
- ❌ **PostgreSQL checkpointer 升级到 LangGraph AsyncPostgresSaver**
- ❌ **移除 V19-V22 工具面缺陷**

---

## 6. 验收标准

### 6.1 单元测试
- `pytest tests/core/test_l2_prompts.py` 4 fixture mock 全过（24-32 测试）
- `pytest tests/core/test_system_mapper.py`（Phase 1.6 新增）4 fixture 全过
- `pytest tests/agents/ui/test_execution_graph.py` 11 个原测试不退化
- `pytest tests/core/test_l1_prompts.py tests/core/test_phase15_prompts.py` L1 + Phase 1.5 53 测试不退化

### 6.2 Live Test
- `L1_LIVE=1 pytest tests/core/test_l1_prompts.py::test_l1_live_all_fixtures` 4 fixture 全过（N2 fallback ≤ 1/4）
- `L2_LIVE=1 pytest tests/core/test_l2_prompts.py::test_l2_live_all_fixtures` 4 fixture 全过
- `safe_structured_invoke` fallback 触发率 < 30%
- assert JSON 解析失败率 < 1%（v1.7 baseline < 5%）

### 6.3 E2E 集成测试
- `python scratch/test_l2_e2e.py` 跑通 3 case（登录/表单/边界值）
- 验证 record 落库 + ReportBuilder HTML 输出 + WebSocket 流正常

### 6.4 端到端真实系统
- 在 http://192.168.31.155 真实目标系统上跑过至少 1 case
- prompt 截屏能 grep 到 `<prd_rules>` / `<focus_areas>` / `<scenarios>` / `<risk_points>` 4 个标签
- HTML 报告 L2 卡片显示 reasoning_chain + token 折线
- WebSocket 流能在监控页看到 node_enter / node_exit / 告警事件

---

## 7. 时间线 + Commit 序列

| Day | 阶段 | Commit | 验证 |
|---|---|---|---|
| 1-2 | **Phase 1.6** | `fix(layer1): Phase 1.6 N2+explore+SystemMap 三件套加固` | N2 fallback ≤ 1/4 + explore V1.6 + SystemMap 20/30 + 4 fixture mock |
| 3-4 | Phase A | `fix(layer1+layer2): L2 safety net + test infrastructure` | 11 原测 + 4 fixture mock + e2e 3 case |
| 5-7 | Phase B | `feat(layer2): L2 prompts V1.6 migration` | 4 fixture live 全过 + Phase A/1.6 不退化 |
| 8 | Phase C | `feat(layer2): L1→L2 business model linkage` | HTML 报告 L2 卡片 + e2e prompt grep |
| 9-10 | Phase D | `feat(layer2): observability` | 报告折线 + WS 告警 + 完整 e2e |
| **合计** | **1.6+A+B+C+D** | **5 个独立 commit** | **L2 + planning_graph 追平 L1 V1.7 同等工程标准** | 

---

## 8. 关键文件改动清单

| 文件 | 改动 | 阶段 |
|---|---|---|
| `tests/core/test_l2_prompts.py` | 新增 | A |
| `tests/core/test_system_mapper.py` | 新增 | 1.6 |
| `tests/conftest.py` | 加 `L2_LIVE` 开关 | A |
| `scratch/test_l2_e2e.py` | 新增 | A |
| `core/skills/system_modeler.py` | 1.6.1 修 fallback | 1.6 |
| `core/skills/system_mapper.py` | 1.6.3 采样 + invariant | 1.6 |
| `agents/ui/planning_graph.py` | 1.6.2 explore V1.6 化 | 1.6 |
| `agents/ui/execution_graph.py` | A1-A4/A6 + D1 + D4 | A + D |
| `agents/ui/tools.py` | A5 evaluate_js 黑名单 | A |
| `agents/ui/prompts.py` | B1-B5 + C1-C4 | B + C |
| `core/runtime.py` | A3 session_summary 注入 | A |
| `core/llm_client.py` | B2 新增 pydantic `AssertionResult` | B |
| `core/execution_logger.py` | D2 node_enter/exit | D |
| `core/report_builder.py` | C5 + D3 L2 卡片 + token 折线 | C + D |
| `api/websocket.py` | D3 + D4 推流 | D |
| `docs/prompt-engineering.md` | 1.6.4 扩 §8 加 planning_graph 章节 | 1.6 + 完结后 |
| `docs/devlog/22-layer2-v2.0-completion.md` | 新增（V2.0 完结总结） | 完结后 |
| `docs/devlog/22-phase16-completion.md` | 新增（Phase 1.6 完结总结） | 1.6 完结后 |
| `CONTEXT.md` | 补充 V2.0 + Phase 1.6 记录 | 完结后 |
| `docs/l2-verification-report-v2.0.md` | 新增（类比 v1.7 报告） | 完结后 |

---

## 9. 后续 (V2.1+)

### V2.1 候选 (Backlog)
- **Gap Analyzer**（SystemModel vs SystemMap 比对，输出"疑似功能缺失"）—— **GPT 2026-06-01 新建议**，本计划 V2.0 不做
- tools.py 14 工具缺陷修复（hover / wait_for_visible / OCR / 截图对比）
- `input_text` value 验证
- `mark_task_*` 二次自我验证

### Phase E (Reflection, 条件启动)
- 评估前置：收集 50+ case 数据，看 assert fail 占比 > 30% 才上
- 失败触发反思：assert FAIL → 调反思 LLM 生成 `self_reflection: str` → 注入下一 step 的 decide `<context>`
- 预期收益：pass 率提升 ≥ 5% 才合入

### V2.5+ 路线
- Business Graph 数据库选型 (Neo4j vs PostgreSQL jsonb)
- LangSmith/Langfuse 集成
- 跨任务长期 Memory 沉淀
- Multi-Agent 协同
- LangGraph AsyncPostgresSaver 升级

---

## 10. 修订记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1 | 2026-06-01 (cb8c8ab) | 初版：4 阶段 (A/B/C/D) |
| **v2** | **2026-06-01 (本次)** | **新增 Phase 1.6 (1.6/A/B/C/D 5 阶段)；执行顺序变更为 1.6→A→B→C→D；新增 Gap Analyzer V2.1 候选；工时 7-8d → 9-10d。依据：GPT 外部评审 + V1.7 报告 P0 漏洞核对** |

---

## 11. 参考资料

### 项目内部
- `docs/prompt-engineering.md` — V1.6 5 段 XML 模板（已扩 L2 章节 §8）
- `docs/l1-verification-report-v1.7.md` — L1 + Phase 1.5 验证报告
- `docs/devlog/19-layer1-hardening.md` — V1.5 L1 鲁棒性
- `docs/devlog/20-layer1-prompt-engineering-v17.md` — V1.6 + V1.7 L1 收尾
- `docs/devlog/16-phase2-v1.1-v1.2-graph-refactor.md` — V1.2 SystemMapper 引入
- `CONTEXT.md` — 项目全局状态

### 外部
- Anthropic Prompt Engineering 2026 — XML 分段 + Output Contract
- Anthropic Context Engineering 2025-09 — compaction + just-in-time
- Anthropic Writing Tools for Agents 2025-09 — 工具 namespace + token efficient
- LangGraph 2026 Production Best Practices — typed state + PostgresSaver
- Reflexion 2023 / ReAct / Plan-and-Execute 2026 — 选 ReAct 沿用
- **GPT 2026-06-01 外部评审**（核心建议：补 SystemMap 桥梁 / 建 Gap Analyzer）

---

**方案就绪 v2。** 执行起点：**1.6.1**（修 N2 SystemModel fallback）。
