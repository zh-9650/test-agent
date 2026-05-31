import asyncio
import os
import json
from dotenv import load_dotenv
from core.runtime import Runtime

load_dotenv(override=True)

os.environ["MAX_EXPLORE_PAGES"] = "4"
os.environ["MAX_EXPLORE_MINUTES"] = "4"

async def main():
    print("Starting V1.1 & V1.2 End-to-End Test")
    
    task_config = {
        "target_url": "https://www.saucedemo.com/",
        "accounts": [
            {"role": "standard_user", "username": "standard_user", "password": "secret_sauce"}
        ],
        "prd": """
SauceDemo 是一款电商演示系统。
核心流程：
1. 登录：支持 standard_user, locked_out_user 等账号，密码 secret_sauce。
2. 商品列表：展示商品，支持加入购物车。
3. 购物车：查看已选商品，进行结算。
4. 结算流程：填写用户信息（First Name, Last Name, Zip Code），确认订单并完成。
        """,
        "api_doc": """
前端无公开后端 API 文档，全流程页面交互验证。
""",
        "focus_areas": ["登录页错误提示", "加入购物车流程", "结算表单输入"]
    }

    from core.document_parser import parse_and_fetch_links
    task_config = await parse_and_fetch_links(task_config)
    
    from core.skills.system_modeler import generate_system_model
    system_model = await generate_system_model(
        prd_content=task_config.get("prd", ""),
        api_doc_content=task_config.get("api_doc", ""),
        changelog_content=task_config.get("changelog", "")
    )
    task_config["_system_model"] = system_model.model_dump()
    
    from core.execution_logger import log_task_created
    import uuid
    task_id_uuid = str(uuid.uuid4())
    await log_task_created(
        task_id=task_id_uuid,
        task_name="E2E Test",
        target_url=task_config["target_url"],
        config=task_config,
    )
    task_config["task_id"] = task_id_uuid
    
    runtime = Runtime(task_config=task_config)
    
    print("== 正在执行测试 (流式输出) ==")
    try:
        async for update in runtime.run_stream():
            update_type = update.get("type")
            data = update.get("data", {})
            if update_type == "ai_thinking":
                print(f"[AI] {data.get('thought', '')}")
            elif update_type == "action_result":
                print(f"[ACTION] {data.get('tool_name')}: {data.get('result', '')}")
            elif update_type == "assertion_result":
                assertion = data.get("assertion", {})
                if assertion:
                    if isinstance(assertion, dict):
                        print(f"[ASSERTION] {assertion.get('status')} - {assertion.get('reasoning')}")
                    else:
                        print(f"[ASSERTION] {assertion.status} - {assertion.reasoning}")
            elif update_type == "session_complete":
                print(f"[SESSION_COMPLETE] Data: {data}")
    except Exception as e:
        print(f"[ERROR] during execution: {e}")

if __name__ == "__main__":
    asyncio.run(main())
