"""pytest configuration for async tests."""

import asyncio
import os
import pytest

# Ensure we use test database for all tests to protect production data
os.environ["DATABASE_URL"] = "postgresql://postgres:123456@localhost:5432/smart_test_test"

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the whole session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()



