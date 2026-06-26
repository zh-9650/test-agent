"""pytest configuration for async tests."""
import asyncio
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load .env from project root so ANTHROPIC_* vars are available to live LLM tests.
# Use non-override mode so test-specific env vars (set below) take precedence.
load_dotenv()

# Ensure we use test database for all tests to protect production data
os.environ["DATABASE_URL"] = "postgresql://postgres:123456@localhost:5432/smart_test_test"
_session_suffix = str(os.getpid())
os.environ.setdefault(
    "BROWSER_USE_CONFIG_DIR",
    str(Path(".tmp") / f"browser-use-{_session_suffix}"),
)


def pytest_configure(config):
    """Use a process-specific temp root to avoid Windows ACL collisions."""
    config.option.basetemp = str(
        Path(".tmp") / f"pytest-runtime-{_session_suffix}"
    )

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the whole session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

