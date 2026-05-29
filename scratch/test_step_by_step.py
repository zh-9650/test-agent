import asyncio
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.runtime import Runtime
from database.connection import init_database
from core.llm_client import get_llm_client
from agents.ui.planning_graph import build_planning_graph
from agents.ui.tools import get_current_page, ui_tools

async def main():
    print("1. Initializing database...")
    await init_database()
    
    print("2. Constructing Runtime...")
    task_config = {
        "task_name": "Step-by-step verification",
        "target_url": "http://192.168.31.155/login",
        "accounts": [{"role": "test", "username": "test_c", "password": "123456"}]
    }
    rt = Runtime(task_config)
    
    print("3. Launching browser...")
    await rt._launch_browser()
    print("Browser launched successfully!")
    print("Current page URL:", rt.page.url)
    
    print("4. Testing LLM Client initialization...")
    llm = get_llm_client("default")
    print("LLM client obtained:", type(llm))
    
    print("5. Extracting page semantics...")
    from core.page_semantic import extract_page_semantics, take_screenshot
    page_info = await extract_page_semantics(rt.page)
    print("Semantics extracted successfully!")
    print("Title:", page_info.get("title"))
    print("Number of interactive elements:", len(page_info.get("interactive_elements", [])))
    
    print("6. Calling LLM for first exploration decision...")
    from langchain_core.messages import SystemMessage, HumanMessage
    from agents.ui.prompts import get_exploration_system_prompt, _format_page_info
    
    system_prompt = get_exploration_system_prompt()
    page_summary = _format_page_info(page_info)
    human_msg = f"当前页面:\n{page_summary}\n请进行探索。"
    
    print("Sending request to LLM...")
    llm_with_tools = llm.bind_tools(ui_tools)
    response = await llm_with_tools.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_msg)
    ])
    
    print("LLM Response received!")
    print("Response Content Type:", type(response.content))
    print("Response Content:", response.content)
    print("Response Tool Calls:", response.tool_calls)
    
    print("7. Closing browser...")
    await rt._close_browser()
    print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
