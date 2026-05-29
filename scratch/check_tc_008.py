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
        print("=== Checking TC-008 Steps ===")
        steps = conn.execute(text("""
            SELECT id, step_index, action_type, action_target, result, assertion_result, created_at 
            FROM task_step 
            WHERE task_id = 46 AND test_case_id = 'TC-008' 
            ORDER BY step_index
        """)).fetchall()

        for s in steps:
            print(f"Index: {s.step_index} | ID: {s.id}")
            print(f"  Action: {s.action_type} -> {s.action_target}")
            print(f"  Result: {s.result}")
            print(f"  Time: {s.created_at}")
            print()

if __name__ == "__main__":
    main()
