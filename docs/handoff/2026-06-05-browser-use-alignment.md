# 2026-06-05: browser-use 对齐 + LLM 决策问题修复

## 概要

- **分支**: `dev/phase1-implementation`
- **触发**: 用户分享前一日 handoff（"2 周改了 3 轮没变好"）→ 决定全面对齐 browser-use 的 LLM 输入数据层
- **基线**: 30% / 10% / 0%（3 轮 10 题 WebVoyager，高方差）
- **成果**: 单 commit `f9ea4ff` (12 files, +2173/-204) + 1 cleanup commit `735aa60` (15 files, -4627)
- **烟测**: 1/3 (33%) → 2/3 (67%) — 3 case 烟测 WV-001/WV-005/WV-007 两次跑

## 模型配置

- **多模态**: mimo-v2.5 (Anthropic-compatible)
- **文本**: mimo-v2.5-pro
- **Context**: 1M tokens
- **Max output**: 128K tokens

## Part A: browser-use 对齐（5 模块）

### A1: LLM 输入数据层补齐

**目标**: 仿 browser-use 的 `<browser_state>` 字段丰富度

**改动**:
- `core/page_semantic.py:_extract_input` — **已存在** `value` 字段提取（**审计阶段误判**）
- `core/page_semantic.py:_extract_select` — 新增 `value` 字段（当前选中的 option text）
- `core/page_semantic.py:track_page_requests` — 升级 `_pending_requests` 从 set 到 dict (method+url+start_time), 新增 `_closed_popups` 弹窗事件流（监听 `page.on('dialog')` 和 `page.on('popup')`）
- `core/page_semantic.py:extract_page_semantics` — 输出 `pending_requests_detail` (URL+method+duration) 和 `closed_popups`
- `agents/ui/prompts.py:_format_page_info` — 渲染视口 `视口: 50% (Y: 600/1200, 视口上方: 600px, 视口下方: 0px)`, 渲染 `⏳ METHOD URL (Xms)`, 渲染 `- dialog: "..." (auto-dismissed)`

**行业标准依据**: browser-use `BrowserStateSummary` 字段集 + Playwright a11y tree 模式

### A2: agent_history 消息结构

**目标**: 仿 browser-use `<agent_history><step_N>{Evaluation, Memory, Next Goal, Action, Action Results}</step_N>`

**改动**:
- `core/interfaces.py:TestState` — 新增字段 `agent_history: list[dict]` (最近 10 步, deque 淘汰)
- `agents/ui/execution_graph.py:decide_node` — 渲染最近 5 步到 `<agent_history>` XML 块
- `agents/ui/execution_graph.py:decide_node` — 调 LLM 后存 `_last_ai_text` 字段
- `agents/ui/execution_graph.py:execute_node` — 追加 step 到 agent_history
- `agents/ui/prompts.py:parse_browser_use_decision()` — 正则解析 LLM 输出的 Evaluation/Memory/Next Goal (中英双标)

**未做（划线）**:
- ❌ 强制 LLM 输出这 4 字段（mimo-v2.5 不稳定遵循，**先做松约束**）
- ❌ bind_tools → with_structured_output（破坏 LangGraph 工具调度）

### A3: 截断激进

**目标**: 1M context 装得下，激进放大

| 维度 | 旧值 | 新值 | env 变量 |
|---|---|---|---|
| 字符预算 | 3000 | 10000 | `L2_PAGE_INFO_CHAR_BUDGET` |
| 元素数截断 | 50 | 100 | `L2_MAX_INTERACTIVE_ELEMENTS` |
| 元素显示上限 | 30 | 80 | hard-coded |
| Context 压缩阈值 | 30K | (未改, 保留 30K) | `L2_TOKEN_BUDGET` |

**改动**: `core/page_semantic.py:extract_page_semantics` 提 env, `agents/ui/prompts.py:_format_page_info` 改 hard-coded

### A4: 工具集 +7

**目标**: 补齐 browser-use 核心工具，**不**做浏览器控制无关的（read_file/write_file）

| 工具 | 用途 | browser-use 对应 |
|---|---|---|
| `find(query, role=None)` | 按描述/role 找元素（不执行动作） | `FindElement` |
| `get_dropdown_options(target)` | 列出 select 所有选项 | `GetDropdownOptions` |
| `get_specific_elements(roles)` | 按 role 过滤 | (内部用) |
| `switch_tab(index)` | 切 tab | `SwitchTab` |
| `close_tab(index)` | 关 tab | `CloseTab` |
| `refresh()` | 刷新 | (自有) |
| `get_page_links()` | 列出所有可见链接 | (自有) |

**改动**: `agents/ui/tools.py` 7 个新 `@tool`, 加入 `tools` 列表和 `__all__`

**role_to_css 映射**: `link → a[href]`, `textbox → input[type='text']`, `combobox → select` (Playwright CSS 不直接支持这些 role 关键字)

### A5: 消息缓存

**目标**: Anthropic 提示缓存, 节省 cost

**改动**:
- `agents/ui/execution_graph.py:decide_node` — SystemMessage 加 `additional_kwargs={"cache_control": {"type": "ephemeral"}}`
- 加 `[cached-block-end]` marker SystemMessage 作为 cache boundary
- env `L2_CACHE_SYSTEM=1` 默认开, `=0` 关闭

## Part B: LLM 决策问题修复（3 项）

### B1: target 格式硬约束（系统提示规则 15）

**问题**: LLM 把元素描述当 target: `click(target="[57] button 'Search or jump to…'")` → 解析失败

**修复**:
- `agents/ui/prompts.py` — 规则 15: "target 参数必须是 #N 格式 (N 是 1-100 之间的整数, 对应'交互元素'列表里的 # 编号). 禁止把元素的文本描述传给 target. 如果只看到描述, 改用 find(query=...)"
- 加 good example 示范 `click(target="#57")`, 加 bad example 展示 `[57] button 'Search or jump to…'` 错误

**效果**: WV-005 不再 0 步退 (从 2 步走到 10 步走完搜索流)

### B2: 提取完整性（系统提示规则 16 + Goal Reminder 注入）

**问题**: LLM 看到 "title and score" 只 extract 一个就 mark_complete → judge 判 fail

**修复**:
- `agents/ui/prompts.py` — 规则 16: "提取完整性 — 当 step 要求多个字段, 必须每个字段分别 extract, 全部进 extracted_content 后再 mark_complete"
- `agents/ui/execution_graph.py:goal_reminder` — 解析 expected 含 "和"/"及"/"and"/"、" 时自动注入 ⚠️ 提取完整性提醒
- 加 good example 示范多字段提取

**效果**: **WV-007 修好** (从漏 title 失败 → title+score 全提 成功)

### B3: 4 字段输出引导（中英双标 + example）

**问题**: 规则 14 "输出 Evaluation/Memory/Next Goal" LLM 不遵循

**修复**:
- `agents/ui/prompts.py` — 规则 14 接受中英双标 (`评价`/`记忆`/`下一步` 或 `Evaluation`/`Memory`/`Next Goal`)
- 加 good example 示范 4 字段先输出再调工具

**效果**: 部分起效（日志看部分 case LLM 开始输出 4 字段）。**未完全解决**（小模型不稳定）

## Part C: 不做的事（明确划线）

| 不做 | 原因 |
|---|---|
| bind_tools → with_structured_output | 破坏 LangGraph 工具调度，风险大于收益 |
| 改 5 节点 LangGraph 拓扑 (observe/decide/execute/assert/record) | 健壮，已迭代 2 周 |
| 改 2-phase 架构 (planning + execution) | 产品差异化 |
| 拆单 agent loop (多 case 并发) | 产品需求 |
| 迁移到 browser-use a11y tree 优先 | 我们的 CDP + browser-use + Playwright 三级降级更鲁棒 |
| 改 Anthropic SDK → LiteLLM | 无收益 |
| 强制 4 字段输出 (with_structured_output) | 风险大，先做松约束 |
| 71 工具全做 | 只做浏览器控制相关 (read_file/write_file 不做) |
| 拆 LangGraph checkpointing 改造 | 无收益 |
| 改 password 注入逻辑 (tools.py:711-791) | 之前 audit 列出，**未做** (改完 system_prompt 已 work) |

## 测试覆盖

- `tests/core/test_l2_prompts.py` — 4 个新 system_prompt test (target 格式 / 提取完整性 / 4 字段 / examples), 4 个 parse_browser_use_decision test
- `tests/agents/ui/test_tools.py` — 5 个新工具 test (refresh / get_page_links / find / get_dropdown_options / get_specific_elements), 1 个 tools 列表完整性 test
- `tests/core/test_page_semantic.py:test_max_50_elements` — 改 env-overridable, 改 110 元素 + 5 按钮 (115 元素)
- `tests/core/test_l2_prompts.py:test_b4_format_page_info_caps_interactive_elements_count` — 改 100 元素期望 `前 80/100`

**全量测试**: 208+ passed (agents/ui 全集 + core 关键 + prompts)
**不跑**: `tests/core/test_runtime.py` (pre-existing 超时 issue, 不归这次改)

## 烟测结果

3 case WebVoyager 烟测（WV-001 Amazon, WV-005 GitHub, WV-007 HN）：

| Case | 第一轮 (对齐后) | 第二轮 (修复后) | 备注 |
|---|---|---|---|
| WV-001 | ✅ 3步 117s | ✅ 3步 167s | 稳定 |
| WV-005 | ❌ 2步 59s (locator 失败) | ❌ 10步 277s (搜了但截图早) | 进展（不再 0 步退） |
| WV-007 | ❌ 6步 246s (漏 title) | ✅ 6步 196s (title+score 全提) | **修好** |
| **合计** | **1/3 = 33%** | **2/3 = 67%** | +33% |

**基线对比**: 历史 10 case 30% / 10% / 0% (高方差 ±15%)

**Token 消耗**: 第一轮 15-20 万, 第二轮 25-30 万

## Commits

```
735aa60 chore: clean up historical docs and one-off scripts  (15 files, -4627)
f9ea4ff browser-use 对齐 + 修复 3 LLM 决策问题  (12 files, +2173/-204)
5c3eb24 feat(cdp): CDP XPath stable resolve + session cache + anti-bot + llm alias  (前一个 commit)
```

## 已知未解决问题

### P1 (下次接手先做)

1. **WV-005 截图时机**: search 工具完成后没等 networkidle，截图过早抓到搜索按钮页而非结果页
   - 修法: `search()` 工具内部 `await page.wait_for_load_state("networkidle")` 再 return

2. **WV-005 star count 抽取**: 即便进结果页，`extracted_content` 抽取只看到 "star" 文本没看到数字
   - 修法: `extract_text` 支持 href/text 多级遍历

3. **小样本方差**: n=3 一次 ±33%, 需跑 10 case 拿稳定数据
   - 修法: `python -m tests.benchmarks.webvoyager_subset.runner --output data/bench_v3.md` (但 runner 不支持 --limit, 需改 runner)

### P2 (有数据再做)

4. **4 字段 Evaluation/Memory/Next Goal**: mimo-v2.5 不稳定遵循，目前松约束
   - 修法: 跑 100 case 失败分布分析, Goal Drift > 20% 才考虑 with_structured_output

5. **弹窗事件流测试覆盖**: `_closed_popups` 实现但单测没覆盖 dialog/popup 实际触发
   - 修法: 加 test_dialog_auto_dismissed, test_popup_tracked

6. **SystemMessage 缓存实际效果**: 加了 cache_control 但没 A/B test
   - 修法: 跑同样 case 2 次对比 token 消耗

## Working Tree 状态

未触动 M (8 个, 不是本次改的):
- `CLAUDE.md` (用户工作需要)
- `api/app.py`, `core/execution_logger.py`, `core/runtime.py`, `database/models.py`
- `tests/core/test_context_manager.py`, `tests/core/test_llm_client.py`, `tests/core/test_runtime.py`

未触动 ?? (4 个, 工具/用户):
- `.codegraph/`, `.codex/` (opencode 工具缓存)
- `AGENTS.md` (用户工作需要)
- `scripts/trigger_fast.py` (用户脚本)

未触动 ?? (13 个, 产出):
- `data/bench_aligned*.md` (本次烟测报告)
- `data/bench_wv007_run*.md` (前次)
- `docs/handoff/2026-06-05-audit-fixes-and-benchmark.md` (用户源 handoff)

## 下次接手建议

1. **跑 5+ case 烟测拿稳定数据**（不要 n=3 估方差）
2. **修 P1 第 1 项** (search 工具 wait_for_load_state) — 影响 WV-005 等所有搜索 case
3. **如要继续改 system_prompt**，先 `_format_page_info` 跑一次单测看输出（已有 60+ 断言）
4. **如要改 agent_history**，注意 `execute_node` 末尾只追加 1 步（不是所有 tool_call），多 tool_call 用 batch 时会少记
5. **如要改模型**，先看 `core/llm_client.py` 的 model alias 配置

## 相关文档

- `docs/refactor/2026-06-05-browser-use-alignment-plan.md` — 本次实施计划
- `docs/refactor/2026-06-05-needed-changes.md` — 早期审计清单 (含 false positive)
- `docs/research/2026-06-05-llm-input-comparison.md` — browser-use / playwright-mcp / 我们对比
- `docs/benchmark/2026-06-05-browser-use-alignment.md` — 烟测报告

## 行业标准依据

- browser-use 源码: `browser_use/agent/message_manager/service.py`, `browser_use/agent/prompts.py`
- Playwright MCP: `https://github.com/microsoft/playwright-mcp`
- Anthropic Prompt Engineering 2026: XML tags, few-shot, output contract
- Anthropic Context Engineering 2025-09: just-in-time context, no hardcode
- ReAct (Yao et al. 2022): thought → action → observation
- W3C ARIA: role, accessible name, state (用于 a11y tree 设计)
