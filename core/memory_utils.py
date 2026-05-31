"""core/memory_utils.py — Memory System utilities for retrieving and reflecting."""
import json
import re
from urllib.parse import urlparse
from sqlalchemy import and_, or_, select
from langchain_core.messages import HumanMessage

from core.llm_client import get_llm_client
from database.connection import async_session
from database.models import AgentMemory, TaskStep, Task

# Pattern to match URLs and bare IP addresses in text
_URL_PATTERN = re.compile(r'https?://\S+|ftp://\S+|(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?(?:/\S*)?')


def _sanitize_memory_value(text: str) -> str:
    """Strip any URLs from a memory value to prevent ghost-URL leakage."""
    return _URL_PATTERN.sub('', text).strip()

async def retrieve_memories(target_url: str, query_text: str = None) -> str:
    """Retrieve relevant memories for a target URL using Postgres Native Full-Text Search."""
    domain = urlparse(target_url).netloc or target_url
    print(f"[MemoryRetrieval] Retrieving memories for domain={domain}, target_url={target_url}")
    
    async with async_session() as session:
        # Bug fix: Use scope_type-aware filtering to prevent cross-domain memory leakage.
        # Instead of a simple scope_value IN (...), we pair each scope_type with its
        # expected scope_value to ensure domain memories don't leak across domains.
        sql = select(AgentMemory).where(
            or_(
                # Global memories: scope_type='global' and scope_value='*'
                and_(AgentMemory.scope_type == 'global', AgentMemory.scope_value == '*'),
                # Domain memories: scope_type='domain' and scope_value matches extracted domain
                and_(AgentMemory.scope_type == 'domain', AgentMemory.scope_value == domain),
                # URL-specific memories: scope_value matches the exact target URL
                AgentMemory.scope_value == target_url,
            )
        )
        
        if query_text:
            from sqlalchemy import text
            # Use simple dictionary to avoid dependency on zhparser, and use websearch_to_tsquery for loose matching
            # Also fallback to basic ILIKE for exact keyword matches if FTS misses
            keywords = [w for w in query_text.replace('"', ' ').replace("'", ' ').split() if len(w) > 1][:5]
            if keywords:
                # Build a simple OR query for text search
                tsquery_str = " | ".join(keywords)
                sql = sql.where(
                    text(f"(to_tsvector('simple', memory_value) @@ plainto_tsquery('simple', :tsq)) OR (memory_value ILIKE :like_kw)")
                ).params(tsq=tsquery_str, like_kw=f"%{keywords[0]}%")
                
        # Limit to top 10 most relevant/recent
        sql = sql.order_by(AgentMemory.updated_at.desc()).limit(10)
        
        result = await session.execute(sql)
        memories = result.scalars().all()
        
    if not memories:
        return ""
        
    mem_str = "\n## AI 测试记忆与知识库 (Global & Domain Knowledge)\n"
    mem_str += "以下是 AI 在过去的测试中总结出的系统经验与规则，请在测试时严格参考这些知识以避免踩坑：\n"
    mem_str += "⚠️ 警告：以下记忆中不包含任何可直接使用的 URL，请勿从记忆中复制或推测 URL 来进行导航。始终以当前任务提供的目标 URL 为准。\n"
    for m in memories:
        value = _sanitize_memory_value(m.memory_value) if m.scope_type == 'global' else m.memory_value
        mem_str += f"- [{m.scope_type.upper()}] {m.memory_key}: {value}\n"
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
        prompt += "⚠️ 重要规则：在 memory_value 中 **绝对不要包含任何 URL 或网址**（如 http://xxx, https://xxx）。只记录抽象的规则、教训和页面特征描述，不要记录具体的 URL 地址。\n"
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
                    raw_value = item.get("memory_value", "")
                    scope = item.get("scope_type", "domain")
                    # Sanitize global memories to strip any URLs the LLM may have included
                    if scope == "global":
                        raw_value = _sanitize_memory_value(raw_value)
                    mem = AgentMemory(
                        scope_type=scope,
                        scope_value="*" if scope == "global" else domain,
                        memory_key=item.get("memory_key", "Auto-learned rule"),
                        memory_value=raw_value
                    )
                    session.add(mem)
                await session.commit()
        except Exception as e:
            print(f"Reflection failed: {e}")
