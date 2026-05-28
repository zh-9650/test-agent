"""
agents/ui/execution_graph.py — Execution subgraph for UI test execution.

Builds a LangGraph subgraph that iterates through test cases,
observe → decide → execute → assert → record → next.
"""