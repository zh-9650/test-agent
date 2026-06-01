# L2 全面加固 V2.0 — 完整计划

**日期**: 2026-06-01
**作者**: Lead
**前置**: V1.7 (b16ffe8) L1 + Phase 1.5 prompt 全面加固、L1 收尾 (c2e5a2f)
**状态**: 待执行
**范围**: A + B + C + D 全做（4 阶段，7-8 天，4 个独立 commit）

---

## 0. TL;DR

L1 + Phase 1.5 8 个 skill 全部 V1.6 化完成 (b16ffe8 + c2e5a2f)，L2 (execution_graph) 仍是 prompt 调用的 hot path 但工程标准远落后 L1。本计划用 4 阶段 (A 安全网 → B Prompt V1.6 → C 联动 L1 → D 可观测性) 让 L2 追平 L1 V1.7 同等工程标准。

| 阶段 | 工时 | 关键产出 | Commit |
|---|---|---|---|
| **A** 安全网 + 测试基础设施 | 1.5d | 5 个漏洞修复 + `test_l2_prompts.py` + e2e | `fix(layer1+layer2): L2 safety net + test infrastructure` |
| **B** Prompt V1.6 化 | 2.5d | 3 个 prompt 重写 + `safe_structured_invoke` + pydantic | `feat(layer2): L2 prompts V1.6 migration` |
| **C** 联动 L1 业务模型 | 1d | `<context>` 注入 4 字段 + ReportBuilder L2 卡片 | `feat(layer2): L1→L2 business model linkage` |
| **D** 可观测性 | 1d | token 估算 + node 事件 + WebSocket 告警 | `feat(layer2): observability` |
| **合计** | **7-8d** | **L2 达到 L1 V1.7 同等工程标准** | 4 commit |

**核心决策**（来自 2026-06-01 session 拍板）：

1. **范围**：A + B + C + D 全做（不做 Phase E Reflection）
2. **测试**：`test_l2_prompts.py` + `L2_LIVE` 开关 + `scratch/test_l2_e2e.py` 端到端集成测试
3. **evaluate_js 沙箱**：关键字黑名单（5 个：page.goto / page.evaluate / window.location / location.href / fetch(）
4. **合并**：阶段独立 commit（4 个）
5. **不做**：Business Graph / LangSmith / Multi-Agent / 改 tools.py 14 工具（除 evaluate_js）/ checkpointer 升级

---

## 1. 背景与现状

### 1.1 L2 定位

L2 (execution_graph) 是测试执行的引擎，对每条 test_case 跑 `observe → decide → execute → assert → record` 的 ReAct 循环。典型 5 步 case ≈ **6-10 次 LLM 调用**（每个 decide 1 次，assert 0-1 次），单 case 最多 76 个 node 调用。

**L2 是 prompt 调用的 hot path**，调用频次是 L1 + Phase 1.5 合计的 30-100 倍。

### 1.2 L2 vs L1 V1.7 现状对比

| 维度 | L1/Phase 1.5 (V1.7) | L2 (execution_graph) |
|---|---|---|
| Prompt 模式 | V1.6 5 段 XML + Output Contract | V1.5 之前 `##` 自由文本 |
| `safe_structured_invoke` + pydantic | ✅ 全部 8 skill | ❌ assert_node 手剥 JSON 3 层 fallback |
| Inter-node 契约 | ✅ L1↔L2 文档化 (`docs/prompt-engineering.md` §3) | ❌ 缺 |
| 回归测试 | 53 mock + 8 live skip | 11 mock（无 L2 prompt 测试） |
| Live test 开关 | `L1_LIVE=1` | 无 |
| Context 管理 | 静态 | 按"条"截断 + base64 截图全塞 = 撞 65K token 风险 |
| 异常恢复 | 2 safety valve | 工具失败**不**计入 consecutive_failures |
| 联动 L1 业务模型 | L1 → Phase 1.5 → ReportBuilder 完整 | L2 ↔ L1 业务模型**单向**（L2 几乎不消费 rules/focus_areas/RiskPoint） |

### 1.3 23 个设计漏洞（按 ROI 排序）

**P0 — 本轮修**：
- V8-V12 context 爆炸（按"条"截断 + base64 截图全塞 + session_summary 被覆盖 + 无 token 估算）
- V13 工具失败不计入 consecutive_failures
- V17 assert JSON 解析失败无重试
- V20 evaluate_js 任意 URL 跳转

**P1 — 随 B 阶段 prompt 化解决**：
- V1-V7 prompt 质量问题（XML 缺失 / 无 Output Contract / 无契约）
- V14 assert system prompt 英文硬编码
- V15 账号密码进 system prompt 明文
- V16 `rules` / `focus_areas` 未消费
- V18 assert 不区分上游已判过的错误

**P2 — 记入 V2.1+ backlog**：
- V19 tools.py 14 工具缺陷（hover/wait_for_visible/OCR/截图对比）
- V21 `input_text` 不验证 value
- V22 没有截图对比工具
- V23 `mark_task_*` 无 LLM 自我验证

---

## 2. 设计原则

| 原则 | 含义 | 借鉴来源 |
|---|---|---|
| **V1.6 模式一致性** | L2 3 个 prompt 全用 `<role>/<context>/<task>/<rules>/<examples>/<output_contract>` | 项目内部 L1 V1.7 沉淀 |
| **State-driven Agent** | L2 内部状态字段（current_step/consecutive_failures/last_assertion）显式化，**关键决策不埋在 message content 里** | LangGraph 2026 best practice |
| **Token 预算硬约束** | 单 step 估算 < 30K tokens，超出走 compaction；按 token 不按条截断 | Anthropic Context Engineering 2025-09 |
| **ReAct + Hierarchical Assertion 沿用** | 不引入 Plan-and-Execute / Reflection（复杂度溢出 ROI） | 2026 三模式（ReAct 默认、Reflection 要 oracle） |
| **联动 L1 业务模型** | `rules` / `focus_areas` / `scenarios` / `RiskPoint` 必须进 `<context>` | CLAUDE.md Rule 3 |
| **可测试优先** | 改动前先建 test_l2_prompts.py + `L2_LIVE=1` 开关 | L1 模板 |
| **schema 校验前移到 LLM 端** | assert 改用 pydantic `safe_structured_invoke`，不再手剥 | 已有 `llm_client.py` |

---

## 3. 阶段拆解

### 3.1 Phase A — 安全网 + 测试基础设施 (1.5 天)

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

### 3.2 Phase B — Prompt V1.6 化 (2.5 天)

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

### 3.4 Phase D — 可观测性 (1 天)

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

### 4.2 可扩展性
- **B1-B2 的 V1.6 模板是通用工厂方法**——未来加 L3 Reflection、L4 Multi-Agent 都能直接套
- **A1 的 `test_l2_prompts.py` 是新测试基础设施**——4 fixture 模板可复用到 L3/L4
- **D2 的 execution_logger 扩展点不限于 L2**——所有子图的 node_enter/exit 都能用
- **A2 的 token 估算**可推广到所有 LLM 调用节点（N1-N3 + L2 + Phase 1.5）

### 4.3 风险与缓解

| 风险 | 缓解 |
|---|---|
| B1 改 decide_prompt 触发"幻觉漂移" | A1 先建测试套，B1-B2 每改一版跑 4 fixture live 验证 |
| 工具面 (V19-V22) 暂不动 | 记入 V2.1 backlog |
| evaluate_js 沙箱化可能影响合法用例 | A5 只黑名单 5 个关键字 + 错误提示清晰，引导 LLM 用 navigate |
| token 估算不准（中文/工具描述） | D1 用 `tiktoken` 库，分中英文单独校准；偏差 > 30% 回退到按"条"截断 |
| WebSocket 告警刷屏 | D4 限频（每 case 最多 1 次告警） |
| C3/C4 注入可能让 prompt 超过 token 上限 | C3/C4 注入时按"前 5 条"截断，超出在 doc 里标注 |
| e2e 集成测试不稳定（网络/目标系统） | `scratch/test_l2_e2e.py` 允许部分 case 失败不阻塞主流程 |

---

## 5. 不在 V2.0 范围（明确）

- ❌ **Phase E Reflection**：需 50 case 数据评估 ROI
- ❌ **Business Graph 数据库选型**：V2.5+ 路线
- ❌ **LangSmith/Langfuse 集成**：运维基建，单独议
- ❌ **Multi-Agent 协同**：V3 路线
- ❌ **改 tools.py 14 工具**（除 evaluate_js 黑名单）：避免破坏现有 11 个测试
- ❌ **PostgreSQL checkpointer 升级到 LangGraph AsyncPostgresSaver**：架构级改动
- ❌ **移除 V19-V22 工具面缺陷**（hover/visibility/OCR/JS 沙箱化等）：记入 V2.1 backlog

---

## 6. 验收标准

### 6.1 单元测试
- `pytest tests/core/test_l2_prompts.py` 4 fixture mock 全过（24-32 测试）
- `pytest tests/agents/ui/test_execution_graph.py` 11 个原测试不退化
- `pytest tests/core/test_l1_prompts.py tests/core/test_phase15_prompts.py` L1 + Phase 1.5 53 测试不退化

### 6.2 Live Test
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
| 1-1.5 | A | `fix(layer1+layer2): L2 safety net + test infrastructure` | 11 原测 + 4 fixture mock + e2e 3 case |
| 2.5-4 | B | `feat(layer2): L2 prompts V1.6 migration` | 4 fixture live 全过 + Phase A 不退化 |
| 5 | C | `feat(layer2): L1→L2 business model linkage` | HTML 报告 L2 卡片 + e2e prompt grep |
| 6-7 | D | `feat(layer2): observability` | 报告折线 + WS 告警 + 完整 e2e |
| **合计** | **A+B+C+D** | **4 个独立 commit** | **L2 达到 L1 V1.7 同等工程标准** |

---

## 8. 关键文件改动清单

| 文件 | 改动 | 阶段 |
|---|---|---|
| `tests/core/test_l2_prompts.py` | 新增 | A |
| `tests/conftest.py` | 加 `L2_LIVE` 开关 | A |
| `scratch/test_l2_e2e.py` | 新增 | A |
| `agents/ui/execution_graph.py` | A1-A4/A6 + D1 + D4 | A + D |
| `agents/ui/tools.py` | A5 evaluate_js 黑名单 | A |
| `agents/ui/prompts.py` | B1-B5 + C1-C4 | B + C |
| `core/runtime.py` | A3 session_summary 注入 | A |
| `core/llm_client.py` | B2 新增 pydantic `AssertionResult` | B |
| `core/execution_logger.py` | D2 node_enter/exit | D |
| `core/report_builder.py` | C5 + D3 L2 卡片 + token 折线 | C + D |
| `api/websocket.py` | D3 + D4 推流 | D |
| `docs/devlog/21-layer2-v2.0.md` | 新增（总结） | 完结后 |
| `CONTEXT.md` | 补充 V2.0 记录 | 完结后 |
| `docs/prompt-engineering.md` | 补充 L2 模板 + 联动契约 | 完结后 |

---

## 9. 后续 (V2.1+ / E 阶段)

### V2.1 候选 (Backlog)
- tools.py 14 工具缺陷修复（hover / wait_for_visible / OCR / 截图对比）
- `input_text` value 验证
- `mark_task_*` 二次自我验证

### Phase E (Reflection, 条件启动)
- 评估前置：收集 50+ case 数据，看 assert fail 占比 > 30% 才上
- 失败触发反思：assert FAIL → 调反思 LLM 生成 `self_reflection: str` → 注入下一 step 的 decide `<context>`
- `recursion_limit` + `consecutive_failures` 改成 reflection 触发的 safety
- 预期收益：pass 率提升 ≥ 5% 才合入

### V2.5+ 路线
- Business Graph 数据库选型 (Neo4j vs PostgreSQL jsonb)
- LangSmith/Langfuse 集成
- 跨任务长期 Memory 沉淀
- Multi-Agent 协同
- LangGraph AsyncPostgresSaver 升级

---

## 10. 参考资料

### 项目内部
- `docs/prompt-engineering.md` — V1.6 5 段 XML 模板（待本计划完成后扩 L2 章节）
- `docs/l1-verification-report-v1.7.md` — L1 + Phase 1.5 验证报告
- `docs/devlog/19-layer1-hardening.md` — V1.5 L1 鲁棒性
- `docs/devlog/20-layer1-prompt-engineering-v17.md` — V1.6 + V1.7 L1 收尾
- `CONTEXT.md` — 项目全局状态

### 外部
- Anthropic Prompt Engineering 2026 — XML 分段 + Output Contract + 工具 prompt 工程
- Anthropic Context Engineering 2025-09 — just-in-time retrieval + compaction
- Anthropic Writing Tools for Agents 2025-09 — 工具 namespace + token efficient
- LangGraph 2026 Production Best Practices — typed state + PostgresSaver + state 精简
- Reflexion 2023 / ReAct / Plan-and-Execute 2026 三模式 — 选 ReAct 沿用
- LangChain State of Agent Engineering 2026 — observability + 60% production incidents 是 state 管理

---

**方案就绪。** 执行起点：A1（建 `test_l2_prompts.py` + `L2_LIVE` 开关）。
