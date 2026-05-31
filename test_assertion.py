import asyncio
import os
from core.interfaces import TestCase, AssertionResult
from agents.ui.execution_graph import assert_node
from dotenv import load_dotenv

load_dotenv()

async def main():
    print("Testing assert_node...")
    
    # Mock state
    class MockChangeReport:
        url_changed = True
        url_before = "https://www.saucedemo.com/"
        url_after = "https://www.saucedemo.com/inventory.html"
        new_elements = ["产品列表"]
        gone_elements = ["登录按钮"]
        js_errors = []
        error_messages_visible = []
        modal_appeared = False
        
    test_case = TestCase(
        id="TC-001",
        title="登录测试",
        description="",
        steps=["输入用户名", "输入密码", "点击登录"],
        expected="登录成功并进入商品列表页"
    )
    
    state = {
        "test_plan": [test_case],
        "current_index": 0,
        "current_step": 3, # meaning we just executed step 3 (index 2)
        "tool_calls": [{"name": "click", "args": {"target": "#login-button"}}],
        "_last_change_report": MockChangeReport(),
        "page_info": {"url": "https://www.saucedemo.com/inventory.html", "title": "Swag Labs"},
        "consecutive_failures": 0
    }
    
    result = await assert_node(state)
    
    print("\n--- Assertion Result ---")
    assertion = result.get("_last_assertion")
    if assertion:
        print(f"Status: {assertion.status}")
        print(f"Reasoning: {assertion.reasoning}")
    else:
        print("No assertion returned!")

if __name__ == "__main__":
    asyncio.run(main())
