from pydantic import BaseModel, Field
from core.llm_client import get_llm_client, safe_structured_invoke
from core.interfaces import ExplorationGoal

class ExplorationGoalList(BaseModel):
    """Structured extraction of exploration goals."""
    goals: list[ExplorationGoal] = Field(default_factory=list, description="List of specific exploration targets/goals to find in the UI")

async def extract_goals(use_case_model: dict, mode: str = "direct") -> list[ExplorationGoal]:
    """
    Node 3: Goal Generator.
    Extract specific exploration goals (what to click/find) directly from the UseCaseModel.
    This drives the Goal-Driven Explorer by mapping each UseCase to a UI exploration target.
    """
    if not use_case_model or "use_cases" not in use_case_model:
        return []

    if mode == "direct":
        print("[GoalExtractor] Using direct mapping mode for goals.")
        goals = []
        for uc in use_case_model.get("use_cases", []):
            name = uc.get("name", "")
            if name:
                goals.append(ExplorationGoal(
                    goal=f"找到【{name}】的能力入口",
                    priority="high"
                ))
        return goals

    prompt = f"""
你是一位测试规划专家。请基于以下提炼出的"用例模型 (UseCase Model)"，
为自动化探索智能体（Explorer）制定具体的页面探索目标（Goals）。

UseCase Model:
{use_case_model}

请分析上述系统中的 `use_cases`。原则上，系统里的每一个用例 (UseCase) 都应该对应一个在 UI 页面上的"入口"或"操作流"。
请输出一系列具体的"寻找业务能力入口"目标。
例如如果用例 name 是"提交采购申请"，那么探索目标应该是"找到创建并提交新采购申请的能力"。

要求：
1. 目标必须是具体的、可操作的业务级寻路指令。
2. 禁止输出极其具体的 UI 级动作（如"点击红色提交按钮"）。要给 Explorer 探索空间的自由度。
3. 请为每个目标分配合理的优先级 (high, medium, low)。

只返回 JSON。键名必须严格使用: goals (数组)。每个元素含字段: goal, priority。
"""

    result = await safe_structured_invoke(prompt, ExplorationGoalList, model_type="default")
    if result is None:
        return []
    return result.goals
        
    if mode == "direct":
        print("[GoalExtractor] Using direct mapping mode for goals.")
        goals = []
        for uc in use_case_model.get("use_cases", []):
            name = uc.get("name", "")
            if name:
                goals.append(ExplorationGoal(
                    goal=f"找到【{name}】的能力入口",
                    priority="high"
                ))
        return goals

    llm = get_llm_client("default")
    
    prompt = f"""
你是一位测试规划专家。请基于以下提炼出的“用例模型 (UseCase Model)”，
为自动化探索智能体（Explorer）制定具体的页面探索目标（Goals）。

UseCase Model:
{use_case_model}

请分析上述系统中的 `use_cases`。原则上，系统里的每一个用例 (UseCase) 都应该对应一个在 UI 页面上的“入口”或“操作流”。
请输出一系列具体的“寻找业务能力入口”目标。
例如如果用例 name 是“提交采购申请”，那么探索目标应该是“找到创建并提交新采购申请的能力”。

要求：
1. 目标必须是具体的、可操作的业务级寻路指令。
2. 禁止输出极其具体的 UI 级动作（如“点击红色提交按钮”）。要给 Explorer 探索空间的自由度。
3. 请为每个目标分配合理的优先级 (high, medium, low)。
"""
    
    llm_with_struct = llm.with_structured_output(ExplorationGoalList)
    try:
        result = await llm_with_struct.ainvoke(prompt)
        if result is None:
            return []
        return result.goals
    except Exception as e:
        print(f"[GoalExtractor] Error: {e}")
        return []
