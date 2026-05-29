import asyncio
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.runtime import Runtime
from database.connection import init_database

async def main():
    print("=== Initializing Database ===")
    await init_database()
    
    print("=== Configuring Test Task ===")
    task_config = {
        "task_name": "E2E Phase 1 Live Verification",
        "target_url": "http://192.168.31.155/login",
        "accounts": [
            {
                "role": "test",
                "username": "test_c",
                "password": "123456"
            }
        ],
        "rules": "不要点击非登录相关的外部链接，主要验证用户名密码登录和界面功能。",
        "focus_areas": "用户登录、表单输入、登录结果校验"
    }
    
    # Configure safety limits for quick validation
    os.environ["MAX_EXPLORE_PAGES"] = "3"
    os.environ["MAX_EXPLORE_MINUTES"] = "1"
    os.environ["MAX_STEPS_PER_CASE"] = "6"
    os.environ["MAX_CONSECUTIVE_FAILURES"] = "2"
    
    print("=== Launching Runtime ===")
    runtime = Runtime(task_config)
    
    print("=== Running Test Session ===")
    results = await runtime.run()
    
    print("\n=== Final Execution Results ===")
    print(f"Total Results: {len(results)}")
    for r in results:
        print(f"[{r.test_case_id}] Status: {r.status} - {r.summary} ({r.duration_seconds:.2f}s)")
        print("Steps:")
        for idx, s in enumerate(r.steps):
            print(f"  Step {idx+1}: {s.action_type} target={s.action_target} args={s.action_args} result={s.result}")
            if s.assertion:
                print(f"    Assertion: {s.assertion.status} - {s.assertion.reasoning}")
                
if __name__ == "__main__":
    asyncio.run(main())
