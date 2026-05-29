"""
main.py — AI Native Testing Platform unified entry point.

Starts both backend (uvicorn) and frontend (npm run dev).
Auto-detects and creates the smart_test database.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys

from dotenv import load_dotenv

load_dotenv()

BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))
FRONTEND_PORT = int(os.getenv("FRONTEND_PORT", "5173"))
START_FRONTEND = os.getenv("START_FRONTEND", "true").lower() in ("true", "1", "yes")


def main() -> None:
    """Start the backend and optionally the frontend dev server."""
    import uvicorn

    processes: list[subprocess.Popen] = []

    def shutdown(signum: int, frame: object) -> None:
        """Gracefully terminate child processes on SIGINT/SIGTERM."""
        print("\n[main] Shutting down...")
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
        for proc in processes:
            proc.wait(timeout=10)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Start frontend dev server (if enabled)
    if START_FRONTEND:
        frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")
        if os.path.isdir(frontend_dir):
            print(f"[main] Starting frontend dev server on port {FRONTEND_PORT}...")
            env = os.environ.copy()
            env["PORT"] = str(FRONTEND_PORT)
            frontend_proc = subprocess.Popen(
                ["npm.cmd", "run", "dev", "--", "--port", str(FRONTEND_PORT), "--host", "127.0.0.1"],
                cwd=frontend_dir,
                env=env,
            )
            processes.append(frontend_proc)
        else:
            print(f"[main] Warning: frontend directory not found at {frontend_dir}, skipping.")

    # Start backend (uvicorn)
    print(f"[main] Starting backend on port {BACKEND_PORT}...")
    uvicorn.run(
        "api.app:app",
        host="0.0.0.0",
        port=BACKEND_PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()
