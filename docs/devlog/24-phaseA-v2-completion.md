# V2.0 Phase A — L2 Safety Net + Test Infrastructure

**时间**: 2026-06-02
**责任人**: Lead
**前置**: V1.6.2/1.6.3/1.6.4 (f4c7e40) L1 收尾 + V2.0 v2 计划 (008bb79) §3.0 Phase A
**状态**: ✅ 已完成
**Commit**: `db6c6fd` — fix(layer1+layer2): L2 safety net + test infrastructure (V2.0 A)
**范围**: Phase A (V2.0 §3.0) — 6 个 P0 修复 + 1 隐藏 bug + 1 误报修复 + 4 个测试文件 + 1 个 E2E 脚本
**E2E 站点**: `https://practice.expandtesting.com/login` (凭据 `practice` / `SuperSecretPassword!`)

---

## 1. 业务目标

V2.0 计划 §3.0 Phase A 是 L2 (执行图) 的 6 个 P0 防御措施 + 测试基础设施:

| ID | 目标 | 漏洞 | 文件 |
|----|------|------|------|
| **A1** | L2 prompts 5 个完整 mock 化测试 (含 V1.6 模板) | V-A1: 无 L2 prompt 测试, 改坏无人知 | `tests/core/test_l2_prompts.py` |
| **A2** | Token-aware 截断 (30K) + 截图压缩 (JPEG q=60) | V-A2: 65K 上下文炸裂风险 | `execution_graph.py` + `page_semantic.py` |
| **A3** | `session_summary` 进独立 state 字段, 跨 case 续传 | V-A3: V1.7 漏点 (insert(0,...) 覆盖) | `execution_graph.py` + `runtime.py` |
| **A4** | execute_node 工具失败 → consecutive_failures | V-A4: 失败沉默 | `execution_graph.py` |
| **A5** | evaluate_js 5 关键词黑名单 | V-A5: JS 沙箱缺失 | `tools.py` |
| **A6** | AIMessage JSON 解析失败 → 降级 inconclusive | V-A6: LLM 偶发 JSON 错位致误报 | `execution_graph.py` |

**Phase A 目标**:
- 6 个 P0 防御落盘, **不允许 L2 阶段重复 V1.7 漏点**
- 18 个新测试 (A1) + 修复 3 个 pre-existing + 1 个 E2E
- 在公开测试站点 (非内网) 端到端跑通至少 1 个 case

---

## 2. A1 — L2 prompts 5 个 mock 化测试

### 2.1 改造点

`tests/core/test_l2_prompts.py` 新增, 覆盖 5 个 L2 提示函数:

| 函数 | 测试数 | 关键断言 |
|------|--------|----------|
| `get_execution_system_prompt` | 4 | V1.6 5 段 XML 完整 / 5 个子任务语义 / 工具列表完整 / role/context/task/rules/examples/output_contract 全有 |
| `get_decide_step_prompt` | 3 | 输入元素映射 / 当前步骤编号 / 期望结果引导 |
| `get_assert_prompt` | 4 | 期望结果回显 / 变化检测结果 / 5 段 XML 完整 / 失败保留 4 字段 |
| `get_observe_prompt` | 3 | 页面 URL / 元素映射 / 当前 step 引导 |
| `get_execute_task_prompt` | 3 | 工具名 / 目标定位 / 5 段 XML 完整 |

**L1_LIVE / L2_LIVE 隔离**: 默认全 mock, 设 `L2_LIVE=1` 跑真实 LLM (1 个测试)。

**测试数**: 17 mock + 1 live skip = **18 个测试**。

---

## 3. A2 — Token-aware 截断 + 截图压缩

### 3.1 Token 截断 (`_truncate_messages_by_token`)

```python
def _truncate_messages_by_token(messages, budget):
    """Keep system + last 5, drop middle oldest-first until <= budget."""
    # 借鉴 Anthropic Context Engineering 2025-09 + MS Compaction 2026
```

- 保留: `messages[0]` (system) + 末 5 条
- 丢弃: 中间从最老开始丢, 直到 token 总数 ≤ `L2_TOKEN_BUDGET` (默认 30000)
- 应用点: `record_node` (写盘前最后一次截断)

**为什么不每次都截断**: observe / execute 都跑得快, 主要风险在 record 累积时。

### 3.2 截图压缩 (`take_screenshot_compressed`)

```python
async def take_screenshot_compressed(page, quality=60):
    """JPEG q=60, 保留 base64 (LLM 接受). 默认 ~80% size reduction."""
```

- 质量: 默认 60 (env `L2_SCREENSHOT_QUALITY` 可调)
- 17K tokens (PNG) → 4K tokens (JPEG)
- 视觉无明显损失
- 应用点: `execute_node` 的 `screenshot_after` 字段

---

## 4. A3 — `session_summary` 进 state 字段

### 4.1 V1.7 漏点还原

旧代码:
```python
decide_node:
  messages.insert(0, SystemMessage(content=summary_block))
  return {"messages": messages}
```

**问题**: 每步 decide 都会 `insert(0, ...)`, 第二个 case 的 summary 进来时, 把第一个 case 的 summary 顶掉, 然后下一次 step 又被新 prompt 覆盖。**跨 case 续传彻底失效**。

### 4.2 V2.0 修复

- `runtime.py` 写入 `execution_state["session_summary"] = summaries_text`
- `decide_node` 读 `state.get("session_summary", "")`, prepend 到 system_prompt 顶部:
  ```
  <session_summary>
  - TC-001: 登录成功, 跳转到 /secure
  - TC-002: 表单校验失败, 显示红字
  </session_summary>

  [原有 base system_prompt]
  ```

**为什么 state 字段而非 SystemMessage**: state 字段由 LangGraph 持久化, 跨步跨 node 不变; SystemMessage 在 messages list 里会乱。

---

## 5. A4 — 工具失败计入 consecutive_failures

### 5.1 改造点

`execute_node` 检测 3 类失败信号:
- `"执行失败"` — tool 抛异常
- `"未知工具"` — LLM 调了不存在的工具
- `"拒绝执行"` — evaluate_js 撞黑名单

触发即 `consecutive_failures += 1`, **break** 后续工具 (避免 cascade), 成功时 reset 0。

**与 L1 assert_node 行为一致**: 都把"连续失败"作为 safety valve (默认 3 次跳过当前 case)。

---

## 6. A5 — evaluate_js 5 关键词黑名单

### 6.1 关键词列表

```python
JS_BLACKLIST = ["page.goto", "page.evaluate", "window.location", "location.href", "fetch("]
```

**5 个覆盖**:
- 导航类: `page.goto` / `window.location` / `location.href`
- 间接执行类: `page.evaluate`
- 网络绕过类: `fetch(` (避开 Playwright 拦截)

**实现**: 大小写不敏感 substring 检查, 5 关键词全扫一遍, 命中任意 1 个返 `"拒绝执行: 脚本包含禁用操作 {keyword}"`。

**为什么不做 AST 分析**: LLM tool_call 表面积有限, 简单 substring 已足够, AST/regex 过重。

---

## 7. A6 — `_fallback_assertion` 降级

### 7.1 改造点

```python
def _fallback_assertion(reasoning: str, parse_error: str) -> AssertionResult:
    return AssertionResult(
        status="inconclusive",
        reasoning=reasoning,
        raw_response_excerpt=reasoning[:500],
        error_type=parse_error,
    )
```

**触发条件**: AIMessage JSON 解析失败 (LLM 偶发返回单引号、缺逗号、注水解释等)。

**为什么永远 inconclusive**: 永远不假装 pass/fail; 保留原始 LLM 摘录 + 错误类型供调试 + 给后续人工复审留痕。

---

## 8. E2E 跑通过程中发现的 2 个隐藏 bug

### 8.1 Bug #1: `_last_tool_calls` 字段未声明

**症状**: E2E 跑完, 4 步全成, LLM 最后调 `mark_task_complete` 带完整 reasoning, **但 final_status=fail**。

**根因**: `assert_node` Rule 0.5 (mark_task_complete → pass) 读 `state.get("_last_tool_calls", [])` 永远是空。原因是 `execute_node` 返回 `{"_last_tool_calls": tool_calls}`, 但 `TestState` 未声明此字段, **LangGraph TypedDict state 静默 drop 未声明字段**。

**修复** (`core/interfaces.py`):
```python
_last_tool_calls: list[dict[str, Any]]  # execute_node → assert_node
```

**教训**: LangGraph state 字段必须**显式声明**; 不声明的字段会被静默丢弃, 调试极难发现。

### 8.2 Bug #2: `[role='alert']` 撞 Bootstrap-flash 成功消息

**症状**: 登录后 URL 跳转到 `/secure`, LLM 调 `mark_task_complete`, 但 Rule 1 (error_messages) 先 fire, 报"页面错误: ['You logged into a secure area!']"。

**根因**: `_extract_error_messages` 的 selector `[role='alert']:visible` 撞 Bootstrap / practice.expandtesting.com 的成功 flash (Bootstrap 标准做法是用 `role="alert"` 做无障碍)。

**修复** (`core/page_semantic.py`):
```python
"[role='alert']:visible:not(.alert-success):not(.flash-success):not(.flash.success):not(.toast-success):not(.notification-success)"
```

**新增测试** `tests/core/test_page_semantic.py::test_success_messages_not_detected_as_errors` 锁死回归。

---

## 9. 测试结果

### 9.1 V2.0-A 4 文件

```text
tests/core/test_l2_prompts.py           17 passed,  1 skipped   (A1)
tests/agents/ui/test_execution_graph.py 17 passed              (含 3 修复)
tests/agents/ui/test_tools.py           12 passed              (含 1 修复)
tests/core/test_page_semantic.py         9 passed              (含 1 新增)
---
                                       55 passed,  1 skipped in 24.95s
```

### 9.2 E2E (practice.expandtesting.com)

```text
[boot] 已到达 https://practice.expandtesting.com/login
[observe] url=...login elements=25
[decide] input_text #1 (username)     ← LLM 决策
[execute] result='已在 #1 输入文本'
[assert] inconclusive: '中间步骤，页面无明显变化'
[observe] url=...login elements=25
[decide] input_text #2 (password)     ← LLM 决策
[execute] result='已在 #2 输入文本'
[assert] inconclusive: '未触发登录动作'
[observe] url=...login elements=26
[decide] click #5 (Login)             ← LLM 决策
[execute] result='已点击 #5'
[assert] inconclusive: '...已跳转至 /secure, 登录操作可能已成功'
[observe] url=...secure elements=22
[decide] mark_task_complete           ← LLM 决策
[execute] result='任务标记为已成功'
[HierarchicalAssert] LLM Explicit Marker: pass - ...
[assert] pass: '测试用例 TC-L2-001 已成功完成...'

Result: success=true, final_status=pass, duration=40.26s
```

---

## 10. 关键决策与理由

| 决策 | 理由 |
|------|------|
| 公开站点选 practice.expandtesting.com | 专用练习站, 免登录账号, server-rendered, 多测试页 |
| Token 截断: system + 末 5 条 | Anthropic Context Engineering 2025-09 + MS Compaction 2026 |
| 截图压缩: JPEG q=60 | 视觉无明显损失, ~80% size 减少 |
| session_summary 进 state 字段 | 修复 V1.7 漏点, 跨 case 续传 |
| 失败计数: 工具失败 +1, 成功 reset 0 | 与 L1 assert_node 行为一致 |
| JS 沙箱: 5 关键词 substring | 简单足够, AST/regex 过重 |
| _fallback_assertion 永远 inconclusive | 不假装 pass/fail, 留痕供调试 |
| _last_tool_calls 必须进 TestState | LangGraph 未声明字段静默 drop |
| [role='alert'] 加 :not 排除成功类 | Bootstrap 成功 flash 用 [role='alert'] |

---

## 11. 文件清单

| 文件 | 状态 | 行数变化 |
|------|------|----------|
| `agents/ui/execution_graph.py` | modified | +150 / -20 |
| `agents/ui/tools.py` | modified | +30 / -3 |
| `core/page_semantic.py` | modified | +30 / -6 |
| `core/runtime.py` | modified | +18 / 0 |
| `core/interfaces.py` | modified | +1 / 0 |
| `tests/core/test_l2_prompts.py` | **NEW** | +260 |
| `tests/agents/ui/test_execution_graph.py` | modified | +15 / -5 |
| `tests/agents/ui/test_tools.py` | modified | +15 / -2 |
| `tests/core/test_page_semantic.py` | modified | +28 / 0 |
| `scratch/test_l2_e2e.py` | **NEW** | +180 |
| `docs/handoff/2026-06-02-phaseA-v2-completion.md` | **NEW** | handoff |
| `docs/devlog/24-phaseA-v2-completion.md` | **NEW** | 本文件 |

**Total**: 12 files, +982 / -41

---

## 12. 下一阶段

V2.0 Phase B (L2 prompts V1.6 化, ~2.5d):
- B1: 5 个 L2 prompt 改写为 V1.6 5 段 XML
- B2: `_system_model` / `task_config` / `session_summary` 都通过 `<context>` 块注入
- B3: `<output_contract>` 显式约束 tool_call / mark reasoning / AssertionResult schema
- B4: 18 → ~35 个 V1.6.5 测试

完成后 Phase 1 全部完结, 进入 Phase 2 (多 agent 扩展)。
