import json
from pydantic import BaseModel, Field
from core.llm_client import get_llm_client, safe_structured_invoke

class SystemMap(BaseModel):
    """Structured representation of the explored actual system."""
    pages: list[str] = Field(default_factory=list, description="Unique pages discovered (e.g., 'Order List Page', 'Login Page')")
    actions: list[str] = Field(default_factory=list, description="Interactive actions discovered (e.g., 'Click Create Order', 'Submit Approval')")
    forms: list[str] = Field(default_factory=list, description="Forms discovered (e.g., 'Login Form', 'Order Detail Form')")

async def generate_system_map(exploration_history: list[dict]) -> dict:
    """
    Generate a concrete System Map based on the actual UI exploration history.
    """
    if not exploration_history:
        return {"pages": [], "actions": [], "forms": []}
        
    llm = get_llm_client("default")
    
    # Summarize history to fit in prompt
    history_summary = ""
    for idx, page in enumerate(exploration_history[-10:]):  # Limit to last 10 pages to save tokens
        url = page.get("url", "Unknown")
        elements = page.get("interactive_elements", [])
        elems_summary = ", ".join([f"{el.get('role', 'elem')} '{el.get('name', '')}'" for el in elements[:15]])
        history_summary += f"Page {idx+1}: {url}\nElements: {elems_summary}\n\n"
        
    prompt = f"""
你是一位测试架构师。自动化探索智能体刚刚在真实系统中完成了一次探路。
请根据智能体探索到的页面历史和交互元素，绘制一张**真实的系统地图 (System Map)**。

### 探索历史与发现的页面元素:
{history_summary}

你需要提取出系统真实的：
1. pages: 实际发现的页面名称
2. actions: 实际发现的可操作动作（按钮、链接等）
3. forms: 实际发现的表单区域

请完全依据上面的"探索历史"提取，不要凭空猜测文档里有但实际上没找到的功能。

只返回 JSON。键名必须严格使用: pages, actions, forms (均为字符串数组)。
"""

    result = await safe_structured_invoke(prompt, SystemMap, model_type="default")
    if result is None:
        return {"pages": [], "actions": [], "forms": []}
    return result.model_dump()
