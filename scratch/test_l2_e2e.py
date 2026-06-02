"""scratch/test_l2_e2e.py — Layer 2 端到端冒烟测试 (V2.0 A, 2026-06-02).

跟 scratch/test_layer1.py 一样是手动可跑的 e2e 脚本, 但目标换成 L2 execution_graph
+ 公开可访问的 practice.expandtesting.com。

运行:
    $env:PYTHONIOENCODING = "utf-8"; $env:PYTHONUTF8 = "1"; [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    python scratch/test_l2_e2e.py

设计:
- 走 LangGraph execution_graph 的 observe→decide→execute→assert→record 全流程
- 1 个简单用例: 登录 practice.expandtesting.com 并跳转到 /secure
- 验证: 至少 1 个 step, 最终 assertion 为 pass/inconclusive, 不出现浏览器崩溃
- 故意设短 max_steps (5) 避免长跑, 跑出来只验"启动+主流程", 完整 e2e 留给 Layer 1 → L2 集成

Best practice 依据 (V2.0 调研, 2026-06-02):
- Anthropic 2026 prompt engineering: e2e 测试是 contract validation 终极手段
- LangGraph 2026 production: astream() 逐节点观察状态
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Force UTF-8 (Windows 中文安全)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import SystemMessage
from playwright.async_api import async_playwright

from agents.ui.execution_graph import build_execution_graph
from agents.ui.tools import set_current_page, set_current_task, cleanup_task_context
from core.interfaces import Setup, TestCase

# V2.0 A (2026-06-02): e2e 跑前先 init 数据库, 避免 retrieve_memories 撞 "table not found"
try:
    from database.connection import init_database
    log_path = "[boot] init_database()"
    import asyncio
    asyncio.run(init_database())
    print(log_path, "ok")
except Exception as e:
    print(f"[boot] init_database 跳过 ({e})")


# ---------------------------------------------------------------------------
# 默认配置: practice.expandtesting.com (公开测试站, 凭据 practice / SuperSecretPassword!)
# ---------------------------------------------------------------------------

DEFAULT_URL = "https://practice.expandtesting.com/login"
DEFAULT_USERNAME = "practice"
DEFAULT_PASSWORD = "SuperSecretPassword!"


def build_test_case_and_setups() -> tuple[TestCase, dict[str, Setup], dict]:
    """构造 1 个 test case + 1 个 setup + task_config."""
    test_case = TestCase(
        id="TC-L2-001",
        title="登录并跳转到 /secure",
        description=f"用 {DEFAULT_USERNAME}/{DEFAULT_PASSWORD} 登录, 验证跳转到 /secure 并显示 'You logged into a secure area!'",
        preconditions=[],
        steps=["打开登录页", "输入用户名", "输入密码", "点击登录按钮", "验证跳转到 /secure"],
        expected="成功跳转到 https://practice.expandtesting.com/secure 并看到 You logged into a secure area!",
        priority="high",
        category="functional",
    )
    setups: dict[str, Setup] = {}
    task_config = {
        "target_url": DEFAULT_URL,
        "accounts": [
            {"role": "测试员", "username": DEFAULT_USERNAME, "password": DEFAULT_PASSWORD}
        ],
        "session_summary": "",  # V2.0 A3: 第一个 case, 无前序摘要
    }
    return test_case, setups, task_config


async def run_e2e(quiet: bool = False) -> dict:
    """运行 1 个 L2 test case, 走完整 execution_graph, 返回最终结果。"""
    test_case, setups, task_config = build_test_case_and_setups()

    def log(msg: str) -> None:
        if not quiet:
            print(msg)

    log("=" * 60)
    log("🚀 Layer 2 E2E 冒烟测试 (V2.0 A 2026-06-02)")
    log(f"目标: {DEFAULT_URL}")
    log(f"凭据: {DEFAULT_USERNAME} / {DEFAULT_PASSWORD}")
    log(f"用例: {test_case.id} - {test_case.title}")
    log("=" * 60)

    # 短 max_steps 避免长跑
    os.environ["MAX_STEPS_PER_CASE"] = "5"
    os.environ["MAX_CONSECUTIVE_FAILURES"] = "3"

    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True)
    context = await browser.new_context()
    page = await context.new_page()

    # 先导航到目标 URL (跟 runtime._execute_test_case_stream 行为一致)
    log(f"\n[boot] 导航到 {DEFAULT_URL} ...")
    try:
        await page.goto(DEFAULT_URL, wait_until="domcontentloaded", timeout=20000)
        log(f"[boot] 已到达 {page.url}")
    except Exception as e:
        log(f"[boot] 导航失败: {e}")

    task_id = "l2-e2e-task-001"
    set_current_task(task_id)
    set_current_page(page, task_id=task_id)

    # 初始 state
    state = {
        "task_id": task_id,
        "test_plan": [test_case],
        "setups": setups,
        "current_index": 0,
        "current_step": 0,
        "results": [],
        "consecutive_failures": 0,
        "page_info": {},
        "screenshot": "",
        "state_before": {},
        "state_after": {},
        "screenshot_after": "",
        "_collected_steps": [],
        "_last_tool_result": "",
        "_last_change_report": None,
        "_last_assertion": None,
        "task_config": task_config,
        "session_summary": task_config.get("session_summary", ""),
        "messages": [SystemMessage(content=f"开始执行测试用例: {test_case.id} - {test_case.title}")],
    }

    graph = build_execution_graph()
    final_state: dict = {}
    node_visits: list[str] = []

    start = time.time()
    try:
        async for event in graph.astream(state):
            for node_name, node_state in (event.items() if isinstance(event, dict) else []):
                if not isinstance(node_state, dict):
                    continue
                node_visits.append(node_name)
                final_state.update(node_state)
                if node_name == "decide":
                    msgs = node_state.get("messages", [])
                    if msgs:
                        last = msgs[-1]
                        content = getattr(last, "content", "")
                        tool_calls = getattr(last, "tool_calls", [])
                        log(f"  [decide] {content[:80]!r} tool_calls={len(tool_calls)}")
                elif node_name == "execute":
                    log(f"  [execute] result={node_state.get('_last_tool_result', '')[:80]!r}")
                elif node_name == "assert":
                    ar = node_state.get("_last_assertion")
                    log(f"  [assert] {ar.status if ar else 'no-assertion'}: {ar.reasoning[:80] if ar else ''!r}")
                elif node_name == "record":
                    pass
                elif node_name == "observe":
                    pi = node_state.get("page_info", {})
                    log(f"  [observe] url={pi.get('url','')[:60]} elements={len(pi.get('interactive_elements', []))}")
    except Exception as e:
        log(f"❌ 异常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await browser.close()
        await p.stop()
        cleanup_task_context(task_id)

    duration = time.time() - start

    # 汇总
    steps = final_state.get("_collected_steps", [])
    final_assertion = None
    if steps and steps[-1].assertion:
        final_assertion = steps[-1].assertion

    log("\n" + "=" * 60)
    log("📊 L2 E2E 结果汇总")
    log("=" * 60)
    log(f"  Duration: {duration:.2f}s")
    log(f"  Node visits: {node_visits}")
    log(f"  Steps collected: {len(steps)}")
    log(f"  current_step: {final_state.get('current_step', 0)}")
    log(f"  consecutive_failures: {final_state.get('consecutive_failures', 0)}")
    if final_assertion:
        log(f"  Final assertion: {final_assertion.status} - {final_assertion.reasoning[:100]}")
    else:
        log("  Final assertion: (none — test case not completed)")
    log(f"  Final URL: {final_state.get('page_info', {}).get('url', 'n/a')}")
    log("=" * 60)

    result = {
        "duration": duration,
        "node_visits": node_visits,
        "steps": len(steps),
        "current_step": final_state.get("current_step", 0),
        "consecutive_failures": final_state.get("consecutive_failures", 0),
        "final_status": final_assertion.status if final_assertion else "no_assertion",
        "final_url": final_state.get("page_info", {}).get("url", ""),
        "success": (
            len(steps) > 0
            and final_assertion is not None
            and final_assertion.status in ("pass", "inconclusive")
            and final_state.get("consecutive_failures", 0) < 3
        ),
    }
    log(f"\nResult JSON:\n{json.dumps(result, ensure_ascii=False, indent=2)}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Layer 2 端到端 e2e 冒烟测试 (V2.0 A)")
    parser.add_argument("--quiet", action="store_true", help="只打印最终 JSON")
    args = parser.parse_args()
    result = asyncio.run(run_e2e(quiet=args.quiet))
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
