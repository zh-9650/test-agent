import asyncio
import os
from playwright.async_api import async_playwright

async def main():
    print("Launching Playwright...")
    async with async_playwright() as p:
        print("Launching Chromium...")
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await context.new_page()
        
        # Connect to IPv4 127.0.0.1
        print("Navigating to http://127.0.0.1:5173...")
        try:
            # Let's wait up to 10 seconds for the React app to fully render and bundle
            await page.goto("http://127.0.0.1:5173", wait_until="load", timeout=15000)
            await asyncio.sleep(5)  # wait an extra 5 seconds for full rendering
            
            print("Successfully loaded!")
            title = await page.title()
            print("Title:", title)
            
            screenshot_path = r"C:\Users\17381\.gemini\antigravity\brain\0dc0436b-72b2-46b3-8fb5-2966e8de2d91\frontend_loaded.png"
            await page.screenshot(path=screenshot_path)
            print(f"Screenshot saved to: {screenshot_path}")
            
            html = await page.content()
            print(f"HTML size: {len(html)} bytes")
            print("HTML Snippet:", html[:500])
        except Exception as e:
            print("Failed to load frontend:", e)
        finally:
            await browser.close()
            print("Browser closed.")

if __name__ == "__main__":
    asyncio.run(main())
