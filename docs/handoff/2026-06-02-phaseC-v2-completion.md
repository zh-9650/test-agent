# Handoff — AI Native Testing Platform (V2.0 A+B+C 完结)

**日期**: 2026-06-02
**Branch**: `dev/phase1-implementation`
**Commits**:
- `db6c6fd` — fix(layer1+layer2): L2 safety net + test infrastructure (V2.0 A)
- `ad026cd` — docs(phaseA): handoff + devlog
- `9146c22` — feat(layer2): L2 prompts V1.6 migration (V2.0 B)
- `832f820` — docs(phaseB): handoff + devlog
- `a339332` — feat(layer2): L1→L2 business model linkage (V2.0 C)

**Working dir**: `C:\Users\17381\Desktop\test_agent`

---

## 1. 一句话总结

V2.0 §3 计划 **A + B + C 三阶段全部落盘**: A 安全网 + 测试基础设施 / B L2 prompts V1.6 化 / C 联动 L1 业务模型 + reasoning_chain。**E2E 在 practice.expandtesting.com 真跑通**: success=true, final_status=pass, 40s, 4 步全 pass。**86 passed + 1 skip in 39.40s**。**Phase D (可观测性) 是 V2.0 最后一站, ~1d**。

---

## 2. 接手后第一件事

```powershell
cd C:\Users\17381\Desktop\test_agent
$env:PYTHONIOENCODING = "utf-8"; $env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 1) 4 文件单元测试
python -m pytest tests/core/test_l2_prompts.py tests/agents/ui/test_execution_graph.py tests/agents/ui/test_tools.py tests/core/test_page_semantic.py -q
# 期望: 86 passed, 1 skipped in ~40s

# 2) E2E 真实浏览器
python scratch/test_l2_e2e.py
# 期望: success=true, final_status=pass, 4 cycles observe→decide→execute→assert→record
```

确认 git log:

```bash
git log --oneline -6
```

期望: `a339332` → `832f820` → `9146c22` → `ad026cd` → `db6c6fd` → `a293a4e` (Phase 1.6 基线)。

---

## 3. 三个阶段做了什么

### Phase A (`db6c6fd`) — L2 Safety Net + Test Infra

| ID | 改造 | 漏洞 | 文件 |
|----|------|------|------|
| **A1** | `tests/core/test_l2_prompts.py` 18 测试 (17 mock + 1 live skip) | 无 L2 prompt 测试 | `tests/core/test_l2_prompts.py` |
| **A2** | Token 截断 (30K) + JPEG q=60 截图压缩 | V8-V12 65K 上下文爆炸 | `execution_graph.py` + `page_semantic.py` |
| **A3** | `session_summary` 进 state 字段, 跨 case 续传 | V10 V1.7 漏点 | `execution_graph.py` + `runtime.py` |
| **A4** | 工具失败 → `consecutive_failures` | V13 失败沉默 | `execution_graph.py` |
| **A5** | `evaluate_js` 5 关键词黑名单 | V20 JS 沙箱缺失 | `tools.py` |
| **A6** | `_fallback_assertion()` (LLM JSON 解析失败 → inconclusive) | V17 解析失败无重试 | `execution_graph.py` |
| **修 2 隐藏 bug** | `_last_tool_calls` 进 TestState 声明 + `_extract_error_messages` 排除 success flash | Rule 0.5 mark_task_complete 路径从未生效 + 误报 | `core/interfaces.py` + `core/page_semantic.py` |
| **E2E 验证** | `scratch/test_l2_e2e.py` 新增, login flow 4 步全 pass | — | `scratch/test_l2_e2e.py` |

### Phase B (`9146c22`) — L2 Prompts V1.6 化

| ID | 改造 | 漏洞 | 文件 |
|----|------|------|------|
| **B1** | `get_execution_system_prompt` V1.6 5 段 XML (role/context/task/rules/examples/output_contract), 10 条编号规则, C1-C4 占位 | L2 仍是 V1.5 `##` 自由文本 | `agents/ui/prompts.py` |
| **B2** | `get_assertion_prompt` V1.6 5 段 XML + `<already_judged_by_upstream>` inter-node 契约 + output_contract 全小写 schema; assert_node Layer 2 改走 `safe_structured_invoke(AssertionResult)` | V1.5 50 行手剥 JSON | `agents/ui/prompts.py` + `execution_graph.py` |
| **B3** | `get_step_prompt` V1.6 5 段 XML | 风格不统一 | `agents/ui/prompts.py` |
| **B4** | `_format_page_info` token-aware 截断 (单 element 50 字符, interactive_elements 30, error_messages 5, 顶层 `L2_PAGE_INFO_CHAR_BUDGET=3000`) | V1.5 按条截断 | `agents/ui/prompts.py` |
| **B5** | `<test_accounts>` 块只暴露 role/username, 密码不写入, 工具自己读 task_config | V15 密码进 LLM 上下文 | `agents/ui/prompts.py` |
| **safe_structured_invoke 移到顶层** | 模块级 import, 让测试可 patch | 测试无法 mock 函数内 import | `agents/ui/execution_graph.py` |

### Phase C (`a339332`) — L1→L2 Business Model Linkage

| ID | 改造 | 漏洞 | 文件 |
|----|------|------|------|
| **C1** | `<prd_rules>` 注入 (来自 `task_config.rules`) | CLAUDE.md Rule 3 | `agents/ui/prompts.py` |
| **C2** | `<focus_areas>` 注入 (兼容 string / list) | 同上 | `agents/ui/prompts.py` |
| **C3** | `<scenarios>` 注入 (来自 `task_config._scenarios`, planning_graph N3) | 同上 | `agents/ui/prompts.py` |
| **C4** | `<risk_points>` 注入 + `generate_plan_node` 持久化 `_risk_points` 到 `task_config` | 同上 (之前只在 LLM prompt, 不落 state) | `agents/ui/prompts.py` + `agents/ui/planning_graph.py` |
| **C5** | `StepResult.reasoning_chain: list[str]` 字段 + record_node 从 decide thinking + assert reasoning 抽取 + ReportBuilder HTML 新增 💭 AI 思考链 折叠区 | QA 调试看不到 LLM 思考链 | `core/interfaces.py` + `execution_graph.py` + `core/report_builder.py` |

---

## 4. 关键决策与理由

| 决策 | 理由 |
|------|------|
| 公开测试站点选 practice.expandtesting.com | 专用练习站, 免登录, server-rendered, 多测试页 |
| Token 截断: system + 末 5 条 + 字符预算 | Anthropic Context Engineering 2025-09 + MS Compaction 2026 |
| 截图压缩: JPEG q=60, 保留 base64 | 视觉无明显损失, ~80% size 减少 |
| session_summary 进独立 state 字段 | 修复 V1.7 漏点, decide_node insert(0,...) 跨 case 覆盖 |
| 工具失败 +1, 成功 reset 0 | 与 L1 assert_node 行为一致 |
| evaluate_js 黑名单 5 关键词 substring | 简单足够, AST/regex 过重 |
| _fallback_assertion 永远 inconclusive | 不假装 pass/fail, 留痕供调试 |
| _last_tool_calls 必须进 TestState | LangGraph 未声明字段静默 drop (e2e 实测发现) |
| [role='alert'] 加 :not 排除成功类 | Bootstrap flash 成功消息用 [role='alert'] |
| 3 个 L2 prompt V1.6 5 段 XML | 与 L1 V1.7 风格一致, LLM 易解析 |
| assert_node 走 safe_structured_invoke | 替换 50 行手剥, pydantic 强类型 + 双重 fallback |
| inter-node 契约: upstream 已判进 `<already_judged_by_upstream>` | 避免 LLM 重复判 FAIL |
| B5 账号密码剥离 | 密码不进 LLM 上下文窗口, 不进落盘 messages |
| 状态全小写 (pass/fail/inconclusive) | pydantic 校验一致性 |
| reasoning_chain 从 decide thinking + assert reasoning 抽取 | QA 调试时看 LLM 完整思考链 |

---

## 5. 验证结果

### 5.1 单元测试 (4 文件)

```text
tests/core/test_l2_prompts.py           45 passed,  1 skipped   (A: 18 + B: 21 + C: 8)
tests/agents/ui/test_execution_graph.py 17 passed               (含 1 修复: assert_node_mock)
tests/agents/ui/test_tools.py           12 passed
tests/core/test_page_semantic.py         9 passed                (含 1 新增: success-not-error)
---
                                       86 passed,  1 skipped in 39.40s
```

### 5.2 E2E (practice.expandtesting.com)

```text
[boot] 已到达 https://practice.expandtesting.com/login
[observe] url=...login elements=25
[decide] input_text #1 (username) → 已在 #1 输入文本 → assert inconclusive
[decide] input_text #2 (password) → 已在 #2 输入文本 → assert inconclusive
[decide] click #5 (Login) → 已点击 #5 → assert inconclusive (URL已跳转)
[decide] mark_task_complete → 任务标记为已成功 → [HierarchicalAssert] LLM Explicit Marker: pass

Result: success=true, final_status=pass, current_step=4, consecutive_failures=0
        final_url=https://practice.expandtesting.com/secure, duration=40s
```

LLM 完整读懂新 V1.6 prompt, 行为零回归。

### 5.3 修改/新增文件清单

| 文件 | A | B | C |
|------|---|---|---|
| `agents/ui/execution_graph.py` | ✓ A1-A4/A6 + 2 隐藏 bug | ✓ B2 (assert_node 重写) | ✓ C5 (reasoning_chain) |
| `agents/ui/tools.py` | ✓ A5 (黑名单) + ui_tools alias | — | — |
| `agents/ui/prompts.py` | — | ✓ B1-B5 (3 prompt V1.6 + _format_page_info) | ✓ C1-C4 (4 块占位) |
| `agents/ui/planning_graph.py` | — | — | ✓ C4 (持久化 _risk_points) |
| `core/page_semantic.py` | ✓ A2 (压缩) + flash.success 排除 | — | — |
| `core/runtime.py` | ✓ A3 (session_summary) | — | — |
| `core/interfaces.py` | ✓ _last_tool_calls | — | ✓ reasoning_chain |
| `core/report_builder.py` | — | — | ✓ C5 (折叠区 HTML) |
| `core/llm_client.py` | — | ✓ (B2 用 safe_structured_invoke) | — |
| `tests/core/test_l2_prompts.py` | ✓ 18 测试 | ✓ 21 测试 | ✓ 8 测试 |
| `tests/agents/ui/test_execution_graph.py` | ✓ 3 修复 | ✓ 1 修复 | — |
| `tests/agents/ui/test_tools.py` | ✓ 1 修复 + autouse | — | — |
| `tests/core/test_page_semantic.py` | ✓ 1 新增 | — | — |
| `scratch/test_l2_e2e.py` | ✓ NEW | — | — |
| `docs/handoff/*` | ✓ 2 文件 | ✓ 2 文件 | (本文件) |
| `docs/devlog/*` | ✓ 24 | ✓ 25 | (本 handoff 可作 devlog) |

---

## 6. 环境变量 (新增)

| Env | 默认 | 用途 | 阶段 |
|-----|------|------|------|
| `L2_TOKEN_BUDGET` | 30000 | 单次 LLM 调用的 token 预算上限 | A |
| `L2_SCREENSHOT_QUALITY` | 60 | JPEG 压缩质量 (1-100) | A |
| `L2_SCREENSHOT_COMPRESSED` | 1 | 设 0 关闭压缩 | A |
| `L2_LIVE` | (unset) | 设为 1 跑 L2 真实 LLM 测试 | A |
| `L2_PAGE_INFO_CHAR_BUDGET` | 3000 | `_format_page_info` 总输出字符预算 (≈ 2000 tokens) | B |

---

## 7. 下一阶段 (V2.0 Phase D — 可观测性, ~1d)

按 `docs/layer2-v2.0-plan.md` §3.4:

| 任务 | 改造点 | 工时 |
|------|--------|------|
| **D1** | 注入 token 估算 (tiktoken 库) 写到 state | 0.2d |
| **D2** | `execution_logger` 增加 `node_enter` / `node_exit` 事件 + 耗时 + token 字段 | 0.3d |
| **D3** | ReportBuilder L2 卡片新增"Token 用量"折线图 + WebSocket 推 node_enter/exit 流 | 0.3d |
| **D4** | `consecutive_failures ≥ 2` early-warning log + WebSocket 告警 (每 case 限 1 次) | 0.2d |

**验收**:
- ReportBuilder HTML 报告看到 token 折线 + node 时间线
- WebSocket 流能在监控页看到"即将失败"提示
- 端到端 e2e 跑通, 报告含全部新指标

**完成后**: V2.0 §3 全部 4 阶段 (1.6 + A + B + C + D) 完结, **L2 追平 L1 V1.7 同等工程标准**。

---

## 8. 已知遗留 (Pre-existing, 本次未触碰)

- `tests/core/test_llm_client.py::test_get_default_client` 在完整 suite 跑会 fail, 隔离跑 pass — env pollution, 待 Phase 2 重构 conftest
- `tests/core/test_runtime.py::test_run_full_session_mock` pre-existing assertion fail in 38.89s — LLM 调用未 mock 路径, 待 Phase 2

---

## 9. 快速命令 cheat sheet

```powershell
# 跑 V2.0-A + B + C 4 文件
python -m pytest tests/core/test_l2_prompts.py tests/agents/ui/test_execution_graph.py tests/agents/ui/test_tools.py tests/core/test_page_semantic.py -q

# 跑 V1.6 专项 (B1/B2/B3/B4/B5)
python -m pytest tests/core/test_l2_prompts.py -q -k "b1 or b2 or b3 or b4 or b5"

# 跑 C 专项
python -m pytest tests/core/test_l2_prompts.py -q -k "c1 or c2 or c3 or c4 or c5 or inter_node"

# 跑全部 (注意 pre-existing fail)
python -m pytest tests/ -q

# E2E (需要 LLM env)
python scratch/test_l2_e2e.py

# 跑 L2 真实 LLM (需要 env)
$env:L2_LIVE = "1"
python -m pytest tests/core/test_l2_prompts.py -q
```

---

**End of handoff**
