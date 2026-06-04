"""深入测试 MiMo v2.5 tool_use 能力."""
import os
from dotenv import load_dotenv
load_dotenv('.env')
from anthropic import Anthropic

client = Anthropic(
    api_key=os.environ['ANTHROPIC_AUTH_TOKEN'],
    base_url=os.environ['ANTHROPIC_BASE_URL'],
)

print('=== Test A: 工具调用 (max_tokens=2000) ===')
try:
    msg = client.messages.create(
        model=os.environ['ANTHROPIC_MODEL'],
        max_tokens=2000,
        tools=[{
            'name': 'click',
            'description': '点击页面上的元素',
            'input_schema': {
                'type': 'object',
                'properties': {'target': {'type': 'string', 'description': '元素编号如 #1'}},
                'required': ['target'],
            },
        }, {
            'name': 'input_text',
            'description': '在输入框中输入文字',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'target': {'type': 'string'},
                    'value': {'type': 'string'},
                },
                'required': ['target', 'value'],
            },
        }],
        system='你是一个测试工程师, 用工具操作 web 页面.',
        messages=[{'role': 'user', 'content': '在用户名输入框 (元素 #username) 输入 "test_c".'}],
    )
    print('Stop reason:', msg.stop_reason)
    print('Usage:', msg.usage)
    print('Content blocks:')
    for i, block in enumerate(msg.content):
        print(f'  [{i}] type={block.type}')
        if block.type == 'thinking':
            print(f'      text (first 200): {block.thinking[:200] if hasattr(block, "thinking") else "N/A"}')
        elif block.type == 'text':
            print(f'      text (first 200): {block.text[:200]}')
        elif block.type == 'tool_use':
            print(f'      name={block.name} input={block.input}')
except Exception as e:
    print('FAIL:', type(e).__name__, str(e)[:500])

print()
print('=== Test B: 不带 thinking 强制 tool_use (看模型是否懂 tool schema) ===')
try:
    msg = client.messages.create(
        model=os.environ['ANTHROPIC_MODEL'],
        max_tokens=1000,
        tools=[{
            'name': 'get_weather',
            'description': '获取天气',
            'input_schema': {
                'type': 'object',
                'properties': {'city': {'type': 'string'}},
                'required': ['city'],
            },
        }],
        messages=[{'role': 'user', 'content': '北京今天天气如何?'}],
    )
    print('Stop reason:', msg.stop_reason)
    for i, block in enumerate(msg.content):
        print(f'  [{i}] type={block.type}', end='')
        if block.type == 'text':
            print(f' text: {block.text[:150]}')
        elif block.type == 'tool_use':
            print(f' tool={block.name} input={block.input}')
        else:
            print()
except Exception as e:
    print('FAIL:', type(e).__name__, str(e)[:300])

print()
print('=== Test C: 看模型 metadata / 支持的能力 ===')
# 一些 Anthropic 兼容端点会暴露额外信息
try:
    msg = client.messages.create(
        model=os.environ['ANTHROPIC_MODEL'],
        max_tokens=50,
        messages=[{'role': 'user', 'content': 'hi'}],
    )
    print('Model:', msg.model)
    print('Type:', msg.type)
    print('ID:', msg.id)
except Exception as e:
    print('FAIL:', e)
