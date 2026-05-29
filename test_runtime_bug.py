import asyncio
from langchain_core.messages import AIMessage
from agents.ui.planning_graph import explore_execute_node
from agents.ui.tools import set_current_page

class MockLocator:
    async def fill(self, value, timeout=None):
        pass

class MockPage:
    def get_by_label(self, label):
        class MockResult:
            async def count(self): return 0
        return MockResult()
    def get_by_role(self, role, name=None):
        class MockResult:
            async def count(self): return 0
        return MockResult()
    def get_by_text(self, text, exact=False):
        class MockResult:
            async def count(self): return 0
        return MockResult()
    def get_by_placeholder(self, text):
        class MockResult:
            async def count(self): return 0
        return MockResult()
    def locator(self, text):
        class MockResult:
            async def count(self): return 0
        return MockResult()

async def run_test():
    set_current_page(MockPage())
    
    # Mock an AI message with a tool call
    ai_msg = AIMessage(
        content=[{"type": "thinking", "thinking": "Let's login."}, {"type": "tool_use", "name": "input_text", "input": {"target": "#1", "value": "test_c"}, "id": "call_123"}],
        tool_calls=[{"name": "input_text", "args": {"target": "#1", "value": "test_c"}, "id": "call_123"}]
    )
    
    state = {
        "messages": [ai_msg],
        "page_info": {},
        "task_config": {}
    }
    
    result = await explore_execute_node(state)
    print("explore_execute_node result:", result)
    
    # Simulate _stream_items and runtime logic
    messages = result.get("messages", [])
    if messages:
        msg = messages[-1]
        tool_name = getattr(msg, "name", getattr(msg, "tool_name", "未知"))
        result_text = msg.content if isinstance(msg.content, str) else str(msg.content)
        print("tool_name:", repr(tool_name))
        print("result_text:", repr(result_text))

if __name__ == "__main__":
    asyncio.run(run_test())
