import requests
import json

url = "http://localhost:8000/api/tasks"
payload = {
    "task_name": "Phase 1.5 Integration Test",
    "target_url": "https://www.saucedemo.com/",
    "config": {
        "accounts": [
            {"role": "standard_user", "username": "standard_user", "password": "secret_sauce"}
        ],
        "prd": "请参考需求文档：https://raw.githubusercontent.com/langchain-ai/langchain/master/README.md",
        "api_doc": "Swagger API:\\n/api/login - POST\\nParameters: username (string), password (string)\\n\\n/api/checkout - POST\\nParameters: firstName (string), lastName (string), postalCode (string, max 10)\\n",
        "focus_areas": ["登录页错误提示", "加入购物车"]
    }
}

headers = {
    "Content-Type": "application/json"
}

try:
    response = requests.post(url, json=payload)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
except Exception as e:
    print(f"Failed to trigger task: {e}")
