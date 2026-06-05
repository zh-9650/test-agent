# 2026-06-05 需要改的东西 — 诚实清单

> 不按 GPT 的 Sprint 0-5 划分
> 不按"人天"估算（GPT 的估算全错：视口过滤、tabs、Sprint 5 fingerprint 校验都已实现）
> 按"现状 → 缺口 → 怎么改"列

---

## 总览：代码实际走了多远

| 模块 | 行数 | 状态 | 真实缺口 |
|------|------|------|---------|
| `core/page_semantic.py` | 872 | 大部分已实现 | pending_requests 缺、视口过滤有 bug |
| `core/interfaces.py` | 494 | 已实现 | — |
| `agents/ui/tools.py` | 1419 | 已实现 18 个工具 | 密码自动注入逻辑复杂、evaluate_js 黑名单过宽 |
| `agents/ui/execution_graph.py` | 1246 | 已实现 5 节点 | 四件套缺、Goal Reminder 已注入 |
| `agents/ui/prompts.py` | 717 | 5 段 XML 已实现 | 4 件套缺、Few-shot 不全 |

---

## 1. 真实存在的 Bug（必修，10-30 分钟活）

### Bug 1.1: 视口过滤只对 input 生效（10 分钟）

**位置**: `core/page_semantic.py:103-129`（视口过滤逻辑）

**问题**: opus 说"只有 input 有 coords，所以视口过滤对其他元素失效"——**这条结论是错的**。
我看 `L482, L506, L524, L544, L573`（5 个 `_extract_*` 函数）都调了 `_get_bbox`，
所以 button/link/select/checkbox/radio **都有 coords**。

但我**同意 opus 的判断**："视口过滤失效"是表象问题。**真正的问题**是：

- `_get_bbox` 在元素被 `display:none` 或 `visibility:hidden` 时可能返回 None
- `_is_in_viewport`（视口过滤内联逻辑）没处理 `coords` 为 None 的情况
- L115 `if not coords: interactive_elements.append(el)` → 静默放行

**修法**: 显式记一个 `_off_viewport_filter_skipped` 字段，让 LLM 知道"列出的不全"。

**工时**: 10 分钟
**风险**: 极低（只加字段，不改逻辑）

### Bug 1.2: AAA/ABAB 检测只看 action name，不看指纹（30 分钟）

**位置**: `execution_graph.py:388-397`

**问题**:
```python
if names3[-1] == names3[-2] == names3[-3] and names3[-1] in write_actions:
    need_replan = True
    page_info["_loop_detected"] = f"AAA (连续 3 次相同写动作: {names3[-1]})"
```

`action_history` 里有 `fingerprint` 字段（L1104），但 AAA/ABAB 检测**完全没用**。
如果 LLM 连续 3 次 click 不同元素（恰好都是 click）→ 误报死循环。

**修法**（opus 的方案对）：
```python
fps3 = set(a.get("fingerprint", "") for a in action_history[-3:])
if names3条件 and len(fps3) == 1:  # 指纹确实没变才算
    need_replan = True
```

**工时**: 30 分钟
**风险**: 极低

### Bug 1.3: CDP click 路径里 `el_info` 可能为 None（15 分钟）

**位置**: `tools.py:620-636`（click 工具的 CDP 分支）

```python
if cdp_sess:
    try:
        el_info = _get_element_info(target)  # 可能返回 None
        coords = el_info.get("coords", {}) if el_info else {}
        if coords and coords.get("x") is not None and coords.get("y") is not None:
            cx = coords["x"] + coords.get("width", 0) / 2
            cy = coords["y"] + coords.get("height", 0) / 2
            clicked = await cdp_click(page, cdp_sess, cx, cy)
            ...
    except Exception as click_err:
        ...
```

问题：`_get_element_info` 返回 None 时，外层 `if cdp_sess:` 已 True，直接进 `try` 没问题，但 `el_info.get(...)` 已经处理。**这里其实没问题**。

但是 L620 的逻辑有个真 bug：**如果 el_info 存在但 coords 缺失**，会**静默回退到 Playwright locator click**，但不会记录"为什么走 fallback"。`print()` 也没记。

**实际状态**: 这是可观测性问题，不是 bug。
**工时**: 5 分钟（加一行日志）/**不做也行**

### Bug 1.4: `_wait_for_stable` 在 `wait` 工具里有怪逻辑

**位置**: `tools.py:873`

```python
await _wait_for_stable(page) if seconds < 3 else None
```

`wait` 是用户**主动**要等这么久的工具，再调一次 `_wait_for_stable` 是双重等待。如果 LLM 调 `wait(5.0)`，实际会等 5s + 0.5s+ fingerprint 轮询 = 5.5s+。

**修法**: 删掉这个 `_wait_for_stable` 调用（或只在 seconds >= 1 时跳过）
**工时**: 1 分钟
**风险**: 极低

### Bug 1.5: `evaluate_js` 黑名单太宽（15 分钟）

**位置**: `tools.py:1233`

```python
blacklist = ("page.goto", "page.evaluate", "window.location", "location.href", "fetch(")
```

`fetch(` 在很多合法场景下被禁。比如 LLM 想"检查页面 fetch 结果" → 被拒。
但 LLM 想"模拟点击"是合理诉求，黑名单应该更精准。

**修法**: 改用正则匹配函数调用（带 `(` 的），避免误杀变量名里有 location 的。

**工时**: 15 分钟
**风险**: 低

### Bug 1.6: `mark_task_complete` 二次确认代码重复

**位置**: `execution_graph.py:808-843` + `_fast_assert:201-216`

两处都有"mark_task_complete 二次确认"逻辑，**完全重复**。一处改了另一处忘改会出 bug。

**修法**: 抽出 `_secondary_confirm_complete()` 函数
**工时**: 15 分钟
**风险**: 极低

---

## 2. 真正缺的功能（要花点时间，1-4 小时活）

### 缺 2.1: pending_requests 感知（1 小时）

**位置**: `core/page_semantic.py`（应加在 tabs 旁边 L86-100）

**现状**: 没实现。LLM 不知道"页面还在加载"

**修法**: 调研报告 `docs/research/2026-06-05-llm-input-comparison.md` §7 给了骨架
**工时**: 1 小时
**风险**: 低（CDP 已就绪）

### 缺 2.2: 截图按需策略的 quota 检查有 off-by-one（10 分钟）

**位置**: `tools.py:894-899`

```python
budget = int(os.getenv("L2_SCREENSHOT_BUDGET", "2"))
used = _screenshot_budget.get(task_id, 0)
if used >= budget:  # 这里 >= 的话, 第 2 次就拒了
    return False
```

如果 `L2_SCREENSHOT_BUDGET=2`，第 1 次 `used=0, 0>=2 False, used→1`，第 2 次 `used=1, 1>=2 False, used→2`，第 3 次 `used=2, 2>=2 True, 拒`。
**实际允许 2 次（正确）**。这个其实没问题。

但是 `_consume_screenshot_quota` 默认返回 True 当 `task_id is None`（L893），这会导致没有 task_id 时无限制截图——是 feature 不是 bug。

**结论**: 没问题，**跳过**。

### 缺 2.3: input_text 密码自动注入逻辑太复杂（1.5 小时重构）

**位置**: `tools.py:711-791`

问题：
1. 80 行内 4 层 try/except
2. 3 次扫描 `page.query_selector_all("input")`（L740, L773）
3. 匹配 username 用了 4 个 if/elif 嵌套（L749-760）
4. `accounts[0]` 兜底（L787）可能在错误账号上注入

**重构方向**: 抽 `_resolve_account_for_username(page, username_val, accounts)` 函数
**工时**: 1.5 小时
**风险**: 中（密码注入错了 LLM 会拿错账号登录）

**建议**: 先跑测试看哪些场景触发这个，再决定要不要动。

### 缺 2.4: 四件套（evaluation/memory/next_goal/action）（3-4 小时）

**位置**: `prompts.py:170-180`（output_contract）+ `execution_graph.py:481-622`（decide_node）

**现状**:
- Goal Reminder 已注入 ✅（L541-552）
- 输出 schema 强 tool_call，没有 evaluation/memory/next_goal ❌
- LLM 上下文 5+ 步后开始丢"我刚才为啥点这个" ❌

**方案选择**:

**方案 A（轻量）**: Prompt 改 1 段 + parse content 字段提取
- 改 `output_contract` 要求 LLM 在 content 里写 `evaluation: ... / memory: ... / next_goal: ...` 然后调 tool_call
- decide_node 解析 content 存到 state
- observe_node 注入到 prompt 顶部
- 风险：LLM 可能不遵守（用 content 写很长废话），但 kimi-k2.6 兼容端点支持 thinking 字段
- 工时：3-4 小时

**方案 B（重）**: 改 `bind_tools` → `with_structured_output`
- 改 LangChain 调用方式
- 影响 11 个工具的 schema
- 工时：6+ 小时，**不建议做**

**建议**: 先做方案 A 的"小实验"——只改 prompt，1 小时内看到 LLM 输出格式变化，**再决定要不要做 state 持久化**。

### 缺 2.5: Few-shot 例子太窄（2 小时）

**位置**: `prompts.py:124-167`

**现状**: 4 good + 3 bad。覆盖：input/click/login/search。
**缺的**：
- scroll 后 observe 看到的元素编号变化
- 弹窗出现时的处理
- 标记成功但页面没变化
- 连续失败触发 replan
- input_text 密码自动注入（用户名填好后密码自动填）
- 提取数据后 mark_complete
- 视口外元素（先 scroll 再操作）

**工时**: 2 小时（每条 15-20 分钟）
**风险**: 低

---

## 3. 可观测性（信息不足，跑测试前先补）

### 缺 3.1: 失败原因分类埋点

**位置**: 各处

**现状**: 日志只有 `_locator_stats` 字段（interfaces.py:290），没人读它。
**需要的**：每个工具失败时记一个 `failure_reason` 字段（"not_found" / "timeout" / "click intercepted" / "wrong target"）

**修法**: 在 `_make_action_result` 加 failure_reason 推断逻辑（已经部分有：status 字段推断）
**工时**: 1 小时
**风险**: 低

### 缺 3.2: `print()` 残留（多处）

**位置**:
- `tools.py:321, 339, 345, 362, 403, 413, 419, 425` (CDP resolve 路径)
- `tools.py:638` (CDP click fallback)
- `page_semantic.py:180, 221`

**问题**: 生产环境 print 到 stdout，跟日志系统不通。debug 友好但运行污染。

**修法**: 换成 `logging.debug(...)` 或 `loguru.debug(...)`
**工时**: 20 分钟
**风险**: 极低

---

## 4. Sprint 0 提到的"输入数据补齐"实际差什么

调研报告列的 P0 字段 vs 实际：

| 字段 | 实际状态 | 缺口 |
|------|---------|------|
| value (input) | ✅ L459 | 无 |
| href (link) | ✅ L509 | 无 |
| checked (checkbox/radio) | ✅ L549, L583 | 无 |
| role | ✅ _get_element_role | 无 |
| tabs | ✅ L86-100 | **只在 len>1 时写, 单 tab 时字段缺失**（改成总是写）|
| viewport | ✅ L72-84 | 无 |
| pending_requests | ❌ | **真缺** |
| bounds (coords) | ✅ 6 个 _extract 都有 | 无 |
| off_viewport_count | ❌ | **缺提示**（让 LLM 知道不全）|

**结论**: 8 个 P0 字段里 6 个已实现，**2 个真缺**（pending_requests、off_viewport_count 提示）。

---

## 5. Sprint 1 提到的"四件套"实际差什么

| 字段 | 实际状态 |
|------|---------|
| Goal Reminder | ✅ L541-552 |
| Memory (跨步) | ⚠️ 只有 session_summary 跨 case 传递，case 内没有 |
| Evaluation | ❌ |
| Next Goal | ❌（与 Goal Reminder 不同，这是 step 内的）|
| Action | ✅ tool_call |

**结论**: 4 件套**只缺 2 个**（evaluation、next_goal）。Memory 有 session_summary 部分覆盖。

---

## 6. 优先级排序

按"修复成本 / 收益"比排：

| # | 改动 | 工时 | 收益 | 风险 |
|---|------|------|------|------|
| 1 | Bug 1.4 wait 工具双重等待 | 1 分钟 | 中 | 极低 |
| 2 | Bug 1.1 视口过滤提示 | 10 分钟 | 中 | 极低 |
| 3 | Bug 1.2 AAA/ABAB 补 fingerprint | 30 分钟 | 中 | 极低 |
| 4 | Bug 1.6 mark_task_complete 二次确认去重 | 15 分钟 | 低 | 极低 |
| 5 | 缺 2.1 pending_requests | 1 小时 | 中 | 低 |
| 6 | tabs 字段总是写（不只多 tab 时） | 5 分钟 | 低 | 极低 |
| 7 | 缺 3.2 print→logging | 20 分钟 | 低 | 极低 |
| 8 | Bug 1.5 evaluate_js 黑名单 | 15 分钟 | 低 | 低 |
| 9 | 缺 2.5 Few-shot 补全 | 2 小时 | 高 | 低 |
| 10 | 缺 2.4 四件套轻量路 | 3-4 小时 | 高 | 中 |
| 11 | 缺 2.3 input_text 密码注入重构 | 1.5 小时 | 低 | 中 |

**推荐顺序**: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9（**8 项，约 4.5 小时**），跑一轮基准看效果。
第 10 项（**四件套**）等数据说话再决定。

---

## 7. 不动的东西

- 视口过滤主逻辑（用 box_x/box_y，**逻辑是对的**）
- AAA/ABAB 检测的"动作名匹配"（补 fingerprint 校验即可，不重写）
- ActionResult 模型（已经达标，model_dump 直接用）
- DOM 指纹算法（已经达标）
- 5 段 XML prompt 结构（V1.6 标准不动）
- bind_tools 机制（**不要改成 with_structured_output**）
- CDP 主路径（**不要回退到只用 Playwright**）
- LangGraph StateGraph 拓扑（5 节点不变）

---

## 8. 测试验证

每改完 1 项，跑：
1. 单元测试：`pytest tests/ -x`（必须全过）
2. 5 个 case 烟测：WV-005/006/007/008/009（手头有基线）
3. 跑前后对比，记到 `docs/benchmark/2026-06-05-2.0A-fixes.md`

8 项全做完后跑 1 轮 10 题看总成功率趋势。

---

## 引用

- 调研报告：`docs/research/2026-06-05-llm-input-comparison.md`
- 交接文档：`docs/handoff/2026-06-05-audit-fixes-and-benchmark.md`
- opus 审计：用户提供的 opus 反馈
