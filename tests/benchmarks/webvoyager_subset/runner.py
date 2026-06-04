"""WebVoyager subset benchmark runner.

对齐 WebVoyager 官方 evaluator (https://github.com/MinorJerry/WebVoyager):
- 跑完任务后保存 last screenshot
- LLM-as-a-Judge (multi-modal MiMo v2.5): 拿 (task, screenshot, agent answer)
  仿 GPT-4V 协议判 SUCCESS / NOT SUCCESS
- 报告: 成功率 / 平均步数 / judge_reasoning

用法:
    python -m tests.benchmarks.webvoyager_subset.runner
    python -m tests.benchmarks.webvoyager_subset.runner --task-id WV-001
    python -m tests.benchmarks.webvoyager_subset.runner --dry-run
    python -m tests.benchmarks.webvoyager_subset.runner --no-judge   # 跳过 LLM judge
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any

# 允许从项目根目录直接执行
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 自动加载项目根目录的 .env
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def load_tasks(tasks_file: Path | None = None) -> list[dict[str, Any]]:
    if tasks_file is None:
        tasks_file = Path(__file__).parent / "tasks.json"
    with open(tasks_file, encoding="utf-8") as f:
        data = json.load(f)
    return data["tasks"]


# ---------------------------------------------------------------------------
# Legacy keyword-based check (保留供对比, 但默认走 LLM judge)
# ---------------------------------------------------------------------------

def check_success_keyword(task: dict[str, Any], final_state: dict[str, Any]) -> tuple[bool, str]:
    """旧版 keyword 匹配. 仅供参考, 不再默认使用."""
    criteria = task.get("success_criteria", "")
    final_text = (final_state.get("page_info", {}).get("title", "") + " " +
                  str(final_state.get("last_action_result", {}).get("extracted_content", "")))
    final_url = final_state.get("page_info", {}).get("url", "")

    if "contains" in criteria:
        m = re.search(r"contains ['\"](.+?)['\"]", criteria)
        if m:
            keyword = m.group(1)
            if keyword in final_url or keyword.lower() in final_text.lower():
                return True, f"matched keyword '{keyword}'"
            return False, f"keyword '{keyword}' not found"

    if "returns" in criteria:
        m = re.search(r"returns (.+)", criteria)
        if m:
            expected = m.group(1)
            content = str(final_state.get("last_action_result", {}).get("extracted_content", ""))
            if not content:
                return False, "extracted_content empty"
            if "contains '$'" in expected or "price" in expected.lower():
                if "$" in content:
                    return True, "price found"
            if "number" in expected.lower():
                if any(c.isdigit() for c in content):
                    return True, "number found"
            if "> 50" in expected or "> 10" in expected:
                if len(content) > 10:
                    return True, f"len={len(content)}"
            return False, f"content does not match '{expected}'"
    return True, "no criteria (assumed pass)"


# ---------------------------------------------------------------------------
# WebVoyager-style LLM Judge (GPT-4V 协议, multi-modal)
# ---------------------------------------------------------------------------

JUDGE_SYSTEM_PROMPT = """As an evaluator, you will be presented with three primary components to assist you in your role:

1. Web Task Instruction: A clear and specific directive in natural language, detailing the online activity to be carried out. These may include conducting searches, verifying information, comparing prices, checking availability, or any other action relevant to the specified web service (such as Amazon, Apple, ArXiv, BBC News, Booking, GitHub, Hacker News, Wolfram Alpha, etc).

2. Result Screenshot: A visual representation of the screen showing the final state after performing the web task. It serves as visual proof of the actions taken in response to the instruction.

3. Result Response: A textual response obtained after the execution of the web task (the agent's own summary or final answer).

-- You DO NOT NEED to interact with web pages or perform actions such as booking flights.
-- You SHOULD NOT make assumptions based on information not presented in the screenshot.
-- Your primary responsibility is to conduct a thorough assessment of the web task instruction against the outcome depicted in the screenshot and the response, evaluating whether the actions taken align with the given instructions.
-- NOTE that the instruction may involve more than one task. Failing to complete any sub-task should be considered unsuccessful.
-- NOTE that the screenshot is authentic, but the response is generated at the end of web browsing, and there may be discrepancies between the text and the screenshots.
-- Note the difference: 1) If Result response contradicts the screenshot, the content of the screenshot prevails. 2) If content in the Result response is not mentioned on the screenshot, you may believe the content.

You should elaborate on how you arrived at your final evaluation and then provide a definitive verdict on whether the task has been successfully accomplished, either as 'SUCCESS' or 'NOT SUCCESS'."""


JUDGE_USER_TEMPLATE = """TASK: {task}
Result Response: {answer}
1 screenshot at the end:

Your verdict (elaborate first, then end with SUCCESS or NOT SUCCESS):"""


async def judge_with_llm(
    task: dict[str, Any],
    final_state: dict[str, Any],
    screenshot_b64: str | None = None,
) -> tuple[bool, str]:
    """LLM-as-a-Judge, 对齐 WebVoyager evaluator 协议.

    Args:
        task: 任务定义
        final_state: 包含 page_info, last_action_result 等
        screenshot_b64: base64 编码的 PNG 截图 (None 时纯文本评估)

    Returns:
        (success, reasoning)
    """
    from anthropic import Anthropic

    instruction = task["instruction"]
    last_ar = final_state.get("last_action_result", {}) or {}
    # agent 最终回答: 优先用 mark_task_complete 的 reasoning, 否则 extracted_content
    agent_answer = (
        last_ar.get("error") or
        last_ar.get("extracted_content") or
        "Agent did not provide a final answer."
    )

    user_text = JUDGE_USER_TEMPLATE.format(task=instruction, answer=agent_answer)

    content: list[dict] = []
    if screenshot_b64:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": screenshot_b64,
            },
        })
    content.append({"type": "text", "text": user_text})

    try:
        client = Anthropic(
            api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
            base_url=os.environ.get("ANTHROPIC_BASE_URL"),
        )
        msg = client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "mimo-v2.5"),
            max_tokens=1500,
            system=JUDGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
        # 提取 judge 文本 (跳过 thinking block)
        text_parts = [b.text for b in msg.content if b.type == "text"]
        verdict_text = "\n".join(text_parts) if text_parts else ""

        # 解析 SUCCESS / NOT SUCCESS (WebVoyager 原版规则)
        if "NOT SUCCESS" in verdict_text:
            return False, verdict_text.strip()
        elif "SUCCESS" in verdict_text:
            return True, verdict_text.strip()
        else:
            return False, f"[judge unparseable] {verdict_text.strip()[:300]}"
    except Exception as e:
        return False, f"[judge error: {type(e).__name__}: {e}]"


# ---------------------------------------------------------------------------
# Run a single task
# ---------------------------------------------------------------------------

async def run_single_task(
    task: dict[str, Any],
    *,
    max_steps: int | None = None,
    dry_run: bool = False,
    use_judge: bool = True,
    screenshot_dir: Path | None = None,
) -> dict[str, Any]:
    """跑单个任务, 返回结果.

    Args:
        task: 任务定义
        max_steps: 最大步数
        dry_run: 不调 LLM
        use_judge: 跑完后调 LLM judge 评估 (WebVoyager 风格)
        screenshot_dir: last screenshot 保存目录
    """
    from agents.ui.tools import set_current_task, set_current_page, cleanup_task_context
    from agents.ui.execution_graph import build_execution_graph
    from core.interfaces import TestCase
    from langchain_core.messages import SystemMessage, HumanMessage

    task_id = task["id"]
    max_steps = max_steps or task.get("max_steps", 12)
    start_time = time.time()

    set_current_task(task_id)

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                # P1: Setup page.goto retry logic
                max_retries = 3
                for attempt in range(1, max_retries + 1):
                    try:
                        wait_until = "domcontentloaded" if attempt == 1 else "commit"
                        timeout = 30000 if attempt == 1 else (20000 if attempt == 2 else 15000)
                        print(f"  [Setup] Navigation attempt {attempt}/{max_retries} to {task['url']} (wait_until={wait_until}, timeout={timeout})...", flush=True)
                        await page.goto(task["url"], wait_until=wait_until, timeout=timeout)
                        break
                    except Exception as goto_err:
                        print(f"  [Setup] Attempt {attempt} failed: {type(goto_err).__name__}: {goto_err}", flush=True)
                        if attempt == max_retries:
                            raise goto_err
                        await asyncio.sleep(2)

                set_current_page(page, task_id)

                test_case = TestCase(
                    id=task_id,
                    title=task["instruction"][:80],
                    description=task["instruction"],
                    steps=[task["instruction"]],
                    expected=task["success_criteria"],
                    priority="P0",
                    category=task["category"],
                )

                if dry_run:
                    from core.page_semantic import extract_page_semantics
                    page_info = await extract_page_semantics(page)
                    return {
                        "task_id": task_id,
                        "status": "dry_run",
                        "duration_s": round(time.time() - start_time, 2),
                        "steps": 0,
                        "page_info": {"url": page_info.get("url"), "title": page_info.get("title")},
                    }

                state = {
                    "messages": [
                        SystemMessage(content=f"执行测试: {task['instruction']}"),
                        HumanMessage(content=task["instruction"]),
                    ],
                    "task_id": task_id,
                    "test_plan": [test_case],
                    "current_index": 0,
                    "current_step": 0,
                    "task_config": {"target_url": task["url"]},
                    "consecutive_failures": 0,
                    "recent_failures": [],
                    "need_replan": False,
                }

                # Set MAX_STEPS_PER_CASE env var so the graph safety valves align with task settings
                os.environ.setdefault("MAX_STEPS_PER_CASE", str(max_steps))
                graph = build_execution_graph()
                step_count = 0
                last_ar = None
                # P2: Time budget limit (default 300s)
                time_limit = task.get("time_budget_s", 300)
                for step_count in range(max_steps):
                    elapsed = time.time() - start_time
                    if elapsed > time_limit:
                        print(f"  [Timeout] Task {task_id} elapsed {elapsed:.1f}s > budget {time_limit}s, forcing break.", flush=True)
                        break
                    result = await graph.ainvoke(state, {"recursion_limit": max(100, max_steps * 10)})
                    state.update(result)
                    last_ar = state.get("_last_action_result")
                    if last_ar and last_ar.action and last_ar.action.startswith("mark_task_"):
                        break

                duration = time.time() - start_time

                # 截图 last screenshot (无论是否 mark_task, 都截一张)
                last_screenshot_b64 = None
                if screenshot_dir is not None:
                    screenshot_dir.mkdir(parents=True, exist_ok=True)
                    screenshot_path = screenshot_dir / f"{task_id}.png"
                    png_bytes = await page.screenshot(type="png", full_page=False)
                    screenshot_path.write_bytes(png_bytes)
                    last_screenshot_b64 = base64.b64encode(png_bytes).decode("utf-8")

                final_state = {
                    "page_info": state.get("page_info", {}),
                    "last_action_result": last_ar.model_dump() if last_ar else {},
                }

                # 评估
                judge_text = ""
                if use_judge:
                    success, judge_text = await judge_with_llm(task, final_state, last_screenshot_b64)
                    reason = f"[judge] {judge_text[:200]}"
                else:
                    success, reason = check_success_keyword(task, final_state)

                return {
                    "task_id": task_id,
                    "site": task.get("site", ""),
                    "status": "success" if success else "fail",
                    "success": success,
                    "reason": reason,
                    "judge_verdict": judge_text,
                    "duration_s": round(duration, 2),
                    "steps": step_count + 1,
                    "tokens": state.get("_last_token_count", 0),
                    "page_info": {
                        "url": final_state["page_info"].get("url"),
                        "title": final_state["page_info"].get("title"),
                    },
                    "last_action": last_ar.action if last_ar else "",
                    "agent_answer": final_state["last_action_result"].get("extracted_content", "")
                    or final_state["last_action_result"].get("error", ""),
                    "action_history": state.get("action_history", []),
                }
            finally:
                await browser.close()
    except Exception as e:
        tb = traceback.format_exc()
        try:
            (PROJECT_ROOT / "data" / "bench_errors").mkdir(parents=True, exist_ok=True)
            log_content = (
                f"=== {task_id} ({task.get('site', '')}) ===\n"
                f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Instruction: {task.get('instruction', '')[:200]}\n"
                f"Exception: {type(e).__name__}: {e}\n\n"
                f"{tb}\n"
            )
            if "state" in locals():
                log_content += "\n=== Action History ===\n"
                action_hist = state.get("action_history", [])
                for idx, act in enumerate(action_hist):
                    log_content += f"Step {idx}: {act}\n"
                log_content += "\n=== Messages ===\n"
                for msg in state.get("messages", []):
                    log_content += f"[{type(msg).__name__}]: {str(msg.content)[:400]}\n"
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        log_content += f"  Tool Calls: {msg.tool_calls}\n"
            (PROJECT_ROOT / "data" / "bench_errors" / f"{task_id}.log").write_text(
                log_content,
                encoding="utf-8",
            )
        except Exception as log_err:
            print(f"Failed to write error log: {log_err}", flush=True)
        return {
            "task_id": task_id,
            "site": task.get("site", ""),
            "status": "error",
            "success": False,
            "reason": f"exception: {type(e).__name__}: {e}",
            "judge_verdict": "",
            "duration_s": round(time.time() - start_time, 2),
            "steps": 0,
            "traceback": tb,
        }
    finally:
        cleanup_task_context(task_id)


async def run_benchmark(
    tasks: list[dict[str, Any]],
    *,
    filter_id: str | None = None,
    dry_run: bool = False,
    use_judge: bool = True,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if filter_id:
        tasks = [t for t in tasks if t["id"] == filter_id]
    screenshot_dir = PROJECT_ROOT / "data" / "screenshots"
    for i, task in enumerate(tasks, 1):
        print(f"[{i}/{len(tasks)}] Running {task['id']} ({task.get('site', '')})...", flush=True)
        result = await run_single_task(
            task, dry_run=dry_run, use_judge=use_judge,
            screenshot_dir=screenshot_dir,
        )
        results.append(result)
        print(f"  → status={result['status']} duration={result.get('duration_s', 0)}s", flush=True)
    return results


def generate_report(results: list[dict[str, Any]]) -> str:
    """Markdown 报告. 仿 WebVoyager 风格: 总分 + 分站点成功率 + LLM judge 详情."""
    lines = ["# WebVoyager Subset Benchmark Report", ""]
    lines.append(f"- Tasks: {len(results)}")
    if not results:
        return "\n".join(lines)

    success = sum(1 for r in results if r.get("success"))
    lines.append(f"- **Success rate: {success}/{len(results)} = {success/len(results)*100:.1f}%**")
    avg_steps = sum(r.get("steps", 0) for r in results) / len(results)
    avg_duration = sum(r.get("duration_s", 0) for r in results) / len(results)
    errors = sum(1 for r in results if r.get("status") == "error")
    lines.append(f"- Avg steps: {avg_steps:.1f}")
    lines.append(f"- Avg duration: {avg_duration:.1f}s")
    lines.append(f"- Errors (network/protocol): {errors}")
    lines.append("")

    # 分 site 聚合
    by_site: dict[str, list[dict]] = {}
    for r in results:
        by_site.setdefault(r.get("site", "?"), []).append(r)
    if len(by_site) > 1:
        lines.append("## Success rate by site")
        lines.append("")
        lines.append("| Site | Success | Total | Rate |")
        lines.append("|------|---------|-------|------|")
        for site, rs in sorted(by_site.items()):
            s = sum(1 for r in rs if r.get("success"))
            t = len(rs)
            lines.append(f"| {site} | {s} | {t} | {s/t*100:.1f}% |")
        lines.append("")

    lines.append("## Per-task detail")
    lines.append("")
    lines.append("| Task | Site | Status | Steps | Duration |")
    lines.append("|------|------|--------|-------|----------|")
    for r in results:
        lines.append(f"| {r['task_id']} | {r.get('site', '')} | {r['status']} | "
                     f"{r.get('steps', 0)} | {r.get('duration_s', 0)}s |")

    # Error tracebacks (full stack for debugging)
    errored = [r for r in results if r.get("status") == "error" and r.get("traceback")]
    if errored:
        lines.append("")
        lines.append("## Error Tracebacks")
        lines.append("")
        lines.append("Full stack traces for tasks that errored. Also written to `data/bench_errors/{task_id}.log`.")
        lines.append("")
        for r in errored:
            lines.append(f"### {r['task_id']} — {r.get('site', '')}")
            lines.append(f"**Reason**: {r.get('reason', '')}")
            lines.append("")
            lines.append("```")
            lines.append(r["traceback"][:3000])
            lines.append("```")
            lines.append("")

    # LLM judge 详情
    judged = [r for r in results if r.get("judge_verdict")]
    if judged:
        lines.append("")
        lines.append("## LLM Judge Verdicts (WebVoyager-style)")
        lines.append("")
        for r in judged:
            verdict_status = "✅ SUCCESS" if r.get("success") else "❌ NOT SUCCESS"
            lines.append(f"### {r['task_id']} — {r.get('site', '')} — {verdict_status}")
            lines.append(f"**Task**: {r.get('reason', '')[:300]}")
            lines.append("")
            if r.get("judge_verdict"):
                # 取最后 500 字符 (judge 的 "Your verdict" 部分)
                v = r["judge_verdict"]
                lines.append("**Judge reasoning**:")
                lines.append("```")
                lines.append(v[:800])
                lines.append("```")
            lines.append("")
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="WebVoyager Subset Benchmark Runner")
    parser.add_argument("--task-id", help="Run single task by ID")
    parser.add_argument("--no-judge", action="store_true", help="Use keyword check instead of LLM judge")
    parser.add_argument("--dry-run", action="store_true", help="Don't call LLM, just check page load")
    parser.add_argument("--max-steps", type=int, default=None, help="Override max steps per task")
    parser.add_argument("--output", type=Path, default=Path("data/webvoyager_report.md"), help="Output report path")
    args = parser.parse_args()

    # 延迟 import (避免加载 dotenv 前解析)
    load_dotenv()

    # V2.0 fix (2026-06-04): init DB before run. decide_node 调 retrieve_memories
    # 需要 smart_test 数据库存在. 之前 benchmark 0/10 是因为 DB 没建, 70ms 早退.
    print("Initializing database...", flush=True)
    from database.connection import init_database
    try:
        asyncio.run(init_database())
        print("DB ready.", flush=True)
    except Exception as e:
        print(f"WARN: DB init failed ({type(e).__name__}: {e}); continuing anyway", flush=True)

    tasks = load_tasks()
    if args.task_id:
        tasks = [t for t in tasks if t["id"] == args.task_id]

    print(f"Running {len(tasks)} task(s)...", flush=True)
    results = asyncio.run(run_benchmark(
        tasks,
        filter_id=args.task_id,
        dry_run=args.dry_run,
        use_judge=not args.no_judge,
    ))

    report = generate_report(results)
    if args.output:
        args.output.write_text(report, encoding="utf-8")
        print(f"\nReport written to {args.output}", flush=True)
    else:
        print(report)


if __name__ == "__main__":
    main()
