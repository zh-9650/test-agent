import asyncio
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.app import _run_test_session

async def main():
    print("=== Running background task session manually with traceback ===")
    try:
        # We run the background session for Task 28
        # Since it already exists in the DB, let's create a new task configuration
        # target_url = "http://192.168.31.155/login"
        # config is empty or contains rules
        await _run_test_session(
            task_db_id=28,
            target_url="http://192.168.31.155/login",
            config={
                "accounts": [{"role": "test", "username": "test_c", "password": "123456"}]
            }
        )
    except Exception as e:
        print("Caught exception in check script:")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
