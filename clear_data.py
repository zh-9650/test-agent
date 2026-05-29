import asyncio
from database.connection import async_session
from sqlalchemy import text

async def clear():
    async with async_session() as session:
        try:
            await session.execute(text("TRUNCATE TABLE agent_memory RESTART IDENTITY CASCADE;"))
            await session.execute(text("TRUNCATE TABLE report RESTART IDENTITY CASCADE;"))
            await session.execute(text("TRUNCATE TABLE task_step RESTART IDENTITY CASCADE;"))
            await session.execute(text("TRUNCATE TABLE task RESTART IDENTITY CASCADE;"))
            await session.commit()
            print("所有数据库数据已成功清除。")
        except Exception as e:
            print(f"Error clearing data: {e}")

if __name__ == "__main__":
    asyncio.run(clear())
