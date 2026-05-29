import os
import sys
import json
from sqlalchemy import create_engine, text

# Add the project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.connection import DATABASE_URL

def main():
    url = DATABASE_URL
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    
    engine = create_engine(url)
    with engine.connect() as conn:
        # Get the latest task ID
        latest_task = conn.execute(text("SELECT id, task_name, target_url, status, total_tests, passed_tests, failed_tests, started_at, completed_at, test_plan FROM task ORDER BY id DESC LIMIT 1")).fetchone()
        if not latest_task:
            print("No tasks found in the database.")
            return

        tid = latest_task.id
        print(f"=== Monitoring Latest Task: ID {tid} ===")
        print(f"  Name: {latest_task.task_name}")
        print(f"  Target URL: {latest_task.target_url}")
        print(f"  Status: {latest_task.status}")
        print(f"  Total Cases: {latest_task.total_tests}")
        print(f"  Passed: {latest_task.passed_tests} | Failed: {latest_task.failed_tests}")
        print(f"  Started: {latest_task.started_at} | Completed: {latest_task.completed_at}")
        
        # Print cases if planned
        if latest_task.test_plan:
            print(f"  Test Plan Case Count: {len(latest_task.test_plan)}")
            print("  Test Plan Cases:")
            for tc in latest_task.test_plan[:5]:
                print(f"    - {tc.get('id')}: {tc.get('title')}")
            if len(latest_task.test_plan) > 5:
                print("    - ...")
        else:
            print("  Test Plan: Still exploring / planning in progress...")

        step_count = conn.execute(text("SELECT COUNT(*) FROM task_step WHERE task_id = :tid"), {"tid": tid}).scalar()
        print(f"  Total Steps Executed: {step_count}")

        # Print latest 5 steps if any
        if step_count > 0:
            print("\n=== Latest 5 Steps ===")
            steps = conn.execute(text("""
                SELECT id, test_case_id, step_index, action_type, action_target, result, created_at 
                FROM task_step 
                WHERE task_id = :tid 
                ORDER BY id DESC LIMIT 5
            """), {"tid": tid}).fetchall()
            for s in steps:
                print(f"  Step ID: {s.id} | Case: {s.test_case_id} | Index: {s.step_index}")
                print(f"    Action: {s.action_type} -> {s.action_target}")
                print(f"    Result: {s.result}")
                print(f"    Time: {s.created_at}")
                print()

        # Check video directory
        videos_dir = f"data/sessions/{tid}/videos"
        if os.path.exists(videos_dir):
            files = os.listdir(videos_dir)
            if files:
                print("\n=== Playwright Video Recording ===")
                for f in files:
                    filepath = os.path.join(videos_dir, f)
                    mtime = os.path.getmtime(filepath)
                    size = os.path.getsize(filepath)
                    import time
                    print(f"  File: {f}")
                    print(f"    Size: {size / 1024:.2f} KB")
                    print(f"    Last Modified: {time.ctime(mtime)}")

if __name__ == "__main__":
    main()
