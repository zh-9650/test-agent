import os
import shutil
import asyncio
from sqlalchemy import create_engine

# 1. Clear database
from database.connection import create_sync_engine
from database.models import Base

def reset_db():
    print("Resetting database...")
    engine = create_sync_engine()
    # Drop all tables
    Base.metadata.drop_all(bind=engine)
    # Recreate all tables
    Base.metadata.create_all(bind=engine)
    print("Database reset complete.")

# 2. Clear data directories
def clear_dirs():
    print("Clearing data directories...")
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    if os.path.exists(data_dir):
        for item in os.listdir(data_dir):
            item_path = os.path.join(data_dir, item)
            if os.path.isdir(item_path):
                shutil.rmtree(item_path, ignore_errors=True)
            else:
                os.remove(item_path)
    print("Data directories cleared.")

if __name__ == "__main__":
    reset_db()
    clear_dirs()
