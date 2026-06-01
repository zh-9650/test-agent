# Phase 2 (V1.6 + V1.7) - L1 + Phase 1.5 Prompt Engineering 加固

**时间**: 2026-06-01
**责任人**: Lead
**前置**: V1.5 Layer 1 鲁棒性加固 (`19-layer1-hardening.md`)、`docs/l1-verification-report.md` 揭示的 3 个盲点
**Commits**: `65324a0` (V1.6 L1 5 skill) + `b16ffe8` (V1.7 Phase 1.5 3 skill + L1 盲点 B/C 修复)

---

## 1. 业务目标

V1.5 加固后,L1 管线在生产端点上"跑得稳",但有两个遗留问题:

1. **L1 prompt 质量未量化**: 5 个 L1 skill 的 prompt 写法各异,无统一结构、无 Output Contract、无 good/bad example,新增 skill 时全靠"复制粘贴 + 祈祷"。
2. **Phase 1.5 三个 skill 仍用旧风格**: `risk_analyzer` / `scenario_extractor` / `session_summary` 三个 L1.5 skill 没用 V1.6 模式,且 `scenario_extractor` / `session_summary` 还在用 `llm.ainvoke().content` 裸调(违反 V1.5 立下的"必须走 `safe_structured_invoke`"规则)。
3. **L1 验证报告的 3 个盲点**: A (互斥性断言缺失) / B (unknown_actor 无下游消费) / C (fast-path 90% 阈值无依据)。

V1.6 解决 1,V1.7 解决 2 + 3。**两次 commit 一起让 L1 + Phase 1.5 8 个 skill 全部用同一套 V1.6 模式,并补齐所有验证盲点。**

## 2. V1.6 (commit `65324a0`): L1 5 skill 加固

### 2.1 模式定义:5 段 XML + Output Contract

所有 L1 skill 的 prompt 统一重写为如下结构(详见 `docs/prompt-engineering.md`):

```xml
<role>你扮演 [具体角色,如 PRD 阅读器 / 业务分析师 / 用例设计师]</role>
<context>[输入数据,如有: <prd>...</prd> <api_doc>...</api_doc> <changelog>...</changelog>]</context>
<task>用一句话说明这一步要做什么</task>
<rules>
- 硬约束 1(枚举值/格式/长度)
- 硬约束 2
- 软建议(可选)
</rules>
<examples>
<example type="good">...</example>
<example type="bad">...</example>
</examples>
<output_contract>
[Output 字段名]: [类型] - [约束]
</output_contract>
```

### 2.2 5 个 L1 skill 的具体改动

| Skill | 关键修复 |
|---|---|
| **knowledge_extractor** | 引入 `<role>` 显式 "无情的规则阅读器",quote fallback 由"找不到就空"升级为"找不到就标 `confidence=low` 并说明" |
| **use_case_modeler** | 硬约束 `related_rules` 必须是 `business_rule.id` 而非文本描述,避免下游 coverage 模糊匹配 |
| **use_case_coverage** | `actor` 字段硬约束 ∈ `knowledge.roles` 或显式 `unknown_actor:*` |
| **system_modeler** | 状态名/边名规范化(统一 camelCase),priority 仅 ∈ {high, medium, low} |
| **goal_extractor** | `name` 必须对应 `use_case.name` 而非自由文本,actions 限定 ∈ use_case.actions |

### 2.3 测试基础设施

- 新增 `tests/core/test_l1_prompts.py`: **4 fixture × 7 不变量 = 28 用例** (其中 4 fixture × 1 live = 4 个,默认 skip,需 `L1_LIVE=1`)
- 7 不变量: schema 合法性 / inter-node 契约 / adversarial quote fallback / priority 枚举 / 节点拼写 / action 归属 / 互斥性
- 修复 L1 live test 暴露的 6 个设计漏洞(见 `docs/l1-verification-report.md`)

### 2.4 端到端验证

`L1_LIVE=1` 跑 4 fixture,5 skill × 4 fixture = 20 个 LLM 调用,**全部通过**,fast path 4/4 命中 100%(详见验证报告第 2.2 节)。

## 3. V1.7 (commit `b16ffe8`): Phase 1.5 加固 + 盲点修复

### 3.1 Phase 1.5 三个 skill 的 V1.6 迁移

| Skill | V1.6 前问题 | V1.7 修复 |
|---|---|---|
| **risk_analyzer** | 无 XML 结构,severity 枚举无约束 | 5 段 XML + Output Contract + good/bad example,severity ∈ {high, medium, low} 硬约束,suggestions 长度 2-5 |
| **scenario_extractor** | 裸 `llm.ainvoke(...).content` 拿字符串(违反"必须走 `safe_structured_invoke`"规则) | 改用 `safe_structured_invoke` + pydantic `ScenarioList`,5 段 XML,id 格式 `S-NNN` 硬约束,entry_hint ≤ 60 字 |
| **session_summary** | 同样裸调 + 手写 JSON 解析,大量 try/except fallback | 改用 `safe_structured_invoke` + pydantic `CaseSummary`,5 段 XML,summary ≤ 100 字,失败时 `_fallback_summary()` 兜底 |

### 3.2 L1 验证报告 3 个盲点的处理

| 盲点 | 验证报告判定 | 实际状态 | V1.7 处理 |
|---|---|---|---|
| **A**: N1.7 互斥性未断言 | "未断言" | **非盲点** | `test_l1_prompts.py:187` 已有 `assert not (covered & missing)`,无需改 |
| **B**: actor 集合差集无下游消费 | "下游从不检查" | **真盲点,已修** | `CoverageReport` 新增 `unknown_actor_count` + `unknown_actor_names` 字段;HTML 报告 L1 卡片新增"未匹配角色"折叠区;`_compute_unknown_actors()` 在所有返回路径上调用;`test_l1_prompts.py` 新增 2 个测试 |
| **C**: fast-path 90% 阈值无依据 | "无注释" | **真盲点,已加 8 行 docstring** | 说明 0.9 阈值依据 (substring 归一化是宽松 fuzzy match) + 实际是 defensive safety net + 何时该警惕 |

### 3.3 测试覆盖

- 新增 `tests/core/test_phase15_prompts.py`: **20 mock + 4 live (skipped)** 用例
  - 4 fixture × 5 测试 = 20 mock: schema 合法性 / risk_analyzer 不变量 / scenario_extractor 不变量 / session_summary 不变量 / status 透传
- `tests/conftest.py` 补 `load_dotenv()`(修复 `L1_LIVE=1` 找不到 ANTHROPIC_* 变量)

### 3.4 端到端验证

```powershell
$env:L1_LIVE = "1"
python -m pytest tests/core/test_l1_prompts.py::test_l1_live_all_fixtures -v -s
python -m pytest tests/core/test_phase15_prompts.py::test_phase15_live_all_fixtures[prd_purchase] -v -s
```

实测:
- L1 4 fixture × 5 skill: **PASSED in 997.72s**,40 rules / 27 use_cases / 100% covered
- Phase 1.5 prd_purchase: **PASSED in 82.99s**,2 risks / 5 scenarios

总耗时 ~18min,100% 命中。详见 `docs/l1-verification-report-v1.7.md`。

## 4. 改动文件清单 (V1.6 + V1.7)

### 新增
- `docs/prompt-engineering.md` — V1.6 方法论 + L1↔L2 节点契约
- `docs/l1-verification-report-v1.7.md` — V1.7 复验报告(含 live test 实测数据)
- `tests/core/test_l1_prompts.py` — 28 个 L1 回归测试
- `tests/core/test_phase15_prompts.py` — 24 个 Phase 1.5 回归测试

### 修改
- `core/skills/knowledge_extractor.py` (V1.6 重写)
- `core/skills/use_case_modeler.py` (V1.6 重写)
- `core/skills/use_case_coverage.py` (V1.6 + V1.7 unknown_actor 字段 + fast-path docstring)
- `core/skills/system_modeler.py` (V1.6 重写)
- `core/skills/goal_extractor.py` (V1.6 重写 + V1.5 死代码清理)
- `core/skills/risk_analyzer.py` (V1.7 V1.6 重写)
- `core/skills/scenario_extractor.py` (V1.7 V1.6 重写 + 切到 safe_structured_invoke)
- `core/skills/session_summary.py` (V1.7 V1.6 重写 + 切到 safe_structured_invoke + `_fallback_summary()`)
- `core/report_builder.py` (V1.7 HTML 报告新增未匹配角色卡片)
- `core/llm_client.py` (V1.5 引入,本轮被 3 个 Phase 1.5 skill 实际使用)
- `tests/conftest.py` (V1.7 加 `load_dotenv()`)
- `tests/core/test_l1_prompts.py` (V1.7 新增 2 个 unknown_actor 测试)

## 5. 意义

### L1 + Phase 1.5 全部加固完成
- **8 个 skill** (5 L1 + 3 Phase 1.5) 全部统一为 V1.6 5 段 XML + Output Contract 模式
- **53 个 mock 回归测试 + 8 个 live skip** 测试全过
- **3 个 L1 验证报告盲点全处理** (A 非盲点 / B 修 / C 注释)
- **生产端点耐受性** 进一步增强 (`safe_structured_invoke` 在 Phase 1.5 3 个 skill 上也落地)

### L1 收尾 (此 devlog 即收尾标志)
- 不再发现新的 L1 设计漏洞
- 测试覆盖完整,新增 skill 只需复用 V1.6 模板 + 加 invariant 测试
- L1 在 5 段 XML + Output Contract 上沉淀为项目惯例

### 下一步:从 L1 转向 L2 (`execution_graph.py`)
- L1 + Phase 1.5 是"一次任务调一次 LLM" → 加固 ROI 已经收割完
- **L2 才是 prompt 调用的 hot path** — 每步调一次 LLM,典型任务 15-50 步 → 总调用量是 L1 的 30-100 倍
- V1.6 模式可直接复用,预计 1-2 天可完成

详细优先级见 `docs/l1-verification-report-v1.7.md` 第 8 节。
