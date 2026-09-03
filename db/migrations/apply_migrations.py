"""
Applies all .sql files in this directory, in filename order, tracking
what's already been applied in a schema_migrations table so it's safe to
re-run.

Usage:
    DATABASE_URL=postgresql://localhost/propview_dev python apply_migrations.py
"""

import os
import sys
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).parent


def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "postgresql://localhost/propview_dev")
    conn = psycopg.connect(database_url, autocommit=True)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    applied = {row[0] for row in conn.execute("SELECT filename FROM schema_migrations").fetchall()}

    sql_files = sorted(p for p in MIGRATIONS_DIR.glob("*.sql"))
    if not sql_files:
        sys.exit(f"No .sql files found in {MIGRATIONS_DIR}")

    for path in sql_files:
        if path.name in applied:
            print(f"skip  {path.name} (already applied)")
            continue
        print(f"apply {path.name}")
        conn.execute(path.read_text())
        conn.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,))

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
