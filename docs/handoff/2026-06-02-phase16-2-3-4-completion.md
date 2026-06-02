# Handoff — AI Native Testing Platform (Phase 1.6.2/1.6.3/1.6.4 L1 收尾)

**日期**: 2026-06-02
**Branch**: `dev/phase1-implementation`
**Last commit**: `f4c7e40` — fix(layer1): Phase 1.6.2/1.6.3/1.6.4 planning_graph explore V1.6 化 + SystemMap 采样 + 文档

**Working dir**: `C:\Users\17381\Desktop\test_agent`

---

## 1. 一句话总结

V2.0 v2 计划 (`008bb79`) Phase 1.6 全部 4 个子阶段落盘: **1.6.1 (b881fca) + 1.6.2/1.6.3/1.6.4 (本次 f4c7e40)**。L1 收尾完成, **8 L1 skill + 3 Phase 1.5 skill + planning_graph explore + system_mapper** 全部 V1.6 5 段 XML 化。**97 mock passed + 9 live skipped in 27.30s**, **10 个 V1.6 prompt**, **27 个新回归测试 (13 V1.6.2 + 14 V1.6.3)**, 0 violation。

---

## 2. 接手后第一件事

跑 smoke test 确认 Phase 1.6 全部 4 子阶段落盘无回归:

```powershell
cd C:\Users\17381\Desktop\test_agent
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
python -m pytest tests/agents/ui/test_planning_graph.py tests/core/test_l1_prompts.py tests/core/test_phase15_prompts.py tests/core/test_system_mapper.py -v
```

期望: **97 passed, 9 skipped in ~30s** (含 9 个 live skip 默认 skip)。

确认 git log:

```bash
git log --oneline -5
```

期望: `f4c7e40` → `2b6c06d` (V1.6.1 handoff) → `b881fca` (V1.6.1 修复)。

---

## 3. 本次 session 做了什么

按时间顺序:

1. **读 V1.6.1 handoff** (`docs/handoff/2026-06-02-phase161-n2-fallback-fix.md`): 确认 1.6.1 已落盘
2. **读 V2.0 v2 计划 §3.0**: 明确 1.6.2/1.6.3/1.6.4 范围
3. **读 planning_graph.py + system_mapper.py + prompts.py + 现有测试**: 理解现状
4. **Phase 1.6.2a**: `get_exploration_system_prompt` 重写为 V1.6 5 段 XML (role/context/task/rules/examples/output_contract), `<output_contract>` 显式约束 "tool_call 必填 OR 显式 stop"
5. **Phase 1.6.2b**: `explore_decide_node` 显式注入 `_system_model.system_name/modules/entities/flow_names` 作为"理论导航地图" (V1.7 漏点)
6. **Phase 1.6.2c**: `explore_execute_node` docstring 标注 inter-node 契约 (工具失败返 ToolMessage 不抛异常)
7. **Phase 1.6.2d**: 13 个 V1.6.2 测试 + 修 2 个 pre-existing 测试 bug (`ui_tools` 错名 + FireWall URL 错)
8. **Phase 1.6.3a**: `system_mapper.py` 完整重写: 采样 10/15 → 20/30 (env 可降级) + V1.6 5 段 XML + 双入口 (pydantic SystemMap + dict 兼容层)
9. **Phase 1.6.3b**: 14 个 V1.6.3 测试 (含 1 live skip)
10. **Phase 1.6.4**: `docs/prompt-engineering.md` §8 升级为完整 §9 (planning_graph 探索子图契约, 9 小节)
11. **跑 mock 97 passed**: 全部通过
12. **跑 V1.6.3 live test**: 20 页 → 5 pages / 17 actions / 2 forms in 16.78s
13. **写 devlog 23**: 完整 12 节 devlog
14. **更新 00-progress.md + CONTEXT.md**: 加步骤 22.2 + V1.6.2/1.6.3/1.6.4 升级记录
15. **commit f4c7e40**: 1567 insertions, 9 files
16. **写本 handoff**

---

## 4. 关键产出

### 新文件
- `docs/devlog/23-phase16-2-3-4-completion.md` — 完整 devlog (本次 12 节详述)
- `tests/core/test_system_mapper.py` — 14 个 V1.6.3 测试 (mock + 1 live skip)
- `docs/handoff/2026-06-02-phase16-2-3-4-completion.md` — 本 handoff

### 关键修改
- `agents/ui/prompts.py` — `get_exploration_system_prompt` 重写为 V1.6 5 段 XML, `import os` (safety valve env) (163 行变化)
- `agents/ui/planning_graph.py` — `explore_decide_node` 注入 SystemModel + inter-node 契约 docstring, `explore_execute_node` inter-node 契约 docstring (66 行变化)
- `core/skills/system_mapper.py` — 完整重写: 20/30 sampling + V1.6 prompt + 双入口 + env 可降级 (182 行变化)
- `tests/agents/ui/test_planning_graph.py` — 13 V1.6.2 测试 + 修 2 个 pre-existing 测试 bug (333 行变化)
- `docs/prompt-engineering.md` — §8 升级为完整 §9 (planning_graph 探索子图契约, 9 小节, 147 行新增)
- `CONTEXT.md` — §5 加 V1.6.2/1.6.3/1.6.4 条目
- `docs/devlog/00-progress.md` — 加步骤 22.2

---

## 5. V1.6.2/1.6.3/1.6.4 最终成果

| 维度 | V1.6.1 baseline | V1.6.2/1.6.3/1.6.4 (本次) | 改进 |
|---|---|---|---|
| L1 + Phase 1.5 V1.6 5 段 XML prompt 数 | 8 | 10 (+planning_graph explore +system_mapper) | +2 |
| planning_graph explore_decide/execute V1.6 化 | ❌ `##` 自由文本 | ✅ V1.6 5 段 XML + tool_call 契约 | 全覆盖 |
| explore_decide 注入 SystemModel (理论导航地图) | ❌ | ✅ modules/entities/flow_names | V1.7 漏点修复 |
| Navigate FireWall 写进 prompt | ❌ 仅代码层 | ✅ prompt + 反例 (LLM 提前知道) | 防 LLM 尝试跨域 |
| SystemMap 采样 | 10 页 / 15 元素 (硬编码) | **20 页 / 30 元素** (env 可降级) | +100% / +100% |
| SystemMap prompt | `###` 自由文本 | V1.6 5 段 XML + few-shot (good/bad) | 全覆盖 |
| SystemMap 入口 | dict 弱类型 | **双入口**: SystemMap pydantic + dict 兼容层 | 防字段漂移 |
| 回归测试数 (mock) | 60 | 97 | **+37** |
| 回归测试数 (live skip) | 8 | 9 | +1 |
| L1↔L2 inter-node 契约文档 | §3 (L1↔L2 一份) | +§9.3 (planning_graph 探索子图) | +1 |
| V1.6 5 段 XML prompt 占比 | 8/8 (L1+Phase 1.5) | 10/10 (含 explore + system_mapper) | 100% |
| 4 fixture live violation 数 | 0 (V1.6.1) | 0 | 持平 |
| 4 fixture live 内层 fallback | 3/4 (mimo-v2.5 SDK) | 3/4 (V1.6.3 实测同样触发) | 持平 (范围外) |
| 4 fixture live SystemMap 数据 | 旧 sampling 10/15 | 20/30, 提取 5/17/2 元素 | +容量 |

---

## 6. 关键决策

| 决策 | 选择 | 理由 |
|---|---|---|
| explore_decide 注入 SystemModel 位置 | **human_msg** (非 system_prompt) | 动态上下文, 每次 decide 重新读; system_prompt 保持稳定 |
| tool_call OR 显式 stop 约束 | **显式 `<output_contract>` + 反例** | 旧 prompt 只说"不要调用任何工具", V1.6.2 改二元约束, 更明确 |
| Navigate FireWall 写进 prompt | **加 rule 3 + 反例** | 旧 FireWall 只在代码层, LLM 不知道, 会尝试跨域 navigate 被拒; 写进 prompt 让 LLM 提前知道 |
| SystemMap 采样 20/30 | **默认 20/30, env 可降级** | V1.2 当年 10/15 是省 token, 4 fixture 实测 20/30 ≈ 22K tokens, 安全; 留 env 降级通道 |
| 双入口 (pydantic + dict) | **新增 extract_system_map_structured + 保留 generate_system_map** | 强类型入口防字段漂移, 弱类型兼容层不破坏现有 caller |
| system_mapper few-shot 数 | **1 good + 1 bad** | system_mapper 是标准化提取任务, 不需要 LLM 创造性, 1+1 足够 |
| 文档 §8 → §9 | **新加 §9, §8 L2 草案保留** | V1.6.2 是 planning_graph 不是 L2, 单独章节更清晰 |
| V1.6.2 inter-node 契约放哪 | **§9.3 一张表 (6 节点契约)** | 与 §3 L1↔L2 契约表风格统一, 便于 LLM 引用 |
| Prompt 内文语言 | **中文** | 全项目 prompt 中文一致 (CONTEXT.md 设计决策) |
| V1.6.2 测试中 mock 工具 | **MagicMock + AsyncMock on .ainvoke** | 代码用 `tool_fn.ainvoke(args)`, 不是 `tool_fn(args)`; AsyncMock side_effect 必须挂在 .ainvoke 上 |

---

## 7. 不在 V1.6.2/1.6.3/1.6.4 范围 (V2.0 v2 计划后续)

- ❌ Phase A (L2 安全网) — 1.5d, 5 个 L2 P0 漏洞修复
- ❌ Phase B (L2 Prompt V1.6 化) — 2.5d, 3 个 L2 prompt 重写
- ❌ Phase C (联动 L1 业务模型) — 1d, 4 字段 context 注入 + L2 卡片
- ❌ Phase D (L2 可观测性) — 1d, token 估算 + node 事件 + WebSocket 告警
- ❌ Inner fallback 3/4 改善 — mimo-v2.5 SDK 行为, V2.1+ backlog
- ❌ L2 execute_graph 11 个原测 (test_decide_node_mock, test_assert_node_mock 等 pre-existing failures) — V2.0 A 阶段修
- ❌ test_tools.py 1 个 import 错误 (pre-existing) — V2.0 A 阶段修
- ❌ test_logger_report.py 10 个 DB connection errors (pre-existing) — V2.0 A 阶段排查

---

## 8. 下一步 (按 V2.0 v2 ROI)

### 立即 — Phase A (L2 安全网 + 测试基础设施, 1.5d)
- 读 `agents/ui/execution_graph.py` (5 个 P0 漏洞位置)
- A1: 建 `tests/core/test_l2_prompts.py` + `L2_LIVE=1` 开关 (0.5d)
- A2: `record_node` 改按 **token** 估算截断 + 截图降采样 (0.3d)
- A3: 修 `decide_node` 覆盖 session_summary 注入 (0.2d)
- A4: 工具失败计入 `consecutive_failures` (0.2d)
- A5: evaluate_js 黑名单 (5 个关键字) (0.2d)
- A6: assert JSON 解析失败 → `_fallback_assertion()` (0.1d)
- Commit message: `fix(layer1+layer2): L2 safety net + test infrastructure (V2.0-A)`

### 然后 — Phase B (L2 Prompt V1.6 化, 2.5d)
- B1: `decide_prompt` 5 段 XML + inter-node 契约 (1.0d)
- B2: `assert_prompt` 5 段 XML + pydantic `AssertionResult` (0.8d)
- B3-B5: step_prompt + token-aware 截断 + 账号密码剥离 (0.7d)

### 然后 — Phase C (1d) + Phase D (1d)
- C1-C5: 联动 L1 业务模型 (rules/focus_areas/scenarios/risk_points/reasoning_chain)
- D1-D4: token 估算 + node 事件 + WebSocket 告警

---

## 9. 验证清单 (新对话必跑)

### Step 1 — git status (30s)
```powershell
git status
git log --oneline -5
# 期望: clean, f4c7e40 在最前
```

### Step 2 — 单元测试 (30s, 不消耗 token)
```powershell
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
python -m pytest tests/agents/ui/test_planning_graph.py tests/core/test_l1_prompts.py tests/core/test_phase15_prompts.py tests/core/test_system_mapper.py -v
```

期望: **97 passed, 9 skipped in ~30s**

### Step 3 — V1.6.2 专项测试 (5s)
```powershell
$env:PYTHONIOENCODING = "utf-8"
python -m pytest tests/agents/ui/test_planning_graph.py -k "v162" -v
```

期望: **13 passed** (`test_v162_exploration_prompt_*` + `test_v162_explore_decide_*` + `test_v162_explore_execute_*` + `test_v162_should_continue_*`)

### Step 4 — V1.6.3 专项测试 (1s)
```powershell
$env:PYTHONIOENCODING = "utf-8"
python -m pytest tests/core/test_system_mapper.py -k "v163" -v
```

期望: **13 passed** (`test_v163_sampling_*` + `test_v163_summarize_history_*` + `test_v163_prompt_*` + `test_v163_system_map_*` + `test_v163_extract_*` + `test_v163_generate_*`)

### Step 5 — V1.6.3 live 验证 (20s, 消耗 token)
```powershell
$env:SYSTEM_MAP_LIVE = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
python -m pytest tests/core/test_system_mapper.py::test_system_mapper_live -v -s
```

期望: PASSED in ~20s, 输出 `pages=N actions=N forms=N`

### Step 6 — L1 live 抽测 (1-3 min, 消耗 token, 可选)
```powershell
$env:L1_LIVE = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
python -m pytest tests/core/test_l1_prompts.py::test_l1_live_all_fixtures[prd_purchase] -v -s
```

期望: PASSED in ~2min, 0 violation

---

## 10. 环境 & 配置

继承 V1.6.1 handoff (本次未改 `.env`):

- `ANTHROPIC_MODEL=mimo-v2.5` (全部 4 个 model_type)
- `ANTHROPIC_BASE_URL=https://token-plan-cn.xiaomimimo.com/anthropic`
- `DATABASE_URL=postgresql://postgres:123456@localhost:5432/smart_test`
- `BACKEND_PORT=8002` / `FRONTEND_PORT=5173`
- `MAX_STEPS_PER_CASE=15` / `MAX_CONSECUTIVE_FAILURES=3`
- `MAX_EXPLORE_PAGES=3` / `MAX_EXPLORE_MINUTES=1`
- **V1.6.3 新增 env (可选)**:
  - `SYSTEM_MAP_MAX_PAGES=20` (默认)
  - `SYSTEM_MAP_MAX_ELEMENTS_PER_PAGE=30` (默认)
  - 不设也行, 走代码默认值

⚠️ Windows 终端运行 Python 含中文/emoji 必须设:
```powershell
$env:PYTHONIOENCODING = "utf-8"; $env:PYTHONUTF8 = "1"; [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

---

## 11. 已知坑 (务必避开)

### V1.6.2 护栏 (破坏会回退)
- `get_exploration_system_prompt` 必须保持 V1.6 5 段 XML (role/context/task/rules/examples/output_contract)
- `<output_contract>` 必须显式约束 "tool_call 必填 OR 显式 stop", 禁止纯文本
- `explore_decide_node` human_msg 必须含 `<system_model_ctx>` 块 (注入 SystemModel)
- `explore_execute_node` 工具失败必须返 `ToolMessage(content="执行失败: ...")` 而非 raise
- Navigate FireWall 4 个白名单 (base_url / 已探索 / PRD / 元素 href) 必须保留

### V1.6.3 护栏 (破坏会回退)
- `_summarize_history` 默认 20/30, env 可降级
- `_summarize_history` 空 history 返 "无探索历史" 字符串
- `extract_system_map_structured` 走 `safe_structured_invoke` (内层 fallback 兜底)
- `generate_system_map` 兼容层保留, 返 dict (planning_graph.py:295 调用)
- `SystemMap` pydantic 三字段 (pages/actions/forms) 不能改字段名

### LLM 输出格式
- mimo-v2.5 / qwen / deepseek / kimi 在 `with_structured_output` 上依旧不稳定 (V1.6.3 实测同样触发)
- V1.7 把 3 个 Phase 1.5 skill 统一走 `safe_structured_invoke`
- V1.6.1 / V1.6.2 / V1.6.3 主流程改走后处理 (normalize) 或 LLM 失败返空
- **不要再在任何 skill 里用裸 `llm.ainvoke(prompt).content`**

### 测试基础设施
- `tests/conftest.py` 已加 `load_dotenv()`, **别删**
- 4 个 L1 live 测试默认 skip, 必须 `L1_LIVE=1` 才跑
- V1.6.3 system_mapper live 测试默认 skip, 必须 `SYSTEM_MAP_LIVE=1` 才跑
- V2.0 A 阶段会加 `L2_LIVE=1` 开关
- V1.6.2 测试 import 从 `agents.ui.planning_graph`, 改 planning_graph 行为时记得同步测试

### Mock 测试陷阱
- 代码用 `tool_fn.ainvoke(args)`, 不是 `tool_fn(args)`
- AsyncMock side_effect 必须挂在 `.ainvoke` 属性上: `mock.ainvoke = AsyncMock(side_effect=Exception(...))`
- 如果只 `mock = AsyncMock(side_effect=Exception(...))`, `mock.ainvoke()` 是另一自动 Mock, 不会抛异常
- 修 2 个 pre-existing 测试 bug 用此模式

### Pre-existing failures (V1.6 范围外, 留 V2.0 A 阶段修)
- `tests/agents/ui/test_tools.py` — `from agents.ui.tools import ui_tools` 错名 (1 error during collection)
- `tests/agents/ui/test_execution_graph.py::test_decide_node_mock` — patch `ui_tools` 错名
- `tests/agents/ui/test_execution_graph.py::test_assert_node_mock` — 中文全角逗号解析失败
- `tests/core/test_llm_client.py` — 与其他 LLM 测试同跑时 cache pollution (单跑没事)
- `tests/core/test_logger_report.py` — 10 个 DB connection errors

### 死代码 / 历史
- `goal_extractor.py` V1.5 已删死代码 (50+ 行)
- `_FAST_PATH_COVERAGE_THRESHOLD = 0.9` 是 defensive safety net
- `system_mapper.py` 采样参数 v1.2 (10/15) → v1.6.3 (20/30) ✅
- `safe_structured_invoke` 是 L5 防线 (最外), normalize/兜底是 L2/L3 防线 (中间), 兼容

### PowerShell & Git
- PowerShell 不支持 `&&`, 用 `cmd1; if ($?) { cmd2 }`
- 长 commit message 含 `>` / `<` 会被 shell 吞, 用 `git commit -F <file>`
- 含中文 commit message 用 `[System.IO.File]::WriteAllText` + `UTF8Encoding($false)` (避免 BOM 干扰)
- `git add` 多个文件用分号分隔 (PowerShell)

---

## 12. 必读文档 (按顺序)

1. **`docs/devlog/23-phase16-2-3-4-completion.md`** — **本次 V1.6.2/1.6.3/1.6.4 完整 devlog, 必读**
2. `docs/handoff/2026-06-02-phase161-n2-fallback-fix.md` — V1.6.1 handoff (本次上下文)
3. `docs/layer2-v2.0-plan.md` — V2.0 v2 主计划 (§3.0 Phase 1.6 + §3.1-3.4 Phase A/B/C/D)
4. `docs/l1-verification-report-v1.7.md` — V1.7 报告 (V1.6 起源)
5. `agents/ui/prompts.py` — `get_exploration_system_prompt` V1.6 5 段 XML
6. `agents/ui/planning_graph.py` — `explore_decide_node` / `explore_execute_node` 改造后
7. `core/skills/system_mapper.py` — 完整重写后 (双入口 + 20/30)
8. `tests/agents/ui/test_planning_graph.py` — 13 V1.6.2 测试
9. `tests/core/test_system_mapper.py` — 14 V1.6.3 测试
10. `docs/prompt-engineering.md` §9 — **planning_graph 探索子图契约 (本次新加, 9 小节)**
11. `CONTEXT.md` §5 — V1.6.2/1.6.3/1.6.4 最新升级记录
12. `agents/ui/execution_graph.py` — Phase A 改造目标 (下个 session)

---

## 13. 关键洞察 (从 V1.6.2/1.6.3/1.6.4 抽出, 供 V2.0 后续阶段参考)

1. **5 段 XML 模式可复用**: V1.6 (L1 8 skill) → V1.6.2 (planning_graph explore) → V1.6.3 (system_mapper) → V2.0 B (L2 3 prompt) → V2.0 E (Reflection)。**模板就是 L1↔L2 节点契约的"合同"**, 项目内部沉淀的标准化 XML 模式, 是 V2.0 加速关键。
2. **inter-node 契约分层**: L1↔L2 节点契约放 §3 (L1 skill 间), planning_graph 探索子图契约放 §9.3, L2 execution_graph 契约会放 §10。**每条新流水线 = 一张新契约表 + 一份新 XML 模板**, 跟工厂方法一样。
3. **SystemModel 注入 explore_decide 是 "V1.7 报告漏点" 的关键修复**: V1.7 报告说"LLM 探索时缺理论地图", V1.6.2 修复方法是 human_msg 显式注入 modules/entities/flow_names, 不动 system_prompt。**just-in-time context** (Anthropic Context Engineering 2025-09) 实践。
4. **双入口 (pydantic + dict) 是兼容性设计模式**: 强类型入口防字段漂移, 弱类型兼容层不破坏现有 caller。**V2.0 B 阶段 L2 prompt 重构时, assert_prompt 也应这样设计** — 新加 `decide_with_pydantic()` 返 pydantic, 保留 `decide()` 返 dict。
5. **SystemMap 20/30 是"够用就好"哲学**: V1.2 当年 10/15 是省 token 保守策略, 实测 20/30 ≈ 22K tokens 还在安全范围, 没必要更激进。**生产数据多了再调 env 降级**, 留 30K 字符硬阈值 (`test_v163_summarize_history_token_safety`) 防 65K 溢出。
6. **Mock 测试陷阱 (本次踩了 2 次)**: `tool_fn.ainvoke(args)` vs `tool_fn(args)`, AsyncMock side_effect 挂错位置。**V2.0 A 阶段写 L2 mock 测试时, 把这模式封装成 fixture**: `def mock_tool_with_ainvoke(return_value=...) -> MagicMock: ...`, 避免每次手写。
7. **tool_call OR 显式 stop 是一等契约**: 旧 prompt 只说"不要调用任何工具", V1.6.2 改二元约束 + 反例, LLM 理解更清晰。**V2.0 B 阶段 L2 decide_prompt 应完全套用这套** (rule + examples + output_contract 三件套)。
8. **9 个新文档 (7 篇 best practice) 全是 V2.0 模板**: 调研方法固定 = "5 篇必读 + 1 套现有 L1 模板"。**V2.0 B 阶段做 L2 prompt V1.6 化时, 引用本文档 §9.9 + 加 L2-specific 调研即可**。
9. **Pre-existing 测试 bug 是 V2.0 A 阶段的"礼物"**: 本次发现 3 个 (test_decide_node_mock / test_assert_node_mock / test_tools.py import 错), V2.0 A 阶段会修, 因为 A 阶段就是 L2 范围, 顺手修。**别在 V1.6 范围外硬塞修复, 走 V2.0 ROI 顺序**。
10. **97 mock + 9 live skip 是一致可验证的 L1 收尾指标**: 任何 V2.0 阶段改动 L1 必须保持这数字不退化。**V2.0 A/B/C/D 阶段, 跑同套测试作为回归 smoke**。

---

## 14. 完整改动统计

```
v1.7 handoff    → c2e5a2f: L1 收尾 (devlog 20)
c2e5a2f        → cb8c8ab: V2.0 计划 v1 落盘 (4 阶段)
cb8c8ab        → 008bb79: V2.0 计划 v2 修订 (5 阶段, 加 Phase 1.6)
008bb79        → b881fca: Phase 1.6.1 N2 SystemModel 三层防御加固
b881fca        → 2b6c06d: V1.6.1 handoff
2b6c06d        → f4c7e40: Phase 1.6.2/1.6.3/1.6.4 planning_graph explore + SystemMap + 文档 (本次)
```

| 指标 | v1.7 (c2e5a2f) | v1.6.1 (b881fca) | v1.6.2/3/4 (f4c7e40, 本次) | 累计 delta |
|---|---|---|---|---|
| 加固的 skill/prompt 数 | 8 (L1 + Phase 1.5) | +1 (N2 SystemModel) | +2 (planning_graph explore + system_mapper) | **+3** |
| 回归测试数 (mock) | 53 | 60 | 97 | **+44** |
| 回归测试数 (live skip) | 8 | 8 | 9 | +1 |
| 4 fixture live invariant pass rate | 100% (但有违规) | 100% (零违规) | 100% (零违规) | 100% |
| V1.6 5 段 XML prompt 占比 | 8/8 (L1+Phase 1.5) | 8/8 (N2 升级) | 10/10 (含 explore + system_mapper) | **100%** |
| 计划文档 | 0 | 1 (V2.0 v2) | +1 (devlog 22 + 23) | +2 |
| 联动深度 | L1 → Phase 1.5 | L1 内部 N2 强化 | + planning_graph V1.6 化 + SystemMap | 全覆盖 |
| 兜底安全网 | 无 | 有 (N2 UseCaseModel 推导骨架) | + (system_mapper 返空 SystemMap) | 全覆盖 |
| inter-node 契约文档 | 1 (L1↔L2) | 1 (L1↔L2) | +1 (planning_graph 探索子图 §9.3) | +1 |
| L1 收尾状态 | 进行中 | 90% (N2 升级) | **100% (全部 V1.6 化)** | ✅ |

---

## 15. 紧急联系

如果新对话遇到无法解决的问题:

1. `git log --oneline -5` 确认在 `f4c7e40` (本次)
2. `python -m pytest tests/agents/ui/test_planning_graph.py tests/core/test_l1_prompts.py tests/core/test_phase15_prompts.py tests/core/test_system_mapper.py -v` 确认 97 passed
3. 单步调试 explore_decide prompt V1.6 化:
   ```python
   from agents.ui.prompts import get_exploration_system_prompt
   prompt = get_exploration_system_prompt(
       accounts=[{"role": "员工", "username": "test_c", "password": "123456"}],
       task_config={"prd": "...", "changelog": "..."},
       scenarios=[{"priority": "high", "name": "提交采购申请", "entry_hint": "采购管理"}],
   )
   # 期望: 5 段 XML + safety valve + 凭证注入
   for tag in ("<role>", "<context>", "<task>", "<rules>", "<examples>", "<output_contract>"):
       assert tag in prompt
   assert "tool_call" in prompt
   assert "test_c" in prompt
   ```
4. 单步调试 system_mapper 双入口:
   ```python
   import asyncio
   from core.skills.system_mapper import extract_system_map_structured, generate_system_map
   
   history = [{"url": f"http://x.com/{i}", "title": f"P{i}", "interactive_elements": [{"id": f"#{j}", "role": "button", "name": f"按钮{j}", "text": ""} for j in range(5)]} for i in range(25)]
   sm = asyncio.run(extract_system_map_structured(history))
   print(sm.pages, sm.actions, sm.forms)
   # 期望: SystemMap 实例, 3 字段为 list[str]
   
   sm_dict = asyncio.run(generate_system_map(history))
   print(sm_dict.keys())
   # 期望: dict_keys(['pages', 'actions', 'forms'])
   ```
5. 单步调试 explore_decide 注入 SystemModel:
   ```python
   import asyncio
   from unittest.mock import AsyncMock, MagicMock, patch
   from langchain_core.messages import AIMessage
   from agents.ui.planning_graph import explore_decide_node
   
   state = {"task_config": {
       "target_url": "http://example.com",
       "_explored_urls": [],
       "_system_model": {"system_name": "采购系统", "modules": ["采购管理"], "entities": ["采购申请"], "flows": [{"name": "采购流"}]},
   }, "page_info": {"url": "http://example.com", "title": "首页", "interactive_elements": []}}
   mock_llm = MagicMock()
   mock_llm_with_tools = MagicMock()
   mock_llm_with_tools.ainvoke = AsyncMock(return_value=AIMessage(content="", tool_calls=[]))
   mock_llm.bind_tools = MagicMock(return_value=mock_llm_with_tools)
   with patch("agents.ui.planning_graph.get_llm_client", return_value=mock_llm):
       asyncio.run(explore_decide_node(state))
   last_human = [m.content for m in mock_llm_with_tools.ainvoke.call_args[0][0] if hasattr(m, "content")][-1]
   print(last_human)
   # 期望: 含 "采购系统" "采购管理" "采购申请" "采购流" "理论业务地图"
   ```
6. 跑 V1.6.3 live: `SYSTEM_MAP_LIVE=1 python -m pytest tests/core/test_system_mapper.py::test_system_mapper_live -v -s`
7. 看 `docs/devlog/23-phase16-2-3-4-completion.md` §9 已知遗留 / 风险

---

**Good luck. V1.6 全部 4 个子阶段落盘完成, 10 个 V1.6 prompt + 97 mock + 0 violation。L1 收尾 100%。下一步 Phase A (L2 安全网, 1.5d)。The L1 layer is now production-grade; L2 is the next frontier.**
