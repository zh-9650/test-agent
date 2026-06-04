"""用 Anthropic 原生 image 格式测 MiMo v2.5 多模态."""
import os, sys, base64
from pathlib import Path
PROJECT_ROOT = Path('.').resolve()
sys.path.insert(0, str(PROJECT_ROOT))
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from anthropic import Anthropic
client = Anthropic(
    api_key=os.environ['ANTHROPIC_AUTH_TOKEN'],
    base_url=os.environ['ANTHROPIC_BASE_URL'],
)

with open('hn.png', 'rb') as f:
    b64 = base64.b64encode(f.read()).decode('utf-8')
print(f"b64 len: {len(b64)}")

# Anthropic 原生格式
try:
    msg = client.messages.create(
        model=os.environ['ANTHROPIC_MODEL'],
        max_tokens=500,
        messages=[{
            'role': 'user',
            'content': [
                {
                    'type': 'image',
                    'source': {
                        'type': 'base64',
                        'media_type': 'image/png',
                        'data': b64,
                    },
                },
                {'type': 'text', 'text': '这张截图显示的是什么网站? 顶部第一篇文章的标题是什么? 用中文简洁回答.'},
            ],
        }],
    )
    print('Stop reason:', msg.stop_reason)
    for block in msg.content:
        print(f'  block type={block.type}')
        if block.type == 'text':
            print(f'    text: {block.text[:400]}')
        elif block.type == 'thinking':
            t = block.thinking if hasattr(block, 'thinking') else ''
            print(f'    thinking: {t[:300]}')
except Exception as e:
    print('FAIL:', type(e).__name__, str(e)[:500])
