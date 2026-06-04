"""验证 MiMo v2.5 多模态能力 (image input)."""
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

# 1. 找一张截图
import subprocess
subprocess.run(['python', '-c', '''
import asyncio
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        page = await b.new_page()
        await page.goto("https://news.ycombinator.com/", wait_until="domcontentloaded", timeout=30000)
        await page.screenshot(path="hn.png", type="png")
        await b.close()
asyncio.run(main())
'''], check=True)

with open('hn.png', 'rb') as f:
    b64 = base64.b64encode(f.read()).decode('utf-8')

print(f"Screenshot size: {len(b64)} bytes base64")

# 2. 发给 MiMo, 问截图里有什么
try:
    msg = client.messages.create(
        model=os.environ['ANTHROPIC_MODEL'],
        max_tokens=500,
        messages=[{
            'role': 'user',
            'content': [
                {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{b64}'}},
                {'type': 'text', 'text': '这张截图显示的是什么网站? 顶部第一篇文章的标题是什么? 用中文回答.'},
            ],
        }],
    )
    print('Stop reason:', msg.stop_reason)
    for block in msg.content:
        print(f'  block type={block.type}')
        if block.type == 'text':
            print(f'    text: {block.text[:300]}')
        elif block.type == 'thinking':
            print(f'    thinking: {block.thinking[:200] if hasattr(block, "thinking") else "N/A"}')
except Exception as e:
    print('FAIL:', type(e).__name__, str(e)[:500])
