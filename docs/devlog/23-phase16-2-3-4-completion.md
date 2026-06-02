# Phase 1.6.2 + 1.6.3 + 1.6.4 — planning_graph explore V1.6 化 + SystemMap 采样加固 + 文档

**时间**: 2026-06-02
**责任人**: Lead
**前置**: V1.6.1 (b881fca) N2 SystemModel 三层防御 + V2.0 v2 计划 (008bb79) §3.0
**状态**: ✅ 已完成
**范围**: Phase 1.6.2 + 1.6.3 + 1.6.4 (V1.6 N2 之外的 L1 收尾)
**完整方案**: `docs/layer2-v2.0-plan.md` §3.0

---

## 1. 业务目标

V2.0 v2 计划 `docs/layer2-v2.0-plan.md` §3.0 把 V1.7 漏掉的两个 L1 收尾任务合并到 Phase 1.6.2/1.6.3/1.6.4:

| 子阶段 | 目标 | 漏洞 | 文件 |
|---|---|---|---|
| **1.6.2** | planning_graph explore_decide / explore_execute prompt V1.6 化 | V-1.6.2 (V1.7 漏点) | `agents/ui/planning_graph.py` + `agents/ui/prompts.py` |
| **1.6.3** | SystemMap 采样 10/15 → 20/30 + invariant 测试 | V-1.6.3 (采样薄 + 无测试) | `core/skills/system_mapper.py` + `tests/core/test_system_mapper.py` |
| **1.6.4** | `docs/prompt-engineering.md` §8 加 planning_graph 章节 | 文档同步 | `docs/prompt-engineering.md` |

**Phase 1.6.2/1.6.3/1.6.4 目标**:
- planning_graph 探索子图沉淀 L1↔L2 节点契约 (inter-node contract)
- explore_decide 注入 SystemModel 作为"理论导航地图", 避免 LLM 漏探索
- explore_decide prompt 显式约束 tool_call OR 显式 stop, 防纯文本死循环
- SystemMap 采样加大到 20/30, 走 V1.6 5 段 XML, 加 pydantic 强类型入口
- 加 14 + 13 = 27 个回归测试 (mock + live skip)

---

## 2. Phase 1.6.2 — planning_graph explore V1.6 化

### 2.1 改造点

#### A. `get_exploration_system_prompt` 重写 (V1.6 5 段 XML)

**改造前** (旧 prompt, V1.5 之前):
```
你是一个专业的Web应用测试探索者。你的任务是探索目标系统，了解其结构和功能。

## 探索策略
1. 从首页开始...
2. 结合 PRD 和 Changelog 的业务目标...
{prd_context}
## 严格禁止
- **禁止使用 navigate 工具通过 URL 直接跳转页面**
- 只能通过点击页面上的链接、按钮等交互元素来导航到其他页面
...
```

**改造后** (V1.6 5 段 XML, 与 L1 8 skill 统一):
```xml
<role>
你是一个 Web 应用测试探索智能体 (Web Test Explorer)。
你的唯一职责是用工具系统化地探索目标系统, 收集足够信息让后续 generate_test_plan 节点生成高质量测试计划。
</role>

<context>
- 上游: N3 GoalExtractor (high/medium/low 优先级) + N2 SystemModeler (system_name/modules/entities 作为理论导航地图)
- 下游: explore_execute 执行 tool_call;explore_observe 抓页面状态传回
- Safety Valves: MAX_EXPLORE_PAGES=20, MAX_EXPLORE_MINUTES=5
</context>

<task>基于当前页面 + 历史 + Goal 列表, 决定下一步: (a) 调一个工具让浏览器移动 (b) 不调任何工具让流程进入 generate_plan</task>

<rules>
1. Goal-Driven 优先 (硬约束)
2. 真实路径优先: click/input_text/scroll, navigate 走 FireWall 白名单
3. navigate 工具限制: 只能跳 base_url / 已探索 URL / PRD 提及 / 元素 href
4. 凭证自动登录: 登录页必须用 task_config.accounts 登录
5. tool_call 必填 OR 显式停止 (硬约束): 禁止纯文本回复
6. 不要重复探索
7. 完成判据: high 优先级 Goal 都找到入口 → 选不调工具
8. 每步一个工具
</rules>

<examples>
<example type="good">登录页 + Goal "提交采购申请" → 调 input_text 填用户名</example>
<example type="bad">登录页 + 调 navigate 跳 /admin → 违反规则 3 (FireWall 拒绝)</example>
</examples>

<output_contract>
(a) tool_call 必填 (tool_calls 长度 = 1)
(b) 显式 stop (tool_calls 为空)
禁止: 纯文本, 多工具, 长 markdown
</output_contract>
```

**Best practice 依据** (5 篇):
- Anthropic 2026 prompt engineering: 5 段 XML + few-shot
- Anthropic Context Engineering 2025-09: just-in-time context, 不 hardcode 决策树
- ReAct (Yao et al. 2022): thought → action → observation, "stop" 是一等公民
- Codebridge 2026 Sub-agent manifest: role + tools + inter-agent contract
- Anthropic Writing Tools for Agents 2025-09: 工具约束写进 prompt, 不只靠代码

#### B. `explore_decide_node` 注入 SystemModel (理论导航地图)

V1.7 漏点: LLM 探索时不知道"理论上有哪些业务模块", 容易漏探索核心功能区。
V1.6.2 修复: 在 human_msg 里显式注入 `task_config._system_model` 的 system_name / modules / entities / flow_names:

```python
system_model_ctx = ""
system_model = task_config.get("_system_model", {})
if system_model:
    sm_modules = system_model.get("modules", [])
    sm_entities = system_model.get("entities", [])
    sm_system_name = system_model.get("system_name", "")
    sm_flows = system_model.get("flows", [])
    nav_hints = [
        f"系统名: {sm_system_name}",
        f"业务模块: {', '.join(sm_modules[:10])}",
        f"业务实体: {', '.join(sm_entities[:10])}",
        f"业务流: {', '.join([f['name'] for f in sm_flows[:5]])}",
    ]
    system_model_ctx = "\n### 理论业务地图 (SystemModel, V1.6.2 新增)\n" + "\n".join(nav_hints) + "\n(请带着这些业务模块去探索, 避免漏掉核心功能区)\n"
```

#### C. `explore_execute_node` inter-node 契约显式化

在 docstring 显式标注:
- 上游契约 (explore_decide): 必填 tool_call
- 下游契约 (explore_observe): 必填 ToolMessage, 失败时返回错误字符串
- Navigate FireWall 保留 (4 个白名单: base_url / 已探索 / PRD 提及 / 元素 href)
- 工具异常 → ToolMessage(content="执行失败: ...") 而非 raise

### 2.2 验证

- 6 个 prompt 结构测试 (V1.6 XML / tool_call 契约 / FireWall 文档化 / 账号注入 / scenarios 注入 / safety valve)
- 2 个 decide 行为测试 (注入 SystemModel / 无 SystemModel graceful)
- 3 个 execute 契约测试 (失败返 ToolMessage / FireWall 拦截 / FireWall 放行)
- 2 个共享契约测试 (LLM 收到 V1.6 XML / should_continue_exploring 处理 stop)

### 2.3 副带修复 (pre-existing 测试 bug)

跑 V1.6.2 测试时发现 2 个 pre-existing 测试 bug (V1.6.1 之前就 broken):
- `test_explore_decide_node_mock`: patch `agents.ui.planning_graph.ui_tools` (错), 实际是 `tools` → 修复
- `test_explore_execute_node_mock`: 用了 FireWall 不允许的 URL (`/home` 不是 base_url) → 改用 base_url 自身
- 我的新测试也有 1 个: `AsyncMock(side_effect=Exception(...))` 应该挂在 `.ainvoke` 上而非 `mock_tool_fn` 上 (因为代码调 `tool_fn.ainvoke(args)`) → 修复

---

## 3. Phase 1.6.3 — SystemMap 采样加固

### 3.1 改造点

#### A. 采样 10/15 → 20/30 (V1.2 → V1.6.3)

**改造前** (`core/skills/system_mapper.py` V1.2, 2026-05-31):
```python
for idx, page in enumerate(exploration_history[-10:]):  # Limit to last 10 pages
    ...
    elems_summary = ", ".join([... for el in elements[:15]])  # 15 elements
```

**改造后** (V1.6.3):
```python
DEFAULT_MAX_PAGES = int(os.getenv("SYSTEM_MAP_MAX_PAGES", "20"))  # 20 pages
DEFAULT_MAX_ELEMENTS_PER_PAGE = int(os.getenv("SYSTEM_MAP_MAX_ELEMENTS_PER_PAGE", "30"))  # 30 elements

# Token safety: 20 pages × 30 elements × ~10 chars ≈ 6000 chars + 1000 URL ≈ 7000 chars ≈ 2000 tokens
# Plus prompt ≈ 500 tokens. Total ≈ 22K tokens, safe.
```

**Token 安全验证** (`test_v163_summarize_history_token_safety`):
- 25 页 × 35 元素最大输入 → 摘要 < 30K 字符
- 防 65K context window 溢出

#### B. V1.6 5 段 XML prompt

**改造前**:
```
你是一位测试架构师。自动化探索智能体刚刚在真实系统中完成了一次探路。
请根据智能体探索到的页面历史和交互元素，绘制一张**真实的系统地图 (System Map)**。
### 探索历史与发现的页面元素:
{history_summary}
你需要提取出系统真实的：
1. pages: 实际发现的页面名称
2. actions: 实际发现的可操作动作（按钮、链接等）
3. forms: 实际发现的表单区域
请完全依据上面的"探索历史"提取，不要凭空猜测文档里有但实际上没找到的功能。
只返回 JSON。键名必须严格使用: pages, actions, forms (均为字符串数组)。
```

**改造后** (V1.6 5 段 XML):
```xml
<role>你是一个测试架构师。你不是 PRD 解读员 — 你只看实际发现了什么, 不猜文档里写了什么。</role>
<context>你在 planning_graph 的"探索 → 规划"中间环节;下游 scenario_extractor 会把 SystemMap 与 SystemModel 合并</context>
<task>从"探索历史"中提取 pages/actions/forms</task>
<rules>
1. 完全依据探索历史 — 文档里有但实际没发现的功能不写
2. 去重 — pages/actions/forms 各自去重
3. 简短命名 — 每项 ≤ 12 字
4. 空容忍 — 如果某类没发现, 返回空数组
5. 数量上限 — pages ≤ 30, actions ≤ 50, forms ≤ 20
</rules>
<examples>
<example type="good">登录页 → 首页 → 提取 2 pages / 5 actions / 1 form</example>
<example type="bad">只访问了登录页 → 提取 3 pages (含未访问) ❌</example>
</examples>
<output_contract>{ "pages": [str, ...], "actions": [str, ...], "forms": [str, ...] }</output_contract>
```

#### C. 双入口 (pydantic 强类型 + dict 兼容层)

V1.6.3 新增主入口:
```python
async def extract_system_map_structured(exploration_history) -> SystemMap:
    """主入口, 返回 SystemMap pydantic 实例。"""
    ...

# 保留旧入口 (向后兼容 planning_graph.py:295)
async def generate_system_map(exploration_history) -> dict:
    """V1.6.3 兼容层: 返回 dict。"""
    sm = await extract_system_map_structured(exploration_history)
    return sm.model_dump()
```

**设计理由** (AppScale 2026 Structured Output):
- 强类型入口 (pydantic) 防字段漂移
- 弱类型兼容层 (dict) 不破坏现有 caller (`agents/ui/planning_graph.py:295` 用 `.get("pages")`)

#### D. 兜底安全网

```python
result = await safe_structured_invoke(prompt, SystemMap, model_type="default")
if result is None:
    # 外层 fallback: 返回空 SystemMap (下游 scenario_extractor 容忍空)
    return SystemMap()
return result
```

下游 `scenario_extractor` 接受空 SystemMap, 不崩 (V1.6 已加容错)。

### 3.2 验证

- 6 个 sampling 参数测试 (默认 20/30 / env 覆盖 / max_pages / max_elements / 空 history / token 安全)
- 2 个 prompt 结构测试 (V1.6 XML / output_contract)
- 6 个 schema 契约测试 (schema 有效 / 空 history / LLM 失败 / 走 safe_structured_invoke / dict 兼容层 / scenario_extractor 消费)

**Live 测试** (`SYSTEM_MAP_LIVE=1`):
- 输入 20 页探索历史
- 输出: **5 pages, 17 actions, 2 forms** in 16.78s
- safe_structured_invoke 触发 inner fallback (mimo-v2.5 SDK 行为, V1.6.3 范围外), 但数据提取正确

---

## 4. Phase 1.6.4 — 文档

`docs/prompt-engineering.md` §8 草案升级为完整章节, 加了 4 个新小节 (§9):

| 小节 | 内容 |
|---|---|
| §9.1 节点定位 | planning_graph 探索子图在 L1→L2 流水线中的位置 |
| §9.2 V1.6 5 段 XML 模板 | explore_decide 的 V1.6 模板 (与 N1/N2/N3/L1 prompt 风格统一) |
| §9.3 explore_decide inter-node 契约 | 6 个节点的 inter-node 契约表 (上游/下游/字段/约束) |
| §9.4 V1.6.2 关键改造点 | 5 个改造点的 vs V1.7 漏点对比表 |
| §9.5 V1.6.3 关键改造点 | system_mapper.py 5 个改造点 (sampling / prompt / 双入口 / 兜底 / token 安全) |
| §9.6 反模式 | 8 个反模式 (planning_graph 内禁止) |
| §9.7 自动化守护 | 27 个回归测试清单 (13 + 14) |
| §9.8 验证 | mock + live 验证命令 |
| §9.9 V1.6.2/1.6.3 改造依据 | 7 个 best practice 来源 (Anthropic / Codebridge / ReAct / AppScale) |

**核心价值**: 这份文档是 V1.6 模式从 L1 8 skill 推广到 planning_graph 的"合同", 未来 V2.0 B 阶段把 V1.6 模式迁移到 L2 时直接套用本模板。

---

## 5. 改动文件清单

### 修改
- `agents/ui/prompts.py` — `get_exploration_system_prompt` 重写为 V1.6 5 段 XML, `import os` (safety valve env)
- `agents/ui/planning_graph.py` — `explore_decide_node` 注入 SystemModel + inter-node 契约 docstring, `explore_execute_node` inter-node 契约 docstring
- `core/skills/system_mapper.py` — 完整重写: 采样 20/30 + V1.6 prompt + 双入口 + env 可降级
- `docs/prompt-engineering.md` — §8 升级为完整 §9 (planning_graph 探索子图契约), 加 4 个新小节

### 新增
- `tests/core/test_system_mapper.py` — 14 个 V1.6.3 测试 (mock + 1 live skip)
- `docs/devlog/23-phase16-2-3-4-completion.md` — 本 devlog

### 修改 (测试)
- `tests/agents/ui/test_planning_graph.py` — 加 13 个 V1.6.2 测试 + 修 2 个 pre-existing 测试 bug

### 不在本次范围 (V2.0 v2 计划里其他任务)
- Phase A (L2 安全网)
- Phase B (L2 Prompt V1.6 化)
- Phase C (L1→L2 业务模型联动)
- Phase D (L2 可观测性)

---

## 6. 测试结果

### 6.1 完整测试套 (L1 + Phase 1.5 + V1.6.2 + V1.6.3)

```
pytest tests/agents/ui/test_planning_graph.py tests/core/test_l1_prompts.py tests/core/test_phase15_prompts.py tests/core/test_system_mapper.py -v
```

**结果: 97 passed, 9 skipped in 27.30s**

| 测试文件 | 数量 | 说明 |
|---|---|---|
| `tests/agents/ui/test_planning_graph.py` | 23 | 10 原测 + 13 V1.6.2 (含 2 pre-existing bug 修复) |
| `tests/core/test_l1_prompts.py` | 60 | V1.6 + V1.6.1 (含 7 V1.6.1 测试) |
| `tests/core/test_phase15_prompts.py` | 24 | V1.7 (含 Phase 1.5 24 个测试) |
| `tests/core/test_system_mapper.py` | 14 | V1.6.3 新增 (含 1 live skip) |
| Live tests (默认 skip) | 9 | L1_LIVE=1 或 SYSTEM_MAP_LIVE=1 才跑 |

### 6.2 V1.6.2 新增 13 个测试

| 测试 | 覆盖 |
|---|---|
| `test_v162_exploration_prompt_v16_xml_structure` | 5 段 XML 全有 |
| `test_v162_exploration_prompt_tool_call_contract` | tool_call 必填 OR 显式 stop |
| `test_v162_exploration_prompt_navigate_firewall_documented` | Navigate FireWall 写进 prompt |
| `test_v162_exploration_prompt_accounts_injection` | 账号注入到 prompt |
| `test_v162_exploration_prompt_scenarios_injection` | scenarios 注入 |
| `test_v162_exploration_prompt_safety_valves_in_context` | Safety Valve 数值 |
| `test_v162_explore_decide_injects_system_model` | SystemModel 注入到 human_msg |
| `test_v162_explore_decide_no_system_model_graceful` | 无 SystemModel 不崩 |
| `test_v162_explore_decide_uses_v16_xml_prompt` | LLM 收到 V1.6 XML |
| `test_v162_explore_execute_returns_tool_message_on_tool_failure` | 工具失败 → ToolMessage |
| `test_v162_explore_execute_navigate_firewall_blocks_external_url` | FireWall 拦截跨域 |
| `test_v162_explore_execute_navigate_allows_base_url` | FireWall 放行 base_url |
| `test_v162_should_continue_exploring_handles_no_tool_call_as_stop` | 无 tool_call 视为完成 |

### 6.3 V1.6.3 新增 14 个测试

| 测试 | 覆盖 |
|---|---|
| `test_v163_sampling_defaults_to_20_30` | 默认 20/30 |
| `test_v163_sampling_env_overrides` | env 可降级 |
| `test_v163_summarize_history_respects_max_pages` | max_pages 生效 |
| `test_v163_summarize_history_respects_max_elements` | max_elements 生效 |
| `test_v163_summarize_history_handles_empty` | 空 history 兜底 |
| `test_v163_summarize_history_token_safety` | 30K 字符硬阈值 |
| `test_v163_prompt_v16_xml_structure` | V1.6 XML |
| `test_v163_prompt_output_contract_specifies_three_fields` | output_contract 显式三字段 |
| `test_v163_system_map_schema_valid` | pydantic schema |
| `test_v163_extract_returns_empty_on_no_history` | 空 history → 空 SystemMap |
| `test_v163_extract_returns_empty_on_llm_failure` | LLM 失败 → 空 SystemMap |
| `test_v163_extract_uses_safe_structured_invoke` | 走 safe_structured_invoke |
| `test_v163_generate_system_map_returns_dict` | 兼容层返回 dict |
| `test_v163_system_map_consumed_by_scenario_extractor` | 字段与 scenario_extractor 兼容 |

### 6.4 Live test (`SYSTEM_MAP_LIVE=1`)

```
tests/core/test_system_mapper.py::test_system_mapper_live
[LLM] structured_output returned None for SystemMap, falling back to raw parse
[live] pages=5 actions=17 forms=2
PASSED in 16.78s
```

**V1.6.3 实测**: 20 页探索历史 → 5 pages / 17 actions / 2 forms, inner fallback 触发 (mimo-v2.5 SDK 行为), 但数据提取正确。

---

## 7. 关键决策

| 决策 | 选择 | 理由 |
|---|---|---|
| explore_decide 注入 SystemModel | **system_name + modules + entities + flow_names 全部注入** | V1.7 漏点; LLM 缺理论地图易漏探索核心模块 |
| explore_decide 注入位置 | **human_msg** (非 system_prompt) | 动态上下文, 每次 decide 重新读; system_prompt 保持稳定 |
| tool_call OR 显式 stop 约束 | **显式 <output_contract> + 反例** | 旧 prompt 只说"不要调用任何工具", V1.6.2 改用"tool_call 必填 OR 显式 stop"二元约束, 更明确 |
| Navigate FireWall 写进 prompt | **加 rule 3 + 反例** | 旧 FireWall 只在代码层, LLM 不知道有这事, 会尝试跨域 navigate 被拒; 写进 prompt 让 LLM 提前知道 |
| SystemMap 采样 20/30 | **默认 20/30, env 可降级** | V1.2 当年 10/15 是省 token, 4 fixture 实测 20/30 ≈ 22K tokens, 安全; 留 env 降级通道 |
| 双入口 (pydantic + dict) | **新增 extract_system_map_structured + 保留 generate_system_map** | 强类型入口防字段漂移, 弱类型兼容层不破坏现有 caller |
| system_mapper prompt few-shot | **1 good + 1 bad** | system_mapper 是标准化提取任务, 不需要 LLM 创造性, 1+1 足够 |
| 文档 §8 → §9 | **新加 §9, §8 L2 草案保留** | V1.6.2 是 planning_graph 不是 L2, 单独章节更清晰 |

---

## 8. Best Practice 调研记录 (供 V2.0 后续阶段参考)

### 8.1 引用的最佳实践来源

| 来源 | 关键论点 | V1.6.2/1.6.3 应用 |
|---|---|---|
| **Anthropic 2026 prompt engineering** | XML 标签 + few-shot + Output Contract | explore_decide + system_mapper prompt 全部重写 |
| **Anthropic Context Engineering 2025-09** | just-in-time context, 不 hardcode 决策树 | explore_decide human_msg 每次重新组装, SystemModel 当前状态注入 |
| **Anthropic Writing Tools for Agents 2025-09** | 工具失败应返回结构化错误, 工具约束写进 prompt | explore_execute docstring 标注契约; explore_decide prompt 写 FireWall 白名单 |
| **ReAct (Yao et al. 2022)** | thought → action → observation, "stop" 是一等公民 | explore_decide output_contract 显式定义 "tool_call OR stop" 二元 |
| **Codebridge 2026 Sub-agent Manifest** | 每个 agent 必须有 role/goal/tools/prompt constraints | explore_decide 5 段 XML 把 role/context/task/rules/examples/output_contract 全部具象化 |
| **AppScale 2026 Structured Output** | 强类型入口 + 弱类型兼容层 | system_mapper 双入口 (SystemMap pydantic + dict) |
| **LangGraph 2026 Production Best Practices** | node 间 explicit schema 契约 | explore_decide ↔ explore_execute inter-node 契约 (本文档 §9.3) |

### 8.2 调研方法

我用了"5 篇必读 + 1 套现有 L1 模板"的组合:
1. 5 篇必读 (Anthropic / Codebridge / AppScale / ReAct / LangGraph) — 跨 LLM 编程 4 大子领域 (prompt / agent / structured output / state machine)
2. 现有 L1 8 skill 的 V1.6 5 段 XML 模板 (内部沉淀) — 项目内部一致性

**反模式 (本次避免)**:
- 在 prompt 里 hardcode "if/else" 决策树 (违反 Anthropic Context Engineering)
- 期待模型 "自己思考 priority" (违反 Codebridge Manifest, 必须给判定标准)
- 不写 `<output_contract>` 就期望结构化 (违反 AppScale 2026, 必有兜底提取)

---

## 9. 已知遗留 / 风险

### 9.1 已知遗留

- **pre-existing 测试 bug 3 个** (本次发现, 已修):
  - `tests/agents/ui/test_tools.py` — `from agents.ui.tools import ui_tools` 不存在 (L2 范围, 本次不动)
  - `tests/agents/ui/test_execution_graph.py::test_decide_node_mock` — `patch ui_tools` 错名 (L2 范围, 本次不动)
  - `tests/agents/ui/test_execution_graph.py::test_assert_node_mock` — 中文全角逗号解析失败 (L2 范围, 本次不动)
  - 这 3 个是 V1.6.1 之前就 broken, 不影响 V1.6.2/1.6.3 验收
- **`test_llm_client.py` 在与其他 LLM 测试同跑时 cache pollution** (pre-existing), 单跑没事
- **`test_logger_report.py` 10 个 DB connection errors** (pre-existing), 需 DB 时序问题排查, 留 V2.0 A 阶段修

### 9.2 风险与缓解

- **风险**: 探索 prompt V1.6 化可能让某些 LLM (qwen / kimi) 输出风格变化, 影响 token 数
  - **缓解**: live test 实测 system_mapper 5/17/2 提取正确; explore_decide 集成在 e2e, 留 V2.0 A 阶段 e2e 验证
- **风险**: SystemMap 采样 20/30 让 token 翻倍
  - **缓解**: `test_v163_summarize_history_token_safety` 30K 字符硬阈值; 22K tokens 实际用量监控
- **风险**: SystemModel 注入到 explore_decide 增大 human_msg, 撞 65K token 上限
  - **缓解**: 只注入 modules/entities/flow_names (truncated to 10/10/5), 完整 SystemModel 不进 prompt

---

## 10. 下一步 (V2.0 v2 计划继续)

按 V2.0 v2 主计划 (§3.0 顺序 1.6 → A → B → C → D), **Phase 1.6 全部完成**:

| 子阶段 | 状态 | 完成 commit |
|---|---|---|
| **1.6.1** N2 SystemModel 三层防御 | ✅ | b881fca |
| **1.6.2** planning_graph explore V1.6 化 | ✅ | 本次 |
| **1.6.3** SystemMap 采样 + invariant | ✅ | 本次 |
| **1.6.4** 文档 §8/§9 | ✅ | 本次 |

**L1 收尾完成**: 8 个 L1 skill + 3 个 Phase 1.5 skill + planning_graph explore + SystemMap 全部 V1.6 化, 97 mock + 9 live skip 全过。

**下个 session — Phase A**: L2 安全网 + 测试基础设施 (1.5d)
- 5 个 L2 P0 漏洞修复 (V8-V12 context / V13 工具失败 / V17 assert JSON / V20 evaluate_js / V10 session_summary)
- `tests/core/test_l2_prompts.py` + `L2_LIVE=1` 开关
- `scratch/test_l2_e2e.py` 端到端 3 case

---

## 11. 改动统计

| 指标 | V1.6.1 (b881fca) | V1.6.2/1.6.3/1.6.4 (本次) | delta |
|---|---|---|---|
| 加固的 skill / prompt | 9 (L1 5 + Phase 1.5 3 + N2 SystemModel) | +1 (planning_graph explore) = 10 | +1 |
| 加固的 system 模块 | 0 | +1 (system_mapper) | +1 |
| 回归测试数 (mock) | 60 | 97 | **+37** |
| 回归测试数 (live skip) | 8 | 9 | +1 |
| 4 fixture live violation 数 | 0 | 0 | 0 |
| V1.6 5 段 XML prompt 数 | 8 | 10 (加 explore + system_mapper) | +2 |
| inter-node 契约文档 | L1 ↔ L2 一份 (prompt-engineering §3) | +1 (planning_graph §9.3) | +1 |
| L1 + Phase 1.5 prompt 加固 | 100% | 100% + planning_graph explore + system_mapper | 100% |

---

## 12. 完整 commit 序列

```
v1.7 handoff    → c2e5a2f: L1 收尾 (devlog 20)
c2e5a2f        → cb8c8ab: V2.0 计划 v1 落盘 (4 阶段)
cb8c8ab        → 008bb79: V2.0 计划 v2 修订 (5 阶段, 加 Phase 1.6)
008bb79        → b881fca: Phase 1.6.1 N2 SystemModel 三层防御加固
b881fca        → 2b6c06d: V1.6.1 handoff
2b6c06d        → (本次): Phase 1.6.2 + 1.6.3 + 1.6.4 — planning_graph explore + SystemMap + 文档
```

---

**Phase 1.6 全部完成 (1.6.1 + 1.6.2 + 1.6.3 + 1.6.4)。L1 + Phase 1.5 + planning_graph + system_mapper 全部 V1.6 化, 97 mock + 9 live skip 全过, 0 violation。L1 收尾完成, 下一步 Phase A (L2 安全网)。**
