"""api/websocket.py — WebSocket handler for real-time test monitoring."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from database.connection import async_session
from database.models import Task


class ConnectionManager:
    """Manages WebSocket connections per task."""

    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, task_id: str):
        await websocket.accept()
        if task_id not in self.active_connections:
            self.active_connections[task_id] = []
        self.active_connections[task_id].append(websocket)

    def disconnect(self, websocket: WebSocket, task_id: str):
        if task_id in self.active_connections:
            self.active_connections[task_id] = [
                ws for ws in self.active_connections[task_id] if ws != websocket
            ]
            if not self.active_connections[task_id]:
                del self.active_connections[task_id]

    async def send_message(self, task_id: str, message: dict[str, Any]):
        """Send message to all connections for a task."""
        if task_id in self.active_connections:
            dead = []
            for ws in self.active_connections[task_id]:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.active_connections[task_id].remove(ws)

    async def broadcast(self, message: dict[str, Any]):
        """Send to all connected clients."""
        for task_id in list(self.active_connections.keys()):
            await self.send_message(task_id, message)


# Global connection manager
manager = ConnectionManager()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_ws_message(
    msg_type: str,
    test_case_id: str = "",
    step_index: int = 0,
    data: dict | None = None,
) -> dict[str, Any]:
    """Create a standardized WebSocket message."""
    return {
        "type": msg_type,
        "test_case_id": test_case_id,
        "step_index": step_index,
        "data": data or {},
        "timestamp": _now_iso(),
    }


async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """WebSocket endpoint for real-time test monitoring.

    Client connects to: ws://localhost:8000/ws/tasks/{task_id}
    """
    await manager.connect(websocket, task_id)
    try:
        while True:
            # Keep connection alive, listen for client messages (e.g., stop)
            data = await websocket.receive_text()
            if data == "stop":
                await _handle_stop(websocket, task_id)
                break
    except WebSocketDisconnect:
        manager.disconnect(websocket, task_id)
    except Exception:
        manager.disconnect(websocket, task_id)


async def _handle_stop(websocket: WebSocket, task_id: str) -> None:
    """Handle a stop request from a WebSocket client.

    Mirrors the REST endpoint POST /api/tasks/{task_id}/stop:
    1. Update task status to 'cancelled' in the database.
    2. Cancel the background asyncio task if it is still running.
    3. Notify the client via a session_complete message.
    """
    task_db_id = int(task_id)

    # 1. Update DB status to cancelled
    async with async_session() as session:
        task = await session.get(Task, task_db_id)
        if not task:
            await websocket.send_json(
                create_ws_message("error", data={"error": f"Task {task_id} not found"})
            )
            return
        if task.status != "running":
            await websocket.send_json(
                create_ws_message("error", data={"error": f"Task is not running (status: {task.status})"})
            )
            return
        task.status = "cancelled"
        await session.commit()

    # 2. Cancel the background asyncio task
    from api.app import _running_tasks

    background_task = _running_tasks.pop(task_db_id, None)
    if background_task and not background_task.done():
        background_task.cancel()

    # 3. Notify client
    await websocket.send_json(
        create_ws_message("session_complete", data={"action": "stopped"})
    )
    manager.disconnect(websocket, task_id)



