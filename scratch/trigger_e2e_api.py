import json
import urllib.request

def main():
    url = "http://127.0.0.1:8001/api/tasks"
    data = {
        "target_url": "http://192.168.31.155/login",
        "task_name": "E2E Live Verification via API",
        "config": {
            "accounts": [
                {
                    "role": "test",
                    "username": "test_c",
                    "password": "123456"
                }
            ],
            "rules": "不要点击非登录相关的外部链接，主要验证用户名密码登录和界面功能。",
            "focus_areas": "用户登录、表单输入、登录结果校验"
        }
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    
    print("Sending API request to create and launch E2E task...")
    try:
        with urllib.request.urlopen(req) as response:
            res_body = response.read().decode("utf-8")
            res_json = json.loads(res_body)
            print("\n=== Task Created Successfully ===")
            print(f"Task ID: {res_json.get('id')}")
            print(f"Task Name: {res_json.get('task_name')}")
            print(f"Status: {res_json.get('status')}")
            print(f"Created At: {res_json.get('created_at')}")
    except Exception as e:
        print("API Request failed:", e)

if __name__ == "__main__":
    main()
