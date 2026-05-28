"""
agents/ui/setup_manager.py — Setup precondition manager for UI testing.

Manages shared setup operations (e.g., login) that multiple test cases depend on.
Executes setups using the same observe→decide→execute loop as test cases.
"""