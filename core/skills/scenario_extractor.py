"""core/skills/scenario_extractor.py — 从 PRD 提取结构化业务场景。"""
from __future__ import annotations
from typing import Any
from core.llm_client import get_llm_client
from langchain_core.messages import HumanMessage
import json


async def extract_scenarios(
    prd: str,
    changelog: str = "",
    focus_areas: str = "",
    system_model: dict = None,
) -> list[dict]:
    """从 PRD 提取业务场景列表，用于 Goal-Driven 探索。"""
    if not prd and not changelog:
        return []
    
    context = ""
    if prd:
        context += f"## PRD 内容\n{prd[:3000]}\n\n"  # limit to 3000 chars
    if changelog:
        context += f"## 变更日志\n{changelog[:1000]}\n\n"
    if focus_areas:
        context += f"## 重点区域\n{focus_areas}\n\n"
    if system_model:
        context += f"## 提炼出的系统模型认知 (高优先级参考)\n{json.dumps(system_model, ensure_ascii=False, indent=2)}\n\n"
    
    prompt = f"""你是一个测试分析师。请从以下产品文档中提取核心业务场景列表。
每个场景代表一个用户可以完成的端到端业务流程。

{context}

请用严格的 JSON 数组格式输出，每个场景包含:
- "id": 场景编号（如 "S-001"）
- "name": 场景名称（如 "用户下单流程"）
- "entry_hint": 在页面上如何找到这个流程的入口（如 "寻找购物车或下单按钮"）
- "priority": "high" 或 "medium" 或 "low"

必须确保：
1. 所有的键（如 "id", "name"）必须用双引号包裹。
2. 只输出 JSON 数组，不要其他文字。如果文档内容不足以提取场景，返回空数组 []。"""

    try:
        llm = get_llm_client("haiku")
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        text = ""
        if isinstance(response.content, str):
            text = response.content
        elif isinstance(response.content, list):
            # Extract text block from multi-part message
            for block in response.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    break
            if not text:
                text = str(response.content)
        else:
            text = str(response.content)
            
        # Extract JSON block
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
            
        text = text.strip()
        try:
            scenarios = json.loads(text)
        except json.JSONDecodeError:
            import ast
            # Fallback for improperly quoted json (e.g. Python dict string)
            scenarios = ast.literal_eval(text)
            
        if isinstance(scenarios, list):
            print(f"[ScenarioExtractor] Extracted {len(scenarios)} scenarios: {[s.get('name', '') for s in scenarios]}")
            return scenarios
        return []
    except Exception as e:
        print(f"[ScenarioExtractor] Failed: {e}")
        # Print the text to see what was returned
        if 'text' in locals():
            print(f"[ScenarioExtractor] Raw output: {text}")
        return []
