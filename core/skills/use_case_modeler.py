import json
from pydantic import BaseModel
from core.llm_client import get_llm_client, safe_structured_invoke
from core.interfaces import KnowledgeBase, UseCaseModel

async def generate_use_case_model(knowledge: KnowledgeBase) -> UseCaseModel:
    """
    Node 1.5: Use Case Modeling.
    Acts as a cognitive scaffold, bridging the flat KnowledgeBase to the SystemModel state machine.
    """
    prompt = f"""
你是一个专业的系统分析师。你的任务是将零碎的"事实库"组装成"用例模型 (UseCase Model)"。
用例模型是沟通零散规则和整体系统状态机的桥梁。

请仔细阅读以下提取出的结构化事实库 (KnowledgeBase)，分析其中的 roles, entities 和 business_rules：
```json
{knowledge.model_dump_json(indent=2)}
```

基于以上信息，请推导并输出该系统所有的业务用例 (UseCase)。
对于每个用例，你必须明确：
1. name: 用例名称（如 '提交采购申请'）
2. actor: 执行该用例的角色（必须在 roles 列表中）
3. trigger: 触发该用例的前置状态或条件（如 '申请单处于草稿状态'）
4. outcome: 执行后的业务结果或状态变化（如 '申请单状态变为待审批'）
5. related_rules: 列出与此用例强相关的 business_rules 描述

注意：
- 用例应当是粗粒度的业务操作，不要精细到"点击某个特定按钮"。
- 请确保覆盖所有的核心流转动作。

只返回 JSON。键名必须严格使用: use_cases (数组), 每个元素的字段名必须严格使用: name, actor, trigger, outcome, related_rules。
"""

    result = await safe_structured_invoke(prompt, UseCaseModel, model_type="default")
    if result is None or not result.use_cases:
        print("[UseCaseModeler] LLM returned no usable use cases, falling back to empty UseCaseModel")
        return UseCaseModel(use_cases=[])
    return result
