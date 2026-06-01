import json
from pydantic import BaseModel, Field
from core.llm_client import get_llm_client, safe_structured_invoke
from core.interfaces import SystemModel, KnowledgeBase, UseCaseModel

async def generate_system_model(knowledge: KnowledgeBase, use_case_model: UseCaseModel) -> SystemModel:
    """
    Node 2: Business Extraction / System Modeling.
    Consumes the KnowledgeBase and UseCaseModel (Cognitive Scaffold) to generate a Lightweight State Machine graph.
    """
    prompt = f"""
你是一个顶级系统架构师。你的任务是根据"用例脚手架 (UseCase Model)"，为系统构建一张核心认知地图（轻量级状态机）。

相比于之前让你直接从零散的事实库中凭空想象状态机，现在你有了 UseCaseModel 作为坚实的脚手架。
用例模型已经清楚地定义了每个动作的前置触发条件 (trigger) 和执行结果 (outcome)。

请基于传入的 UseCaseModel 和 KnowledgeBase 提取以下信息构建 JSON：
1. system_name: 系统的整体名称。
2. modules: 划分核心业务模块。
3. entities: 继承核心业务实体。
4. roles: 继承角色。
5. flows: 请基于 UseCase 中的 trigger 和 outcome，将离散的用例串联成"轻量状态机(Lightweight State Machine)"。
   对于每个 BusinessFlow，你需要梳理出：
   - name: 业务流名称
   - nodes: 涉及的所有状态节点（如"草稿"、"待审批"、"已完结"）
   - transitions: 状态间的有效流转边（包含 from_state, action, to_state）。(此处的 action 应当直接对应 UseCase 的 name)

### 输入 1：用例脚手架 (UseCaseModel)
```json
{use_case_model.model_dump_json(indent=2)}
```

### 输入 2：知识事实库 (KnowledgeBase，用于补充细节)
```json
{knowledge.model_dump_json(indent=2)}
```

只返回 JSON。键名必须严格使用: system_name, modules, entities, roles, flows (flows 是数组，每个元素含 name, nodes, transitions)。transitions 元素含 from_state, action, to_state。
"""

    result = await safe_structured_invoke(prompt, SystemModel, model_type="default")
    if result is None:
        print("[SystemModeler] LLM returned no usable model, using empty SystemModel")
        return SystemModel()
    return result

