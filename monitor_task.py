import requests
import time
import sys

task_id = 11
url = f"http://localhost:8000/api/tasks/{task_id}"
report_url = f"http://localhost:8000/api/tasks/{task_id}/report"

print(f"Monitoring task {task_id}...")

while True:
    try:
        response = requests.get(url)
        data = response.json()
        status = data.get("status")
        print(f"Current status: {status}")
        if status in ["completed", "failed", "error"]:
            print("Task finished!")
            # Get the report
            report_response = requests.get(report_url)
            print("--- REPORT ---")
            print(report_response.text)
            break
    except Exception as e:
        print(f"Error polling: {e}")
    time.sleep(10)
