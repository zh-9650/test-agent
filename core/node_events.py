"""In-memory observability events for execution graph diagnostics."""

from __future__ import annotations

import json
import sys
import time
from typing import Any

_events: list[dict[str, Any]] = []


def log_node_event(
    task_id: str,
    node_name: str,
    event_type: str,
    duration_ms: int = 0,
    token_count: int = 0,
) -> None:
    event = {
        "task_id": task_id,
        "node": node_name,
        "event": event_type,
        "duration_ms": duration_ms,
        "token_count": token_count,
        "ts": time.time(),
    }
    _events.append(event)
    try:
        sys.stderr.write(
            f"[L2_NODE_EVENT] {json.dumps(event, ensure_ascii=False)}\n"
        )
        sys.stderr.flush()
    except Exception:
        pass


def get_node_events(task_id: str = "") -> list[dict[str, Any]]:
    if not task_id:
        return list(_events)
    return [event for event in _events if event["task_id"] == task_id]


def clear_node_events() -> None:
    _events.clear()
