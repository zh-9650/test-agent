"""
database/connection.py — SQLAlchemy engine, session, and database initialization.

Creates the engine, session factory, and provides utility to auto-create
the smart_test database and all tables on first run.
"""

from __future__ import annotations

import asyncio
import os
from urllib.parse import urlparse

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base

load_dotenv(override=True)

DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://postgres:123456@localhost:5432/smart_test")


# ---------------------------------------------------------------------------
# Engine factory helpers (for tests and runtime reuse)
# ---------------------------------------------------------------------------

def create_async_engine_instance(database_url: str | None = None) -> AsyncEngine:
    """Create an async SQLAlchemy engine using asyncpg.

    Args:
        database_url: Full async PostgreSQL URL. Defaults to DATABASE_URL env var.

    Returns:
        AsyncEngine instance.
    """
    url = database_url or DATABASE_URL
    # Ensure the URL uses asyncpg driver
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif not url.startswith("postgresql+asyncpg://"):
        raise ValueError("DATABASE_URL must start with postgresql://")
    return create_async_engine(
        url,
        echo=False,
        future=True,
        pool_pre_ping=True,
        connect_args={"server_settings": {"client_encoding": "utf8"}},
    )


def create_sync_engine(database_url: str | None = None):
    """Create a synchronous SQLAlchemy engine (for auto-init)."""
    url = database_url or DATABASE_URL
    # Keep psycopg2 driver (or generic postgresql://)
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return create_engine(url, echo=False, future=True)


# ---------------------------------------------------------------------------
# Global engines / session factories (imported by application code)
# ---------------------------------------------------------------------------

# Async engine used by the application
_engine = None


def get_async_engine() -> AsyncEngine:
    """Get or create the singleton async engine."""
    global _engine
    if _engine is None:
        _engine = create_async_engine_instance()
    return _engine


# Session factory: async_sessionmaker with AsyncSession
async_session = async_sessionmaker(
    get_async_engine(),
    class_=AsyncSession,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# Database auto-init
# ---------------------------------------------------------------------------

def _parse_db_url(url: str) -> tuple[str, str]:
    """Parse a PostgreSQL URL and return (admin_url, db_name).

    Args:
        url: PostgreSQL connection URL.

    Returns:
        Tuple of (admin connection URL pointing to 'postgres' db, target db name).
    """
    parsed = urlparse(url)
    db_name = parsed.path.lstrip("/")
    port = parsed.port or 5432
    admin_url = f"{parsed.scheme}://{parsed.username}:{parsed.password}@{parsed.hostname}:{port}/postgres"
    return admin_url, db_name


def _create_database_if_not_exists(db_name: str, admin_url: str) -> None:
    """Create the target database if it does not already exist.

    Args:
        db_name: Name of the database to create.
        admin_url: Connection URL to the 'postgres' admin database.
    """
    # Use sync engine with AUTOCOMMIT isolation to avoid transaction block
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": db_name},
        )
        if not result.scalar():
            # PostgreSQL identifiers cannot contain parameters, so use safe formatting
            conn.execute(text(f'CREATE DATABASE "{db_name}" ENCODING \'UTF8\''))
    engine.dispose()


def _run_create_all(sync_url: str) -> None:
    """Create tables and apply the small Phase 1 compatibility upgrades."""
    engine = create_engine(sync_url)
    with engine.begin() as connection:
        Base.metadata.create_all(bind=connection)
        # create_all() does not add columns to existing tables. Phase 1 avoids
        # Alembic, so additive schema changes must remain idempotent here.
        connection.execute(text(
            "ALTER TABLE task_step "
            "ADD COLUMN IF NOT EXISTS test_case_status VARCHAR(50)"
        ))
        connection.execute(text(
            "ALTER TABLE task_step "
            "ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0"
        ))
        connection.execute(text(
            "ALTER TABLE task_step "
            "ADD COLUMN IF NOT EXISTS failure_context JSONB"
        ))
    engine.dispose()


async def init_database() -> None:
    """Auto-create the smart_test database and tables on first run.

    Steps:
        1. Load DATABASE_URL from environment.
        2. Connect to the 'postgres' admin database.
        3. Check if the target database exists; create it if not.
        4. Connect to the target database and run Base.metadata.create_all().
    """
    admin_url, db_name = _parse_db_url(DATABASE_URL)

    # Step 1: Create database if it doesn't exist (sync)
    _create_database_if_not_exists(db_name, admin_url)

    # Step 2: Build target sync URL for create_all
    parsed = urlparse(DATABASE_URL)
    port = parsed.port or 5432
    target_sync_url = (
        f"{parsed.scheme}://{parsed.username}:{parsed.password}"
        f"@{parsed.hostname}:{port}/{db_name}"
    )
    _run_create_all(target_sync_url)
