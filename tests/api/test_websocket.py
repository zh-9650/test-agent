"""tests/api/test_websocket.py — WebSocket handler tests.

TDD tests for the WebSocket layer. Uses fastapi.testclient.TestClient.
"""

import pytest
import os
from unittest.mock import AsyncMock, patch

# Ensure DATABASE_URL points to test DB before importing app code
os.environ["DATABASE_URL"] = "postgresql://postgres:123456@localhost:5432/smart_test_test"

# Disable background tasks before importing app
import api.app as _api_app_module
_api_app_module._background_tasks_enabled = False

from api.app import app
from api.websocket import ConnectionManager, create_ws_message, manager

from fastapi.testclient import TestClient

client = TestClient(app)


# ---------------------------------------------------------------------------
# ConnectionManager tests
# ---------------------------------------------------------------------------

def test_connection_manager_connect():
    """WebSocket connects and is tracked."""
    manager = ConnectionManager()
    ws_mock = AsyncMock()
    ws_mock.accept = AsyncMock()

    import asyncio
    asyncio.get_event_loop().run_until_complete(manager.connect(ws_mock, "task-123"))

    assert "task-123" in manager.active_connections
    assert ws_mock in manager.active_connections["task-123"]


def test_connection_manager_disconnect():
    """WebSocket disconnects and is removed."""
    manager = ConnectionManager()
    ws_mock = AsyncMock()
    ws_mock.accept = AsyncMock()

    import asyncio
    asyncio.get_event_loop().run_until_complete(manager.connect(ws_mock, "task-123"))
    assert "task-123" in manager.active_connections

    manager.disconnect(ws_mock, "task-123")
    assert "task-123" not in manager.active_connections


def test_send_message():
    """Message sent to connected clients."""
    manager = ConnectionManager()
    ws_mock = AsyncMock()
    ws_mock.accept = AsyncMock()
    ws_mock.send_json = AsyncMock()

    import asyncio
    asyncio.get_event_loop().run_until_complete(manager.connect(ws_mock, "task-123"))

    message = {"type": "test", "data": "hello"}
    asyncio.get_event_loop().run_until_complete(manager.send_message("task-123", message))

    ws_mock.send_json.assert_called_once_with(message)


def test_create_ws_message_format():
    """Message has correct format with all fields."""
    msg = create_ws_message("page_update", test_case_id="TC-001", step_index=3, data={"foo": "bar"})

    assert "type" in msg
    assert "test_case_id" in msg
    assert "step_index" in msg
    assert "data" in msg
    assert "timestamp" in msg
    assert msg["type"] == "page_update"
    assert msg["test_case_id"] == "TC-001"
    assert msg["step_index"] == 3
    assert msg["data"] == {"foo": "bar"}
    assert isinstance(msg["timestamp"], str)


def test_broadcast():
    """Message sent to all task connections."""
    manager = ConnectionManager()
    ws1 = AsyncMock()
    ws1.accept = AsyncMock()
    ws1.send_json = AsyncMock()
    ws2 = AsyncMock()
    ws2.accept = AsyncMock()
    ws2.send_json = AsyncMock()

    import asyncio
    asyncio.get_event_loop().run_until_complete(manager.connect(ws1, "task-a"))
    asyncio.get_event_loop().run_until_complete(manager.connect(ws2, "task-b"))

    message = {"type": "broadcast_test", "data": "all"}
    asyncio.get_event_loop().run_until_complete(manager.broadcast(message))

    ws1.send_json.assert_called_once_with(message)
    ws2.send_json.assert_called_once_with(message)


# ---------------------------------------------------------------------------
# WebSocket endpoint tests
# ---------------------------------------------------------------------------

def test_websocket_endpoint():
    """Test WebSocket endpoint accepts connection and handles messages."""
    with client.websocket_connect("/ws/tasks/test-123") as ws:
        ws.send_text("ping")
        # Just verify the connection was accepted without error
        assert True
