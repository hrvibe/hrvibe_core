#!/usr/bin/env python3
"""
Idempotent schema migration for local development.
Uses DATABASE_URL_LOCAL from .env if set (so you can keep DATABASE_URL for Render);
otherwise falls back to DATABASE_URL.
Creates schema_migrations table and applies initial schema (Base.metadata.create_all).
Safe to run multiple times. Exits non-zero on failure.

Usage (from project root):
  python scripts/migrate_local_db.py

In .env set DATABASE_URL_LOCAL for your local DB, e.g.:
  DATABASE_URL_LOCAL=postgresql://gridavyv@localhost:5432/hrvibe_new
"""
import os
import sys
import logging

# Project root = parent of scripts/
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Load .env from project root
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(_project_root, ".env"))
except ImportError:
    pass

# Use local DB URL for this script so we don't touch Render DB when migrating locally
_local_url = os.getenv("DATABASE_URL_LOCAL") or os.getenv("DATABASE_URL")
if _local_url:
    os.environ["DATABASE_URL"] = _local_url

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("migrate_local_db")

SCHEMA_VERSION_INITIAL = 1


def run_migrate_local() -> bool:
    """Apply migrations idempotently to local DB. Returns True on success, False on failure."""
    try:
        from sqlalchemy import text
        from shared_services.database import get_engine, Base
    except Exception as e:
        logger.error("Failed to import database: %s", e)
        return False

    engine = get_engine()
    url = engine.url
    db_info = f"{url.host or 'localhost'}:{url.port or 5432}/{url.database}"
    logger.info("Local migration targeting database: %s", db_info)

    # Create schema_migrations table if not exists
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.commit()

    # Check if initial schema already applied
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM schema_migrations WHERE version = :v"),
            {"v": SCHEMA_VERSION_INITIAL},
        ).fetchone()
        if row:
            logger.info("Schema version %s already applied; nothing to do.", SCHEMA_VERSION_INITIAL)
            return True

    # Apply initial schema
    logger.info("Applying initial schema (version %s)...", SCHEMA_VERSION_INITIAL)
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        logger.error("Schema create_all failed: %s", e)
        return False

    # Record version
    with engine.connect() as conn:
        conn.execute(
            text("INSERT INTO schema_migrations (version) VALUES (:v)"),
            {"v": SCHEMA_VERSION_INITIAL},
        )
        conn.commit()

    logger.info("Local migration completed successfully (version %s).", SCHEMA_VERSION_INITIAL)
    return True


def main():
    url = os.getenv("DATABASE_URL_LOCAL") or os.getenv("DATABASE_URL")
    if not url:
        logger.error(
            "DATABASE_URL_LOCAL or DATABASE_URL must be set in .env. "
            "For local migration set DATABASE_URL_LOCAL=postgresql://user@localhost:5432/hrvibe_new"
        )
        sys.exit(1)
    if run_migrate_local():
        sys.exit(0)
    sys.exit(1)


if __name__ == "__main__":
    main()
