# Phase 2 (V2.0) - L2 全面加固计划 (Plan)

**时间**: 2026-06-01
**责任人**: Lead
**前置**: V1.7 (b16ffe8) L1 + Phase 1.5 全面加固、L1 收尾 (c2e5a2f)
**状态**: 计划已落盘，待执行
**完整方案**: `docs/layer2-v2.0-plan.md`

---

## 1. 业务目标

L1 + Phase 1.5 8 个 skill 全部 V1.6 化完成 (V1.7)，L2 (execution_graph) 仍是 prompt 调用的 hot path 但工程标准远落后 L1：

- 3 个 L2 prompt 全是 `##` 自由文本（V1.5 之前风格）
- `assert_node` 手剥 JSON 3 层 fallback（没用 `safe_structured_invoke`）
- 没有 L2 prompt 回归测试（`test_l2_prompts.py` 不存在）
- context 按"条"截断 + base64 截图全塞 = 撞 65K token 风险
- 工具失败不计入 `consecutive_failures`
- L2 ↔ L1 业务模型几乎零耦合（`rules` / `focus_areas` / `RiskPoint` 全被忽略）

**V2.0 目标**：用 4 阶段 (A→B→C→D) 让 L2 追平 L1 V1.7 同等工程标准，4 个独立 commit，7-8 天。

## 2. 范围（4 阶段）

| 阶段 | 名称 | 工时 | 修复的关键问题 |
|---|---|---|---|
| **A** | 安全网 + 测试基础设施 | 1.5d | 5 个 P0 漏洞 + `test_l2_prompts.py` + e2e |
| **B** | Prompt V1.6 化 | 2.5d | 3 个 prompt 重写 + pydantic + inter-node 契约 |
| **C** | 联动 L1 业务模型 | 1d | 4 字段 `<context>` 注入 + ReportBuilder L2 卡片 |
| **D** | 可观测性 | 1d | token 估算 + node 事件 + WebSocket 告警 |
| **合计** | | **7-8d** | **4 个独立 commit** |

## 3. 核心决策（已拍板）

| 决策 | 选择 |
|---|---|
| 范围 | A + B + C + D 全做（不做 Phase E Reflection） |
| 测试 | `test_l2_prompts.py` + `L2_LIVE` 开关 + `scratch/test_l2_e2e.py` 端到端集成测试 |
| evaluate_js 沙箱 | 关键字黑名单（5 个：page.goto / page.evaluate / window.location / location.href / fetch(） |
| 合并 | 阶段独立 commit（4 个） |
| 不做 | Business Graph / LangSmith / Multi-Agent / 改 tools.py 14 工具（除 evaluate_js）/ checkpointer 升级 |

## 4. 与 V1.7 的关系

| 维度 | V1.7 (L1 收尾) | V2.0 (L2 收尾) |
|---|---|---|
| 加固的 skill/prompt 数 | 8 (5 L1 + 3 Phase 1.5) | 3 L2 prompt + 1 pydantic schema |
| 回归测试数 (mock) | 53 | 24-32 (新增) |
| 回归测试数 (live skip) | 8 | 4 (新增) |
| 新文档 | 1 (verification report) | 1 (主计划 + devlog 21) |
| 联动深度 | L1 → Phase 1.5 → ReportBuilder 完整 | L1/Phase 1.5 → L2 → ReportBuilder 完整（新增） |
| 可观测性 | execution_logger 基础 | + token 折线 + node 事件 + WS 告警 |

## 5. 关键产出（V2.0 完结时）

- `tests/core/test_l2_prompts.py`（24-32 mock + 4 live skip）
- `scratch/test_l2_e2e.py`（3 case 端到端）
- `agents/ui/prompts.py` 3 个 prompt 全部 V1.6 化
- `core/llm_client.py` 新增 pydantic `AssertionResult`
- `core/report_builder.py` L2 卡片（reasoning_chain + token 折线）
- `core/execution_logger.py` node_enter/exit 事件
- `api/websocket.py` 推 node 流 + 告警
- 4 个独立 commit

## 6. 验收标准

### 单元测试
- 4 fixture mock 全过
- 11 原测试不退化
- L1 + Phase 1.5 53 测试不退化

### Live Test
- `L2_LIVE=1` 4 fixture 全过
- `safe_structured_invoke` fallback 触发率 < 30%
- assert JSON 解析失败率 < 1%

### 端到端
- `scratch/test_l2_e2e.py` 跑通 3 case
- 在 http://192.168.31.155 真实目标系统上跑过至少 1 case
- prompt 截屏能 grep 到 4 个 XML 标签
- HTML 报告 L2 卡片显示 reasoning_chain + token 折线

## 7. V2.0 完结后

写 `docs/devlog/22-layer2-v2.0-completion.md`（实际收尾记录）+ 更新 `CONTEXT.md` + 更新 `docs/prompt-engineering.md` 加 L2 模板 + 写 `docs/l2-verification-report-v2.0.md`（类比 v1.7 报告）。

## 8. 不在 V2.0 范围

- Phase E Reflection（需 50 case 数据评估 ROI）
- Business Graph / LangSmith / Multi-Agent
- 改 tools.py 14 工具（除 evaluate_js 黑名单）
- PostgreSQL checkpointer 升级
- tools.py 工具面缺陷（V19-V22）记入 V2.1 backlog

---

**计划落盘完成。** 完整方案在 `docs/layer2-v2.0-plan.md`。执行起点：A1（建 `test_l2_prompts.py` + `L2_LIVE` 开关）。
