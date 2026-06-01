# Phase 2 (V1.3) - Layer 1 知识提取与状态机建模

**时间**: 2026-06-01
**责任人**: Lead

## 1. 业务目标
为了进一步规范化大模型对长篇 PRD 和接口文档的认知，在原有的 System Modeler 之前，抽离出一个专门的“知识提取层”（Knowledge Extraction Layer / Node 1）。这不仅可以使得大模型的推理颗粒度更细，还能输出更标准、稳定的轻量级状态机（Lightweight State Machine），用于最终生成探索目标。

## 2. 变更详情

### 2.1 接口定义规范 (`core/interfaces.py`)
新增了一系列 Layer 1 的 Pydantic 模型（IR - 中间产物）：
- **`KnowledgeBase`**: 结构化提取的业务事实与规则（包含 business_rules, roles, entities, constraints, raw_facts）。
- **`StateTransition` & `BusinessFlow`**: 定义了状态机流转的结构（起点、动作、终点）。
- **`SystemModel`** (升级): 从原本的纯列表变成了基于 `BusinessFlow`（轻量级状态机）的核心骨架。
- **`ExplorationGoal`**: 将探索目标对象化，增加了 `priority` 优先级字段。

### 2.2 新增核心技能
1. **`core/skills/knowledge_extractor.py`**:
   - 输入: 原始长篇文本 (`prd_content`, `api_doc`, `changelog`)。
   - 输出: 纯粹客观的硬核业务事实库 (`KnowledgeBase`)。
2. **`core/skills/system_modeler.py`** (升级):
   - 输入: 上一步提取的 `KnowledgeBase`。
   - 输出: 基于事实库推导出来的轻量级状态机系统认知地图 (`SystemModel`)。
3. **`core/skills/goal_extractor.py`** (升级):
   - 输入: 升级版的状态机认知 (`SystemModel`)。
   - 输出: 结构化的探索目标列表 (`[ExplorationGoal]`)，每个目标带优先级。

### 2.3 流程与测试接入 (`api/app.py` & `test_e2e_v1.py`)
- 在 FastAPI 接口和测试脚本中全面接入了 `extract_knowledge -> generate_system_model -> extract_goals` 的三段式流水线。
- 新增了 `POST /api/test/layer1` 专门用于测试提取层的链路连通性。

## 3. 测试验证
通过运行 `POST /api/test/layer1` 并传入测试用例文本，验证了三个节点能够依次顺畅工作，成功将人类语言转化为状态机结构并生成寻路策略。
