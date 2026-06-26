"""Tests for core/cdp_client.py resolveNode / releaseObject — Phase 2.0D."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from core.cdp_client import _ax_role_to_type, release_object, resolve_node


class FakeCDP:
    """Minimal fake CDP session for testing."""
    def __init__(self, responses: dict | None = None):
        self.responses = responses or {}
        self.calls: list[dict] = []

    async def send(self, method: str, params: dict | None = None) -> dict:
        self.calls.append({"method": method, "params": params or {}})
        if method in self.responses:
            return self.responses[method]
        return {}


@pytest.mark.asyncio
async def test_resolve_node_returns_object_id():
    cdp = FakeCDP({
        "DOM.resolveNode": {
            "object": {
                "objectId": "obj-123",
                "frameId": "frame-456",
            }
        }
    })
    result = await resolve_node(cdp, backend_node_id=42)
    assert result is not None
    assert result["objectId"] == "obj-123"
    assert result["frameId"] == "frame-456"
    assert result["backendNodeId"] == 42
    assert cdp.calls[0]["method"] == "DOM.resolveNode"
    assert cdp.calls[0]["params"]["backendNodeId"] == 42


@pytest.mark.asyncio
async def test_resolve_node_no_cdp_returns_none():
    assert await resolve_node(None, backend_node_id=42) is None


@pytest.mark.asyncio
async def test_resolve_node_zero_id_returns_none():
    cdp = FakeCDP()
    assert await resolve_node(cdp, backend_node_id=0) is None
    assert len(cdp.calls) == 0  # 不应该发请求


@pytest.mark.asyncio
async def test_resolve_node_cdp_error_returns_none():
    class ErrorCDP:
        async def send(self, method, params=None):
            raise RuntimeError("CDP disconnected")
    result = await resolve_node(ErrorCDP(), backend_node_id=42)
    assert result is None


@pytest.mark.asyncio
async def test_release_object_calls_runtime():
    cdp = FakeCDP()
    await release_object(cdp, "obj-123")
    assert cdp.calls[0]["method"] == "Runtime.releaseObject"
    assert cdp.calls[0]["params"]["objectId"] == "obj-123"


@pytest.mark.asyncio
async def test_release_object_no_cdp_noop():
    await release_object(None, "obj-123")  # should not raise


@pytest.mark.asyncio
async def test_release_object_empty_id_noop():
    cdp = FakeCDP()
    await release_object(cdp, "")
    assert len(cdp.calls) == 0


@pytest.mark.asyncio
async def test_release_object_cdp_error_swallowed():
    class ErrorCDP:
        async def send(self, method, params=None):
            raise RuntimeError("CDP gone")
    await release_object(ErrorCDP(), "obj-123")  # should not raise


def test_ax_role_mapping_preserves_complex_form_control_types():
    assert _ax_role_to_type(
        "button",
        {"tagName": "input", "type": "file"},
    ) == "input"
    assert _ax_role_to_type(
        "textbox",
        {"tagName": "textarea"},
    ) == "textarea"
    assert _ax_role_to_type(
        "combobox",
        {"tagName": "select"},
    ) == "select"
