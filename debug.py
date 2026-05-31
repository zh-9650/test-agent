import asyncio
from core.runtime import Runtime

async def main():
    r = Runtime({
        "target_url": "https://demo.playwright.dev/todomvc/",
        "test_plan": [{"id": "TC-001", "title": "test", "expected": "test", "steps": ["test"]}]
    })
    async for update in r.run_stream():
        if isinstance(update, dict) and 'data' in update and 'screenshot' in update['data']:
            update['data']['screenshot'] = '<base64>'
        print(update)

if __name__ == "__main__":
    asyncio.run(main())
