import asyncio
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.runtime import Runtime
from database.connection import init_database
from core.interfaces import TestCase, Setup
from agents.ui.execution_graph import build_execution_graph

async def main():
    print("Initializing database...")
    await init_database()
    
    # Configure test case for Login Verification
    test_case = TestCase(
        id="TC-001",
        title="用户登录验证",
        description="使用 test_c 账号进行登录，并验证是否成功进入系统",
        preconditions=[],
        steps=[
            "在用户名输入框中输入 test_c",
            "在密码输入框中输入 123456",
            "点击登录按钮进行登录",
            "等待页面跳转并验证登录状态"
        ],
        expected="成功登录系统并进入主页"
    )
    
    task_config = {
        "task_name": "Execution graph single check",
        "target_url": "http://192.168.31.155/login",
        "accounts": [{"role": "test", "username": "test_c", "password": "123456"}],
    }
    
    rt = Runtime(task_config)
    await rt._launch_browser()
    
    print("Building execution graph...")
    graph = build_execution_graph()
    
    # Build initial execution state for this test case
    state = rt._build_initial_state()
    state["test_plan"] = [test_case]
    state["current_index"] = 0
    
    print("Executing execution graph via astream...")
    try:
        async for update in graph.astream(state):
            print("\n--- EXECUTION GRAPH UPDATE RECEIVED ---")
            for node, content in update.items():
                print(f"Node completed: {node}")
                if content is not None:
                    if "current_step" in content:
                        print(f"  Current Step Index: {content['current_step']}")
                    if "_last_tool_result" in content:
                        print(f"  Tool Execution Result: {content['_last_tool_result']}")
                    if "_last_change_report" in content and content["_last_change_report"] is not None:
                        rep = content["_last_change_report"]
                        print(f"  Change Report: URL Changed={rep.url_changed}, New Elements={len(rep.new_elements)}, Modal={rep.modal_appeared}")
                    if "_last_assertion" in content and content["_last_assertion"] is not None:
                        assert_res = content["_last_assertion"]
                        print(f"  Semantic Assertion: Status={assert_res.status}, Reasoning={assert_res.reasoning}")
                    if "_collected_steps" in content:
                        print(f"  Steps collected: {len(content['_collected_steps'])}")
    except Exception as e:
        print("Graph execution error:", e)
        import traceback
        traceback.print_exc()
    finally:
        await rt._close_browser()
        print("Browser closed.")

if __name__ == "__main__":
    asyncio.run(main())
