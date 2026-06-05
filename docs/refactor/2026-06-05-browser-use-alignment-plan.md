# browser-use 对齐实施计划

> 日期：2026-06-05
> 基线：working tree 已含 7+ phase-2.0A 修复（wait 工具、视口提示、Few-shot 6 类、pending_requests 计数、AAA/ABAB 指纹、阈值 50 回归、密码自动注入）
> 目标：在现有基础上补齐 browser-use 的核心数据层和工具集
> 不动：5 节点 LangGraph 拓扑、2-phase 架构、bind_tools 机制

---

## 模块 1: LLM 输入数据补齐（核心）

### 1.1 input value 提取（P0）

**目标**：LLM 拿到 `[3] input "搜索" (value="iPhone", placeholder=...)` 知道输入框已填啥

**改动**：
- `core/page_semantic.py:_extract_input` — 加 `value` 字段提取
- `core/page_semantic.py:_extract_textarea` — 加 `value`
- `core/page_semantic.py:_extract_select` — 加 `value` (selected option)

### 1.2 弹窗事件流（closed_popups）（P0）

**目标**：LLM 拿到"系统已自动关闭 1 个弹窗: 'Newsletter signup'"

**改动**：
- `core/page_semantic.py:track_page_requests` 同模块加 `track_popup_events`
- 监听 `page.on('dialog', ...)` (原生 confirm/alert/prompt)
- 监听 `page.on('popup', ...)` (新窗口)
- `extract_page_semantics` 返回 `closed_popups: [...]`

### 1.3 pending_network_requests 升级到 URL+method（P0）

**当前**：只有计数
**目标**：`正在请求 POST /api/cart (300ms) GET /api/products/123`

**改动**：
- `core/page_semantic.py:track_page_requests` — 改成存 `(method, url, start_time)` 列表
- `extract_page_semantics` 返回 `pending_requests: [{method, url, duration_ms}]`
- `prompts.py:_format_page_info` 渲染 URL 而非计数

### 1.4 scroll 状态扩展（P1）

**当前**：只显示 `视口滚动进度: 50%`
**目标**：`视口: 50% (Y: 600/1200, 视口上方: 600px, 视口下方: 0px)`

**改动**：
- `core/page_semantic.py` — viewport 提取加 `scrollY, innerHeight, scrollHeight, clientHeight`
- 计算 `pixels_above, pixels_below`
- `prompts.py` 渲染

### 1.5 role 字段补全（P1）

**当前**：很多 element role 缺
**目标**：role 缺失时从 tag + attributes 推断

**改动**：
- `core/page_semantic.py:_infer_role(tag, attrs)` — 推断 role
- 应用到 6 个 _extract 函数

---

## 模块 2: agent_history 消息结构重构

### 2.1 目标

仿 browser-use 的 `<agent_history><step_N>` 结构。每步用紧凑格式存：
- `Evaluation of Previous Step`: 对上一步的评价
- `Memory`: 1-3 句进度记忆
- `Next Goal`: 1 句下一步目标
- `Action Results`: 上一步工具返回的 key info

### 2.2 实现

**改动**：
- `core/interfaces.py:TestState` — 新增 `agent_history: list[dict]` 字段（替代散落的 messages 中的 tool/human 序列）
- `agents/ui/execution_graph.py:decide_node` — 构造 UserMessage 时把 history 序列化成 XML
- LLM 输出新字段：强制在 tool_call 之前输出 4 行文本：
  ```
  Evaluation: ...
  Memory: ...
  Next Goal: ...
  ```
  在 `parse_decision_response` 处解析

### 2.3 兼容

- 旧的 `messages` 列表保留（用于 LangGraph 内部 tool_call 调度）
- `agent_history` 单独维护（喂给 LLM 用）
- 第一版先做"读侧"重构（prompt 用 history 格式），第二版做"写侧"强制（要求 LLM 输出 4 字段）

---

## 模块 3: 截断策略激进调整

### 3.1 目标

充分利用 1M context window。

| 维度 | 旧值 | 新值 |
|---|---|---|
| 字符预算 | 3000 | 10000 |
| 元素数 | 50 | 100 |
| 显示上限 | 30 | 80 |
| context 压缩阈值 | 30K | 100K（先不压） |

### 3.2 改动

- `core/page_semantic.py:extract_page_semantics` — 阈值常量提取为 env
- `agents/ui/prompts.py:_format_page_info` — 字符预算提到 10000
- `core/runtime.py:L2_TOKEN_BUDGET` 默认值改 100000

### 3.3 风险

- 元素多了 LLM 选择更慢
- 历史长了噪声多
- 缓解：保留渐进式截断（30→50→100 三档），并把 total_elements 显式标注

---

## 模块 4: 工具集补齐

### 4.1 当前 18 工具 vs browser-use 71 工具

只补 browser-use 核心**对测试场景直接有用**的工具。**不**做浏览器控制无关的（read_file/write_file/bash 等）。

### 4.2 待新增（8 个）

| 工具名 | 用途 | browser-use 对应 | 优先级 |
|---|---|---|---|
| `find(query, role=None)` | 按描述/role 找元素 | `browser_use.tools.FindElement` | P0 |
| `get_dropdown_options(target)` | 列下拉框所有选项 | `browser_use.tools.GetDropdownOptions` | P0 |
| `get_specific_elements(roles)` | 按 role 过滤 | 内部用 | P1 |
| `switch_tab(index)` | 切 tab | `browser_use.tools.SwitchTab` | P0 |
| `close_tab(index)` | 关 tab | `browser_use.tools.CloseTab` | P1 |
| `refresh()` | 刷新页面 | 自有 | P0 |
| `get_page_links()` | 列所有链接 | 自有 | P1 |
| `next_page()` | 分页下一页 | 复用 `click("#next")` 不做 | — |

### 4.3 暂不做

- `read_file / write_file` (浏览器测试用不到)
- `send_keys` 复合 (用 press_key)
- `done` (我们有 mark_task_*)

---

## 模块 5: 消息缓存

### 5.1 目标

state message 加 `cache=True`，Anthropic 自动缓存 5 分钟。

### 5.2 改动

- `agents/ui/execution_graph.py:decide_node` — SystemMessage 加 `additional_kwargs={"cache_control": {"type": "ephemeral"}}`

---

## 实施顺序

1. 模块 1.1-1.5 数据层（90 min）
2. 模块 2 消息结构（60 min）
3. 模块 3 截断激进（15 min）
4. 模块 4 工具集（90 min）
5. 模块 5 缓存（15 min）
6. 单测 + 全量测试（30 min）
7. 5 case 烟测（30 min）

**总计**：~5-6 小时

---

## 不做的事（明确划线）

- ❌ bind_tools → with_structured_output 改造（破坏 LangGraph 工具调度）
- ❌ 改 5 节点 LangGraph 拓扑（observe/decide/execute/assert/record 健壮）
- ❌ 改 2-phase 架构（planning + execution 是产品差异化）
- ❌ 拆单 agent loop（多 case 并发是产品需求）
- ❌ 迁移到 browser-use 的 a11y tree 优先（我们的 CDP + browser-use + Playwright locator 三级降级已经更鲁棒）
- ❌ 改 Anthropic SDK → LiteLLM（无收益）

---

## 验收

- 单元测试：`pytest tests/core tests/agents/ui -x` 全过
- 烟测：5 case WebVoyager 子集跑通
- 文档：`docs/benchmark/2026-06-05-browser-use-alignment.md` 记效果

