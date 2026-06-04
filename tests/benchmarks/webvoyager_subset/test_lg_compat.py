"""验证 MiMo AIMessage 能否被 LangGraph add_messages reducer 接受."""
import os, sys
from pathlib import Path
PROJECT_ROOT = Path('.').resolve()
sys.path.insert(0, str(PROJECT_ROOT))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from langgraph.graph import MessagesState, StateGraph, START, END
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

llm = ChatAnthropic(
    model=os.environ['ANTHROPIC_MODEL'],
    max_tokens=2000,
).bind_tools([{
    'name': 'click',
    'description': '点击元素',
    'input_schema': {
        'type': 'object',
        'properties': {'target': {'type': 'string'}},
        'required': ['target'],
    },
}])

class S(MessagesState):
    pass

def agent(state):
    r = llm.invoke(state['messages'])
    return {'messages': [r]}

g = StateGraph(S)
g.add_node('agent', agent)
g.add_edge(START, 'agent')
g.add_edge('agent', END)
graph = g.compile()

try:
    result = graph.invoke({
        'messages': [
            SystemMessage(content='你是测试工程师.'),
            HumanMessage(content='点击 #submit'),
        ]
    })
    print('OK, last message type:', type(result['messages'][-1]).__name__)
    print('tool_calls:', getattr(result['messages'][-1], 'tool_calls', None))
except Exception as e:
    import traceback
    print('FAIL:', type(e).__name__, str(e)[:300])
    traceback.print_exc()
