import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        print("访问登录页面: http://192.168.31.155/login")
        await page.goto("http://192.168.31.155/login", wait_until="networkidle")
        
        print("输入账号: test_c")
        # 根据常规情况尝试定位用户名和密码框
        await page.fill('input[placeholder="请输入用户名"], input[type="text"], #username', "test_c")
        
        print("输入密码: 123456")
        await page.fill('input[placeholder="请输入密码"], input[type="password"], #password', "123456")
        
        print("点击登录按钮")
        await page.click('button[type="submit"], button:has-text("登录"), button:has-text("Login")')
        
        print("等待登录结果...")
        await page.wait_for_timeout(3000)
        
        title = await page.title()
        url = page.url
        print(f"当前页面标题: {title}")
        print(f"当前页面 URL: {url}")
        
        await page.screenshot(path="login_result.png")
        print("已保存截图至 login_result.png")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
