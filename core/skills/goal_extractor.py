from pydantic import BaseModel, Field
from core.llm_client import get_llm_client

class ExplorationGoals(BaseModel):
    """Structured extraction of exploration goals."""
    goals: list[str] = Field(default_factory=list, description="List of specific exploration targets/goals to find in the UI")

async def extract_goals(system_model: dict) -> list[str]:
    """
    Extract specific exploration goals (what to click/find) from the System Model.
    This drives the Goal-Driven Explorer.
    """
    if not system_model:
        return []
        
    llm = get_llm_client("default")
    
    prompt = f"""
你是一位测试规划专家。请基于以下提炼出的系统建模信息（System Model），
为自动化探索智能体（Explorer）制定具体的探索目标（Goals）。

System Model:
{system_model}

请分析上述系统中的 `business_flows` 和 `roles`，并输出一系列具体的“寻找入口”目标。
例如：
- "找到采购订单创建入口"
- "寻找部门主管审批待办列表"
- "找到驳回按钮或相关功能"
- "找到财务打款确认入口"

要求：
1. 目标必须是具体的、可操作的寻路指令。
2. 这些目标将指导 UI Agent 在页面上寻找对应功能。
"""
    
    llm_with_struct = llm.with_structured_output(ExplorationGoals)
    try:
        result = await llm_with_struct.ainvoke(prompt)
        if result is None:
            return []
        return result.goals
    except Exception as e:
        print(f"[GoalExtractor] Error: {e}")
        return []
