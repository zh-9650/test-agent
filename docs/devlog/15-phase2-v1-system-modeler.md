# 步骤 15: Phase 2 启动 - 引入 System Modeling Agent (V1)

**时间**: 2026-05-31
**责任人**: AI Agent (Antigravity)
**状态**: ✅ 已完成

## 1. 背景与痛点
在 Phase 1.5 完成了所有遗留的基础设施 Bug 修复后，我们针对整个智能规划链路（Planning Graph）进行了一次专家级的架构评审。评审指出，当前链路存在“纸上谈兵”的问题：
- `Scenario Extractor` (场景提取器) 完全基于产品需求文档（PRD）进行盲猜，由于它没有对系统状态转移和边界做结构化收敛，极易生成脱离实际的“幽灵测试用例”。
- `Explorer` 在随后的漫游过程中，使用的是“自由探索”的提示词，导致效率低下。

## 2. 重构计划 (分三步走)
我们决定重构智能规划链路的前半段，将其划分为三个里程碑落地：
- **[x] V1**: 引入 `System Modeling Agent`，基于 PRD 提炼系统的认知骨架（模块、角色、流转、状态），并将其喂给 `Scenario Extractor` 作为高维强上下文。
- **[ ] V1.1**: 将提取出的 Business Flows 转化为具体探索目标，改造当前的自由探索器，变为 `Goal Driven Explorer`。
- **[ ] V1.2**: 探索结束后生成包含真实 UI 控件分布的 `System Map`，与文档认知合并，作为最终生成 Test Plan 的最高质量依据。

## 3. 本次 V1 核心代码改动
1. **新建技能 `core/skills/system_modeler.py`**:
   - 核心方法：`generate_system_model()`
   - 使用 `with_structured_output` 强制 LLM 提取含有 `modules`, `roles`, `business_flows`, `states` 四大维度的 JSON 结构。
   - 增加异常降级策略，确保当大模型提取 JSON 失败时平滑回退，防止中断测试流程。
2. **后台调度链路改造 `api/app.py` & `core/runtime.py`**:
   - 在完成 `parse_and_fetch_links` 动态抓取外部 PRD 后，立刻将其送入 `system_modeler`。
   - 将产生的模型数据序列化后存入 `Task.config["_system_model"]`，持久化至数据库。
3. **注入上下文 `core/skills/scenario_extractor.py`**:
   - 将生成的认知地图作为最优先级的上下文注入 Prompt。
   - 修复了 `scenario_extractor` 中解析带有 `thinking` 推理过程（如 Claude 3.7 模型）多区块响应内容时报错的问题。

## 4. 测试与验证结果
我们使用了“订单审批系统”的伪造 PRD 进行独立脚本测试：
- **结果 1**：成功清洗长文本，淬炼出了精准的四个业务状态（待审批、待打款、已驳回、已完成）。
- **结果 2**：`Scenario Extractor` 不再产生诸如“撤销审批”之类的越界操作用例，并且成功地将主管审批和财务打款融合成了一个极具业务价值的端到端大 Case。

## 5. 下一步行动
启动 V1.1 开发：
- 设计 `Goal Extractor`，将 `_system_model` 里的 `business_flows` 拆解为一个个具体的 URL/UI 寻找目标。
- 修改 `agents/ui/planning_graph.py` 中的 `explore_decide_node` Prompt，替换“自由漫游”为带着目标的寻路指令。
