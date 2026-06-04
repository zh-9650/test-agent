"""Tests for CDP-based element resolution in tools.py — Phase 2.0D."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from agents.ui.tools import _resolve_via_cdp, _current_task_id, _task_contexts


class FakeCDP:
    """Fake CDP for resolve cdp test."""
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    async def send(self, method, params=None):
        self.calls.append({"method": method, "params": params or {}})
        if method in self.responses:
            return self.responses[method]
        return {}


@pytest.mark.asyncio
async def test_resolve_via_cdp_success():
    task_id = "test-task"
    target = "#3"
    
    # Mock lookup output
    entry = {"backend_node_id": 100}
    
    # Mock Playwright Page, Frames, Locators
    mock_locator = AsyncMock()
    mock_locator.count.return_value = 1
    mock_locator.first = mock_locator
    
    mock_frame = MagicMock()
    mock_frame.locator.return_value = mock_locator
    
    mock_page = MagicMock()
    mock_page.frames = [mock_frame]
    
    # Setup Context
    _current_task_id.set(task_id)
    
    # Setup CDP Fake
    fake_cdp = FakeCDP({
        "DOM.resolveNode": {
            "object": {
                "objectId": "obj-100",
                "frameId": "frame-100"
            }
        },
        "Runtime.callFunctionOn": {
            "result": {
                "value": "/html/body/div[1]"
            }
        }
    })
    
    _task_contexts[task_id] = {
        "page": mock_page,
        "cdp_session": fake_cdp,
        "element_map": {}
    }

    # Patch lookup
    with patch("core.backend_node_map.lookup", return_value=entry) as mock_lookup:
        result = await _resolve_via_cdp(mock_page, target, task_id)
        
        # Verify lookup called
        mock_lookup.assert_called_once()
        
        # Verify CDP calls
        methods = [c["method"] for c in fake_cdp.calls]
        assert "DOM.resolveNode" in methods
        assert "Runtime.callFunctionOn" in methods
        
        # There should be:
        # 1. setAttribute (callFunctionOn)
        # 2. xpath calculation (callFunctionOn)
        # 3. removeAttribute (callFunctionOn)
        # 4. Release object
        call_methods = [c["params"].get("functionDeclaration") for c in fake_cdp.calls if c["method"] == "Runtime.callFunctionOn"]
        assert any("setAttribute" in fn for fn in call_methods)
        assert any("removeAttribute" in fn for fn in call_methods)
        assert any("parentNode" in fn for fn in call_methods) # xpath generator
        
        # ReleaseObject call
        assert any(c["method"] == "Runtime.releaseObject" for c in fake_cdp.calls)
        
        # Verify frame locator was created and checked
        mock_frame.locator.assert_called()
        assert result == mock_locator
