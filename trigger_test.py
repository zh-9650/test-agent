import requests
import time
import sys

def run_test():
    base_url = "http://localhost:8000"
    
    # 1. Create a task
    print("Creating task...")
    res = requests.post(f"{base_url}/api/tasks", json={
        "target_url": "http://192.168.31.155/login",
        "task_name": "Login Failure Reflection Test",
        "config": {
            "accounts": [
                {
                    "role": "Test User",
                    "username": "test_c",
                    "password": "123456"
                }
            ],
            "rules": [
                "作为一个测试目标，你必须首先尝试使用错误的密码登录（如输入密码: wrongpass），验证系统是否拒绝访问并报错。",
                "然后才使用正确的密码登录。"
            ]
        }
    })
    
    if res.status_code != 201:
        print(f"Failed to create task: {res.text}")
        sys.exit(1)
        
    task_id = res.json()["id"]
    print(f"Task created with ID: {task_id}")
    
    # 2. Wait for completion
    print("Waiting for task to complete...")
    while True:
        status_res = requests.get(f"{base_url}/api/tasks/{task_id}")
        if status_res.status_code == 200:
            status = status_res.json()["status"]
            print(f"Current status: {status}")
            if status in ["completed", "failed", "cancelled"]:
                break
        time.sleep(5)
        
    # 3. Check memories
    print("Task finished. Checking extracted memories...")
    mem_res = requests.get(f"{base_url}/api/memory")
    memories = mem_res.json().get("memories", [])
    
    print("\n--- Extracted Memories ---")
    for m in memories:
        print(f"[{m['scope_type']}] {m['scope_value']} | {m['memory_key']}: {m['memory_value']}")
        
    if not memories:
        print("No memories extracted.")
        
    print("Done.")

if __name__ == "__main__":
    run_test()
