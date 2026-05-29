import asyncio
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.runtime import Runtime
from database.connection import init_database
from agents.ui.planning_graph import build_planning_graph

async def main():
    print("Initializing database...")
    await init_database()
    
    task_config = {
        "task_name": "Planning graph step check",
        "target_url": "http://192.168.31.155/login",
        "accounts": [{"role": "test", "username": "test_c", "password": "123456"}]
    }
    
    os.environ["MAX_EXPLORE_PAGES"] = "2" # reduce pages for quicker check
    os.environ["MAX_EXPLORE_MINUTES"] = "1"
    
    rt = Runtime(task_config)
    await rt._launch_browser()
    
    print("Building planning graph...")
    graph = build_planning_graph()
    
    state = rt._build_initial_state()
    
    print("Executing planning graph via astream...")
    try:
        async for update in graph.astream(state):
            print("\n--- GRAPH UPDATE RECEIVED ---")
            for node, content in update.items():
                print(f"Node completed: {node}")
                if content is not None:
                    print(f"Content keys: {list(content.keys())}")
                    if "messages" in content:
                        print(f"New Messages count: {len(content['messages'])}")
                    if "test_plan" in content:
                        print(f"Test plan generated: {len(content['test_plan'])} cases!")
                else:
                    print("Content: None")
    except Exception as e:
        print("Graph execution error:", e)
        import traceback
        traceback.print_exc()
    finally:
        await rt._close_browser()
        print("Browser closed.")

if __name__ == "__main__":
    asyncio.run(main())
