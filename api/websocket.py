"""WebSocket transport for authoritative task events."""

from __future__ import annotations

from datetime import datetime, timezone
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, task_id: str) -> None:
        await websocket.accept()
        self.active_connections.setdefault(task_id, []).append(websocket)

    def disconnect(self, websocket: WebSocket, task_id: str) -> None:
        connections = self.active_connections.get(task_id, [])
        self.active_connections[task_id] = [
            current for current in connections if current != websocket
        ]
        if not self.active_connections[task_id]:
            self.active_connections.pop(task_id, None)

    async def send_message(self, task_id: str, message: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for websocket in self.active_connections.get(task_id, []):
            try:
                await websocket.send_json(message)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(websocket, task_id)

    async def broadcast(self, message: dict[str, Any]) -> None:
        for task_id in list(self.active_connections):
            await self.send_message(task_id, message)


manager = ConnectionManager()

StopHandler = Callable[[int], Awaitable[None]]
_stop_handler: StopHandler | None = None


def set_stop_handler(handler: StopHandler) -> None:
    global _stop_handler
    _stop_handler = handler


def create_ws_message(
    msg_type: str,
    *,
    task_id: int | None = None,
    run_id: str = "",
    phase: str | None = None,
    candidate_case_id: str = "",
    attempt_no: int | None = None,
    step_index: int | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": msg_type,
        "task_id": task_id,
        "run_id": run_id,
        "phase": phase,
        "candidate_case_id": candidate_case_id,
        "attempt_no": attempt_no,
        "step_index": step_index,
        "data": data or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def websocket_endpoint(websocket: WebSocket, task_id: str) -> None:
    await manager.connect(websocket, task_id)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "stop" and _stop_handler is not None:
                await _stop_handler(int(task_id))
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket, task_id)
