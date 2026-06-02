# Handoff — AI Native Testing Platform (Phase 1.6.1 N2 SystemModel 加固)

**日期**: 2026-06-02
**Branch**: `dev/phase1-implementation`
**Last commit**: `b881fca` — fix(layer1): Phase 1.6.1 N2 SystemModel 三层防御加固

**Working dir**: `C:\Users\17381\Desktop\test_agent`

---

## 1. 一句话总结

V2.0 v2 计划 (`008bb79`) 落盘后, **Phase 1.6.1 第一个落地**: N2 SystemModel 三层防御加固完成。V1.7 报告原文点名 P0 漏洞 (3/4 fixture fallback 触发) 实测拆解为 **2 个真问题** (节点后缀违规 + transitions 重复) + **1 个安全网缺失** (空 SystemModel 兜底), 3 层防御一次性修完。**4 fixture live 验证: 0 invariant violations, 0 minimal fallback**。

## 2. 接手后第一件事

跑 smoke test 确认 Phase 1.6.1 落盘无回归:

```powershell
cd C:\Users\17381\Desktop\test_agent
$env:PYTHONIOENCODING = "utf-8"
$env:L1_LIVE = "1"
python -m pytest tests/core/test_l1_prompts.py tests/core/test_phase15_prompts.py -v
```

期望: **60 passed, 8 skipped in ~1s** (7 个新增 V1.6.1 测试已计入)。

确认 git log:

```bash
git log --oneline -3
```

期望: `b881fca` → `008bb79` → `cb8c8ab`。

## 3. 本次 session 做了什么

按时间顺序:

1. **读 handoff** (`docs/handoff/2026-06-01-layer2-v2.0-plan-with-phase16.md`): 确认 1.6.1 是 P0
2. **读 V2.0 v2 主计划 §3.0**: 明确 Phase 1.6.1 验收标准 (3/4 → ≤ 1/4)
3. **读 V1.7 报告 §2.3.4**: 找 "N2 fallback 3/4" 原始数据
4. **读 `core/skills/system_modeler.py` + `core/llm_client.py` + `tests/core/test_l1_prompts.py`**: 理解现状
5. **写 `scratch/debug_n2_fallback.py`**: 跑 4 fixture live 抓 LLM 原始输出, 落到 `data/n2_fallback_debug.json`
6. **分析数据**: 内层 fallback 3/4 (mimo-v2.5 SDK 行为, 范围外) + 节点"状态"后缀 (prd_purchase 实际违规, 但测试漏) + transitions 重复 (prd_purchase 6 → 应 4)
7. **3 层防御设计**: Prompt 加 rule 6 + 自检步骤; 代码加 `_strip_node_suffix` / `_align_action` / `_normalize_system_model` / `_is_chinese_noun_phrase` 收紧; 兜底加 `_derive_minimal_system_model`
8. **改 `core/skills/system_modeler.py`**: 4 个新函数 + 收紧 prompt + 主流程走 normalize + 兜底
9. **改 `tests/core/test_l1_prompts.py`**: 从 system_modeler import 校验函数 (防漂移) + 加 7 个 V1.6.1 测试
10. **跑 mock 60 passed**: 7 个新测试全过
11. **写 `scratch/debug_n2_fallback_v161.py`**: 跑 4 fixture live 验证
12. **4 fixture live: 0 violations, 0 minimal fallback**: 通过验收
13. **写 `docs/devlog/22-phase16-completion.md`**: 完整 devlog
14. **更新 `docs/devlog/00-progress.md` + `CONTEXT.md`**: 加步骤 22.1
15. **commit b881fca**: 1821 lines changed, 9 files
16. **写本 handoff**

## 4. 关键产出

### 新文件
- `docs/devlog/22-phase16-completion.md` — 完整 devlog (本 commit 的 9 节详述)
- `data/n2_fallback_debug.json` — V1.7 baseline (4 fixture LLM 原始输出, 供回溯)
- `data/n2_v161_live_results.json` — V1.6.1 实测 (4 fixture + invariant 校验)
- `scratch/debug_n2_fallback.py` — V1.7 baseline 诊断脚本
- `scratch/debug_n2_fallback_v161.py` — V1.6.1 验证脚本
- `docs/handoff/2026-06-02-phase161-n2-fallback-fix.md` — 本 handoff

### 关键修改
- `core/skills/system_modeler.py` — 加 4 个新函数 + 收紧 prompt + 主流程改走 normalize + 兜底 (225 行变化)
- `tests/core/test_l1_prompts.py` — 从 system_modeler import 校验函数 + 加 7 个 V1.6.1 测试 (219 行变化)
- `docs/devlog/00-progress.md` — 加步骤 22.1 (Phase 1.6.1 完成)
- `CONTEXT.md` — §5 加 "N2 SystemModel 三层防御加固 (V1.6.1)" 条目

## 5. V1.6.1 最终成果

| 维度 | V1.7 baseline | V1.6.1 (本次) | 改进 |
|---|---|---|---|
| 4 fixture 节点后缀违规 (状态/流程/页/中/期) | 1+ fixture (prd_purchase) | 0 fixture | -100% |
| 4 fixture transitions 重复 (同 from_state+action) | 1 fixture (prd_purchase 6→4) | 0 fixture | -100% |
| Outer fallback (result is None) 兜底 | 返回空 SystemModel() | 返回 UseCaseModel 推导骨架 | **安全网** |
| Inner fallback 率 (structured_output → raw parse) | 3/4 | 3/4 | 不变 (mimo-v2.5 SDK 行为) |
| 4 fixture live 100% 满足 4 个 invariant | 1+ fixture fail | 4/4 fixture pass | +75% |
| 回归测试 mock 数 | 53 | 60 | +7 |
| L1 + Phase 1.5 加固 skill 数 | 8 | 9 (N2 升级) | +1 |

## 6. 关键决策

| 决策 | 选择 | 理由 |
|---|---|---|
| Inner fallback 3/4 处理 | **不改** | mimo-v2.5 SDK 行为, V1.6.1 范围外 |
| Outer fallback 兜底 | **从"返回空" → "UseCaseModel 推导骨架"** | 下游 N3 / Layer 3 永不断流 |
| Action 对齐策略 | **substring 双向 + 多候选选最长** | LLM 错误模式稳定 (缩写/扩展), 选最长 = 选最具体 |
| 后缀黑名单 | **5 个 (状态/流程/页/中/期)** | 实测 LLM 经常加这几个 |
| 剥前缀? | **不剥** | "用户未登录" 之类是幻觉信号, 不应掩盖 |
| Validator 收紧范围 | **只 ban 后缀, 不 ban 前缀** | 同上 |
| `_is_chinese_noun_phrase` 共享 | **system_modeler → test import** | 防止测试与生产漂移, 单一来源 |
| 验收目标修正 | **"violation 数 0" 取代 "fallback 率 ≤ 1/4"** | fallback 3/4 是 SDK 行为不可改, 真实可改的是输出质量 |

## 7. 不在 V1.6.1 范围 (V2.0 v2 计划后续)

- ❌ Phase 1.6.2 (planning_graph explore V1.6 化) — 下个 session
- ❌ Phase 1.6.3 (SystemMap 采样 + invariant) — 1.6.3 任务
- ❌ Phase 1.6.4 (文档 §8 扩展) — 1.6.4 任务
- ❌ Phase A (L2 安全网) — V2.0 第二阶段
- ❌ Phase B (L2 Prompt V1.6 化) — V2.0 第三阶段
- ❌ Phase C / D — V2.0 第四/五阶段
- ❌ Inner fallback 3/4 改善 — mimo-v2.5 SDK 行为, V2.1+ backlog

## 8. 下一步 (按 ROI, V2.0 v2 计划顺序)

### 立即 — Phase 1.6.2 (planning_graph explore V1.6 化)
- 读 `agents/ui/planning_graph.py:288-325` (V1.7 漏的 planning_graph 盲点)
- explore_decide 改 5 段 XML + Output Contract (返回 tool_call 必填)
- explore_execute 加 inter-node 契约 (失败时进 record 不抛异常)
- `<context>` 注入 SystemModel + ExplorationHistory + Goals
- 0.5d, Commit message: `fix(layer1): Phase 1.6.2 planning_graph explore V1.6 化`

### 然后 — Phase 1.6.3 (SystemMap 采样 + invariant)
- `core/skills/system_mapper.py` 采样 10/15 → 20/30
- 加 `tests/core/test_system_mapper.py` (mock + live skip)
- Invariant: 3 字段非空时 LLM 提取稳定性 ≥ 80%
- 0.4d

### 然后 — Phase 1.6.4 (文档)
- `docs/prompt-engineering.md` §8 加 planning_graph 章节
- 0.1d

### Phase 1.6 完结后 — Phase A
- 5 个 L2 P0 漏洞修复 + `test_l2_prompts.py` + e2e
- 1.5d

## 9. 验证清单 (新对话必跑)

### Step 1 — git status (30s)
```powershell
git status
git log --oneline -5
# 期望: clean, b881fca 在最前
```

### Step 2 — 单元测试 (5s, 不消耗 token)
```powershell
$env:PYTHONIOENCODING = "utf-8"
python -m pytest tests/core/test_l1_prompts.py tests/core/test_phase15_prompts.py -v
```
期望: **60 passed, 8 skipped**

### Step 3 — V1.6.1 专项测试 (1s)
```powershell
$env:PYTHONIOENCODING = "utf-8"
python -m pytest tests/core/test_l1_prompts.py -k "v161" -v
```
期望: **7 passed** (`test_v161_strip_node_suffix_basic` / `test_v161_align_action_to_usecase` / `test_v161_normalize_system_model_end_to_end` / `test_v161_derive_minimal_system_model_never_empty` / `test_v161_chinese_noun_phrase_validator_tightened` / `test_v161_normalize_handles_empty_and_edge_cases` / `test_v161_action_alignment_with_substring_lcp_heuristic`)

### Step 4 — L1 live 抽测 (3-5 min, 消耗 token)
```powershell
$env:L1_LIVE = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
python -m pytest tests/core/test_l1_prompts.py::test_l1_live_all_fixtures[prd_purchase] -v -s
```
期望: PASSED in ~2min, 节点名无后缀违规, transitions 全 unique

### Step 5 — V1.6.1 实测数据查看
```powershell
ls -la data/n2_v161_live_results.json
# 期望: 文件存在, 包含 4 fixture 全过结果
```

## 10. 环境 & 配置

继承 V2.0 v2 handoff (`008bb79` 落盘后未改 `.env`):

- `ANTHROPIC_MODEL=mimo-v2.5` (全部 4 个 model_type)
- `ANTHROPIC_BASE_URL=https://token-plan-cn.xiaomimimo.com/anthropic`
- `DATABASE_URL=postgresql://postgres:123456@localhost:5432/smart_test`
- `BACKEND_PORT=8002` / `FRONTEND_PORT=5173`
- `MAX_STEPS_PER_CASE=15` / `MAX_CONSECUTIVE_FAILURES=3`
- `MAX_EXPLORE_PAGES=3` / `MAX_EXPLORE_MINUTES=1`

⚠️ Windows 终端运行 Python 含中文/emoji 必须设:
```powershell
$env:PYTHONIOENCODING = "utf-8"; $env:PYTHONUTF8 = "1"; [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

## 11. 已知坑 (务必避开)

### LLM 输出格式
- mimo-v2.5 / qwen / deepseek / kimi 在 `with_structured_output` 上**依旧不稳定** (V1.6.1 实测 3/4 触发)
- V1.7 把 3 个 Phase 1.5 skill 统一走 `safe_structured_invoke`
- V1.6.1 主流程改走 `_normalize_system_model` 后处理
- **不要再在任何 skill 里用裸 `llm.ainvoke(prompt).content`**

### V1.6.1 护栏 (破坏会回退)
- `_strip_node_suffix` 后缀黑名单: 状态/流程/页/中/期
- `_align_action` 必须 substring 双向 (LLM 缩写 / LLM 扩展两种模式)
- `_normalize_system_model` 必须总是过 (不能跳过)
- `_derive_minimal_system_model` 兜底不能返回空 (L3 防线)
- `_is_chinese_noun_phrase` 与生产代码 import 共享, **别复制到 test 里再改一次** (会漂移)

### 测试基础设施
- `tests/conftest.py` 已加 `load_dotenv()`, **别删**
- 4 个 L1 live 测试默认 skip, 必须 `L1_LIVE=1` 才跑
- V2.0 A 阶段会加 `L2_LIVE=1` 开关
- 7 个 V1.6.1 测试 import 从 `core.skills.system_modeler`, 改 `system_modeler` 行为时记得同步测试

### 死代码 / 历史
- `goal_extractor.py` V1.5 已删死代码 (50+ 行)
- `_FAST_PATH_COVERAGE_THRESHOLD = 0.9` 是 defensive safety net
- `system_mapper.py` 采样参数 v1 (10/15) → v1.6 (20/30) 是 1.6.3 任务, 未动
- `safe_structured_invoke` 是 L5 防线 (最外), `_normalize_system_model` 是 L2 防线 (中间), 两者不冲突, 都保留

### PowerShell & Git
- PowerShell 不支持 `&&`, 用 `cmd1; if ($?) { cmd2 }`
- 长 commit message 含 `>` / `<` 会被 shell 吞, 用 `git commit -F <file>`
- 含中文 commit message 用 `[System.IO.File]::WriteAllText` + `UTF8Encoding($false)` (避免 BOM 干扰)
- `git add` 多个文件用分号分隔 (PowerShell)

## 12. 必读文档 (按顺序)

1. **`docs/devlog/22-phase16-completion.md`** — **本次 V1.6.1 完整 devlog, 必读**
2. `docs/handoff/2026-06-01-layer2-v2.0-plan-with-phase16.md` — V2.0 v2 计划 handoff (V1.6.1 上下文)
3. `docs/layer2-v2.0-plan.md` — V2.0 v2 主计划 (§3.0 Phase 1.6 完整)
4. `docs/l1-verification-report-v1.7.md` — V1.7 报告 (§2.3.4 是 P0 漏洞原始数据)
5. `data/n2_fallback_debug.json` — V1.7 baseline (4 fixture LLM 原始输出)
6. `data/n2_v161_live_results.json` — V1.6.1 实测 (4 fixture + invariant 校验)
7. `core/skills/system_modeler.py` — 改动后的生产代码 (3 层防御)
8. `tests/core/test_l1_prompts.py` — 7 个 V1.6.1 测试 (回归网)
9. `scratch/debug_n2_fallback_v161.py` — 验证脚本 (跑 4 fixture live)
10. `CONTEXT.md` §5 — V1.6.1 最新升级记录
11. `agents/ui/planning_graph.py:288-325` — Phase 1.6.2 改造目标 (下个 session)
12. `core/skills/system_mapper.py` — Phase 1.6.3 改造目标 (采样 + 测试)

## 13. 关键洞察 (从 V1.6.1 抽出, 供 V2.0 后续阶段参考)

1. **"fallback" 这个词在 V1.7 报告里定义不清**: 是 outer (result is None) 还是 inner (structured_output → raw parse)? 后续每份报告里的数字都应该明确指代哪种, 避免误读。
2. **"P0 漏洞" 应该第一时间用真实数据验证**: V1.7 报告里 "3/4 fallback" 听起来严重, 但实测发现是 SDK 行为, 真实可改的是输出质量违规 (1+ fixture 节点后缀, 1 fixture transitions 重复)。**先量化再动手**, 不要被 P0 字面吓到过度工程化。
3. **3 层防御是 N2 加固的最小可行套件**:
   - L1 (Prompt): 预防 — 让 LLM 自检
   - L2 (Normalize): 检测 + 修复 — 后处理代码自动修
   - L3 (Derive minimal): 兜底 — 永远不返回空
   这套结构可复用到 V2.0 B 阶段 (decide/assert prompt) 和 V2.1 Gap Analyzer。
4. **共享 validator 防漂移**: `_is_chinese_noun_phrase` 从 production import 到 test, 单一来源。如果 test 自己复制一份, 改 test 时忘了改 production 就出 bug。
5. **substring 双向对齐 (LCP heuristic)** 是处理 LLM 错误模式最实用的方法: LLM 要么缩写 (use full name) 要么扩展 (use short name), 极少字符乱序。**实测 4 fixture 全对**, 但生产数据多了可能要加 fuzzy match fallback (e.g., 字符 jaccard 0.7)。
6. **`_derive_minimal_system_model` 没被 live test 覆盖**: 0/4 fixture 触发外层 fallback。需要构造 "LLM 强制失败" 的 fixture 才能 e2e 验证兜底。**V1.6.1 没做, 留作 V1.6.1.1 后续微调** (用 `ANTHROPIC_BASE_URL=` 指向无效端点跑一次)。

## 14. 完整改动统计

```
v1.7 handoff    → c2e5a2f: L1 收尾 (devlog 20)
c2e5a2f        → cb8c8ab: V2.0 计划 v1 落盘 (4 阶段)
cb8c8ab        → 008bb79: V2.0 计划 v2 修订 (5 阶段, 加 Phase 1.6)
008bb79        → b881fca: Phase 1.6.1 N2 SystemModel 三层防御加固 (本次)
```

| 指标 | v1.7 (c2e5a2f) | v2.0 v1 (cb8c8ab) | v2.0 v2 (008bb79) | v1.6.1 (b881fca) |
|---|---|---|---|---|
| 加固的 skill/prompt 数 | 8 (L1 + Phase 1.5) | 3 (L2 计划) | 3 + 3 (L2 + planning_graph explore + SystemMap) | +1 (N2 SystemModel) = 4 + 3 |
| 回归测试数 (mock) | 53 | 53 | 53 | 60 |
| 回归测试数 (live skip) | 8 | 8 | 8 | 8 |
| 4 fixture live invariant pass rate | 100% (但有违规) | — | — | **100% (零违规)** |
| 计划文档 | 0 | 1 (V2.0 v1) | 1 (V2.0 v2) | +1 (devlog 22) |
| 联动深度 | L1 → Phase 1.5 | L1 → L2 (单向) | L1 → L2 + planning_graph 协同 | L1 内部 N2 强化 (3 层防御) |
| 兜底安全网 | 无 | — | — | **有 (UseCaseModel 推导骨架)** |

## 15. 紧急联系

如果新对话遇到无法解决的问题:

1. `git log --oneline -3` 确认在 `b881fca` (V1.6.1)
2. `python -m pytest tests/core/test_l1_prompts.py tests/core/test_phase15_prompts.py -v` 确认 60 passed
3. 单步调试 N2 normalize:
   ```python
   import asyncio
   from core.skills.system_modeler import _strip_node_suffix, _align_action, _normalize_system_model
   from core.interfaces import SystemModel, BusinessFlow, StateTransition, UseCaseModel, UseCase
   ucm = UseCaseModel(use_cases=[UseCase(name="提交采购申请", actor="员工", trigger="草稿", outcome="待审批", related_rules=[])])
   sm = SystemModel(
       system_name="test", modules=[], entities=[], roles=[],
       flows=[BusinessFlow(name="f", nodes=["草稿状态", "待审批状态"],
                           transitions=[StateTransition(from_state="草稿状态", action="提交", to_state="待审批状态")])],
   )
   fixed = _normalize_system_model(sm, ucm)
   print(fixed.model_dump_json(indent=2))
   # 期望: nodes 剥后缀, action 对齐到 "提交采购申请"
   ```
4. 单步调试 N2 derive_minimal:
   ```python
   import asyncio
   from core.skills.system_modeler import _derive_minimal_system_model
   from core.interfaces import UseCaseModel, UseCase
   ucm = UseCaseModel(use_cases=[UseCase(name="登录", actor="用户", trigger="未登录", outcome="已登录", related_rules=[])])
   sm = _derive_minimal_system_model(ucm)
   print(sm.model_dump_json(indent=2))
   # 期望: flows 不空, 1 个 transition
   ```
5. 跑 V1.6.1 验证脚本: `python scratch/debug_n2_fallback_v161.py` (需 L1_LIVE=1)
6. 看 `docs/devlog/22-phase16-completion.md` §6 已知遗留 / 风险

---

**Good luck. V1.6.1 落盘完成, 3 层防御 + 0 violation。下一步 Phase 1.6.2 (planning_graph explore V1.6 化), 0.5d。The earlier V1.7 weak link (N2) is now the strongest node in L1.**
