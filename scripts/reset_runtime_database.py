"""Explicit development-only reset for runtime persistence."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.connection import reset_runtime_database


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--confirm-database",
        required=True,
        help="Exact DATABASE_URL database name to reset",
    )
    args = parser.parse_args()
    asyncio.run(reset_runtime_database(args.confirm_database))
    print(f"Runtime tables reset in database: {args.confirm_database}")


if __name__ == "__main__":
    main()
