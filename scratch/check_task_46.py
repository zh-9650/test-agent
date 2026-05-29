import os
import sys
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
        print("=== Checking Task 46 Status ===")
        t = conn.execute(text("SELECT id, status, total_tests, passed_tests, failed_tests, started_at, completed_at, test_plan FROM task WHERE id = 46")).fetchone()
        if not t:
            print("Task 46 not found.")
            return

        print(f"Task ID: {t.id}")
        print(f"Status: {t.status}")
        print(f"Total Tests in Plan: {t.total_tests}")
        print(f"Passed: {t.passed_tests} | Failed: {t.failed_tests}")
        print(f"Started: {t.started_at} | Completed: {t.completed_at}")

        step_count = conn.execute(text("SELECT COUNT(*) FROM task_step WHERE task_id = 46")).scalar()
        print(f"Total Steps Executed: {step_count}")

        print("\n=== Latest 10 Steps for Task 46 ===")
        steps = conn.execute(text("SELECT id, test_case_id, step_index, action_type, action_target, result, created_at FROM task_step WHERE task_id = 46 ORDER BY id DESC LIMIT 10")).fetchall()
        for s in steps:
            print(f"  Step ID: {s.id} | Case: {s.test_case_id} | Index: {s.step_index}")
            print(f"    Action: {s.action_type} -> {s.action_target}")
            print(f"    Result: {s.result}")
            print(f"    Time: {s.created_at}")
            print()

        print("\n=== Check if there are tasks newer than 46 ===")
        newer = conn.execute(text("SELECT id, task_name, target_url, status, created_at FROM task WHERE id > 46 ORDER BY id DESC")).fetchall()
        if not newer:
            print("No tasks newer than 46 found.")
        for n in newer:
            print(f"Task ID: {n.id} | Name: {n.task_name} | Status: {n.status} | Target: {n.target_url} | Created: {n.created_at}")

if __name__ == "__main__":
    main()
