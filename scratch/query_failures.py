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
        print("=== Querying Failures for Task 46 ===")
        # Get all steps for Task 46 where assertion failed
        steps = conn.execute(text("""
            SELECT id, test_case_id, step_index, action_type, action_target, result, assertion_result, change_report 
            FROM task_step 
            WHERE task_id = 46 AND assertion_result IS NOT NULL
            ORDER BY test_case_id, step_index
        """)).fetchall()

        failed_cases = {}
        for s in steps:
            ar = s.assertion_result
            if isinstance(ar, str):
                try:
                    ar = json.loads(ar)
                except Exception:
                    pass
            
            # If the assertion result status is 'fail'
            if ar and ar.get('status') == 'fail':
                case_id = s.test_case_id
                if case_id not in failed_cases:
                    failed_cases[case_id] = []
                failed_cases[case_id].append({
                    'step_index': s.step_index,
                    'action': f"{s.action_type} -> {s.action_target}",
                    'result': s.result,
                    'assertion': ar
                })

        if not failed_cases:
            print("No assertion failures logged in task_step. Let's check cases marked as failed.")
            
        for case_id, failures in failed_cases.items():
            print(f"\n[Case ID: {case_id}]")
            for f in failures:
                print(f"  Step {f['step_index']}: {f['action']}")
                print(f"    Result: {f['result']}")
                print(f"    Assertion Status: {f['assertion'].get('status')}")
                print(f"    Reasoning: {f['assertion'].get('reasoning')}")
                print(f"    Message: {f['assertion'].get('message')}")

        # Let's print the test_plan to see what the cases are
        t = conn.execute(text("SELECT test_plan FROM task WHERE id = 46")).fetchone()
        if t and t.test_plan:
            print("\n=== Test Cases in Plan ===")
            for tc in t.test_plan:
                tc_id = tc.get('id')
                status = "unknown"
                if tc_id in failed_cases:
                    status = "failed (assertion)"
                print(f"  - {tc_id}: {tc.get('title')} (Preconditions: {tc.get('preconditions')})")

if __name__ == "__main__":
    main()
