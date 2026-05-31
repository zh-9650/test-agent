import re
import asyncio
from typing import Any
from playwright.async_api import async_playwright

URL_PATTERN = re.compile(r'https?://[^\s<>"\']+|(?:www\.)[^\s<>"\']+')

async def fetch_url_content(url: str) -> str:
    """Fetch text content from a URL using Playwright."""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            # Set a shorter timeout since we just want static text
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            
            # Wait a bit for JS frameworks to render
            await asyncio.sleep(2)
            
            # Extract inner text
            content = await page.evaluate("document.body.innerText")
            await browser.close()
            
            # Clean up excessive whitespace
            content = re.sub(r'\n{3,}', '\n\n', content)
            return f"\n--- 内容抓取自: {url} ---\n{content.strip()}\n--- 抓取结束 ---\n"
    except Exception as e:
        return f"\n--- 无法解析链接: {url} (错误: {str(e)}) ---\n"

async def parse_and_fetch_links(config: dict[str, Any]) -> dict[str, Any]:
    """
    Scan config fields for URLs and replace them with fetched content.
    Fields checked: prd, api_doc, changelog.
    """
    enriched_config = dict(config)
    fields_to_check = ["prd", "api_doc", "changelog"]
    
    for field in fields_to_check:
        text = enriched_config.get(field)
        if not text or not isinstance(text, str):
            continue
            
        urls = URL_PATTERN.findall(text)
        if not urls:
            continue
            
        # Deduplicate URLs
        urls = list(set(urls))
        
        # We only process the first 3 URLs per field to prevent timeouts
        extracted_texts = []
        for url in urls[:3]:
            # Ensure it has http prefix
            if url.startswith("www."):
                url = "https://" + url
                
            fetched = await fetch_url_content(url)
            extracted_texts.append(fetched)
            
        # Append the fetched content to the original text
        if extracted_texts:
            enriched_config[field] = text + "\n\n" + "\n".join(extracted_texts)
            
    return enriched_config
