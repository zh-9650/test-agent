"""agents/ui/setup_manager.py — Setup precondition manager for UI testing.

Manages shared setup operations (e.g., login) that multiple test cases depend on.
Executes setups using the same observe→decide→execute loop as test cases.
No hardcoded login functions — the AI decides what to do based on the page.
"""

from __future__ import annotations

from typing import Any

from core.interfaces import Setup, TestCase, TestState

# Module-level import so tests can mock it via patch("agents.ui.setup_manager.build_execution_graph")
# Also avoids circular import issues since execution_graph doesn't import setup_manager.
from agents.ui.execution_graph import build_execution_graph


async def execute_setup(setup: Setup, state: dict[str, Any]) -> dict[str, Any]:
    """Execute a setup using the same observe→decide→execute loop.

    A setup is essentially a mini test case — the AI sees the page,
    decides what to do, and executes. No hardcoded login functions.

    Args:
        setup: The Setup precondition to execute.
        state: The current TestState dict.

    Returns:
        Updated state after setup execution.
    """

    # Create a synthetic test case for the setup
    setup_case = TestCase(
        id=f"SETUP-{setup.id}",
        title=f"Setup: {setup.description}",
        description=setup.description,
        steps=[setup.description],
        expected="Setup completed successfully",
    )

    # Execute using the execution graph
    # The execution graph will handle observe→decide→execute→assert→record
    graph = build_execution_graph()
    setup_state = {
        **state,
        "test_plan": [setup_case],
        "current_index": 0,
        "current_step": 0,
    }

    result = await graph.ainvoke(setup_state)
    return result