"""api/websocket.py — WebSocket handler for real-time test monitoring."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

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
                # Client requested stop
                async with async_session() as session:
                    # Find task by config->task_id
                    result = await session.execute(select(Task))
                    # ... handle stop
                await websocket.send_json(
                    create_ws_message("session_complete", data={"action": "stopped"})
                )
                break
    except WebSocketDisconnect:
        manager.disconnect(websocket, task_id)
    except Exception:
        manager.disconnect(websocket, task_id)


async def stream_runtime_updates(runtime, task_id: str):
    """Stream Runtime updates to WebSocket clients.

    Called by the background task runner when a test session starts.
    Converts Runtime's run_stream() output to WebSocket messages.
    """
    async for update in runtime.run_stream():
        await manager.send_message(task_id, update)
