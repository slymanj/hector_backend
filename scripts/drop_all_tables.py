#!/usr/bin/env python3
"""
Drop ALL tables, views, sequences, and custom enum types in the public schema.

WARNING: This permanently deletes all data in the configured database.
         Does not drop the database itself — only objects inside schema "public".

Usage (from hector_backend/):
    source venv/bin/activate
    python scripts/drop_all_tables.py
    python scripts/drop_all_tables.py --yes   # skip confirmation
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow imports when run as scripts/drop_all_tables.py
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text

from api.utils.settings import settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Drop all public schema objects")
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip interactive confirmation",
    )
    args = parser.parse_args()

    host = settings.DB_HOST
    name = settings.DB_NAME
    user = settings.DB_USER

    print("=" * 60)
    print("  DROP ALL TABLES — DESTRUCTIVE")
    print("=" * 60)
    print(f"  Host: {host}")
    print(f"  Database: {name}")
    print(f"  User: {user}")
    print("=" * 60)

    if not args.yes:
        confirm = input('Type the database name to confirm wipe: ').strip()
        if confirm != name:
            print("Aborted (name did not match).")
            return 1

    engine = create_engine(
        settings.SQLALCHEMY_DATABASE_URI,
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 15},
    )

    sql = """
    DROP SCHEMA IF EXISTS public CASCADE;
    CREATE SCHEMA public;
    GRANT ALL ON SCHEMA public TO public;
    GRANT ALL ON SCHEMA public TO CURRENT_USER;
    """

    print("Dropping schema public CASCADE and recreating empty schema...")
    with engine.connect() as conn:
        conn.execute(text(sql))

    print("Done. Public schema is empty (no tables, no alembic_version, no enums).")
    print("Next:")
    print("  alembic upgrade head")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
