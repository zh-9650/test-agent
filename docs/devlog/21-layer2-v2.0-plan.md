# Phase 1.6 + V2.0 (L2 全面加固) — 计划修订 (Plan v2)

**时间**: 2026-06-01
**责任人**: Lead
**前置**: V2.0 计划 v1 (cb8c8ab) + 2026-06-01 GPT 外部评审
**状态**: 修订后待执行
**完整方案**: `docs/layer2-v2.0-plan.md` v2

---

## 1. 业务目标

V2.0 计划 v1 (cb8c8ab) 落盘后，2026-06-01 收到 GPT 外部评审建议，核心洞察：

1. ✅ L1 + Phase 1.5 已经稳定（4 fixture 100% 覆盖）
2. ⚠️ **N2 SystemModel 是 L1 真实薄弱点**（V1.7 报告原文 3/4 fixture 触发 fallback）—— **V2.0 v1 漏了**
3. ❌ GPT 误判"缺 actual_pages/actions/forms"——**SystemMap V1.2 已存在**（已用 pydantic，被 scenario_extractor 消费）
4. ✅ 方向对：补"理论模型 + 真实系统"桥梁

**V2.0 v2 修订**：
- 新增 **Phase 1.6**（N2 + planning_graph explore + SystemMap 三件套加固，1.5-2 天）
- V2.0 A/B/C/D 4 阶段不变，但**执行顺序变更为 1.6→A→B→C→D**
- 总工时 7-8d → 9-10d
- 5 个独立 commit（新增 Phase 1.6 一个）
- **Gap Analyzer** 推迟到 V2.1（GPT 最有价值的新建议）

## 2. 关键事实核对（V2.0 v1 落盘后）

| 事实 | 来源 | 结论 |
|---|---|---|
| L1 V1.7 4 fixture 100% 覆盖 | `docs/l1-verification-report-v1.7.md` §2.2 | ✅ L1 稳定 |
| N2 fallback 触发率 3/4 fixture | `docs/l1-verification-report-v1.7.md` §2.3 | ✅ 真 P0 漏洞 |
| SystemMap V1.2 已存在 + 走 pydantic | `core/skills/system_mapper.py:5-9` | ❌ GPT 误判"缺" |
| scenario_extractor 已在消费 SystemMap | `agents/ui/planning_graph.py:314` + `core/skills/scenario_extractor.py:4` | ✅ 链路完整 |
| V1.7 没加固 planning_graph explore prompt | grep `V1.7` 范围 | ✅ 漏点（V-1.6.2） |
| SystemMap 采样 10 页/15 元素 | `core/skills/system_mapper.py:22-25` | ⚠️ 偏薄（V-1.6.3） |

## 3. V2.0 v1 → v2 变更

| 项 | v1 | v2 |
|---|---|---|
| 阶段数 | 4 | **5** |
| 阶段名 | A/B/C/D | **1.6/A/B/C/D** |
| Phase 1.6 内容 | 不存在 | N2 fallback + explore V1.6 + SystemMap 采样 + invariant |
| 执行顺序 | A→B→C→D | **1.6→A→B→C→D** |
| 工时 | 7-8d | **9-10d** |
| Commit 数 | 4 | **5** |
| Gap Analyzer | 隐含 V2.5+ | **显式 V2.1 候选** |
| N2 SystemModel fallback | 隐含在 V1.7 收尾 | **显式 Phase 1.6 P0** |

## 4. Phase 1.6 详细任务

| # | 任务 | 文件 | 工时 | 验收 |
|---|---|---|---|---|
| 1.6.1 | 修 N2 SystemModel fallback 频繁触发 | `core/skills/system_modeler.py` | 0.5d | fallback 率 3/4 → ≤ 1/4 |
| 1.6.2 | planning_graph explore_decide / execute V1.6 化 | `agents/ui/planning_graph.py` | 0.5d | 5 段 XML + 契约 |
| 1.6.3 | SystemMap 采样 20/30 + invariant 测试 | `core/skills/system_mapper.py` + `tests/core/test_system_mapper.py` | 0.4d | 4 fixture mock + 稳定性 ≥ 80% |
| 1.6.4 | 文档同步 (prompt-engineering §8 加 planning_graph 章节) | `docs/prompt-engineering.md` | 0.1d | — |

## 5. V2.0 A/B/C/D 不变

V2.0 主体的 4 阶段 16 个任务**完全保留**（详见主计划 v2），Phase 1.6 插在 A 之前。

## 6. 验收标准

### Phase 1.6
- N2 SystemModel fallback 触发率 ≤ 1/4 fixture
- planning_graph explore_decide/execute 走 5 段 XML
- SystemMap 采样 20/30 + `tests/core/test_system_mapper.py` 4 fixture mock 全过
- V1.7 53 mock + 8 live skip 全过不退化
- L1 ↔ L2 集成 smoke test 通过

### V2.0 A/B/C/D（继承 v1 验收）
详见主计划 v2 §6。

## 7. 时间线 + Commit 序列

| Day | 阶段 | Commit |
|---|---|---|
| 1-2 | **Phase 1.6** | `fix(layer1): Phase 1.6 N2+explore+SystemMap 三件套加固` |
| 3-4 | Phase A | `fix(layer1+layer2): L2 safety net + test infrastructure` |
| 5-7 | Phase B | `feat(layer2): L2 prompts V1.6 migration` |
| 8 | Phase C | `feat(layer2): L1→L2 business model linkage` |
| 9-10 | Phase D | `feat(layer2): observability` |
| **合计** | **5 阶段 / 5 commit / 9-10d** | |

## 8. 不在范围内（明确）

- ❌ **Gap Analyzer**（GPT 新建议）—— V2.1 候选
- ❌ Phase E Reflection
- ❌ Business Graph / LangSmith / Multi-Agent
- ❌ 改 tools.py 14 工具（除 evaluate_js 黑名单）
- ❌ checkpointer 升级
- ❌ tools.py 工具面缺陷（V19-V22）—— V2.1+ backlog

## 9. 后续 (V2.1+)

| 优先级 | 项 | 来源 |
|---|---|---|
| P0 | **Gap Analyzer**（SystemModel vs SystemMap 比对） | GPT 2026-06-01 |
| P1 | tools.py 14 工具缺陷 | V2.1 backlog |
| P2 | Phase E Reflection（50 case 数据评估后） | V2.1+ |
| P3 | Business Graph / LangSmith / Multi-Agent | V2.5+ |

---

**计划修订完成。** 执行起点：**Phase 1.6.1**（修 N2 SystemModel fallback）。
