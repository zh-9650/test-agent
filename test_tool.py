import asyncio
from agents.ui.tools import tools_by_name

async def run_test():
    print(tools_by_name.keys())

if __name__ == "__main__":
    asyncio.run(run_test())
