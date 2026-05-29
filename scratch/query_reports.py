import os
import sys
from sqlalchemy import create_engine, text

# Add the project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.connection import DATABASE_URL

def main():
    url = DATABASE_URL
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    
    engine = create_engine(url)
    with engine.connect() as conn:
        print("=== Checking Reports for Task 45 ===")
        reports = conn.execute(text("SELECT id, report_path, summary, created_at FROM report WHERE task_id = 45")).fetchall()
        if not reports:
            print("No reports found for Task 45.")
        for r in reports:
            print(f"Report ID: {r.id}")
            print(f"  Path: {r.report_path}")
            print(f"  Summary: {r.summary}")
            print(f"  Created: {r.created_at}")

        print("\n=== Checking Reports for Task 46 ===")
        reports_46 = conn.execute(text("SELECT id, report_path, summary, created_at FROM report WHERE task_id = 46")).fetchall()
        if not reports_46:
            print("No reports found for Task 46.")
        for r in reports_46:
            print(f"Report ID: {r.id}")
            print(f"  Path: {r.report_path}")
            print(f"  Summary: {r.summary}")
            print(f"  Created: {r.created_at}")

if __name__ == "__main__":
    main()
