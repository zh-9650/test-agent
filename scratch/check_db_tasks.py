import asyncio
import os
import sys
from pathlib import Path
from sqlalchemy import select

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.connection import async_session
from database.models import Task, TaskStep, Report

async def main():
    print("=== Querying database for tasks ===")
    async with async_session() as session:
        # Get tasks
        result = await session.execute(select(Task).order_by(Task.id.desc()).limit(5))
        tasks = result.scalars().all()
        
        print(f"Found {len(tasks)} tasks:")
        for t in tasks:
            print(f"\nTask ID: {t.id} | Name: {t.task_name} | Status: {t.status}")
            print(f"Target URL: {t.target_url}")
            print(f"Total Tests: {t.total_tests} | Passed: {t.passed_tests} | Failed: {t.failed_tests}")
            print(f"Created At: {t.created_at} | Completed At: {t.completed_at}")
            
            # Query steps for this task
            step_result = await session.execute(
                select(TaskStep).where(TaskStep.task_id == t.id).order_by(TaskStep.step_index)
            )
            steps = step_result.scalars().all()
            print(f"Steps recorded: {len(steps)}")
            for s in steps[:10]: # print first 10 steps
                print(f"  [{s.test_case_id}] Step {s.step_index}: {s.action_type} target={s.action_target} | Assertion: {s.assertion_result}")
                if s.result and "失败" in s.result or "错误" in s.result or "Exception" in s.result:
                    print(f"    ERROR RESULT: {s.result}")
            
            # Query reports
            rep_result = await session.execute(select(Report).where(Report.task_id == t.id))
            reports = rep_result.scalars().all()
            for r in reports:
                print(f"  Report Row: Path={r.report_path} | Summary={r.summary}")

if __name__ == "__main__":
    asyncio.run(main())
