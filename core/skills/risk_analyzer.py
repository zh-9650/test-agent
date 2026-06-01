"""core/skills/risk_analyzer.py — 风险分析器：识别高风险元素并输出结构化风险点。

在探索完毕、生成用例前调用。接收页面元素 + 文档上下文，输出风险点列表，
引导 Planner 生成更高价值的边界值/安全测试用例。
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from core.llm_client import get_llm_client

class RiskPoint(BaseModel):
    element: str = Field(description="对应交互元素列表中的 id 或特征描述")
    risk_type: str = Field(description="为什么认为它是高风险点（如 '涉及金额计算'）")
    severity: str = Field(description="'high' 或 'medium' 或 'low'")
    suggestions: list[str] = Field(default_factory=list, description="建议的测试场景列表（如 ['输入负数', '输入超大金额', '输入特殊字符']）")

class RiskAnalysisOutput(BaseModel):
    risk_points: list[RiskPoint] = Field(default_factory=list, description="提取出的风险点列表")


async def analyze_risks(
    page_elements: list[dict[str, Any]],
    swagger: str = "",
    prd: str = "",
) -> list[dict[str, Any]]:
    """调用 LLM 分析页面元素的风险点。

    Args:
        page_elements: 探索阶段收集的所有交互元素列表
        swagger: Swagger/API 文档文本（可选）
        prd: PRD 文档文本（可选）

    Returns:
        风险点列表，每项包含 element, risk_type, suggestions
    """
    if not page_elements:
        return []

    # 格式化元素列表（限制数量避免 token 爆炸）
    elements_text = ""
    for el in page_elements[:40]:
        el_type = el.get("type", "")
        label = el.get("label", "") or el.get("text", "") or el.get("placeholder", "")
        el_id = el.get("id", "")
        elements_text += f"  - {el_id}: {el_type} - {label}\n"

    doc_context = ""
    if prd:
        doc_context += f"\n## PRD 摘要\n{prd[:2000]}\n"
    if swagger:
        doc_context += f"\n## 接口文档摘要\n{swagger[:2000]}\n"

    prompt = f"""你是一个安全与质量保证专家。请分析以下系统的页面信息和 API 文档，找出最容易出问题、需要重点测试的高风险元素。
例如：支付金额输入框、提交订单按钮、删除按钮、带有复杂校验的表单项。

{doc_context}

## 页面元素列表
{elements_text}

请提取高风险点，并为每个高风险点提供建议的测试场景（如 ["输入负数", "输入超大金额", "输入特殊字符"]）。如果没有高风险点，返回空列表。"""

    try:
        llm = get_llm_client("haiku")
        llm_with_struct = llm.with_structured_output(RiskAnalysisOutput)
        response = await llm_with_struct.ainvoke(prompt)
        
        if response and response.risk_points:
            risk_points = [rp.model_dump() for rp in response.risk_points]
            print(f"[RiskAnalyzer] Identified {len(risk_points)} risk points")
            return risk_points
        return []
    except Exception as e:
        print(f"[RiskAnalyzer] Failed: {e}")
        return []
