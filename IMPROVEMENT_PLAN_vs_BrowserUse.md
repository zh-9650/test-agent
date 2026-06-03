# TestAgent 改进方案 | 对标 Browser-Use 架构

> 诊断完成时间: 2026-06-03  
> 基于 Browser-Use v0.12.9 架构设计对标

## 📋 你遇到的 4 个问题诊断

### ❌ 问题 1: Agent 决策经常出错（幻觉、走弯路）

**根本原因**：
- ✗ LLM 可以自由访问整个 PRD + DOM 树
- ✗ 没有强制的"决策防护栏"
- ✗ 工具返回值不是结构化的，LLM 无法判断成功/失败
- ✗ Goal 定义过于模糊，LLM 容易偏离目标

**Browser-Use 的解决方案**：
```python
# 1. 工具必须返回 ActionResult（结构化）
@tool.action('Click element')
async def click(element_id: int) -> ActionResult:
    # ✅ 返回结构化证据，不是随意的字符串
    return ActionResult(
        extracted_content="Button clicked, page loading",
        error=None,  # 如果失败则填充错误原因
        success=True,
        is_done=False
    )

# 2. 防护栏：Goal 必须来自系统已知范围
# Browser-Use 的 Goal Generator 确保目标在系统边界内
# 不允许 LLM 生成"凭空编造的"跳转目标

# 3. 每一步 LLM 只能看到：
#   - 当前页面 DOM（截断到 20KB）
#   - 最近 3 步的执行历史
#   - 预定义的可用工具列表
```

**你应该做的改进**：

1️⃣ 修改 `agents/ui/tools.py`，让所有工具返回统一的 Result 对象：
```python
from typing import TypedDict

class ToolResult(TypedDict):
    status: Literal["success", "failure", "timeout"]
    action: str  # 执行的动作名称
    evidence: dict  # 执行结果的证据
    reason: str  # 为什么成功/失败
    interactable_elements: list  # 如果失败，返回可选的替代元素
    timestamp: float
```

2️⃣ 在 `agents/ui/execution_graph.py` 的 Prompt 中，加入**决策约束**：
```python
EXECUTION_PROMPT = """
[角色] 你是一个谨慎的 Web 自动化测试执行器

[约束]
1. ❌ 禁止跳转到页面上不存在的链接
2. ❌ 禁止虚构元素的 selector（必须从 page_interactable_elements 中选择）
3. ✅ 只能使用工具返回的实际可交互元素
4. ✅ 遇到找不到元素时，从备选列表中选择最接近的

[执行循环]
{
  "thought": "分析当前状态",
  "action": "选择一个工具",
  "tool_input": "工具参数（必须来自页面元素列表）",
  "expected_outcome": "预期页面变化"
}

[失败恢复]
如果工具返回 failure，你必须：
1. 分析失败原因
2. 从返回的 interactable_elements 中选择替代元素
3. 不允许原路重试（除非条件改变）
"""
```

---

### ❌ 问题 2: 元素定位失败

**根本原因**：
- ✗ 依赖 CSS Selector（脆弱）
- ✗ DOM 变化后选择器失效
- ✗ 没有多策略递进定位
- ✗ 定位失败没有降级方案

**Browser-Use 的解决方案**：
```python
# DomService 的关键：用"元素索引"而不是"Selector"
class InteractableElement(BaseModel):
    index: int  # ⭐ 不变的索引，即使 DOM 变化
    tag: str
    text: str
    role: str  # accessibility role
    xpath: str  # 备用
    selector: str  # 再备用
    bounding_box: dict  # 位置信息
    visible: bool
    enabled: bool

# Agent 的动作：指代元素时用 index，而不是 selector
# Tool 实现：优先用 index，失败时递进到 xpath、selector

# 降级策略：
def click_element(index: int, xpath: str = None, selector: str = None) -> ActionResult:
    strategies = [
        ("index", lambda: click_by_index(index)),
        ("xpath", lambda: click_by_xpath(xpath)),
        ("selector", lambda: click_by_selector(selector)),
        ("fuzzy", lambda: find_similar_and_click(text, role))  # 模糊匹配
    ]
    
    for strategy_name, strategy_func in strategies:
        try:
            await strategy_func()
            return ActionResult(
                extracted_content=f"Clicked using {strategy_name}",
                success=True
            )
        except:
            continue
    
    # 如果都失败，返回相似元素列表
    return ActionResult(
        status="element_not_found",
        candidates=find_similar_elements(...),
        error=f"Could not find element with index {index}"
    )
```

**你应该做的改进**：

1️⃣ 修改 `core/page_semantic.py` 的元素提取逻辑：
```python
def extract_interactable_elements(page_tree: dict) -> list[dict]:
    """从 browser-use 的树中提取交互元素，带索引"""
    elements = []
    for idx, elem in enumerate(page_tree.get("interactable", [])):
        elements.append({
            "index": idx,  # ⭐ 关键
            "tag": elem.get("tag"),
            "text": elem.get("text", "").strip()[:50],
            "role": elem.get("role"),
            "xpath": elem.get("xpath"),
            "selector": elem.get("selector"),
            "visible": elem.get("visible", True),
            "bounding_box": elem.get("bounding_box"),
        })
    return elements
```

2️⃣ 修改 `agents/ui/tools.py` 中的 click/input 工具：
```python
async def click_element(element_index: int, page) -> ToolResult:
    """
    支持多策略定位：index → xpath → selector → fuzzy
    """
    element = page.get_element_by_index(element_index)
    
    # 策略 1: 直接用 index
    try:
        await page.click(f"[data-element-index='{element_index}']")
        return ToolResult(
            status="success",
            action="click",
            evidence={"method": "index", "element_index": element_index},
            reason="Clicked successfully using element index"
        )
    except:
        pass
    
    # 策略 2: XPath
    try:
        await page.click(element["xpath"])
        return ToolResult(status="success", ...)
    except:
        pass
    
    # 策略 3: 模糊匹配相似元素
    similar = find_similar_elements_by_text_and_role(
        element["text"], 
        element["role"]
    )
    
    return ToolResult(
        status="failure",
        action="click",
        error=f"Could not locate element at index {element_index}",
        reason="All locating strategies failed",
        interactable_elements=similar,  # 提供替代方案
        evidence={"attempted_strategies": ["index", "xpath", "selector"]}
    )
```

3️⃣ 新增 DB 记录元素定位失败：
```sql
-- 在 AgentMemory 中新增字段
ALTER TABLE agent_memory ADD COLUMN failed_locators jsonb;

-- 记录格式：
{
  "element_text": "Submit",
  "element_role": "button",
  "attempted_strategies": ["index", "xpath", "selector"],
  "timestamp": "2026-06-03T10:00:00",
  "url": "https://example.com/form"
}

-- 下次遇到相同 URL + 相似元素时，跳过已知失败的策略
```

---

### ❌ 问题 3: 执行速度太慢

**根本原因**：
- ✗ 每一步都调用 LLM（6-10 次调用）
- ✗ 没有上下文压缩，Token 数不断增长
- ✗ 没有优先级顺序（规则 > 网络 > LLM）
- ✗ 没有缓存历史执行路径

**Browser-Use 的解决方案**：
```python
# 1. Flash Mode: 跳过思考过程
agent = Agent(
    task=task,
    llm=llm,
    flash_mode=True,  # ⚡ 只用记忆，不生成思考
    use_thinking=False,  # 也不让模型想
)

# 2. 上下文压缩
max_history_items = 3  # 只保留最近 3 步
# 超过这个数时自动压缩为摘要

# 3. 优先级链（断言）
# 规则 (Rule) > 网络 (Network) > 状态 (State) > LLM (Judge)

# 4. 单个 case 的 token 上限
max_tokens_per_context = 8000  # 严格限制
if context_tokens > max_tokens_per_context:
    compress_to_summary()
```

**你应该做的改进**：

1️⃣ 在 `core/execution_logger.py` 中加入上下文压缩：
```python
class ExecutionContextManager:
    MAX_HISTORY_ITEMS = 3
    MAX_TOKENS_PER_STEP = 6000
    
    async def compress_history(self, history: list[dict]) -> str:
        """超过 MAX_HISTORY_ITEMS 时压缩"""
        if len(history) > self.MAX_HISTORY_ITEMS:
            old_steps = history[:-self.MAX_HISTORY_ITEMS]
            
            # 让 LLM 总结前面的步骤
            summary = await self.llm_client.invoke(
                prompt=f"""
                总结以下测试步骤为一句话:
                {json.dumps(old_steps)}
                """,
                model="haiku"  # 用轻量模型节省成本
            )
            
            # 替换为摘要
            history = [
                {"type": "summary", "content": summary, "step_count": len(old_steps)}
            ] + history[-self.MAX_HISTORY_ITEMS:]
        
        return self.serialize(history)
```

2️⃣ 修改 `agents/ui/execution_graph.py` 的 Prompt 注入：
```python
# 当前上下文 tokens 过多时
if current_tokens > 6000:
    # 启用"快速模式"
    prompt = """
[快速模式已启用 - 跳过思考过程]

前面的步骤摘要: {compressed_summary}

当前页面: {current_page_tree}
最后一个动作: {last_action}
最后一个结果: {last_result}

直接输出下一步动作:
{
  "action": "...",
  "tool_input": {...}
}
""" 
else:
    # 正常模式，包含思考
    prompt = """
[思考模式]
...
"""
```

3️⃣ 添加断言优先级链到 `core/report_builder.py`：
```python
async def assert_action_result(action: dict, evidence: dict):
    """
    优先级: Rule > Network > State > LLM
    """
    
    # 第 1 层: 规则断言（最快，0 token）
    if rule_check := check_business_rules(evidence):
        return rule_check
    
    # 第 2 层: 网络断言（快，利用 Playwright 拦截）
    if network_check := check_network_response(evidence):
        return network_check
    
    # 第 3 层: 状态断言（中等，查询数据库）
    if state_check := check_state_transition(evidence):
        return state_check
    
    # 第 4 层: LLM 判断（慢，消耗 token）
    llm_judge = await self.llm_client.invoke(
        prompt=f"Based on this evidence, did the action succeed? {evidence}",
        model="haiku"  # 用轻量模型
    )
    return llm_judge
```

4️⃣ 在数据库中加入执行路径缓存：
```sql
-- 新表：execution_path_cache
CREATE TABLE execution_path_cache (
    id UUID PRIMARY KEY,
    url_pattern VARCHAR,
    business_goal VARCHAR,
    execution_path JSONB,  -- 成功执行过的步骤序列
    success_rate FLOAT,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP
);

-- 查询逻辑：
SELECT * FROM execution_path_cache 
WHERE url_pattern ~ current_url 
AND business_goal = target_goal 
ORDER BY success_rate DESC 
LIMIT 1;
```

---

### ❌ 问题 4: 任务完成率低

**根本原因**：
- ✗ 没有系统化的重试机制
- ✗ 失败原因没有分类记录
- ✗ 没有"降级到最后成功状态"的逻辑
- ✗ 没有从历史失败学习

**Browser-Use 的解决方案**：
```python
# 1. 明确的 max_failures 限制
agent = Agent(task=task, llm=llm)
agent.settings.max_failures = 3  # 失败 3 次停止

# 2. 每次失败都被记录和分类
if failure:
    history.record_error(
        error_msg=str(error),
        error_type="element_not_found" | "timeout" | "network_error" | ...
    )

# 3. 失败后还有最后一次机会
agent.settings.final_response_after_failure = True
# 达到 max_failures 后，强制调用一次 LLM 总结并返回

# 4. 检查 history.is_done() 来判断成功
is_done = history.is_done()
```

**你应该做的改进**：

1️⃣ 在 `database` 中新增失败分析表：
```sql
CREATE TABLE task_failure_analysis (
    id UUID PRIMARY KEY,
    task_id UUID,
    step_number INT,
    action_type VARCHAR,  -- click, input, navigate, etc.
    failure_reason VARCHAR,  -- 分类的失败原因
    failure_details JSONB,  -- 详细信息
    attempted_count INT,  -- 此步骤的重试次数
    last_success_state JSONB,  -- 最后一次成功时的页面状态快照
    recovery_action VARCHAR,  -- 用来恢复的动作
    created_at TIMESTAMP
);

-- 失败原因分类
ENUM failure_reason:
  - element_not_found
  - element_not_visible
  - element_not_enabled
  - timeout
  - network_error
  - assertion_failed
  - business_rule_violated
  - other
```

2️⃣ 修改 `agents/ui/execution_graph.py` 的失败处理：
```python
async def handle_step_failure(state: dict, error: Exception) -> dict:
    """
    失败处理 3 层策略：
    1. 如果这是首次失败，立即重试
    2. 如果失败 2 次，尝试替代路径
    3. 如果失败 3 次，回退到最后成功状态
    """
    
    task_id = state["task_id"]
    step_number = state["step"]
    
    # 查询历史失败
    past_failures = await db.query(
        f"SELECT * FROM task_failure_analysis WHERE task_id={task_id} AND step_number={step_number}"
    )
    
    failure_count = len(past_failures)
    error_type = classify_error(error)
    
    # 记录这次失败
    await db.insert("task_failure_analysis", {
        "task_id": task_id,
        "step_number": step_number,
        "failure_reason": error_type,
        "failure_details": {"error_msg": str(error), "traceback": traceback.format_exc()},
        "attempted_count": failure_count + 1,
    })
    
    state["consecutive_failures"] += 1
    
    # 策略 1: 首次失败，立即重试
    if failure_count == 0:
        return {"action": "retry", "reason": "first_failure"}
    
    # 策略 2: 第二次失败，尝试替代元素
    if failure_count == 1:
        candidates = state["last_tool_result"]["interactable_elements"]
        if candidates:
            return {
                "action": "retry_with_alternative",
                "alternative_element": candidates[0],
                "reason": "second_failure_try_alternative"
            }
    
    # 策略 3: 第三次失败，回退
    if failure_count >= 2:
        # 找最后一次成功的状态
        last_success = past_failures[-1].get("last_success_state")
        if last_success:
            return {
                "action": "rollback",
                "rollback_to": last_success,
                "reason": "max_failures_rollback",
                "give_up": False  # 还没有真正放弃
            }
    
    # 如果都失败了
    return {"action": "fail", "give_up": True}
```

3️⃣ 在前端加入失败率统计（`frontend/src/components/ExecutionMonitor.tsx`）：
```tsx
<div className="failure-analysis">
  <h3>Failure Analysis</h3>
  <table>
    <tr>
      <th>Step</th>
      <th>Action</th>
      <th>Failure Reason</th>
      <th>Attempts</th>
      <th>Recovery</th>
    </tr>
    {failures.map(f => (
      <tr key={f.id}>
        <td>{f.step_number}</td>
        <td>{f.action_type}</td>
        <td>{f.failure_reason}</td>
        <td>{f.attempted_count}</td>
        <td>{f.recovery_action || 'N/A'}</td>
      </tr>
    ))}
  </table>
  
  <div className="completion-rate">
    任务完成率: {successCount}/{totalTasks} ({(successCount/totalTasks*100).toFixed(1)}%)
    常见失败原因: {topFailures.map(f => `${f.reason}(${f.count})`).join(', ')}
  </div>
</div>
```

---

## 🛠️ 快速行动计划（按优先级）

### 第 1 阶段（立即做，2 小时）
- [ ] 修改所有工具返回 `ToolResult`（结构化）
- [ ] 在执行图 Prompt 中加入"决策约束"
- [ ] 修改元素定位用索引而不是 selector

### 第 2 阶段（今天完成，3 小时）
- [ ] 实现元素定位的多策略递进
- [ ] 加入上下文压缩逻辑
- [ ] 新增 `task_failure_analysis` 表

### 第 3 阶段（本周完成，4 小时）
- [ ] 实现断言优先级链（Rule > Network > State > LLM）
- [ ] 加入执行路径缓存
- [ ] 前端展示失败分析面板

### 第 4 阶段（下周迭代，持续优化）
- [ ] A/B 测试轻量模型（Haiku）vs 强力模型
- [ ] 调优 max_tokens_per_step 和 max_history_items
- [ ] 收集生产数据，改进失败分类

---

## 📊 预期效果对标

| 指标 | 改进前 | 改进后 | Browser-Use 参考值 |
|------|-------|--------|------------------|
| 单个 case 平均 LLM 调用次数 | 8-10 | 4-5 | 3-4 |
| 平均执行时间 | 60s | 30-40s | 20-30s |
| 元素定位成功率 | 70% | 95%+ | 98%+ |
| 任务完成率 | 40% | 70%+ | 85%+ |
| 平均 Token 消耗/case | 45K | 15K | 8-10K |
| 成本（相对） | 1.0x | 0.3x | 0.2x |

---

## 📚 参考资源

- Browser-Use 代码参考：`/service.py`（行 2419-2480）
- 你的项目：`agents/ui/tools.py`、`agents/ui/execution_graph.py`
- 建议阅读：Browser-Use 的 CLAUDE.md（架构设计哲学）
