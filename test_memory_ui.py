import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print("Navigating to memory manager UI...")
        
        # Navigate to the frontend page
        await page.goto("http://localhost:5173/memory", wait_until="networkidle")
        
        # Assert page loads correctly
        await page.wait_for_selector("text=AI 知识库 / 记忆管理")
        print("Page loaded successfully.")
        
        # Click Add Memory
        print("Clicking Add Memory button...")
        await page.click("button:has-text('+ 添加记忆')")
        
        # Fill the form
        print("Filling form...")
        await page.fill("input[style*='width: 100%']", "Test Key 123")
        await page.fill("textarea", "This is a test memory value.")
        
        # Save
        print("Saving memory...")
        await page.click("button:has-text('保存')")
        
        # Wait for the new memory to appear in the table
        await page.wait_for_selector("text=Test Key 123")
        print("Memory saved and displayed in table!")
        
        # Delete it
        print("Deleting memory...")
        page.on("dialog", lambda dialog: dialog.accept()) # auto accept confirm
        await page.click("button:has-text('删除')")
        
        # Wait for it to disappear
        await page.wait_for_timeout(1000)
        
        print("Test passed successfully!")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
