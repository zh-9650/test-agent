import json
from pydantic import BaseModel, Field
from core.llm_client import get_llm_client, safe_structured_invoke
from core.interfaces import KnowledgeBase

async def extract_knowledge(prd_content: str, api_doc_content: str, changelog_content: str) -> KnowledgeBase:
    """
    Node 1: Knowledge Extraction.
    Extracts hard facts, business rules, entities, roles, and constraints without summarizing.
    """
    prompt = f"""
你是一个极其严谨的"可追溯知识提取器"。你的任务是阅读以下系统文档，精确提取出所有的核心事实，并**提供严格的原文证据**。
请严格遵守以下【第一原则】：
1. 绝对不要做摘要（Summary）！测试代理需要的是事实，不是概括。
2. 提取必须精准到具体名词、边界值、阈值和条件约束。
3. 【冲突处理原则】：当 PRD 与 Swagger 存在冲突时，必须绝对以 PRD 为准。
4. 【死无对证防范原则】：每一条提取出的知识（KnowledgeItem）必须包含以下信息：
   - text: 知识点本身的描述
   - source: 数据来源（'prd', 'swagger', 'changelog', 或 'inferred'）
   - quote: 能够证明该知识点的一小段【原文引用】（必须能精准用 Ctrl+F 在原文找到！如果 source 是 inferred，请写明推断理由）
   - confidence: 置信度 (0.0 - 1.0)。如果发现文档有矛盾但你被迫做出选择，请降低置信度。

请提取以下维度的信息，如果不包含某类信息请保留空数组，绝对不要无中生有：
1. business_rules: 提取所有的业务逻辑规则（如：金额>5000需要总监审批）。
2. roles: 系统中定义的所有用户角色。
3. entities: 核心业务实体（如：采购单、订单、用户账号）。
4. constraints: 发现的所有阈值与硬性约束。
5. raw_facts: 无法归类到上面但明显是客观事实的陈述。

### 产品需求文档 (PRD)
{prd_content or "未提供"}

### 接口文档 / Swagger
{api_doc_content or "未提供"}

### 变更日志 (Changelog)
{changelog_content or "未提供"}

只返回 JSON。键名必须严格使用: business_rules, roles, entities, constraints, raw_facts (均为数组)。每个元素字段名严格使用: text, source, quote, confidence。
"""

    empty = KnowledgeBase(business_rules=[], roles=[], entities=[], constraints=[], raw_facts=[])
    result = await safe_structured_invoke(prompt, KnowledgeBase, model_type="default")
    if result is None:
        print("[KnowledgeExtractor] LLM returned no usable knowledge, using empty KnowledgeBase")
        return empty
    return result
