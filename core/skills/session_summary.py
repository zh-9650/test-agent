"""core/skills/session_summary.py — Case 结束后生成结构化摘要。"""
from __future__ import annotations
from typing import Any
from core.llm_client import get_llm_client
from langchain_core.messages import HumanMessage
import json


async def generate_case_summary(
    test_case_id: str,
    test_case_title: str,
    status: str,
    steps: list,
    page_urls: list[str] | None = None,
) -> dict:
    """调用 LLM 将 Case 执行结果压缩为简短摘要。"""
    steps_text = ""
    for s in steps[:10]:  # limit to 10 steps
        action = getattr(s, 'action_type', '') or ''
        target = getattr(s, 'action_target', '') or ''
        result = getattr(s, 'result', '') or ''
        assertion_status = ''
        if hasattr(s, 'assertion') and s.assertion:
            assertion_status = s.assertion.status
        steps_text += f"  - {action}({target}) → {result[:80]} [{assertion_status}]\n"
    
    prompt = f"""你是一个测试记录压缩器。请将以下测试用例的执行过程压缩为一段简短摘要（不超过 100 字）。

用例: {test_case_id} - {test_case_title}
状态: {status}
执行步骤:
{steps_text}
访问过的页面: {', '.join(page_urls[:5]) if page_urls else '未知'}

请用 JSON 格式输出:
{{
  "case_id": "{test_case_id}",
  "status": "{status}",
  "summary": "一句话描述做了什么和结果",
  "key_findings": ["发现1", "发现2"]
}}

只输出 JSON，不要其他文字。"""

    try:
        llm = get_llm_client("haiku")
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        # Handle list response (e.g., [{'text': '...', 'type': 'text'}, {'thinking': '...', 'type': 'thinking'}])
        content = response.content
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                    elif item.get("type") == "thinking":
                        continue  # skip thinking blocks
                elif isinstance(item, str):
                    text_parts.append(item)
            text = " ".join(text_parts).strip()
        elif isinstance(content, str):
            text = content
        else:
            text = str(content)
        # Try to parse JSON
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        try:
            result = json.loads(text.strip())
        except json.JSONDecodeError:
            import ast
            result = ast.literal_eval(text.strip())
        if isinstance(result, dict):
            print(f"[SessionSummary] Case {test_case_id}: {result.get('summary', '')}")
            return result
        else:
            # If result is not a dict, wrap it
            return {
                "case_id": test_case_id,
                "status": status,
                "summary": str(result)[:100],
                "key_findings": []
            }
    except Exception as e:
        print(f"[SessionSummary] Failed for {test_case_id}: {e}")
        return {
            "case_id": test_case_id,
            "status": status,
            "summary": f"{test_case_title} - {status}",
            "key_findings": []
        }
