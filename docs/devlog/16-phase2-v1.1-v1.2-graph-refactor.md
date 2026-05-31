# Phase 2 (V1.1 & V1.2) - Goal-Driven Explorer & System Mapper

**时间**: 2026-05-31
**责任人**: Lead

## 1. 业务目标
将原本依赖固定 PRD 瞎逛的探索节点，升级为“目标驱动”（Goal-Driven）的定向探索，并在探索完毕后基于真实的游历路径生成系统级大地图（System Map），再交给场景提取器（Scenario Extractor）规划测试用例。这彻底闭环了“认知 -> 探索 -> 验证 -> 规划”的整套智能链路。

## 2. 变更详情

### 2.1 新增核心技能
1. **`core/skills/goal_extractor.py`**:
   - 输入: 结构化的 `SystemModel` (来自 V1 的成果)。
   - 输出: 行动目标列表 (Goals)。例如“找到购物车入口”。
2. **`core/skills/system_mapper.py`**:
   - 输入: `_exploration_history` (探索过程中的 DOM 切片和 URL 记录)。
   - 输出: 结合业务流的 `SystemMap` 结构，真正描绘了站点的 UI 拓扑。

### 2.2 核心图谱重构 (`agents/ui/planning_graph.py`)
重新梳理了规划子图 (Planning Graph) 的节点链路：
- 插入 `extract_goals_node`：图谱启动时，先提炼目标。
- 改造 `explore_decide_node`：Prompt 中注入提取出的 Goals，强制模型在探索时优先完成目标寻找。
- 插入 `generate_system_map_node`：探索结束后收集所有浏览历史并生成 System Map。
- 插入 `extract_scenarios_node`：利用 System Map 提供真实依据，合并 PRD 的指导，提取具备实操价值的测试场景。

### 2.3 运行时收敛 (`core/runtime.py`)
- 移除了提前运行的 `extract_scenarios` 调用。所有的前置分析现在都被完全并入了 LangGraph 管理的 `planning_graph`，使得状态流转更加一致、可控。

## 3. 测试验证
新增了专用端到端测试用例 `test_e2e_v1.py`：
- 修改了环境变量 `MAX_EXPLORE_PAGES` 和 `MAX_EXPLORE_MINUTES` 放开探索限制。
- 模拟调用 `SystemModeler` 后直接送入 Runtime。
- 执行结果证明：Agent 成功将目标附带在探索上下文中，并严格依序流转，整个拓扑图重构确切生效。
