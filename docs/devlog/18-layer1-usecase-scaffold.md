# Phase 2 (V1.4) - 用例脚手架 (UseCase Cognitive Scaffold)

**时间**: 2026-06-01
**责任人**: Lead

## 1. 业务目标
在原有的 KnowledgeBase (Node 1) 与 SystemModel (Node 2) 之间，大模型直接从零散的事实和规则中凭空想象状态机的难度依然较大。为了进一步稳固状态机的生成质量，引入了 Node 1.5：**用例脚手架 (UseCase Model)**。
这一层负责将事实转化为基于角色的原子级业务用例，明确定义前置触发条件 (trigger) 和执行结果 (outcome)，从而为下一步生成严格的状态机 (State Machine) 提供中间脚手架。

## 2. 变更详情

### 2.1 接口层新增 (`core/interfaces.py`)
- **`UseCase`**: 单个用例的脚手架模型，包含：`name` (用例名称), `actor` (执行角色), `trigger` (触发条件), `outcome` (执行结果), `related_rules`。
- **`UseCaseModel`**: 系统全量用例集合 (`Node 1.5` 输出)。
- 修改了 **`KnowledgeItem`**：为事实库引入了更严格的可追溯指针体系（`text`, `source`, `quote`, `confidence`）。

### 2.2 核心技能与流水线升级
1. **`core/skills/use_case_modeler.py`**:
   - 新增模块，消费 `KnowledgeBase` 并产出 `UseCaseModel`。
2. **`core/skills/system_modeler.py`** (逻辑升级):
   - 现在的输入除了 `KnowledgeBase`，还强依赖于 `UseCaseModel`。
   - LLM 不再凭空脑补状态流转边，而是基于 UseCase 的 `trigger` (from_state) 和 `outcome` (to_state)，并将 UseCase 的 `name` 作为流转动作 (action)。极大地提升了状态机图的严谨性。
3. **流水线调整 (`api/app.py` & `test_e2e_v1.py`)**:
   - 原有的 Node 1 -> Node 2 -> Node 3 链路变更为：`Node 1 (KnowledgeBase) -> Node 1.5 (UseCaseModel) -> Node 2 (SystemModel) -> Node 3 (ExplorationGoals)`。

## 3. 意义
这一步不仅让最终的 Test Case 规划有据可依，连中间的 System Map 状态流转也是从有原文出处 (quote) 的原子规则严密推导而来。极大削弱了大模型的幻觉随机性。
