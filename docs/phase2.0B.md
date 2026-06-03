# Phase 2.0B — Execution Loop 韧性增强

## 背景

Phase 2.0A 完成了 L2 执行循环的 6 项升级（Goal Reminder、ActionResult、Wait-for-Stable、DOM 语义增强、Failure Memory、Loop Detection）。真实运行后（Task 8）暴露了 4 个设计缺陷：

1. **密码注入无意图校验** — 误把用户名输入框当密码框注入，导致后续 6 步全部脱轨
2. **mark_task_complete 零信任** — LLM 编造"教师主界面已跳转"但实际仍在登录页，assert 无条件 pass
3. **无动作前后值对比** — input_text 不返回实际填入值，assert 只看"页面有变化"看不穿"填错值"
4. **脱轨无纠正机制** — 连续失败后 LLM 从不回头检查前置条件

同时，来自两层架构分析（2026-06-03）的 3 个技术债：

5. **assert 节点每步强串行 LLM 调用**（改造成本最大）
6. **record/observe 职责错位**（context 压缩应在 observe、Loop Detection 应在 observe）
7. **SystemMessage 每步重建**（改造成本最低）

原计划的 **CDP 迁移**（backendNodeId + CDP click/input + AXTree-led）推迟到 Phase 2.0C，原因：
- 当前瓶颈不是 locator 稳定性，而是执行逻辑韧性
- 需先在 Playwright 层跑出 100 条 case 的 locator 失败率数据

---

## Sprint 计划

### Sprint B1: Step 语义写入与校验（修复缺陷 A/B/C）

**目标**: input_text 注入前校验 LLM 意图；mark_task_complete 后二次确认；工具返回实际值。

#### B1.1 — 密码注入意图校验
- 文件: `agents/ui/tools.py` — `input_text()`
- 当前: 检测到 `type=password` 就静默注入密码
- 修复: 注入前校验 `current_step_text`（来自 `task_config["_current_step_text"]`），确认语义确实是"输入密码"；如果不匹配则 warn 日志 + 不注入
- 新增: `agents/ui/tools.py` — 新增 `_should_auto_inject_password(task_config, step_text) -> bool`
- 接入: `execute_node` 先将 `current_step_text` 注册到 task_context，供 tool 读取

#### B1.2 — mark_task_complete 二次确认
- 文件: `agents/ui/execution_graph.py` — `assert_node()`
- 当前: Layer 0.5 碰到 `mark_task_complete` 直接返回 pass
- 修复: `mark_task_complete` / `mark_task_failed` / `mark_task_skipped` 后，拍摄新截图 + 比对 URL 和交互元素是否有实质变化；无变化时降级为 `inconclusive`，并追加 reasoning 说明"无实质页面变化"
- 触发条件: marking 工具后 state_after 的 URL 和 page_info 与 state_before 一致 → 降级

#### B1.3 — 工具返回实际填入值
- 文件: `core/interfaces.py` — `ActionResult` 增加 `filled_value: str = ""`
- 文件: `agents/ui/tools.py` — `input_text()` 返回时设置 `filled_value`（实际填入的 value，密码注入后也是实际密码值，非明文截断为前 2 位 + **** 脱敏）
- 文件: `agents/ui/execution_graph.py` — `assert_node` Layer 2 将 `ActionResult.filled_value` 注入断言 prompt，让 LLM 判断填入内容是否符合 step 语义

#### B1.4 — Step Context 注册贯通
- 文件: `agents/ui/execution_graph.py` — `execute_node`
- 当前: `execute_node` 已将 `task_config` 注册到 `set_task_config()`
- 修复: 增加 `current_test_case.steps[current_step_index]` 注册到 task_context，供 tool 读取当前步骤描述
- 文件: `agents/ui/tools.py` — 新增 `get_current_step_text() -> str`

#### B1.5 — 测试用例间状态隔离（修复 Task 8 发现的新问题）

**背景**: Task 8 真实运行暴露：TC-001 和 TC-002 虽然都访问同一登录页，但元素索引差异巨大（#208 vs #608），说明上一个 case 的页面状态残留影响了下一个 case。`clear_cookies()` + `navigate` 现有重置机制不够健壮。

**修复**:
- 文件: `core/runtime.py` — `_execute_test_case()` / `_execute_test_case_stream()`
- 增强浏览器状态重置逻辑：
  1. 清除 cookies + localStorage + sessionStorage 后，等待页面完全卸载
  2. 重新导航到 target_url，等待 `networkidle` + `_wait_for_stable`
  3. 验证当前 URL = target_url，否则重试一次
  4. 在 `_execute_test_case_stream` 中 yield `state_reset` 事件供前端显示
- 文件: `agents/ui/execution_graph.py` — `observe_node` 顶部注入"测试用例状态重置"日志

---

### Sprint B2: 脱轨纠正 + 职责重分配（修复缺陷 D + 架构问题 6+7）

**目标**: LLM 脱轨后能自我纠正；record 只做 StepResult 打包；context 压缩提前。

#### B2.1 — 脱轨纠正（阶段护栏）
- 文件: `agents/ui/execution_graph.py` — `observe_node`
- 规则: 连续 2 步页面无实质变化（no URL change, no new/gone elements, no modal）且 action 没工具报错 → 强制设置 `need_replan = True`
- 与 Sprint 6 Loop Detection 的区别: Loop Detection 只检测 AAA/ABAB 死循环；脱轨纠正检测"页面停滞不前"（即使是不同 action）
- `_format_page_info` 在脱轨触发时追加 `[CORRECTIVE] 页面已连续 N 步无变化，建议回到上一步检查前置条件是否满足`

#### B2.2 — SystemMessage 不重建
- 文件: `agents/ui/execution_graph.py` — `decide_node`
- 当前: `messages.insert(0, SystemMessage(content=system_prompt))` 每步插入新 SystemMessage
- 修复: 如果 `messages[0]` 已是 SystemMessage 则替换内容，否则 insert
```python
if messages and isinstance(messages[0], SystemMessage):
    messages[0] = SystemMessage(content=system_prompt)
else:
    messages.insert(0, SystemMessage(content=system_prompt))
```

#### B2.3 — Context 压缩移至 observe
- 文件: `agents/ui/execution_graph.py`
- record_node: 移除 context 压缩逻辑
- observe_node: 在开头加入 context 压缩（decide 之前执行，确保压缩后的消息被 LLM 看到）
- 保留 record_node 的 `_step_token_log` 累积（仅统计，不压缩）

#### B2.4 — Loop Detection 移至 observe
- 文件: `agents/ui/execution_graph.py`
- record_node: 移除 AAA/ABAB 检测逻辑（保留 `action_history` 追加）
- observe_node: 在 context 压缩后执行 AAA/ABAB + 脱轨检测，设置 `need_replan`

---

### Sprint B3: assert 条件边 + CDP 数据采集（修复架构问题 5 + 准备 2.0C 决策依据）

**目标**: 只有最终步骤 + 复杂情况才走 LLM assert；采集 100 条 case 的 locator 失败率。

#### B3.1 — assert 条件边

**设计**:
```
execute → should_assert_llm? → {assert_node, record}
                                  ↓ LLM path     ↓ skip assert
```

- 新增函数 `_fast_assert(state) -> dict | None`: 封装当前 assert_node Layer 0 的快判逻辑（marker tasks、action error、page_changed 中间步骤）
- 新增条件边 `should_assert_llm(state) -> str`:
  - `_fast_assert` 有结果 → `"record"`（跳过 assert_node，但结果由 record_node 兜底写入 state）
  - 最终步骤 → `"assert_node"`
  - 其余 → `"assert_node"`（复杂判断）
- record_node 的 skip-assert 路径: `_last_assertion` 为 None 时调用 `_fast_assert` 兜底；兜底不到则生成默认 `inconclusive`
- assert_node 顶部复用 `_fast_assert` 作为 Layer 0（双重安全，可能状态已变）

#### B3.2 — Locator 失败率统计
- 文件: `agents/ui/tools.py` — `_resolve_element` 每次失败时计数
- 文件: `core/interfaces.py` — `TestState` 增加 `_locator_stats: dict = {"total": 0, "failed": 0}`
- 文件: `agents/ui/execution_graph.py` — `execute_node` 每次 locator 解析失败（catch ValueError）累加计数器
- 采集满 100 条 case 后自动计算失败率，存入 `task_config["_locator_failure_rate"]`
- 若 > 30% → 触发 Phase 2.0C CDP 迁移决策

#### B3.3 — Phase 2.0C 前置条件
- 未来 Phase 2.0C 入口检查: `task_config["_locator_failure_rate"] > 0.3`
- 若满足，自动将目标系统标记为"高 locator 失效系统"，后续任务走 CDP 执行路径
- 文档产出: `docs/phase2.0C.md`（CDP 适配器设计、AXTree 替换、混合模式策略）

---

## 路线图

```
Phase 2.0B (本阶段)
├── Sprint B1: Step语义 + 意图校验 + 二次确认     ← 修复核心缺陷
├── Sprint B2: 脱轨纠正 + 职责重分配              ← 解决架构问题
└── Sprint B3: assert条件边 + 数据采集             ← 性能优化 + 决策依据

Phase 2.0C (未来, 条件触发)
└── CDP 迁移: backendNodeId + CDP click/input + AXTree-led
    └── 触发条件: 100 case 后 locator 失败率 > 30%
```

## 安全边界

- **B1.1 密码注入意图校验**: 不校验时不注入（宁可漏填也不误填），漏填后由 LLM 在第 2 步尝试填密码时自然补全
- **B1.2 二次确认**: 降级为 inconclusive 而非 fail，保留人工判定空间
- **B2.1 脱轨纠正**: 先 warn 再强制 replan，不直接 fail
- **B3.1 条件边**: 兜底走 inconclusive 而非 hard fail，保持执行流不中断

## 实验性/待验证设计

### assert 条件边的 Overhead 量化

**当前瓶颈假设**: 即使 assert_node 内部有大比例快判路径，LangGraph 调度 + 函数调用 + state 序列化的开销依然存在。

**待验证数据**: 加条件边前后对比 3 项指标：
1. 每步总耗时（µs，`_last_node_duration_ms`）
2. 每步总 token 消耗（`_last_token_count`）
3. 断言准确率（pass/fail 比例 vs 人工判定）

**预期收益**: 
- 中间步骤跳过 assert_node → 每步节省 ~2-5ms LangGraph 调度开销
- 但收益以 µs 计，相对于 LLM decide 调用的秒级耗时占比 < 0.5%

**决策规则**（Sprint B3 实现后跑 50 case 验证）:
- 若 `avg_step_duration 下降 > 10ms` → 条件边永久启用
- 若 `assertion 准确率下降 > 5%` → 回滚到无条件边，只保留 `_fast_assert` 作为 assert_node 内部优化
- 若数据不明显 → 条件边保留但标记为 low-priority，后续重构再评估

### Step Context 注册 vs. RAG Memory

**当前重复**: `decide_node` 中已经做了 `retrieve_memories(target_url, query_text)`，而 B1.4 新增的 `get_current_step_text()` 是另一个途径。

**待验证**: 两种方式在密码注入意图校验中的准确率对比：
- A: `get_current_step_text()` 直接读取 step 文本（字符串匹配）
- B: `retrieve_memories()` 检索历史相似的步骤作为参考

**预期**: A 更快更准（精确匹配），B 耗时且模糊。先在 B1.1 中只用 A，后续若发现准确率不足再叠加 B。

## 附录: 已知数据与决策

### Task 8 TC-002 失败链回顾

```
Step 1: input_text(target="#610", value="test_password")  # LLM 意图: 填用户名
        → 工具检测到 type=password, 静默注入密码
        → assert: "页面已变化" (pass)
Step 2-6: 连续点击各种按钮, 全部 disabled
Step 7: evaluate_js 强行移除 disabled + 点击
Step 8: mark_task_complete("已跳转到教师主界面...")
        → assert 零信任 pass
```

### 根因分类

| # | 根因 | 致命度 | Sprint |
|---|------|--------|--------|
| A | 密码注入无意图校验 | 🔴 致命 | B1.1 |
| B | mark_task_complete 零信任 | 🔴 致命 | B1.2 |
| C | 工具不返回实际值 | 🟡 严重 | B1.3 |
| D | 脱轨后无纠正 | 🟡 严重 | B2.1 |
| 5 | assert 每步串行 | 🟢 轻微 | B3.1 |
| 6 | 职责错位 | 🟢 轻微 | B2.3/B2.4 |
| 7 | SystemMessage 重建 | 🟢 轻微 | B2.2 |
