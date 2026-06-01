"""core/skills/goal_extractor.py — Node 3: Goal Generator.

L1 Pipeline Position:
  上游: N1.5 UseCaseModel (refined by N1.7)
  下游: Layer 2 Explorer 顺序执行
  本节点职责: 把每个 use_case 映射成一个带优先级的探索目标

NOTE (2026-06-01): removed dead code from V1.5 that duplicated the LLM path with
a deprecated `llm.with_structured_output` call.
"""
from pydantic import BaseModel, Field
from core.llm_client import safe_structured_invoke
from core.interfaces import ExplorationGoal


class ExplorationGoalList(BaseModel):
    """Structured extraction of exploration goals."""
    goals: list[ExplorationGoal] = Field(default_factory=list, description="List of specific exploration targets/goals to find in the UI")


async def extract_goals(use_case_model: dict, mode: str = "direct") -> list[ExplorationGoal]:
    """Node 3: Goal Generator.
    Maps each UseCase to one UI exploration target. Two modes:
    - "direct" (default): rule-based 1:1 mapping, no LLM cost. Fast and predictable.
    - "llm": LLM rewrites goals with priority + creative phrasing. Used when caller
      wants priority signal beyond a uniform "high".
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
                    priority="high",
                ))
        return goals

    prompt = f"""<role>
你是一位测试规划专家。你的唯一职责是为自动化探索智能体(Explorer)制定具体的"业务能力入口"探索目标。
</role>

<context>
你在 L1 流水线的末端。
- 上游: N1.5 UseCaseModel(已通过 N1.7 覆盖自检)
- 下游: Layer 2 Explorer 顺序消费 goals[] 列表
- 你的成功定义: Explorer 能直接照着 goals 列表在 UI 里"找入口",零回填
</context>

<task>
基于以下 UseCaseModel,为每个 use_case 生成一个探索目标(goal)+优先级(priority)。
</task>

<rules>
1. **唯一性硬约束**: 同一个 use_case.name **最多产生 1 个 goal**。禁止把同一个用例拆成多个目标。
2. **粒度反向约束**: 目标是"业务级寻路指令",如"找到创建并提交新采购申请的能力"。**禁止**细到 UI 级动作("点击红色提交按钮")。要给 Explorer 探索空间的自由度。
3. **priority 判定标准 (重要, 不是"合理就行")**:
   - `high` = 核心业务流(登录、支付、主 CRUD、删除/恢复等不可逆操作、状态机核心 transition)
   - `medium` = 支撑功能(修改密码、个人资料、查询列表、设置)
   - `low` = 边角功能(UI 偏好、关于我们、帮助文档)
4. **goal 文本格式**: 统一以"找到【{use_case.name}】的能力入口"开头,可补充一句"并在 UI 中验证其 trigger 条件"。
</rules>

<output_contract>
Return ONLY the following JSON object. No markdown fences. No explanation. No preamble.

{{
  "goals": [
    {{"goal": str, "priority": enum}}
  ]
}}

字段约束:
- `priority` ∈ {{"high", "medium", "low"}}
- `goals.length == use_cases.length` (1:1 映射,无重复无遗漏)
- `goal` 长度 ≤ 80 字
</output_contract>

### UseCaseModel
```json
{use_case_model}
```
"""
    result = await safe_structured_invoke(prompt, ExplorationGoalList, model_type="default")
    if result is None:
        return []
    return result.goals
