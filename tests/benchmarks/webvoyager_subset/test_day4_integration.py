"""Day 4 integration test — extract_page_semantics persists backendNodeId to BackendNodeMap."""
import asyncio
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import core.backend_node_map as backend_node_map  # type: ignore
from core.page_semantic import extract_page_semantics


async def main():
    backend_node_map.clear_all()
    task_id = "day4-integration"

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                await page.goto("https://news.ycombinator.com/", wait_until="domcontentloaded", timeout=30000)
                # Phase 2.0D: 传 task_id 触发 backendNodeId 持久化
                page_info = await extract_page_semantics(page, task_id=task_id, current_step=0)
                assert page_info is not None
                entries = backend_node_map.get_all(task_id)
                print(f"Persisted entries: {len(entries)}")
                assert len(entries) > 0, "Expected at least one backendNodeId persisted"

                # Verify a few entries have reasonable backend_node_id
                for eid, ent in list(entries.items())[:3]:
                    print(f"  {eid} → backendNodeId={ent['backend_node_id']} attrs={ent['attrs']}")
                    assert ent["backend_node_id"] > 0
                    assert ent["last_seen_step"] == 0

                # Verify second observation updates last_seen_step
                await extract_page_semantics(page, task_id=task_id, current_step=5)
                snap = backend_node_map.get_all(task_id)
                for ent in snap.values():
                    assert ent["last_seen_step"] == 5

                print("\n[OK] Day 4 integration: backendNodeId persistence works end-to-end")
            finally:
                await browser.close()
    finally:
        backend_node_map.clear_all()


if __name__ == "__main__":
    asyncio.run(main())
