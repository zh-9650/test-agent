import asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

async def check_db(name):
    url = f"postgresql+asyncpg://postgres:123456@localhost:5432/{name}"
    engine = create_async_engine(url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    print(f"\n=== Database: {name} ===")
    try:
        async with async_session() as session:
            res = await session.execute(text("SELECT id, task_name, status, created_at FROM task ORDER BY id DESC LIMIT 5"))
            rows = res.fetchall()
            print(f"Latest Tasks ({len(rows)}):")
            for r in rows:
                print(f"  ID: {r[0]} | Name: {r[1]} | Status: {r[2]} | Created: {r[3]}")
                
            res_steps = await session.execute(text("SELECT count(*) FROM task_step"))
            print(f"Total Steps: {res_steps.scalar()}")
    except Exception as e:
        print(f"Error checking {name}: {e}")
    finally:
        await engine.dispose()

async def main():
    await check_db("smart_test")
    await check_db("smart_test_test")

if __name__ == "__main__":
    asyncio.run(main())
