import asyncio
from playwright.async_api import async_playwright

async def main():
    print("Launching Playwright...")
    async with async_playwright() as p:
        print("Launching Chromium...")
        browser = await p.chromium.launch(headless=True)
        print("Creating context...")
        context = await browser.new_context()
        print("Creating page...")
        page = await context.new_page()
        
        print("Navigating to http://192.168.31.155/login...")
        try:
            # Set a 5-second timeout for the navigation to see if it responds quickly
            await page.goto("http://192.168.31.155/login", wait_until="networkidle", timeout=5000)
            print("Navigation successful!")
            print("Page Title:", await page.title())
            html = await page.content()
            print("HTML Length:", len(html))
        except Exception as e:
            print("Navigation failed:", e)
        finally:
            await browser.close()
            print("Browser closed.")

if __name__ == "__main__":
    asyncio.run(main())
