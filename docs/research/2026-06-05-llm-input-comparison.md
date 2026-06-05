# 调研：browser-use / Playwright MCP 在调用 LLM 前喂了哪些数据

> 日期：2026-06-05
> 目的：诊断"LLM 决策时数据不够"这个根因，对照标杆找差距
> 范围：browser-use 0.12.6 / Microsoft playwright-mcp（v0.6+）

---

## 1. 共同点：都基于"无障碍树（a11y tree）"喂数据

两者都不发 raw DOM，不发完整 HTML，只发**浏览器内部的 Accessibility Node 树**（即屏幕阅读器用的那棵树）。原因：

- 屏幕阅读器树天然只包含"对用户有意义"的元素（按钮、输入框、链接、标题）
- 自带 role / name / state / value，LLM 不用再猜"这是啥"
- 隐藏元素、装饰元素、style 节点都过滤掉了
- Token 量级是 DOM 的 1/10~1/50

**这一层我们的差距**：我们已经做到了（CDP AXTree + browser-use DOM service + Playwright locator 三级降级），但提取的字段偏少，且没把"完整的 a11y 语义状态"带回来（见第 4 节）。

---

## 2. browser-use 在每次 LLM 调用前构造的 UserMessage 结构

来源：`browser_use/agent/message_manager/service.py` + `browser_use/agent/prompts.py`

```
┌─ SystemMessage (固定指令, 可缓存) ──────────────────────┐
│ - 角色 + 思考规则 + 工具列表 + 工具调用 JSON schema        │
│ - flash_mode / browser-use 专用精简版可选                 │
└────────────────────────────────────────────────────────┘
┌─ UserMessage (state, 每步重建, 可缓存) ─────────────────┐
│                                                         │
│  <agent_history>                                        │
│    <step_1>                                             │
│      Evaluation of Previous Step: ...                   │
│      Memory: ...        ← 1-3 句进度记忆                │
│      Next Goal: ...                                     │
│      Action Results: ...                                │
│    </step_1>                                            │
│    <step_2> ...                                         │
│    ...                                                  │
│  </agent_history>                                       │
│                                                         │
│  <agent_state>                                          │
│    <user_request>原始任务</user_request>                 │
│    <file_system>...</file_system>                      │
│    <todo_contents>...</todo_contents>                   │
│    <plan>...</plan>                                     │
│    <step_info>步数 / 最大步数 / 剩余步数</step_info>     │
│    <available_file_paths>...</available_file_paths>     │
│    <sensitive_data>...</sensitive_data>                 │
│  </agent_state>                                         │
│                                                         │
│  <browser_state>                                        │
│    URL: ...                                             │
│    Title: ...                                           │
│    Tabs: ...        ← 多 tab 状态                       │
│    Interactive elements:                                │
│      [1] button "Search"                                │
│      [2] textbox "Search..." (placeholder=...)          │
│      ...                                                │
│    ... (truncated to 40000 chars)                       │
│  </browser_state>                                       │
│                                                         │
│  <browser_vision>                                       │
│    [截图 base64, optional, with bounding boxes]         │
│  </browser_vision>                                      │
│                                                         │
│  <read_state> (仅当上一步是 extract/read_file 时)        │
│    提取的文本 / 文件内容                                  │
│  </read_state>                                           │
└────────────────────────────────────────────────────────┘
```

**关键设计**：

1. **AgentOutput schema 强制 LLM 输出 6 个字段**：
   ```json
   {
     "thinking": "...",                    // 思考过程
     "evaluation_previous_goal": "...",    // 对上一步的评价（1句）
     "memory": "...",                      // 进度记忆（1-3句）
     "next_goal": "...",                   // 下一步目标（1句）
     "current_plan_item": 0,               // 当前在 plan 哪一项
     "plan_update": ["...", "..."],        // 动态更新 todo
     "action": [{"click": {"index": 5}}, ...]
   }
   ```
   → **强制 LLM 维护"上一步评价 + 当前进度记忆"**，解决"上下文长了就忘"的问题。

2. **每步有 fresh state message**（不堆 messages），通过缓存降低 token 成本。

3. **Tabs 状态**单独字段（多 tab 场景必须）。

4. **Pending network requests** 在 state 里（`pending_network_requests`），LLM 知道"页面还在加载"。

5. **Closed popups** 单独字段（自动关闭的 JS 弹窗消息记录）。

6. **Recent events** 可选（最近浏览器事件的文本摘要）。

---

## 3. Playwright MCP 在每次工具响应里喂的数据

来源：Microsoft playwright-mcp 官方文档 + mcp-playwright-browser 改进版

### 3.1 Snapshot 格式（核心数据格式）

playwright-mcp 用的是 **YAML 风格的缩进树**：

```yaml
- heading "Login" [level=1]
- form "Sign in" [ref=1]
  - textbox "Email" [ref=2]
  - textbox "Password" [type=password] [ref=3]
  - checkbox "Remember me" [ref=4]
  - button "Sign In" [ref=5]
  - link "Forgot password?" [ref=6]
- text: "Don't have an account?"
- link "Create account" [ref=7]
```

**关键字段**：
- **role**: `button` / `link` / `textbox` / `checkbox` / `heading` / `menu` ...
- **accessible name**: 屏幕阅读器念出来的文字
- **state**: `[checked]` `[disabled]` `[expanded]` `[required]` `[type=password]`
- **ref**: 唯一稳定引用（`e1`, `e2` ... 或 `ax-{nodeId}`）
- **value**: `[value="user@example.com"]` （输入框当前值）
- **level**: heading 层级

### 3.2 每个工具的响应

```
Tool: browser_click
Input:  { element: "Sign In button", ref: "5" }
Output: {
  result: "Clicked",
  snapshot: "<新页面的 a11y snapshot, incremental>"
}
```

**默认**每次 action 后都返回新 snapshot，LLM 立即知道结果。**可配置** `includeSnapshot: false` 省 70-80% token。

### 3.3 mcp-playwright-browser 增强版喂得更多

| 维度 | 微软版 | mcp-playwright-browser v2 |
|------|-------|---------------------------|
| 总工具数 | 15+ | 71 |
| 元素发现 | a11y tree only | DOM + a11y + visual 三档 |
| 滚动感知 | ❌ | ✅ 滚轮状态、容器滚动 |
| 多 tab | basic | 完整 pageId 管理 |
| 表单审计 | ❌ | `form_audit` + `fill_form` |
| 弹窗处理 | ❌ | 弹窗状态可访问 |
| 状态文件 | ❌ | cookie/storage 导入导出 |
| 元素 UID | ref=eN | ref=ax-{nodeId}（CDP backendNodeId） |
| 截断策略 | --max-elements | 280KB 硬上限 + 截断标记 |
| 抓取级别 | 单档 | light / balanced / full × low/high = 30 档 |

**Token 优化关键**：
- 微软默认 streaming snapshot（全量进 context）→ 60-80K token/step
- CLI 改存 YAML 文件 → LLM 自取 → 27K vs 114K per task，4x 节省
- `includeSnapshot: false` → 70-80% token 节省

---

## 4. 我们系统当前实际喂给 LLM 的数据

来源：`core/page_semantic.py:18-107` + `agents/ui/prompts.py:382-469`

### 4.1 observe 节点抓的 page_info 结构

```python
{
  "url": "...",
  "title": "...",
  "interactive_elements": [
    {
      "id": "#1",
      "type": "input",              # tag 名
      "text": "搜索",                # 文本
      "label": "...",               # label
      "placeholder": "搜索商品",
      "input_type": "text",         # 弱支持
      "required": True,             # 有
      "checked": False,             # 有
      "enabled": True,              # 有
      "visible": True,              # 有
      "readonly": False,            # 有
      "role": "textbox",            # 有
      "backend_node_id": "...",     # 有 (CDP)
      "xpath": "...",
      "coords": {"x": 100, "y": 200, "width": 300, "height": 40}
    },
    ...
  ],
  "headings": [...],
  "forms": [...],
  "modals": [...],
  "nav_items": [...],
  "error_messages": [...],
  "js_errors": [...],
  "network_errors": [...],
  "loading": False,
  "pagination": None,
  "tables": [...],
  "truncated": False
}
```

### 4.2 decide 节点喂给 LLM 的文本（`_format_page_info`）

```
URL: https://amazon.com
标题: Amazon

交互元素 (前 30/45 个):
  [1] input "搜索" placeholder="搜索商品..." (visible, type=search)
  [2] button "搜索" (visible, enabled)
  [3] link "登录" (visible)
  ...

可见错误 (前 5 个): ...
```

### 4.3 decide 节点 system prompt 喂的上下文

来源：`prompts.py:16-181`（`get_execution_system_prompt`）

```
<role>你是一个 UI Test Executor</role>
<context>
  <test_case> TC-001: 搜索 iPhone </test_case>
  <test_accounts> (角色 + 用户名, 密码不暴露) </test_accounts>
  <focus_areas>...</focus_areas>
  <scenarios>...</scenarios>
  <risk_points>...</risk_points>
  <memory>...</memory>
  <session_summary>...</session_summary>
</context>
<task>...</task>
<rules>1-12 条规则</rules>
<examples>1 good + 1 bad</examples>
<output_contract>...</output_contract>
```

**当前步 prompt**（`get_step_prompt`）:
```
<current_step>
  <index>1/3</index>
  <text>在搜索框输入 "iPhone"</text>
</current_step>
请观察页面状态, 决定下一步操作...
```

---

## 5. 差距对比表（核心！）

| 数据维度 | browser-use | playwright-mcp | mcp-playwright-browser v2 | **我们当前** | 差距评估 |
|---------|------------|----------------|--------------------------|-------------|---------|
| **元素基础信息** | ✅ | ✅ | ✅ | ✅ | 平 |
| **element ref (稳定 ID)** | ✅ `[1]` | ✅ `ref=eN` | ✅ `ax-{nodeId}` | ✅ `#1` | 平（每次重建会重编号）|
| **role / accessible name** | ✅ | ✅ | ✅ | ⚠️ 弱（role 经常缺） | **缺** |
| **元素 value（输入框当前值）** | ✅ `[value="..."]` | ✅ `[value="..."]` | ✅ | ❌ 抓不到 | **缺** |
| **state (checked/disabled/expanded)** | ✅ | ✅ | ✅ | ⚠️ 部分 | 平 |
| **多 tab 状态** | ✅ `tabs` | ✅ `browser_tabs` | ✅ pageId | ❌ 不喂 | **缺** |
| **滚动状态 (scrollY, viewport)** | ✅ PageInfo | ❌ | ✅ 滚轮感知 | ❌ | **缺** |
| **pending network requests** | ✅ | ❌ | ✅ | ❌ | **缺** |
| **弹窗/对话框事件** | ✅ closed_popups | ❌ | ✅ | ❌ | **缺** |
| **JS 错误** | ✅ browser_errors | ❌ console | ✅ | ✅ js_errors | 平 |
| **Network 错误** | ✅ | ❌ | ✅ | ✅ network_errors | 平 |
| **截图（按需）** | ✅ with bbox | ✅ | ✅ with bbox map | ✅ JPEG 压缩 | 平 |
| **上一步评价 / Memory / Next Goal** | ✅ 强制 schema | ❌ 不需要 | ❌ | ❌ 完全没有 | **缺**（最大差距）|
| **Plan/Todo 状态** | ✅ `<plan>` | ❌ | ❌ | ❌ | **缺** |
| **截断策略** | 40000 字符 | --max-elements | 280KB 硬上限 + truncated 标记 | 3000 字符 + 50 元素 | **远不够** |
| **元素数截断时告知 LLM** | ✅ "truncated at..." | ❌ | ✅ "truncated" flag | ✅ "还有 N 个省略" | 平 |
| **错误注入 (上下文隔离)** | ✅ sensitive_data filter | ❌ | ✅ | ✅ B5 fix | 平 |
| **消息缓存** | ✅ cache=True state msg | n/a | n/a | ❌ 不缓存 | **缺** |
| **多档抓取级别 (light/full)** | ❌ | ❌ | ✅ 30 档 | ❌ | **缺** |

---

## 6. 关键差距排序（按"对成功率影响最大"排）

### P0 - 立刻影响决策质量

1. **"上一步评价 / Memory / Next Goal" 字段缺失**
   - browser-use 强制 LLM 输出这 4 个字段，等于"显式维护进度记忆"
   - 我们只让 LLM 输出 `tool_call`，**没有强制它先写"我刚做完什么"和"我接下来要做啥"**
   - 后果：上下文长（5 步以后）就开始丢上下文 → 决策随机

2. **元素 value（输入框当前值）抓不到**
   - LLM 输入完 "123456" 后，再 observe 看不到"已经填了 123456"
   - 后果：重复填、覆盖填、不知道是不是填成功

3. **多 tab 状态**
   - LLM 不知道打开了几个 tab，当前在哪个
   - 后果：tab 切换混乱

### P1 - 显著影响决策质量

4. **滚动状态**（scrollY, viewport_height, pixels_above/below）
   - LLM 不知道"页面是否滚到底了"、当前 viewport 看到的是哪一段
   - 后果：找不到 viewport 外的元素 → "元素不存在"误判

5. **pending network requests**
   - LLM 不知道"页面还在加载"，过早行动
   - 后果：点了还没加载完的按钮 → 状态错乱

6. **截断上限 3000 字符 / 50 元素**
   - 真实网页 50 元素不够，3000 字符也不够
   - 后果：关键元素被截掉

### P2 - 锦上添花

7. **弹窗事件流**（closed_popups）
8. **消息缓存**（cache=True）
9. **多档抓取级别**（按步骤智能选择 light/balanced/full）
10. **role 字段补全**（很多元素 role 是空的）

---

## 7. 落地方案（按 ROI 排序）

### 方案 1: 加 P0 字段（最小改动，3-5 小时）
**改动文件**：
- `core/page_semantic.py`: `_extract_input` 加 `value` 属性；`extract_page_semantics` 加 `tabs`、`scroll`、`pending_requests` 字段
- `agents/ui/prompts.py`: `_format_page_info` 加这些字段的展示
- `agents/ui/prompts.py`: `get_execution_system_prompt` 加 **强制输出 schema**（Evaluation / Memory / Next Goal / Action）
- `core/interfaces.py`: `AgentDecision` 加 4 个字段

**预期收益**：决策稳定性 +30-50%（基于 browser-use 公开数据）

### 方案 2: 截断上限提升到 8000 字符 / 80 元素
**改动**：1 个 env 变量 + 1 行 prompt
**预期收益**：长页面覆盖率 +20%

### 方案 3: 多档抓取级别（Step 1 用 light, Step 3+ 用 full）
**改动**：observe 节点按 step_index 选抓取档
**预期收益**：token 减半 + 关键步骤信息更全

### 方案 4: 消息缓存（state message cache=True）
**改动**：1 行（Anthropic 特定）
**预期收益**：成本 -30%

---

## 8. 验证方法

- 选 WV-007 同一任务（基线: 1/3 success）
- 跑 3 轮，测方案 1 + 2
- 关注：success 率 + 决策一致性（同样的 case 跑 3 次，输出是否一致）

---

## 引用

- browser-use: https://github.com/browser-use/browser-use
  - `agent/service.py` - Agent 主循环
  - `agent/message_manager/service.py` - 消息管理
  - `agent/prompts.py` - 提示词构造
  - `browser/views.py` - BrowserStateSummary 定义
- playwright-mcp: https://github.com/microsoft/playwright-mcp
- mcp-playwright-browser v2: https://github.com/Mhrnqaruni/mcp-playwright-browser
