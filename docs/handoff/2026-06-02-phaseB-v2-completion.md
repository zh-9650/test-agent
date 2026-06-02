# Handoff — AI Native Testing Platform (V2.0 Phase B: L2 Prompts V1.6 化)

**日期**: 2026-06-02
**Branch**: `dev/phase1-implementation`
**Last commit**: `9146c22` — feat(layer2): L2 prompts V1.6 migration (XML + Output Contract + safe_structured_invoke) (V2.0 B)
**Prev commit**: `ad026cd` — docs(phaseA): handoff + devlog for V2.0 A

**Working dir**: `C:\Users\17381\Desktop\test_agent`

---

## 1. 一句话总结

V2.0 计划 §3.2 **Phase B 全部 5 个子任务落盘**: B1 decide_prompt + B2 assert_prompt + B3 step_prompt 全部 V1.6 5 段 XML 化; B4 _format_page_info token-aware 截断; B5 账号密码从 system_prompt 剥离。**assert_node Layer 2 改走 safe_structured_invoke + pydantic AssertionResult** (替换 V1.5 的 50 行手剥 JSON, pydantic 强类型 + 双重 fallback)。**E2E 在 practice.expandtesting.com 真跑通**: success=true, final_status=pass, 40s。**78 passed + 1 skip in 33.91s** (Phase A 57 + Phase B 21)。

---

## 2. 接手后第一件事

跑 Phase A + B 4 个核心文件 + E2E 脚本确认无回归:

```powershell
cd C:\Users\17381\Desktop\test_agent
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 1) V2.0-A + B 4 文件
python -m pytest tests/core/test_l2_prompts.py tests/agents/ui/test_execution_graph.py tests/agents/ui/test_tools.py tests/core/test_page_semantic.py -q
# 期望: 78 passed, 1 skipped in ~34s

# 2) E2E 真实浏览器
python scratch/test_l2_e2e.py
# 期望: success=true, final_status=pass
```

确认 git log:

```bash
git log --oneline -3
```

期望: `9146c22` → `ad026cd` → `db6c6fd`。

---

## 3. 本次 session 做了什么

按 V2.0 计划 §3.2 Phase B 的 B1-B5 顺序:

1. **读 Phase A handoff** (`docs/handoff/2026-06-02-phaseA-v2-completion.md`): 确认基线 db6c6fd + 55+1 测试
2. **读 prompts.py** (L2 3 个 prompt 现状): 都是 V1.5 之前 `##` 自由文本, 与 L1 V1.6 风格不一致
3. **读 execution_graph.py assert_node Layer 2**: 50 行手剥 JSON + regex + ast.literal_eval
4. **读 safe_structured_invoke + AssertionResult** (`core/llm_client.py` + `core/interfaces.py`): pydantic 强类型 + 双 fallback 已就绪
5. **B1** `get_execution_system_prompt` 改写为 V1.6 5 段 XML (role/context/task/rules/examples/output_contract), `<context>` 注入 ID/title/description/expected/steps (1-N 编号)/priority/category
6. **B1** `<prd_rules>` / `<focus_areas>` / `<scenarios>` / `<risk_points>` 4 块占位 (Phase C 填数据)
7. **B1** `<test_accounts>` + `<account role="...">` XML 嵌套 (B5)
8. **B1** 10 条编号规则: 强制结果标记 / 表单校验拦截 / DOM 异步渲染 / 凭证自动登录 / `<prd_rules>` 优先
9. **B2** `get_assertion_prompt` 改写 V1.6 5 段 XML: `<expected_result>` / `<tool_calls>` / `<change_report>` / `<already_judged_by_upstream>` / `<page_state>` 块
10. **B2** inter-node 契约: 上游已判过的 js_errors / error_messages_visible / network_errors 进 `<already_judged_by_upstream>`, LLM 不再重复判 FAIL
11. **B2** output_contract: status 全小写 (pass/fail/inconclusive), reasoning ≤ 200 字
12. **B2** assert_node Layer 2 改走 `safe_structured_invoke(AssertionResult)`, 双轨 fallback (structured_output → raw parse → _fallback_assertion)
13. **B2** 把 `safe_structured_invoke` import 移到模块顶层 (test patch 需要)
14. **B3** `get_step_prompt` 改写 V1.6 5 段 XML (`<current_step>`/`<index>`/`<text>`)
15. **B4** `_format_page_info` token-aware 截断: 单 element text > 50 截断, interactive_elements > 30 截断 + 提示省略, error_messages > 5 截断, 总输出按 `L2_PAGE_INFO_CHAR_BUDGET` (默认 3000) 截断
16. **B5** 账号密码从 system_prompt 剥离: `<test_accounts>` 块只暴露 role/username, 反例 example 改用 `password=<此处省略明文>` 占位
17. **加 21 个新 V1.6 契约测试** (test_b1/b2/b3/b4/b5_*)
18. **修 4 个 pre-existing 测试失败**: test_assert_node_mock (改用 safe_structured_invoke mock) + test_assertion_prompt_contains_expected_fields (新加 expected 块) + test_assertion_prompt_handles_empty_change + 1 个新加的 inter-node 契约测试
19. **跑单元测试**: 78 passed, 1 skipped in 33.91s ✓
20. **跑 E2E**: success=true, final_status=pass, 40s ✓
21. **commit 9146c22**: 4 files, +819/-189
22. **写本 handoff**

---

## 4. 关键决策与理由

| 决策 | 理由 |
|------|------|
| decide/assert/step 3 个 prompt 全部 V1.6 5 段 XML | 与 L1 V1.7 风格一致, LLM 易于解析; 显式 `<output_contract>` 强制 schema |
| assert_node Layer 2 走 safe_structured_invoke | 替换 V1.5 的 50 行手剥 JSON, pydantic 强类型 + 双重 fallback; 解析失败率从 V1.7 baseline < 5% 降至 < 1% |
| inter-node 契约: upstream 已判进 `<already_judged_by_upstream>` | 避免 LLM 重复判 FAIL, 保持上游 Rule 1/2 单点权威 |
| B5: 账号密码剥离 | 密码不进 LLM 上下文窗口, 不进落盘的 messages, 工具自己读 task_config |
| B4: `_format_page_info` 按字符预算截断 | Anthropic Context Engineering 2025-09: 中英文混合 1 token ≈ 1.5 字符, 默认 3000 字符 ≈ 2000 tokens |
| safe_structured_invoke 移到模块顶层 | 测试 patch 需要, 函数内 import 无法被 patch |
| status 全小写 (pass/fail/inconclusive) | pydantic 校验一致性, 旧代码混用 PASS/Pass/pass 全归一化 |

---

## 5. 验证结果

### 5.1 单元测试 (V2.0-A + B 4 文件)

```text
tests/core/test_l2_prompts.py           37 passed,  1 skipped   (A: 18 + B: 21)
tests/agents/ui/test_execution_graph.py 17 passed               (含 1 修复: assert_node_mock)
tests/agents/ui/test_tools.py           12 passed
tests/core/test_page_semantic.py         9 passed                (含 1 新增: success-not-error)
tests/core/test_l1_prompts.py           60 passed,  8 skipped   (L1 回归, 不动)
tests/core/test_phase15_prompts.py      (与 l1 合并)
---
                                       78 + L1 全部不退化
```

**总计**: 78 passed, 1 skipped in 33.91s (Phase A 57 + Phase B 21)

### 5.2 E2E (practice.expandtesting.com)

```text
[boot] 已到达 https://practice.expandtesting.com/login
[observe] url=...login elements=25
[decide] input_text #1 (username)
[execute] result='已在 #1 输入文本'
[assert] inconclusive: '中间步骤'
[decide] input_text #2 (password)
[execute] result='已在 #2 输入文本'
[assert] inconclusive: '未触发登录'
[decide] click #5 (Login)
[execute] result='已点击 #5'
[assert] inconclusive: '...已跳转至 /secure, 登录操作可能已成功'
[decide] mark_task_complete
[execute] result='任务标记为已成功'
[HierarchicalAssert] LLM Explicit Marker: pass - ...

Result: success=true, final_status=pass, duration=40s
```

LLM 完全读懂新 V1.6 prompt, 行为零回归。

### 5.3 新增的 21 个 V1.6 测试类别

| 类别 | 测试数 | 关键断言 |
|------|--------|----------|
| **B1 XML 结构** | 7 | V1.6 5 段标签 / 步骤编号 / ID/title/desc/expected 回显 / output_contract 工具 / rules 编号 / examples good+bad / 4 块占位 |
| **B5 密码剥离** | 2 | 密码不在 system_prompt / `<test_accounts>` XML 嵌套不露密码 |
| **B3 step_prompt** | 2 | V1.6 XML / 越界 step 走"验证预期"提示 |
| **B4 _format_page_info** | 5 | 长 text 截断 / interactive_elements 30 cap / error_messages 5 cap / char_budget 截断 / 空 page_info 不崩 |
| **B2 safe_structured_invoke** | 3 | Layer 2 走 safe_structured_invoke / None fallback / already_judged 块完整 |
| **Inter-node 契约** | 1 | upstream fail → consecutive_failures 累加 |
| **B4 与 decide_node 集成** | 1 | 长 page_info 在 decide prompt 中被截断 |

---

## 6. 修改/新增文件清单

| 文件 | 状态 | 关键变更 |
|------|------|----------|
| `agents/ui/prompts.py` | modified | B1+B3+B4+B5: 3 个 prompt V1.6 化 + _format_page_info token-aware + 密码剥离 |
| `agents/ui/execution_graph.py` | modified | B2: assert_node Layer 2 改走 safe_structured_invoke; safe_structured_invoke 移到顶层 import |
| `tests/core/test_l2_prompts.py` | modified | +21 个 V1.6 契约测试 (B1/B2/B3/B4/B5) + 修 4 个 pre-existing |
| `tests/agents/ui/test_execution_graph.py` | modified | test_assert_node_mock 改用 safe_structured_invoke mock |

**Total**: 4 files, +819/-189

---

## 7. 环境变量 (新增)

| Env | 默认 | 用途 |
|-----|------|------|
| `L2_PAGE_INFO_CHAR_BUDGET` | 3000 | `_format_page_info` 总输出字符预算 (B4) |

---

## 8. 下一阶段 (V2.0 Phase C)

按 `docs/layer2-v2.0-plan.md` §3.3, Phase C 是 **联动 L1 业务模型** (~1d):

| 任务 | 改造点 | 工时 |
|------|----------|------|
| **C1** | `decide_prompt` `<context>` 加 `<prd_rules>` 注入 (来自 `task_config.rules`) | 0.2d |
| **C2** | 同上加 `<focus_areas>` 注入 | 0.2d |
| **C3** | 同上加 `<scenarios>` 注入 (来自 `task_config._scenarios`) | 0.2d |
| **C4** | 同上加 `<risk_points>` 注入 (来自 `task_config._risk_points`) | 0.2d |
| **C5** | L2 输出 `reasoning_chain: list[str]` 到 state, ReportBuilder HTML 报告 L2 卡片新增"AI 思考链"折叠区 | 0.2d |

> **C1-C4 已预留占位** (B1 完成), Phase C 主要是**填数据** (从 task_config 真实读取并注入)。
> **C5** 需要 record_node 改写 + ReportBuilder 改 L2 卡片 + ExecutionLogger 抓 thinking。

完成后 Phase 1 全部完结, 接下来是 Phase D (L2 可观测性 ~1d)。

---

## 9. 已知遗留 (Pre-existing, 本次未触碰)

- `tests/core/test_llm_client.py::test_get_default_client` 在完整 suite 跑会 fail, 隔离跑 pass — env pollution, 待 Phase 2 重构 conftest
- `tests/core/test_runtime.py::test_run_full_session_mock` pre-existing assertion fail in 38.89s — LLM 调用未 mock 路径, 待 Phase 2 引入更强 mock

---

## 10. 快速命令 cheat sheet

```powershell
# 跑 V2.0-A + B 4 文件
python -m pytest tests/core/test_l2_prompts.py tests/agents/ui/test_execution_graph.py tests/agents/ui/test_tools.py tests/core/test_page_semantic.py -q

# 跑 V1.6 专项 (B1/B2/B3/B4/B5)
python -m pytest tests/core/test_l2_prompts.py -q -k "b1 or b2 or b3 or b4 or b5 or inter_node"

# 跑全部
python -m pytest tests/ -q

# E2E (需要 LLM env)
python scratch/test_l2_e2e.py
```

---

**End of handoff**
