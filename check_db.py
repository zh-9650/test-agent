import asyncio
from database.connection import async_session
from database.models import TaskStep, Task
from sqlalchemy import select

async def main():
    async with async_session() as s:
        steps = (await s.execute(select(TaskStep).where(TaskStep.task_id==54).order_by(TaskStep.step_index))).scalars().all()
        for st in steps:
            print(f"Step {st.step_index}: Action={st.action_type}, Target={st.action_target}")
            print(f"  Result: {st.result}")
            print(f"  Assertion: {st.assertion_result}")
            print("-" * 20)
        
        task = await s.get(Task, 54)
        print(f"Task status: {task.status}")

asyncio.run(main())
