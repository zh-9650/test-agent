import httpx
import asyncio

API_URL = "http://127.0.0.1:8001/api"

async def start_task(target_url, task_name, prd, changelog):
    async with httpx.AsyncClient() as client:
        print(f"Starting task: {task_name} for {target_url}")
        res = await client.post(f"{API_URL}/tasks", json={
            "target_url": target_url,
            "task_name": task_name,
            "config": {
                "prd": prd,
                "changelog": changelog,
                "focus_areas": ["Input field", "Todo list", "Filters", "Editing"]
            }
        })
        res.raise_for_status()
        data = res.json()
        print(f"Task started: {data['id']}")
        return data['id']

async def wait_for_tasks(task_ids):
    async with httpx.AsyncClient(timeout=60.0) as client:
        while True:
            all_done = True
            for tid in task_ids:
                res = await client.get(f"{API_URL}/tasks/{tid}")
                if res.status_code == 200:
                    status = res.json().get("status")
                    if status in ["pending", "running"]:
                        all_done = False
                    else:
                        print(f"Task {tid} finished with status: {status}")
            
            if all_done:
                print("All tasks completed!")
                break
            print("Waiting for tasks to complete...")
            await asyncio.sleep(5)

async def main():
    print("Testing against a real application using PRD...")
    
    prd_text = """
    # TodoMVC 产品需求文档 (PRD)
    
    ## 1. 核心业务目标
    允许用户记录、跟踪和管理日常待办事项。
    
    ## 2. 功能列表
    1. **新增待办 (Add Todo)**
       - 用户在顶部的输入框输入文本后，按 `Enter` 键即可创建新的待办事项。
       - 新增后，输入框应清空，并且新事项出现在列表末尾（或列表顶部，取决于实现）。
    2. **完成/取消待办 (Toggle Status)**
       - 每个事项左侧有一个复选框。点击复选框可将事项标记为“已完成”（文本带有删除线且颜色变浅）。
       - 再次点击可取消完成状态，恢复为“进行中”（Active）。
    3. **批量切换状态 (Toggle All)**
       - 输入框左侧有一个向下的箭头图标。点击该图标可以将所有事项统一标记为已完成或统一取消完成。
    4. **删除待办 (Delete Todo)**
       - 将鼠标悬停在某个待办事项上时，右侧会出现一个红色的 `X` 按钮。点击该按钮可删除该事项。
    5. **列表过滤 (Filters)**
       - 列表底部有三个过滤按钮：`All`（所有）、`Active`（进行中）、`Completed`（已完成）。
       - 点击不同的按钮，列表应仅显示对应状态的事项。
    6. **清除已完成 (Clear Completed)**
       - 如果列表中存在已完成的事项，底部右侧会出现 `Clear completed` 按钮。
       - 点击后，所有已完成的事项将被一次性删除。
    7. **双击编辑 (Edit Todo)**
       - 双击某个待办事项的文本内容，进入编辑模式。
       - 在编辑模式下，修改文本后按 `Enter` 键保存修改，或者点击页面其他空白处（失去焦点）保存修改。
       - 按 `Escape` 键可取消编辑，恢复原状。
    """
    
    changelog_text = """
    # 发版日志 v1.2.0
    1. 优化了底部的 Filter 过滤功能，现在点击不同状态时能够做到无刷新切换视图。
    2. 修复了双击编辑时按 Escape 键无法正确取消的 Bug。
    """
    
    t1_id = await start_task(
        "https://demo.playwright.dev/todomvc/",
        "TodoMVC Full Regression",
        prd=prd_text,
        changelog=changelog_text
    )
    
    await wait_for_tasks([t1_id])

if __name__ == "__main__":
    asyncio.run(main())
