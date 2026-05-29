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
        print("=== Recent 10 Tasks ===")
        tasks = conn.execute(text("SELECT id, task_name, target_url, status, created_at, started_at, completed_at, config, test_plan FROM task ORDER BY id DESC LIMIT 10")).fetchall()
        for t in tasks:
            name_bytes = t.task_name.encode('utf-8', errors='ignore') if isinstance(t.task_name, str) else b''
            # Try to decode safely for display
            try:
                display_name = t.task_name
            except Exception:
                display_name = repr(t.task_name)
            
            print(f"Task ID: {t.id} | Name: {display_name} | Status: {t.status}")
            print(f"  Target URL: {t.target_url}")
            print(f"  Created: {t.created_at} | Started: {t.started_at} | Completed: {t.completed_at}")
            print(f"  Config: {json.dumps(t.config, ensure_ascii=False) if t.config else 'None'}")
            print(f"  Test Plan Case Count: {len(t.test_plan) if t.test_plan else 'None'}")
            print("-" * 50)

        print("\n=== Checking steps for Task 45 ===")
        steps_45 = conn.execute(text("SELECT id, test_case_id, step_index, action_type, action_target, result, created_at FROM task_step WHERE task_id = 45 ORDER BY step_index")).fetchall()
        if not steps_45:
            print("No steps found for Task 45.")
        for s in steps_45:
            print(f"  Step ID: {s.id} | Case: {s.test_case_id} | Index: {s.step_index}")
            print(f"    Action: {s.action_type} -> {s.action_target}")
            print(f"    Result: {s.result}")
            
        print("\n=== Checking steps for Task 46 ===")
        steps_46 = conn.execute(text("SELECT id, test_case_id, step_index, action_type, action_target, result, created_at FROM task_step WHERE task_id = 46 ORDER BY step_index DESC LIMIT 5")).fetchall()
        if not steps_46:
            print("No steps found for Task 46 yet.")
        for s in steps_46:
            print(f"  Step ID: {s.id} | Case: {s.test_case_id} | Index: {s.step_index}")
            print(f"    Action: {s.action_type} -> {s.action_target}")
            print(f"    Result: {s.result}")

if __name__ == "__main__":
    main()
