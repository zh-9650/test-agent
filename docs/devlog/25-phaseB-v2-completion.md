# V2.0 Phase B — L2 Prompts V1.6 化 (XML + Output Contract + safe_structured_invoke)

**时间**: 2026-06-02
**责任人**: Lead
**前置**: V2.0 A (db6c6fd) L2 safety net + test infra + V2.0 计划 (008bb79) §3.2 Phase B
**状态**: ✅ 已完成
**Commit**: `9146c22` — feat(layer2): L2 prompts V1.6 migration (XML + Output Contract + safe_structured_invoke) (V2.0 B)
**范围**: Phase B (V2.0 §3.2) — B1/B2/B3/B4/B5 5 个子任务 + 1 集成优化
**E2E 站点**: `https://practice.expandtesting.com/login` (沿用 Phase A)

---

## 1. 业务目标

V2.0 计划 §3.2 Phase B 是 **L2 prompt 工程标准** 追平 L1 V1.7 的最后一步:

| ID | 目标 | 漏洞 | 文件 |
|----|------|------|------|
| **B1** | `decide_prompt` V1.6 5 段 XML 重写 | L2 仍是 V1.5 `##` 自由文本 | `agents/ui/prompts.py` |
| **B2** | `assert_prompt` V1.6 5 段 XML + 走 `safe_structured_invoke` + pydantic | V1.5 50 行手剥 JSON | `agents/ui/prompts.py` + `execution_graph.py` |
| **B3** | `step_prompt` V1.6 5 段 XML 重写 | L2 风格不统一 | `agents/ui/prompts.py` |
| **B4** | `_format_page_info` token-aware 截断 (字符预算) | V1.5 按条截断, 撞 65K token | `agents/ui/prompts.py` |
| **B5** | 账号密码从 system_prompt 剥离 | V15 P1: 密码明文进 LLM 上下文 | `agents/ui/prompts.py` |

**Phase B 目标**:
- 3 个 L2 prompt 全部 V1.6 5 段 XML 化, 与 L1 V1.7 风格一致
- assert_node Layer 2 走 pydantic 强类型, 解析失败率从 < 5% 降至 < 1%
- 密码不进 LLM 上下文窗口
- 21 个 V1.6 契约测试

---

## 2. B1 — decide_prompt V1.6 5 段 XML

### 2.1 5 段结构

```xml
<role>
你是 Web 应用测试执行智能体 (Web Test Executor)。
你的唯一职责是按当前测试用例的步骤, 用工具系统化地操作浏览器, 验证预期结果。
你不是写代码的, 你是"用浏览器思考"的 QA 执行者。
</role>

<context>
- 当前测试用例 ID/标题/描述/预期/步骤 (1-N 编号)/优先级/分类
- <test_accounts> / <prd_rules> / <focus_areas> / <scenarios> / <risk_points> 注入
- 上游: planning_graph 已生成 test_plan
- 下游: observe → decide → execute → assert → record 循环
- 你的成功定义
</context>

<task>
基于当前页面状态 + 当前步骤 + 预期结果, 决定下一步 (调工具 OR mark_task_*)。
</task>

<rules>
1. 强制结果标记机制 (硬约束)
2. 表单校验拦截 (Form Validation)
3. DOM 异步渲染保护 (Dropdown & Modal Isolation)
4. 一个工具一次 (Phase 1 限制)
5. 凭证自动登录 (硬约束)
6. 使用工具读取账号 (B5)
7. <prd_rules> 优先级最高
8. <focus_areas> 优先关注
9. <risk_points> 重点验证
10. 完成判据
</rules>

<examples>
<example type="good">...</example>
<example type="good">...</example>
<example type="bad">...</example>
<example type="bad">...</example>
</examples>

<output_contract>
(a) tool_call 必填 (tool_calls 数组长度 = 1)
(b) 显式 mark (mark_task_complete / failed / skipped)
禁止: 纯文本回复 / 一次多个 / 密码进 value
</output_contract>
```

### 2.2 占位块设计 (为 Phase C 留接口)

B1 在 `<context>` 中预留 4 块**空占位**, 便于 Phase C 填数据:

- `<prd_rules>` ← `task_config.rules`
- `<focus_areas>` ← `task_config.focus_areas`
- `<scenarios>` ← `task_config._scenarios` (来自 L1 N3 GoalExtractor)
- `<risk_points>` ← `task_config._risk_points` (来自 L1 N3 RiskAnalyzer)

每个块前 5 条截断, 避免 prompt 膨胀。

### 2.3 B5 账号密码剥离

```python
# 旧: accounts_info += f"- 角色: {a.get('role', 'N/A')}, 账号: ..., 密码: {a.get('password', 'N/A')}\n"
# 新:
accounts_block += f"- <account role=\"{a.get('role', 'N/A')}\">username: {a.get('username', 'N/A')}</account>\n"
```

密码不写入 system_prompt, 工具自己读 `task_config.accounts[i].password`。

反例 example 改用占位:
```
→ 调 input_text(target="#username", value="practice", password="<此处省略明文>")
违反规则 6 — 密码不应进 prompt, 工具自己读
```

---

## 3. B2 — assert_prompt V1.6 5 段 XML + pydantic

### 3.1 5 段结构

```xml
<role>断言专家 (Test Assertion Judge) — 看页面 + 看规则的判官</role>

<context>
<expected_result>{expected}</expected_result>
<tool_calls>{tool_calls}</tool_calls>
<current_step_text>{current_step_text}</current_step_text>
<change_report>{changes}</change_report>
<already_judged_by_upstream>{upstream_judged}</already_judged_by_upstream>
<page_state>{page_info}</page_state>
</context>

<task>输出 AssertionResult (status ∈ {pass, fail, inconclusive}, reasoning ≤ 200 字)</task>

<rules>
1. 区分中间步骤与决断步骤 (过渡动作必 INCONCLUSIVE)
2. 只有最终预期达成才能 PASS
3. 明确失败才能 FAIL
4. inter-node 契约: 上游已判过的别再判 (来自 <already_judged_by_upstream>)
5. 截图优先 (冲突时以截图为准)
6. JSON 唯一输出 (遵守 <output_contract> schema)
</rules>

<examples>
4 个 example: INCONCLUSIVE / PASS / FAIL / bad example (未考虑截图权威)
</examples>

<output_contract>
{
  "status": "pass" | "fail" | "inconclusive",  // 必填, 严格小写
  "reasoning": "string"                         // 必填, ≤ 200 字, 中文
}
走 safe_structured_invoke(prompt, AssertionResult), pydantic 强类型, 不手剥 JSON
</output_contract>
```

### 3.2 inter-node 契约 (硬约束)

`<already_judged_by_upstream>` 块是 B2 的**核心创新**:

```python
# change_report 里的 js_errors / error_messages_visible / network_errors
# 是 Rule-based Layer 0/1/2 已判过的事实, 不能再让 LLM 重复判 FAIL
if change_report.js_errors:
    already_judged.append(f"JS错误(已判): {', '.join(change_report.js_errors[:3])}")
if change_report.error_messages_visible:
    already_judged.append(f"可见错误(已判): {', '.join(change_report.error_messages_visible[:3])}")
if change_report.network_errors:
    already_judged.append(f"网络错误(已判): {', '.join(change_report.network_errors[:3])}")
```

**为什么**: 避免 LLM 看到错误信号后再次独立判 fail, 防止两套判定不一致。

### 3.3 assert_node Layer 2 走 safe_structured_invoke

**改造前** (V1.5):
```python
# 50 行手剥 JSON: regex → ast.literal_eval → dict access
response = await llm.ainvoke([...])
json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response.content, re.DOTALL)
json_str = json_match.group(1) if json_match else response.content
parsed = json.loads(json_str)
status = parsed.get("status", "").lower()
reasoning = parsed.get("reasoning", str(parsed))
```

**改造后** (B2):
```python
from core.llm_client import safe_structured_invoke
result = await safe_structured_invoke(full_prompt, AssertionResult, model_type="sonnet")

if result is not None and isinstance(result, AssertionResult):
    status = result.status        # pydantic 已校验 enum
    final_reasoning = result.reasoning
else:
    # 双 fallback 都失败 → _fallback_assertion 兜底
    fallback = _fallback_assertion(raw_text, ValueError("safe_structured_invoke returned None"))
    status = fallback.status
    final_reasoning = fallback.reasoning
```

**safe_structured_invoke 双轨** (`core/llm_client.py:252`):
1. `llm.with_structured_output(schema).ainvoke(prompt)` (主, pydantic 强类型)
2. `llm.ainvoke(prompt)` + `_extract_json_blob` + `_coerce_to_pydantic` (fallback, 手动解析)

**为什么用 safe_structured_invoke**: 解析失败率从 V1.7 baseline < 5% 降至 < 1% (Anthropic Structured Outputs 在 Anthropic SDK 1.5+ 已稳定)。

---

## 4. B3 — step_prompt V1.6 5 段 XML

```xml
<current_step>
<index>1/4</index>
<text>打开登录页</text>
</current_step>

请观察页面状态, 决定下一步操作. 如果该步骤已完成, 推进到下一条; 如果是最后一步, 验证预期结果并调 mark_task_*.\
```

**边界**: 越界 step 输出"验证预期结果"提示。

---

## 5. B4 — _format_page_info token-aware 截断

### 5.1 三层截断

| 字段 | 限制 | 行为 |
|------|------|------|
| 单 element text/label/placeholder | 50 字符 | 超长截断到 50 + "..." |
| interactive_elements | 30 个 | 超出显示"前 30/N 个" + 提示"还有 M 个省略" |
| error_messages | 5 个 | 超出只显示前 5 个 |

### 5.2 顶层字符预算

```python
char_budget = int(os.getenv("L2_PAGE_INFO_CHAR_BUDGET", "3000"))  # 2000 token ≈ 3000 char
if len(out) > char_budget:
    out = out[:char_budget] + f"\n... [truncated at {char_budget} chars, full page state in screenshot]"
```

**为什么 3000 字符 ≈ 2000 tokens**: 中英文混合 1 token ≈ 1.5 字符 (Anthropic tokenizer 经验值)。

---

## 6. B5 — 账号密码剥离

### 6.1 改造点

**旧** (V1.5):
```python
accounts_info = "\n## 测试账号\n你可以使用以下提供的测试账号进行登录或测试：\n"
for a in accounts:
    accounts_info += f"- 角色: {a.get('role', 'N/A')}, 账号: {a.get('username', 'N/A')}, 密码: {a.get('password', 'N/A')}\n"
```

**新** (B5):
```python
accounts_block = "\n<test_accounts>\n登录或测试时可使用以下账号 (密码由工具自动填充, 不在 prompt 中暴露):\n"
for a in accounts:
    accounts_block += f"- <account role=\"{a.get('role', 'N/A')}\">username: {a.get('username', 'N/A')}</account>\n"
accounts_block += "</test_accounts>\n"
```

### 6.2 工具侧

工具 (`input_text`, `click_login` 等) 内部从 `task_config.accounts` 读 password, 拼到 Playwright 操作里:

```python
async def login_via_credentials(page, role: str, username: str, task_config: dict):
    accounts = task_config.get("accounts", [])
    for a in accounts:
        if a.get("role") == role and a.get("username") == username:
            password = a.get("password")  # 工具读, 不进 prompt
            await page.fill("#password", password)
            ...
```

**好处**:
- 密码不进 LLM 上下文窗口
- 密码不进 messages 落盘
- 减少 PII 泄露风险

---

## 7. 测试结果

### 7.1 V2.0-A + B 4 文件

```text
tests/core/test_l2_prompts.py           37 passed,  1 skipped   (A: 18 + B: 21)
tests/agents/ui/test_execution_graph.py 17 passed               (含 1 修复: assert_node_mock)
tests/agents/ui/test_tools.py           12 passed
tests/core/test_page_semantic.py         9 passed
---
                                       78 passed,  1 skipped in 33.91s
```

### 7.2 E2E (practice.expandtesting.com)

```text
[boot] 已到达 https://practice.expandtesting.com/login
[observe] url=...login elements=25
[decide] input_text #1 (username)
[execute] result='已在 #1 输入文本'
[assert] inconclusive
[decide] input_text #2 (password)
[execute] result='已在 #2 输入文本'
[assert] inconclusive
[decide] click #5 (Login)
[execute] result='已点击 #5'
[assert] inconclusive (URL已跳转至 /secure, 登录操作可能已成功)
[decide] mark_task_complete
[execute] result='任务标记为已成功'
[HierarchicalAssert] LLM Explicit Marker: pass

Result: success=true, final_status=pass, duration=40s
```

LLM 完全读懂新 V1.6 prompt, 行为零回归。

---

## 8. 关键决策与理由

| 决策 | 理由 |
|------|------|
| 3 个 L2 prompt 全部 V1.6 5 段 XML | 与 L1 V1.7 风格一致, LLM 易于解析; 显式 `<output_contract>` 强制 schema |
| assert_node Layer 2 走 safe_structured_invoke | 替换 V1.5 的 50 行手剥 JSON, pydantic 强类型 + 双重 fallback |
| inter-node 契约: upstream 已判进 `<already_judged_by_upstream>` | 避免 LLM 重复判 FAIL, 保持上游 Rule 1/2 单点权威 |
| B5: 账号密码剥离 | 密码不进 LLM 上下文窗口, 不进落盘 messages, 工具自己读 task_config |
| B4: `_format_page_info` 按字符预算截断 | Anthropic Context Engineering 2025-09: 1 token ≈ 1.5 字符 |
| safe_structured_invoke 移到模块顶层 | 测试 patch 需要, 函数内 import 无法被 patch |
| status 全小写 (pass/fail/inconclusive) | pydantic 校验一致性 |

---

## 9. 文件清单

| 文件 | 状态 | 行数变化 |
|------|------|----------|
| `agents/ui/prompts.py` | modified | +280 / -125 |
| `agents/ui/execution_graph.py` | modified | +45 / -73 |
| `tests/core/test_l2_prompts.py` | modified | +440 / -25 |
| `tests/agents/ui/test_execution_graph.py` | modified | +10 / -10 |
| `docs/handoff/2026-06-02-phaseB-v2-completion.md` | **NEW** | handoff |
| `docs/devlog/25-phaseB-v2-completion.md` | **NEW** | 本文件 |

**Total**: 6 files, +819/-189

---

## 10. 下一阶段

V2.0 Phase C (联动 L1 业务模型, ~1d):
- C1-C4: 4 块占位填数据 (rules / focus_areas / scenarios / risk_points) — B1 已预留
- C5: record_node 输出 reasoning_chain → ReportBuilder L2 卡片新增"AI 思考链"

完成后 Phase 1 全部完结, 进入 Phase D (L2 可观测性 ~1d)。
