import asyncio
import os
import sys
from pathlib import Path
from sqlalchemy import text

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.connection import async_session

async def main():
    print("=== Clearing history database data ===")
    async with async_session() as session:
        try:
            # PostgreSQL command to truncate tables and restart auto-increment ids to 1
            await session.execute(text("TRUNCATE TABLE report, task_step, task RESTART IDENTITY CASCADE;"))
            await session.commit()
            print("Successfully truncated report, task_step, and task tables and restarted identities!")
        except Exception as e:
            print("Failed to truncate tables:", e)
            await session.rollback()

if __name__ == "__main__":
    asyncio.run(main())
