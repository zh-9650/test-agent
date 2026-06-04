"""core/backend_node_map.py — Phase 2.0D: backendNodeId persistence layer.

Why this exists
---------------
CDP's `backendNodeId` is a stable identifier for a DOM node across page
navigations, iframe boundaries, and DOM mutations. Storing backendNodeId
from one observe() cycle and reusing it for the next execute() cycle:

1. **Avoids brittle XPath/CSS selectors** that break when class names or
   DOM structure change between navigations.
2. **Survives minor DOM reorders** — backendNodeId stays attached to the
   node even when its position in the DOM tree shifts.
3. **Enables fast re-anchoring** — instead of re-running the full AXTree
   query to find a target by text, we resolve_node() directly.

Persistence semantics
---------------------
- Map is keyed by `task_id` so multiple concurrent test runs don't
  interfere.
- Map is `element_id -> {backend_node_id, frame_id, last_seen_step, attrs_snapshot}`
- Entries older than MAX_AGE_STEPS are pruned on access.
- Map is a single-process dict; for multi-worker deployment, swap with
  a Redis-backed implementation (out of scope Phase 2.0D).

This module is deliberately side-effect-free: pure data structure with
get/set/prune. CDP session management stays in cdp_client.py.
"""

from __future__ import annotations

import time
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_AGE_STEPS = 20  # entries older than this are pruned on access
MAX_ENTRIES_PER_TASK = 500  # hard cap to prevent unbounded growth

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

# task_id -> { element_id (str) -> entry dict }
_node_map: dict[str, dict[str, dict[str, Any]]] = {}


def _prune_old(task_id: str, current_step: int) -> None:
    """Remove entries older than MAX_AGE_STEPS for the given task."""
    entries = _node_map.get(task_id)
    if not entries:
        return
    stale = [
        eid for eid, ent in entries.items()
        if current_step - ent.get("last_seen_step", 0) > MAX_AGE_STEPS
    ]
    for eid in stale:
        entries.pop(eid, None)
    # Hard cap
    if len(entries) > MAX_ENTRIES_PER_TASK:
        sorted_by_step = sorted(
            entries.items(),
            key=lambda kv: kv[1].get("last_seen_step", 0),
        )
        for eid, _ in sorted_by_step[: len(entries) - MAX_ENTRIES_PER_TASK]:
            entries.pop(eid, None)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def store(task_id: str, element_id: str, backend_node_id: int,
          frame_id: str = "", attrs: dict | None = None,
          current_step: int = 0) -> None:
    """Store or update a backendNodeId entry for an element.

    Args:
        task_id: owning test task
        element_id: e.g. "#3" or "submit-btn" — LLM-facing identifier
        backend_node_id: CDP backendNodeId from AXTree
        frame_id: frame this node lives in (for iframe handling)
        attrs: snapshot of HTML attributes (id/class/text) for verification
        current_step: current execution step (used for age-based pruning)
    """
    if not task_id or not element_id or not backend_node_id:
        return
    bucket = _node_map.setdefault(task_id, {})
    bucket[element_id] = {
        "backend_node_id": int(backend_node_id),
        "frame_id": frame_id or "",
        "attrs": dict(attrs) if attrs else {},
        "last_seen_step": int(current_step),
        "stored_at": time.time(),
    }


def lookup(task_id: str, element_id: str, current_step: int = 0) -> dict[str, Any] | None:
    """Look up a stored backendNodeId. Returns None if missing or stale.

    Side effect: prunes entries older than MAX_AGE_STEPS from this task.
    """
    if not task_id or not element_id:
        return None
    _prune_old(task_id, current_step)
    bucket = _node_map.get(task_id, {})
    entry = bucket.get(element_id)
    if not entry:
        return None
    # Touch: update last_seen_step so the entry survives longer
    entry["last_seen_step"] = int(current_step)
    return dict(entry)  # defensive copy


def get_all(task_id: str) -> dict[str, dict[str, Any]]:
    """Return a snapshot of all entries for a task (for debugging / test inspection)."""
    bucket = _node_map.get(task_id, {})
    return {eid: dict(ent) for eid, ent in bucket.items()}


def clear(task_id: str) -> None:
    """Remove all entries for a task (call on task end / cleanup)."""
    _node_map.pop(task_id, None)


def clear_all() -> None:
    """Wipe the entire map (test helper)."""
    _node_map.clear()


def stats() -> dict[str, Any]:
    """Aggregate stats for monitoring / test assertions."""
    return {
        "tasks": len(_node_map),
        "total_entries": sum(len(b) for b in _node_map.values()),
        "per_task": {tid: len(b) for tid, b in _node_map.items()},
    }
