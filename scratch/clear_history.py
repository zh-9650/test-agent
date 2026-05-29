import os
import sys
import shutil
import urllib.request
import json
from sqlalchemy import create_engine, text

# Add the project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.connection import DATABASE_URL

def stop_running_tasks():
    print("=== Stopping Running Tasks via API ===")
    url = DATABASE_URL
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    
    engine = create_engine(url)
    running_ids = []
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT id FROM task WHERE status = 'running'")).fetchall()
            running_ids = [row[0] for row in result]
    except Exception as e:
        print(f"Failed to query database for running tasks: {e}")
        return
    
    for tid in running_ids:
        print(f"Attempting to stop Task {tid}...")
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:8001/api/tasks/{tid}/stop",
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                resp_data = json.loads(response.read().decode('utf-8'))
                print(f"Successfully stopped Task {tid}: {resp_data}")
        except Exception as e:
            print(f"Could not stop Task {tid} via API: {e} (The task might have finished or backend is starting up)")

def clear_database():
    print("\n=== Clearing Database Tables ===")
    url = DATABASE_URL
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            # PostgreSQL requires AUTOCOMMIT or transaction block.
            # Using transaction block ensures all tables are truncated CASCADE.
            with conn.begin():
                print("Truncating tables: task, task_step, report...")
                conn.execute(text("TRUNCATE TABLE task, task_step, report CASCADE;"))
            print("Database tables cleared successfully!")
    except Exception as e:
        print(f"Failed to truncate database tables: {e}")

def clear_files():
    print("\n=== Clearing Session, Screenshot, and Report Files ===")
    directories = [
        "data/sessions",
        "data/reports",
        "data/screenshots"
    ]
    for d in directories:
        if not os.path.exists(d):
            continue
        print(f"Cleaning directory: {d}...")
        for item in os.listdir(d):
            if item == ".gitkeep":
                continue
            path = os.path.join(d, item)
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                print(f"  Removed: {path}")
            except Exception as e:
                print(f"  Failed to remove {path}: {e}")
    print("Files cleared successfully!")

if __name__ == "__main__":
    stop_running_tasks()
    clear_database()
    clear_files()
    print("\n=== All historical execution records have been successfully cleared! ===")
