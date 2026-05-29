import os
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.tools import tool

load_dotenv()

llm = ChatAnthropic(
    model=os.getenv('ANTHROPIC_MODEL'),
    api_key=os.getenv('ANTHROPIC_AUTH_TOKEN'),
    base_url=os.getenv('ANTHROPIC_BASE_URL')
)

@tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

llm_with_tools = llm.bind_tools([add])
response = llm_with_tools.invoke("What is 2 + 3?")
print("Response content:", response.content)
print("Tool calls:", response.tool_calls)
