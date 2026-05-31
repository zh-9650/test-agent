import asyncio
import os
import sys

from core.runtime import Runtime

async def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    r = Runtime({
        "target_url": "https://demo.playwright.dev/todomvc/",
        # No test_plan provided, so it must explore and generate one
    })
    try:
        async for update in r.run_stream():
            if isinstance(update, dict) and 'data' in update and 'screenshot' in update['data']:
                update['data']['screenshot'] = '<base64>'
            print(update)
    except Exception as e:
        print(f"EXCEPTION: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
