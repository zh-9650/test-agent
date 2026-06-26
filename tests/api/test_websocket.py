"""WebSocket transport tests."""

from unittest.mock import AsyncMock

import pytest

from api.websocket import ConnectionManager, create_ws_message


@pytest.mark.asyncio
async def test_connection_manager_connect_and_disconnect():
    manager = ConnectionManager()
    websocket = AsyncMock()
    await manager.connect(websocket, "task-123")
    websocket.accept.assert_awaited_once()
    assert websocket in manager.active_connections["task-123"]
    manager.disconnect(websocket, "task-123")
    assert "task-123" not in manager.active_connections


@pytest.mark.asyncio
async def test_send_message():
    manager = ConnectionManager()
    websocket = AsyncMock()
    await manager.connect(websocket, "task-123")
    message = create_ws_message(
        "phase_started",
        task_id=123,
        phase="analyzing",
    )
    await manager.send_message("task-123", message)
    websocket.send_json.assert_awaited_once_with(message)


@pytest.mark.asyncio
async def test_broadcast():
    manager = ConnectionManager()
    first = AsyncMock()
    second = AsyncMock()
    await manager.connect(first, "task-a")
    await manager.connect(second, "task-b")
    message = create_ws_message("session_completed")
    await manager.broadcast(message)
    first.send_json.assert_awaited_once_with(message)
    second.send_json.assert_awaited_once_with(message)


def test_message_envelope():
    message = create_ws_message(
        "case_step",
        task_id=1,
        run_id="run-1",
        phase="executing",
        candidate_case_id="TC-1",
        attempt_no=2,
        step_index=3,
        data={"result": "ok"},
    )
    assert set(message) == {
        "type",
        "task_id",
        "run_id",
        "phase",
        "candidate_case_id",
        "attempt_no",
        "step_index",
        "data",
        "timestamp",
    }
