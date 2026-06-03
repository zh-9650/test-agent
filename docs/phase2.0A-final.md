# Phase 2.0A 最终版

> 范围收敛版。不做全量 CDP 迁移，只解决"Agent 能想到但做不到"的问题。

## 一句话目标

```
提升执行成功率
不要碰规划层
不要大重构
```

## 不做（推迟到 Phase 2.0B / 2.1）

- ❌ 全量 CDP 迁移（感知增强只加 AXTree，执行层保持 Playwright）
- ❌ EventBus / Watchdog
- ❌ Assertion Engine 重构
- ❌ 多 Agent 协作
- ❌ Scenario 重规划

## CDP 策略

```
Phase 2.0A:
  Observe = Playwright + CDP AXTree（感知增强）
  Execute = Playwright（保持不动）

Phase 2.0B（如果数据证明 locator 失败 > 30%）:
  full CDP: backendNodeId 锚点 + CDP 点击/输入 + AXTree 主导感知
```

---

## Sprint 1: Goal Reminder (P0) — 0.5天

**最高 ROI。** 每步 Decide 强制注入，杜绝目标漂移。

**改动范围**：`agents/ui/execution_graph.py` — `decide_node()`

```python
goal_reminder = f"""════════════════════════════════════════════════════
🧭 CURRENT TEST GOAL
   用例ID: {test_case.id}
   标题: {test_case.title}
   描述: {test_case.description}
   当前步骤: {current_step}/{total_steps}
✅ SUCCESS CRITERIA: {test_case.expected}
════════════════════════════════════════════════════"""

# 拼到 HumanMessage 顶部
human_content = f"{goal_reminder}\n\n{step_prompt}\n\n当前页面状态:\n{page_summary}"
```

---

## Sprint 2: ActionResult 标准化 (P0) — 1天

**收益**：Execute 不再是黑盒，Assert 直接读结构化证据。

**改动范围**：
- `core/interfaces.py` — 新增 `ActionResult` 模型
- `agents/ui/tools.py` — 所有工具统一返回 `ActionResult`
- `agents/ui/execution_graph.py` — `assert_node` 复用 `ActionResult.page_changed`

```python
class ActionResult(BaseModel):
    action: str          # "click" | "input_text" | "navigate"
    target: str | int    # "#id" | index
    success: bool
    error: str | None
    before_url: str
    after_url: str
    page_changed: bool   # DOM 指纹比对
    url_changed: bool
```

---

## Sprint 3: Wait-for-Stable 下沉 (P0) — 1天

**不新增 LangGraph 节点。** 直接在工具函数内部做。

**改动范围**：`agents/ui/tools.py`

```python
async def wait_for_stable(page, timeout=5000):
    try:
        await page.wait_for_load_state("networkidle", timeout=2000)
    except:
        pass  # 企业系统 WebSocket/SSE 永不 idle
    for _ in range(timeout // 250):
        before = _fingerprint(page)
        await asyncio.sleep(0.25)
        after = _fingerprint(page)
        if before == after:
            await asyncio.sleep(0.5)
            return
```

---

## Sprint 4: DOM 语义增强 (P0) — 1天

**改动范围**：`core/page_semantic.py` + `agents/ui/prompts.py`

在 `page_semantic.py` 提取的元素信息中增加：

| 字段 | 来源 | 用途 |
|---|---|---|
| `visible` | CDP computed style / Playwright `is_visible()` | 过滤不可见元素 |
| `enabled` | `is_enabled()` / `disabled` 属性 | 避免点击禁用按钮 |
| `readonly` | `readonly` 属性 | 避免向只读输入框填值 |
| `required` | `required` 属性 | 提示必填 |
| `checked` | `checked` / `aria-checked` | checkbox/radio 状态 |
| `role` | `role` 属性 / tag 推断 | 语义角色 |

**Prompt 格式**改为紧凑索引样式：
```
[0] button "登录" (enabled=true)
[1] checkbox "同意协议" (checked=false)
[2] input "用户名" (visible=true, required=true)
```

---

## Sprint 5: Failure Memory (P1) — 0.5天

**改动范围**：`core/interfaces.py` + `execution_graph.py`

```python
# TestState 新增
recent_failures: deque[dict]  # maxlen=3
```

**规则**：
- 工具失败时 `append({action, target, error})`
- **不自动清空**（deque 自动淘汰旧条目）
- observe 时注入最近 2 条失败到 Prompt 顶部

---

## Sprint 6: Loop Detection (P1) — 0.5天

**改动范围**：`execution_graph.py` — `record_node`

**检测条件**（同时满足）：
- AAA：相同动作一级分类连续 3 次
- ABAB：动作一级分类交替重复 4 次
- **+** 页面指纹从未改变
- **+** URL 从未改变

**触发**：`Micro-Replan` — 注入 `[SYSTEM INTERRUPT]`，当前步骤调整策略，不清除已完成步骤。

---

## 工期汇总

| Sprint | 内容 | 工期 | 优先级 |
|---|---|---|---|
| 1 | Goal Reminder | 0.5天 | P0 |
| 2 | ActionResult 标准化 | 1天 | P0 |
| 3 | Wait-for-Stable 下沉 | 1天 | P0 |
| 4 | DOM 语义增强 | 1天 | P0 |
| 5 | Failure Memory | 0.5天 | P1 |
| 6 | Loop Detection | 0.5天 | P1 |
| **合计** | | **3.5~4.5天** | |

## 路线图

```
Phase1（已完成）
  Knowledge Extraction → SystemModel → SystemMap → Scenario → Plan
  ==============================================

Phase2.0A ← 现在做
  Goal Reminder → ActionResult → Wait-for-Stable → DOM增强 → Failure Memory → Loop Detection
  ==============================================

Phase2.0B ← 视数据决定
  CDP迁移: backendNodeId + CDP点击/输入 + AXTree主导
  ==============================================

Phase2.1
  Assertion Evidence Layer: DOM + AXTree + Tool + Business + Network
  ==============================================

Phase3.0
  真正业务测试 Agent
```

---

## 风险控制

| 风险 | 应对 |
|---|---|
| DOM 语义增强后 Prompt 变长 | `_format_page_info()` 截断策略保持不变 |
| Wait-for-Stable 超时 | 超时不抛异常，继续执行 |
| Goal Reminder 让 Prompt 变长 | 只加 3 行固定格式，增量 < 50 tokens |
| Sprint 5~6 依赖 Sprint 2 的 ActionResult | Sprint 5 可并行开发 |
