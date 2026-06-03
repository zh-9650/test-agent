# Smart Test Agent — 全局路线图与优化计划汇总 (Master Roadmap)

## 说明

本文汇总了项目所有已讨论但未实施的优化计划，包括：

1. `docs/layer2-v2.0-plan.md` — 2026-06-01 GPT 外部评审 + V2.0 原始计划
2. `docs/phase2.0B.md` — 2026-06-03 执行缺陷修复计划
3. 2026-06-03 L2 架构三层问题分析
4. `BROWSER_USE_VS_OUR_ARCH.md` — 12 维浏览器对比改进建议
5. `CODE_COMPARISON_AND_IMPROVEMENTS.md` — 代码级改进清单
6. `IMPROVEMENT_PLAN_vs_BrowserUse.md` — 4 问题改进路线
7. `docs/PRD.md` — 44 个用户故事中未实现的
8. 各 handoff 文档中的 backlog 项目

按 6 个层级组织：P0 立即 → P1 短期 → P2 中期 → P3 长期 → P4 候选 → P5 实验。

---

## P0 — 立即 (Phase 2.0B, 当前 Sprint)

执行缺陷修复。Task 8 真实运行暴露的 4 个致命缺陷 + 3 个架构选项。

### B1: Step 语义校验与意图校验

| # | 来源 | 内容 | 文件 |
|---|------|------|------|
| B1.1 | Task8 | **密码注入意图校验**: 在 `input_text` 检测到 `type=password` 时，不直接注入，先校验 `current_step_text` 语义是否为"输入密码" | `tools.py` |
| B1.2 | Task8 | **mark_task_complete 二次确认**: marker 类工具后截图 + URL/元素对比，无实质变化降级为 inconclusive | `execution_graph.py` |
| B1.3 | Task8 | **工具返回实际填入值**: ActionResult 新增 `filled_value`，assert prompt 注入让 LLM 判断填入是否符合 step 语义 | `interfaces.py`, `tools.py`, `execution_graph.py` |
| B1.4 | Task8 | **Step Context 注册贯通**: `execute_node` 将 `current_step_text` 注册到 task_context，供 tool 通过 `get_current_step_text()` 读取 | `execution_graph.py`, `tools.py` |
| B1.5 | GPT 评审 | ~~V1.6 5 段 XML 迁移~~ **已由 Phase B 完成** | — |

### B2: 脱轨纠正 + 职责重分配

| # | 来源 | 内容 | 文件 |
|---|------|------|------|
| B2.1 | Task8 | **脱轨纠正护栏**: 连续 2 步页面无实质变化 + 无工具报错 → 强制 `need_replan = True`，追加 `[CORRECTIVE]` 提示 | `execution_graph.py` |
| B2.2 | 架构问题3 | **SystemMessage 不重建**: `messages[0]` 已是 SystemMessage 则替换内容而非 insert | `execution_graph.py` |
| B2.3 | 架构问题2 | **Context 压缩移至 observe**: record 移除压缩逻辑，observe 开头执行 token-aware truncation | `execution_graph.py` |
| B2.4 | 架构问题2 | **Loop Detection 移至 observe**: record 移除 AAA/ABAB（保留 action_history 追加），observe 做检测 + 设置 need_replan | `execution_graph.py` |

### B3: assert 条件边 + 数据采集

| # | 来源 | 内容 | 文件 |
|---|------|------|------|
| B3.1 | 架构问题1 | **assert 条件边**: `execute → should_assert_llm → {assert_node, record}`，只有最终步骤 + 复杂情况才走 LLM | `execution_graph.py` |
| B3.2 | PRD 决策 | **Locator 失败率统计**: `_locator_stats` 计数器，100 case 后自动计算失败率 | `interfaces.py`, `execution_graph.py` |

---

## P1 — 短期 (Phase 2.0C, 待条件触发)

| # | 来源 | 触发条件 | 内容 |
|---|------|----------|------|
| P1.1 | `phase2.0A-final.md` | 100 case locator 失败率 > 30% | **CDP 迁移**: `backendNodeId` 锚定 + CDP click/input + AXTree-led 感知 |
| P1.2 | `BROWSER_USE_VS_OUR_ARCH.md` §7 | P1.1 启动后并行 | **CDP Adapter**: 统一工具层抽象，Playwright/CDP 双后端可切换 |
| P1.3 | `CODE_COMPARISON.md` §E | P1.1 启动后并行 | **事件驱动架构**: 从轮询 DOM + 截图 改为 CDP DOM 事件监听 |
| P1.4 | `IMPROVEMENT_PLAN.md` §3 | Locator 数据充足 | **右键菜单 / iframe / shadow DOM 支持**: CDP 副作用树+独立 context |

---

## P2 — 中期 (Phase 2.1)

### 核心引擎升级

| # | 来源 | 内容 | 优先级 |
|---|------|------|--------|
| P2.1 | `layer2-v2.0-plan.md` V2.1 backlog | **Gap Analyzer**: SystemModel vs SystemMap 比对，标记遗漏模块/多出模块 | P2-A |
| P2.2 | `layer2-v2.0-plan.md` V2.1 backlog | **Phase E Reflection**: 执行后 LLM 自我反思，循环优化策略 | P2-A |
| P2.3 | `layer2-v2.0-plan.md` V2.1 backlog | **tools.py 14 工具缺陷修复** (实验性): | P2-B |
|  | | - verify: Action 执行后回读元素状态确认 | |
|  | | - list_options: 读取 select 选项文本 | |
|  | | - multi_select: 支持多选下拉框 | |
|  | | - file_upload: Playwright file chooser + 安全校验 | |
|  | | - switch_tab: 浏览器选项卡间切换 | |
|  | | - close_tab: 关闭当前选项卡 | |
|  | | - extract_table: 结构化表格提取 | |
|  | | - check_element: 判断 checkbox/radio 是否选中 | |
|  | | - scroll_to_element: 精准滚动到元素 | |
|  | | - drag_and_drop: 拖拽操作 | |
|  | | - get_cookie/set_cookie/delete_cookie: Cookie 管理 | |
|  | | - screenshot: 纯截图工具 (不依赖 LLM) | |
| P2.4 | GPT 评审 §6.2 | **evaluate_js 黑名单漏洞复测**: 当前黑名单 `page.goto`, `page.evaluate`, `window.location`, `location.href`, `fetch` — 可能被 `eval()` / `Function()` / `document.location` / `fetch` 拼接绕过 | P2-B |

### Prompt 工程

| # | 来源 | 内容 |
|---|------|------|
| P2.5 | GPT 评审 §"补理论+真实桥梁" | **LLM TheoryBridge**: 在 planning_graph 注入理论架构 + SystemMap 真实数据，消除理论 vs 实际鸿沟 |
| P2.6 | `prompt-engineering.md` §10 | **L2 Prompt 工程文档**: 为 execution_graph 创建完整 prompt 契约文档 (对照 §9 planning_graph 标准) |

### 记忆与知识库

| # | 来源 | 内容 |
|---|------|------|
| P2.7 | `phase2.0A-final.md` roadmap | **跨任务长期 Memory 沉淀**: 多任务间共享测试经验，按 URL 域名索引 |
| P2.8 | `PRD.md` US-027-030 | **AgentMemory 知识检索增强**: RAG 查询历史测试发现 |

---

## P3 — 长期 (Phase 2.5)

### 多 Agent 协同

| # | 来源 | 内容 |
|---|------|------|
| P3.1 | `PRD.md` US-040-042 | **Multi-Agent 并行执行**: 多个 Agent 同时测试不同模块 |
| P3.2 | `layer2-v2.0-plan.md` V2.5+ | **LangSmith 集成**: 全链路可观测性、trace 可视化、LLM 调用分析 |
| P3.3 | `PRD.md` US-043-044 | **Agent 间沟通仲裁**: 冲突检测、资源协商、结果汇总 |

### 架构升级

| # | 来源 | 内容 |
|---|------|------|
| P3.4 | `BROWSER_USE_VS_OUR_ARCH.md` §9 | **性能优化体系**: LLM 调用缓存、相似页面去重、并行工具执行 |
| P3.5 | `BROWSER_USE_VS_OUR_ARCH.md` §3 | **混合 DOM 感知**: Playwright AXTree + CDP AXTree 双源合并，置信度加权 |
| P3.6 | `BROWSER_USE_VS_OUR_ARCH.md` §5 | **MessageManager 重构**: 借鉴 browser-use 的固定 system message + 动态上下文窗口 |

### 测试报告

| # | 来源 | 内容 |
|---|------|------|
| P3.7 | `PRD.md` US-021-026 | **报告增强**: 视频录播、AI 汇总、失败趋势图、多格式导出 (PDF/CSV) |
| P3.8 | `BROWSER_USE_VS_OUR_ARCH.md` §10 | **计划与实际差异热力图**: execute vs plan 偏差可视化 |

---

## P4 — 候选 (待评估)

### 需要更多数据验证

| # | 来源 | 内容 | 评估条件 |
|---|------|------|----------|
| P4.1 | GPT 评审 §"建 Gap Analyzer" | **Gap Analyzer P0 化**: 提升为 V2.1 P0 (vs 原 V2.1 候选) | 50+ case 后 SystemModel 偏差数据 |
| P4.2 | `layer2-v2.0-plan.md` V2.1 | **PostgreSQL checkpointer 升级**: 从 MemorySaver 切到 AsyncPostgresSaver | LangGraph checkpoint 大小 > 100MB |
| P4.3 | `test-case-reviewer.md` | **自动化审查生成**: L1 测试用例供给下游 API 测试 | L1 用例质量达标 |
| P4.4 | `BROWSER_USE_VS_OUR_ARCH.md` §11 | **端到端基准测试套件**: 20+ fixture 对比 browser-use 准确率/速度 | 有稳定目标系统 |

### 低优先级优化

| # | 来源 | 内容 |
|---|------|------|
| P4.5 | `CODE_COMPARISON.md` §B | **元素定位策略优化**: 多策略加权 (XPath, CSS, text, role, `data-testid`) |
| P4.6 | `BROWSER_USE_VS_OUR_ARCH.md` §4 | **Action 链式执行**: 连续的 `fill→click→wait` 合并为单次 LLM 调用 |

---

## P5 — 实验 (Research / Pre-development)

| # | 来源 | 内容 | 预期收益 |
|---|------|------|----------|
| P5.1 | `PRD.md` US-036 | **Human-in-the-Loop 增强**: 比当前 blocking event 更灵活的审批流 | 安全敏感场景 |
| P5.2 | `BROWSER_USE_VS_OUR_ARCH.md` §12 | **CDP 事件总线**: 取代 polling 式 DOM 轮询 | 减少 ~90% 无意义 DOM 查询 |
| P5.3 | GPT 评审 §"学术对齐" | **Embedding 语义相似度**: 替换 substring 匹配的实体对齐 | 提升 N2 准确率 |
| P5.4 | GPT 评审 §"学术对齐" | **LLM-as-Judge 自动评估**: 替代人工判定 assertion 质量 | 减少人工 review |
| P5.5 | `docs/l1-verification-report-v1.7.md` §8 | **Qwen/DeepSeek 替代 Kimi**: 降低 API 成本 | 成本降低 ~50% |
| P5.6 | `BROWSER_USE_VS_OUR_ARCH.md` §6 | **StateModel 对齐 browser-use**: 统一 state 模型定义 | 生态兼容 |
| P5.7 | `BROWSER_USE_VS_OUR_ARCH.md` §8 | **安全沙箱升级**: 浏览器隔离、脚本白名单、日志审计 | 生产安全 |
| P5.8 | `docs/layer2-v2.0-plan.md` V2.5+ | **Business Graph**: 业务状态流转图数据库 | 超复杂系统建模 |
| P5.9 | `CONTEXT.md` §3 | **Phase 3 自主测试团队**: 完全自主接管回归测试 | 终极目标 |

---

## 已完成的 GPT 评审建议

以下 GPT 2026-06-01 外部评审建议已在 V2.0 v2 计划中完成，不再重复：

| # | GPT 建议 | 完成方式 | 完成时间 |
|---|----------|----------|----------|
| ✅ | N2 SystemModel 加固 (P0) | Phase 1.6.1, 3 层防御 | 2026-06-02 |
| ✅ | planning_graph explore V1.6 化 | Phase 1.6.2, 5 段 XML + output_contract | 2026-06-02 |
| ✅ | SystemMap 采样增强 | Phase 1.6.3, 10/15 → 20/30 | 2026-06-02 |
| ✅ | L2 安全网 + P0 修复 | V2.0 Phase A, 6 fixes | 2026-06-02 |
| ✅ | L2 Prompt V1.6 化 | V2.0 Phase B, 3 prompts | 2026-06-02 |
| ✅ | L1→L2 业务模型联动 | V2.0 Phase C, 4 路注入 | 2026-06-02 |
| ✅ | L2 可观测性 | V2.0 Phase D, tiktoken + WebSocket | 2026-06-02 |
| ✅ | 密码脱敏剥离 | Phase B, 密码不进 prompt | 2026-06-02 |
| ✅ | Goal Reminder (P0) | Phase 2.0A Sprint 1 | 2026-06-03 |
| ✅ | Failure Memory (P1) | Phase 2.0A Sprint 5 | 2026-06-03 |
| ✅ | Loop Detection (P2) | Phase 2.0A Sprint 6 | 2026-06-03 |

---

## 路线图可视化

```
现在
 │
 ├─ P0 ─── Phase 2.0B (B1→B2→B3) ─── 2026-06-W1
 │          执行韧性增强 + 缺陷修复
 │
 ├─ P1 ─── Phase 2.0C (条件触发)
 │          CDP 迁移 + AXTree 🔄 locator 失败率 > 30%
 │
 ├─ P2 ─── Phase 2.1
 │          ┌ Gap Analyzer + Reflection
 │          ├ 14 工具缺陷修复
 │          ├ L2 Prompt 工程文档
 │          └ 跨任务 Memory
 │
 ├─ P3 ─── Phase 2.5
 │          ┌ Multi-Agent
 │          ├ LangSmith 集成
 │          ├ 混合 DOM 感知
 │          └ 报告增强
 │
 ├─ P4 ─── 待评估
 │          ┌ Gap Analyzer P0
 │          ├ PG checkpointer
 │          ├ 基准测试套件
 │          └ 低优先级优化
 │
 └─ P5 ─── 实验
             ┌ HITL 增强
             ├ CDP 事件总线
             ├ Embedding 对齐
             └ LLM-as-Judge
```

## 决策阈值清单

| 决策 | 触发条件 | 动作 |
|------|----------|------|
| CDP 迁移 (P1.1) | 100 case locator 失败率 > 30% | 启动 Phase 2.0C |
| Gap Analyzer P0 (P4.1) | 50+ case SystemModel 偏差 > 20% | 提升至 P2 |
| PG Checkpointer (P4.2) | LangGraph checkpoint > 100MB | 切换持久化 |
| Qwen/DeepSeek 替代 (P5.5) | API 成本 > $X/月 | 启动实验评估 |
| Phase 3 (P5.9) | 200+ case 准确率 > 90% | 启动架构设计 |

## 参考文档

| 文档 | 路径 |
|------|------|
| GPT 评审 V2.0 计划 v2 | `docs/layer2-v2.0-plan.md` |
| Phase 2.0A 最终版 | `docs/phase2.0A-final.md` |
| Phase 2.0B 执行韧性 | `docs/phase2.0B.md` |
| 架构白皮书 | `ARCHITECTURE.md` |
| Browser-use 12 维对比 | `BROWSER_USE_VS_OUR_ARCH.md` |
| 代码级改进清单 | `CODE_COMPARISON_AND_IMPROVEMENTS.md` |
| 4 问题改进路线 | `IMPROVEMENT_PLAN_vs_BrowserUse.md` |
| 44 用户故事 | `docs/PRD.md` |
| Prompt 工程契约 | `docs/prompt-engineering.md` |
| L1 验证报告 | `docs/l1-verification-report-v1.7.md` |
| 全局上下文 | `CONTEXT.md` |
