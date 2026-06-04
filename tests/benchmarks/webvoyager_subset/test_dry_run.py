"""WebVoyager benchmark dry-run smoke test — verify structure & Playwright integration.
不调 LLM, 仅验证: 浏览器能起 / extract_page_semantics 能跑 / 状态正确写入.
"""
import asyncio
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.benchmarks.webvoyager_subset.runner import load_tasks, run_single_task


async def main():
    tasks = load_tasks()
    # 选最简单的题 (Hacker News, 6 步)
    task = next(t for t in tasks if t["id"] == "WV-007")
    print(f"Running dry-run on {task['id']} ({task['site']})...")
    result = await run_single_task(task, dry_run=True)
    print(f"Result: {result}")
    assert result["status"] == "dry_run", f"Expected dry_run, got {result['status']}"
    assert "page_info" in result
    assert result["page_info"].get("url"), "page_info.url should be populated"
    assert "ycombinator" in result["page_info"]["url"].lower(), f"URL not Hacker News: {result['page_info']}"
    assert "hacker" in result["page_info"]["title"].lower(), f"title not Hacker News: {result['page_info']}"
    print(f"\n[OK] dry-run passed: url={result['page_info']['url']} title={result['page_info']['title']!r}")


if __name__ == "__main__":
    asyncio.run(main())
