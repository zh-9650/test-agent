"""tests/api/test_app.py — FastAPI REST endpoint tests.

TDD tests for the API layer. Uses httpx.AsyncClient with ASGITransport.
The background task runner is mocked to avoid running actual tests.

All async tests are wrapped in a single event loop to avoid asyncpg
session/connection lifecycle issues with pytest-asyncio.
"""

import asyncio
import os
import pytest
from datetime import datetime, timezone

# Ensure DATABASE_URL points to test DB before importing app code
os.environ["DATABASE_URL"] = "postgresql://postgres:123456@localhost:5432/smart_test_test"

from sqlalchemy import select, text as sa_text

# Disable background tasks before importing app
import api.app as _api_app_module
_api_app_module._background_tasks_enabled = False

from api.app import app
from database.models import Base, Task, TaskStep, Report
from database.connection import async_session, create_async_engine_instance

from httpx import AsyncClient, ASGITransport


# ---------------------------------------------------------------------------
# Session-scoped setup / teardown
# ---------------------------------------------------------------------------

def setup_module():
    """Create test database tables before running any tests."""
    from sqlalchemy import create_engine, text
    from urllib.parse import urlparse

    db_url = os.environ["DATABASE_URL"]
    parsed = urlparse(db_url)
    db_name = parsed.path.lstrip("/")
    admin_url = f"{parsed.scheme}://{parsed.username}:{parsed.password}@{parsed.hostname}:{parsed.port or 5432}/postgres"

    # Create test database if not exists
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        result = conn.execute(
            text(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'")
        )
        if not result.scalar():
            conn.execute(text(f"CREATE DATABASE {db_name}"))
    admin_engine.dispose()

    # Create tables using async engine
    async def _create_tables():
        engine = create_async_engine_instance(db_url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()
    asyncio.get_event_loop().run_until_complete(_create_tables())


def teardown_module():
    """Drop the test database after all tests finish."""
    from sqlalchemy import create_engine, text
    from urllib.parse import urlparse

    db_url = os.environ["DATABASE_URL"]
    parsed = urlparse(db_url)
    db_name = parsed.path.lstrip("/")
    admin_url = f"{parsed.scheme}://{parsed.username}:{parsed.password}@{parsed.hostname}:{parsed.port or 5432}/postgres"

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(
            text(f"""
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = '{db_name}' AND pid <> pg_backend_pid()
            """)
        )
        conn.execute(text(f"DROP DATABASE IF EXISTS {db_name}"))
    admin_engine.dispose()


# ---------------------------------------------------------------------------
# Client helper
# ---------------------------------------------------------------------------

async def _get_client():
    """Async generator for httpx AsyncClient."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_create_task():
    """POST /api/tasks should create a task and return TaskResponse (201)."""
    async def _test():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/tasks", json={
                "target_url": "http://example.com/login",
                "task_name": "Login Test",
                "config": {"rules": ["check_login"]}
            })
            assert response.status_code == 201
            data = response.json()
            assert data["target_url"] == "http://example.com/login"
            assert data["task_name"] == "Login Test"
            assert data["status"] == "pending"
            assert "id" in data

    asyncio.get_event_loop().run_until_complete(_test())


def test_list_tasks():
    """GET /api/tasks should return a paginated list of tasks."""
    async def _test():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # First create a task
            await client.post("/api/tasks", json={
                "target_url": "http://example.com/list",
                "task_name": "List Test"
            })

            response = await client.get("/api/tasks")
            assert response.status_code == 200
            data = response.json()
            assert "tasks" in data
            assert "total" in data
            assert len(data["tasks"]) >= 1

    asyncio.get_event_loop().run_until_complete(_test())


def test_get_task():
    """GET /api/tasks/{id} should return a single task."""
    async def _test():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            create_response = await client.post("/api/tasks", json={
                "target_url": "http://example.com/get",
                "task_name": "Get Test"
            })
            task_id = create_response.json()["id"]

            response = await client.get(f"/api/tasks/{task_id}")
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == task_id
            assert data["task_name"] == "Get Test"

    asyncio.get_event_loop().run_until_complete(_test())


def test_get_task_not_found():
    """GET /api/tasks/99999 should return 404."""
    async def _test():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/tasks/99999")
            assert response.status_code == 404

    asyncio.get_event_loop().run_until_complete(_test())


def test_get_task_steps():
    """GET /api/tasks/{id}/steps should return task steps."""
    async def _test():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Create a task
            create_response = await client.post("/api/tasks", json={
                "target_url": "http://example.com/steps",
                "task_name": "Steps Test"
            })
            task_id = create_response.json()["id"]

            # Insert a step directly into the database
            async with async_session() as session:
                step = TaskStep(
                    task_id=task_id,
                    test_case_id="TC-001",
                    step_index=0,
                    action_type="click",
                    action_target="#login",
                    result="clicked",
                    screenshot_path="/tmp/s.png",
                )
                session.add(step)
                await session.commit()

            response = await client.get(f"/api/tasks/{task_id}/steps")
            assert response.status_code == 200
            data = response.json()
            assert "steps" in data
            assert data["total"] >= 1

    asyncio.get_event_loop().run_until_complete(_test())


def test_stop_task_not_running():
    """POST /api/tasks/{id}/stop on non-running task should return 400."""
    async def _test():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Create a task (defaults to pending)
            create_response = await client.post("/api/tasks", json={
                "target_url": "http://example.com/stop",
                "task_name": "Stop Test"
            })
            task_id = create_response.json()["id"]

            response = await client.post(f"/api/tasks/{task_id}/stop")
            assert response.status_code == 400

    asyncio.get_event_loop().run_until_complete(_test())


def test_delete_task():
    """DELETE /api/tasks/{id} should delete a task."""
    async def _test():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            create_response = await client.post("/api/tasks", json={
                "target_url": "http://example.com/delete",
                "task_name": "Delete Test"
            })
            task_id = create_response.json()["id"]

            response = await client.delete(f"/api/tasks/{task_id}")
            assert response.status_code == 200
            data = response.json()
            assert data["message"] == "Task deleted"

            # Verify it's gone
            get_response = await client.get(f"/api/tasks/{task_id}")
            assert get_response.status_code == 404

    asyncio.get_event_loop().run_until_complete(_test())


def test_cors_headers():
    """Response should include CORS headers for frontend dev server."""
    async def _test():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.options("/api/tasks", headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            })
            assert response.status_code == 200
            assert "access-control-allow-origin" in response.headers
            assert response.headers["access-control-allow-origin"] == "http://localhost:5173"

    asyncio.get_event_loop().run_until_complete(_test())
