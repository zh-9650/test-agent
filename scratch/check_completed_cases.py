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
        print("=== Checking Completed Test Cases for Task 46 ===")
        # We can look up test case results from the steps
        # Each case's steps are logged, and when a case finishes, does it update passed_tests / failed_tests?
        # Let's list all distinct test_case_id and their step counts, and check if any step has an assertion failure.
        cases = conn.execute(text("""
            SELECT test_case_id, COUNT(*) as step_count,
                   MIN(created_at) as started_at, MAX(created_at) as ended_at
            FROM task_step 
            WHERE task_id = 46
            GROUP BY test_case_id
            ORDER BY test_case_id
        """)).fetchall()

        for c in cases:
            # Check if any step in this case failed its assertion
            failures = conn.execute(text("""
                SELECT COUNT(*) FROM task_step 
                WHERE task_id = 46 AND test_case_id = :case_id AND assertion_result->>'status' = 'fail'
            """), {"case_id": c.test_case_id}).scalar()
            
            # Check the last step index and action
            last_step = conn.execute(text("""
                SELECT step_index, action_type, action_target, result, assertion_result FROM task_step 
                WHERE task_id = 46 AND test_case_id = :case_id 
                ORDER BY step_index DESC LIMIT 1
            """), {"case_id": c.test_case_id}).fetchone()

            status = "PASSED" if failures == 0 else "FAILED"
            print(f"Case: {c.test_case_id} | Status: {status} | Steps: {c.step_count} | Duration: {c.ended_at - c.started_at}")
            if last_step:
                print(f"  Last Step Index {last_step.step_index}: {last_step.action_type} -> {last_step.action_target}")
                print(f"  Result: {last_step.result}")
                ar = last_step.assertion_result
                if ar:
                    print(f"  Last Assertion Reasoning: {ar.get('reasoning')[:120]}...")
            print("-" * 50)

if __name__ == "__main__":
    main()
