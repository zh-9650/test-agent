"""core/memory_utils.py — Memory System utilities for retrieving and reflecting."""
import json
from urllib.parse import urlparse
from sqlalchemy import select
from langchain_core.messages import HumanMessage

from core.llm_client import get_llm_client
from database.connection import async_session
from database.models import AgentMemory, TaskStep, Task

async def retrieve_memories(target_url: str) -> str:
    """Retrieve relevant memories for a target URL."""
    domain = urlparse(target_url).netloc or target_url
    
    async with async_session() as session:
        query = select(AgentMemory).where(
            AgentMemory.scope_value.in_(['*', domain, target_url])
        )
        result = await session.execute(query)
        memories = result.scalars().all()
        
    if not memories:
        return ""
        
    mem_str = "\n## AI 测试记忆与知识库 (Global & Domain Knowledge)\n"
    mem_str += "以下是 AI 在过去的测试中总结出的系统经验与规则，请在测试时严格参考这些知识以避免踩坑：\n"
    for m in memories:
        mem_str += f"- [{m.scope_type.upper()}] {m.memory_key}: {m.memory_value}\n"
    return mem_str


async def reflect_on_task(task_id: int) -> None:
    """Analyze task steps and extract new memories."""
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if not task:
            return
            
        query = select(TaskStep).where(TaskStep.task_id == task_id).order_by(TaskStep.step_index)
        result = await session.execute(query)
        steps = result.scalars().all()
        
        failed_steps = [s for s in steps if s.assertion_result and s.assertion_result.get("status") == "fail"]
        
        if not failed_steps:
            return  # No failures to learn from
            
        domain = urlparse(task.target_url).netloc or task.target_url
        
        llm = get_llm_client("default") # use qwen-max
        prompt = "你是一个 AI 测试系统的记忆提炼模块。以下是最近一次测试任务中失败的步骤日志。\n"
        prompt += "请分析这些失败原因，总结出可避免未来重蹈覆辙的规则或页面特征。\n"
        prompt += "输出必须是合法的 JSON 数组，每个对象包含: 'scope_type' (填 'global' 或 'domain'), 'memory_key' (简短标识), 'memory_value' (具体规则/教训)。如果没有值得学习的，返回空数组 []。\n"
        prompt += f"当前 Domain: {domain}\n\n失败日志:\n"
        for s in failed_steps:
            prompt += f"步骤 {s.step_index}: 操作 {s.action_type} target={s.action_target}. 断言结果: {json.dumps(s.assertion_result, ensure_ascii=False)}\n"
            
        try:
            res = await llm.ainvoke([HumanMessage(content=prompt)])
            text = res.content if isinstance(res.content, str) else str(res.content)
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            
            data = json.loads(text.strip())
            if isinstance(data, list):
                for item in data:
                    mem = AgentMemory(
                        scope_type=item.get("scope_type", "domain"),
                        scope_value="*" if item.get("scope_type") == "global" else domain,
                        memory_key=item.get("memory_key", "Auto-learned rule"),
                        memory_value=item.get("memory_value", "")
                    )
                    session.add(mem)
                await session.commit()
        except Exception as e:
            print(f"Reflection failed: {e}")
