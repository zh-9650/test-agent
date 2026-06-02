# Handoff — AI Native Testing Platform (V2.0 Phase A: L2 Safety Net + Test Infra)

**日期**: 2026-06-02
**Branch**: `dev/phase1-implementation`
**Last commit**: `db6c6fd` — fix(layer1+layer2): L2 safety net + test infrastructure (V2.0 A)
**Prev commit**: `a293a4e` — docs(handoff): Phase 1.6.2/1.6.3/1.6.4 handoff (L1 收尾完结)

**Working dir**: `C:\Users\17381\Desktop\test_agent`

---

## 1. 一句话总结

V2.0 v2 计划 (`docs/layer2-v2.0-plan.md`) **Phase A 全部 6 个 P0 + 1 隐藏 bug 修复 + 1 误报修复落盘**。**E2E 在 practice.expandtesting.com 真实跑通**: LLM input username → input password → click → mark_task_complete, 4 步全 pass, duration 40s, consecutive_failures=0。**55 + 1 skip 单元测试** 全部通过, **未引入回归**。

---

## 2. 接手后第一件事

跑 V2.0-A 的 4 个核心文件 + E2E 脚本确认 Phase A 落盘无回归:

```powershell
cd C:\Users\17381\Desktop\test_agent
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 1) V2.0-A 单元测试 (4 文件)
python -m pytest tests/core/test_l2_prompts.py tests/agents/ui/test_execution_graph.py tests/agents/ui/test_tools.py tests/core/test_page_semantic.py -q
# 期望: 55 passed, 1 skipped in ~25s

# 2) E2E 真实浏览器 (需要 ANTHROPIC_* env)
python scratch/test_l2_e2e.py
# 期望: success=true, final_status=pass, 4 cycles of observe→decide→execute→assert→record
```

确认 git log:

```bash
git log --oneline -3
```

期望: `db6c6fd` → `a293a4e` (Phase 1.6.2/1.6.3/1.6.4 handoff)。

---

## 3. 本次 session 做了什么

按 V2.0 计划 §3.0 Phase A 的 A1-A6 顺序:

1. **读 V1.6.2/3/4 handoff** (`docs/handoff/2026-06-02-phase16-2-3-4-completion.md`): 确认基线 f4c7e40 + 97 mock + 9 skip
2. **读 V2.0 v2 计划** (`docs/layer2-v2.0-plan.md`): 明确 A1-A6 范围 (token 预算 / session 摘要 / 失败计数 / JS 沙箱 / 降级断言)
3. **读 execution_graph.py / tools.py / prompts.py / interfaces.py / conftest.py / page_semantic.py / runtime.py**: 理解现状
4. **搜公开测试站点** (用户要求避开 192.168.31.155): 候选 6 个, 选中 `practice.expandtesting.com/login` (凭据 `practice` / `SuperSecretPassword!`)
5. **A1** 创建 `tests/core/test_l2_prompts.py` (17 mock + 1 live skip)
6. **A2** 实现 `_truncate_messages_by_token()` (30K budget) + `take_screenshot_compressed()` (JPEG q=60, 节省 ~80% tokens)
7. **A3** `decide_node` 改读 `state.session_summary` (不是 SystemMessage), prepend `<session_summary>` 块到 system_prompt 顶部
8. **A4** `execute_node` 检测 "执行失败" | "未知工具" | "拒绝执行" → `consecutive_failures += 1`, 成功时 reset 0
9. **A5** `evaluate_js` 5 关键词黑名单: `page.goto` / `page.evaluate` / `window.location` / `location.href` / `fetch(`
10. **A6** 抽 `_fallback_assertion(reasoning, parse_error) -> AssertionResult(status="inconclusive", ...)` (AIMessage JSON 解析失败时降级)
11. **修 3 个 pre-existing test 失败** (test_execution_graph.py): observe_node_mock / decide_node_mock / assert_node_mock
12. **修 test_tools.py**: autouse `_auto_set_task` fixture + `ui_tools = tools` alias + `get_element_map()` 工具
13. **写 scratch/test_l2_e2e.py** (Playwright + LangGraph astream, 5-step cap)
14. **跑 E2E** 第一次: `final_status=fail` — **发现两个隐藏 bug**:
    - `_last_tool_calls` 未在 TestState 声明, LangGraph 静默 drop, Rule 0.5 (mark_task_complete → pass) **从未真正生效**
    - `_extract_error_messages` 的 `[role='alert']` 撞 Bootstrap-flash 成功消息, 误判为错误
15. **修两个隐藏 bug**:
    - `core/interfaces.py`: 添加 `_last_tool_calls: list[dict[str, Any]]` 字段
    - `core/page_semantic.py`: `[role='alert']` 加 `:not(.alert-success):not(.flash.success):not(.toast-success):not(.notification-success)`
16. **加测试** `tests/core/test_page_semantic.py::test_success_messages_not_detected_as_errors`
17. **重跑 E2E**: **success=true, final_status=pass, duration 40s**, LLM 正确填账号→点登录→mark_task_complete
18. **跑 V2.0-A 单元测试**: 55 passed, 1 skipped in 24.95s ✓
19. **commit db6c6fd**: 982 insertions, 10 files
20. **写本 handoff**

---

## 4. 关键决策与理由

| 决策 | 理由 |
|------|------|
| 公开测试站点选 practice.expandtesting.com | 专用练习站, 免登录账号, server-rendered (无 React 闪屏), 多测试页 (/login /secure /dropdown /checkboxes /dynamic-id) |
| Token 截断: 保留 system + 末 5 条, 丢中间最老 | Anthropic Context Engineering 2025-09 + MS Compaction 2026: 系统指令最重要, 近期对话次要, 老对话可丢 |
| 截图压缩: JPEG q=60, 保留 base64 | 视觉无明显损失, ~80% size 减少, 17K→4K tokens |
| session_summary 进独立 state 字段 | 修复 V1.7 漏点: decide_node `messages.insert(0, SystemMessage(...))` 每步覆盖前 case 留下的 summary |
| 失败计数: 工具失败 +1, 成功 reset 0 | 与 L1 assert_node 行为一致, 防止老 fail 累积 |
| JS 沙箱: 5 关键词 substring 检查 | LLM tool_call 表面积有限, 简单 substring 已足够; AST/regex 过重 |
| _fallback_assertion 永远 inconclusive | 永远不假装 pass/fail; 保留原始 LLM 摘录 + 错误类型供调试 |
| _last_tool_calls 必须进 TestState 声明 | LangGraph TypedDict state 未声明字段会被静默 drop (本次 e2e 实测) |
| [role='alert'] 加 :not 排除成功类 | Bootstrap/Flash 成功消息用 [role='alert'] 做无障碍, 需排除 |

---

## 5. 验证结果

### 5.1 单元测试 (V2.0-A 4 文件)

```text
tests/core/test_l2_prompts.py           17 passed, 1 skipped   (A1: 5 prompts × 3-4 cases)
tests/agents/ui/test_execution_graph.py 17 passed               (含 3 修复 pre-existing)
tests/agents/ui/test_tools.py           12 passed               (含 1 修复 + autouse + alias)
tests/core/test_page_semantic.py         9 passed                (含 1 新增 success-not-error)
---
                                       55 passed, 1 skipped in 24.95s
```

### 5.2 E2E (practice.expandtesting.com)

```json
{
  "duration": 40.26,
  "node_visits": [
    "observe", "decide", "execute", "assert", "record",  // input username
    "observe", "decide", "execute", "assert", "record",  // input password
    "observe", "decide", "execute", "assert", "record",  // click login
    "observe", "decide", "execute", "assert", "record"   // mark_task_complete
  ],
  "steps": 1,
  "current_step": 4,
  "consecutive_failures": 0,
  "final_status": "pass",
  "final_url": "https://practice.expandtesting.com/secure",
  "success": true
}
```

### 5.3 完整 suite (含 pre-existing 问题, 与本次无关)

- `tests/core/test_llm_client.py::test_get_default_client`: 完整 suite 跑会 fail, 单跑 pass; pre-existing env pollution (其他测试污染 ANTHROPIC_AUTH_TOKEN), **不在本次 V2.0-A 范围**
- `tests/core/test_runtime.py::test_run_full_session_mock`: pre-existing assertion fail in 38.89s (LLM 调用 _save_report 的 summary 路径), 不在 V2.0-A 范围

---

## 6. 修改/新增文件清单

| 文件 | 状态 | 关键变更 |
|------|------|----------|
| `agents/ui/execution_graph.py` | modified | A1 prompts usage / A2 token truncate / A3 session_summary / A4 consecutive_failures / A6 fallback_assertion / _last_tool_calls declared in TestState (interfaces.py) |
| `agents/ui/tools.py` | modified | A5 JS keyword blacklist / `ui_tools = tools` alias / `get_element_map()` helper |
| `core/page_semantic.py` | modified | A2 `take_screenshot_compressed()` (JPEG q=60) / `_extract_error_messages` 排除 .alert-success 等 |
| `core/runtime.py` | modified | A3 `_execute_test_case*` 写入 `session_summary` state 字段 (2 处, stream + 非 stream) |
| `core/interfaces.py` | modified | **新增** `_last_tool_calls: list[dict[str, Any]]` 字段 (修复隐藏 bug) |
| `tests/core/test_l2_prompts.py` | **NEW** | A1 18 个测试 (17 mock + 1 live skip) |
| `tests/agents/ui/test_execution_graph.py` | modified | 修 3 个 pre-existing test (observe / decide / assert mock) |
| `tests/agents/ui/test_tools.py` | modified | autouse `_auto_set_task` fixture + 修 1 个 pre-existing |
| `tests/core/test_page_semantic.py` | modified | **新增** `test_success_messages_not_detected_as_errors` (覆盖 _extract_error_messages 修复) |
| `scratch/test_l2_e2e.py` | **NEW** | 完整 E2E 冒烟脚本 (Playwright + LangGraph astream) |

**Total**: 10 files, +982 / -41

---

## 7. 环境变量 (新增)

| Env | 默认 | 用途 |
|-----|------|------|
| `L2_TOKEN_BUDGET` | 30000 | 单次 LLM 调用的 token 预算上限 (A2) |
| `L2_SCREENSHOT_QUALITY` | 60 | JPEG 压缩质量 (1-100, 越低越小) (A2) |
| `L2_SCREENSHOT_COMPRESSED` | 1 | 设 0 关闭压缩 (A2) |
| `L2_LIVE` | (unset) | 设为 1 跑 L2 真实 LLM 测试 (A1) |
| `L2_DEBUG_ASSERT` | (unset) | 设为 1 打印 assert_node 内部状态 (debug 用, 已在 e2e 后移除) |

---

## 8. 下一阶段 (V2.0 Phase B)

按 `docs/layer2-v2.0-plan.md` §3.0, Phase B 是 **L2 prompts V1.6 化** (~2.5d):

- **B1**: 5 个 L2 提示 (observe_system / decide_system / execute_task / assert_task / record_task) 改写为 V1.6 5 段 XML (role/context/task/rules/examples/output_contract)
- **B2**: 把 `_system_model` / `task_config` / `session_summary` 都通过 `<context>` 块注入, 不再用 SystemMessage 切片
- **B3**: `<output_contract>` 显式约束 tool_call 必填 / mark_task_complete reasoning 格式 / AssertionResult JSON schema
- **B4**: 18 → ~35 个 V1.6.5 测试

预计 2.5d 工作量, 完成后 Phase 1 全部完结, 可进入 Phase 2 (多 agent 扩展 / API agent / Mobile agent)。

---

## 9. 已知遗留 (Pre-existing, 已在 V1.6.4 handoff 记录, 本次未触碰)

- `tests/core/test_llm_client.py::test_get_default_client` 在完整 suite 跑会 fail, 隔离跑 pass — env pollution, 待 Phase 2 重构 conftest 时统一修
- `tests/core/test_runtime.py::test_run_full_session_mock` pre-existing assertion fail (38.89s) — LLM 调用了未 mock 的 `_save_report` 路径, 待 Phase 2 引入更强 mock
- `scratch/test_l1_e2e.py` 已存在, 本次新增 `scratch/test_l2_e2e.py`, 命名规范

---

## 10. 快速命令 cheat sheet

```powershell
# 跑 V2.0-A 4 文件
python -m pytest tests/core/test_l2_prompts.py tests/agents/ui/test_execution_graph.py tests/agents/ui/test_tools.py tests/core/test_page_semantic.py -q

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
