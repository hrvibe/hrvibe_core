#!/usr/bin/env python3
"""
Idempotent schema migration entrypoint for Render.com (one-off job or bash).
Creates schema_migrations table and applies initial schema (Base.metadata.create_all).
Safe to run multiple times. Exits non-zero on failure.
Usage: python scripts/migrate.py (run from project root, or set PYTHONPATH to project root).
"""
import os
import sys
import logging

# Project root = parent of scripts/
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Load env before importing database (needs DATABASE_URL)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("migrate")

# Migration version for initial schema (create_all)
SCHEMA_VERSION_INITIAL = 1


def run_migrate() -> bool:
    """
    Apply migrations idempotently. Returns True on success, False on failure.
    """
    try:
        from sqlalchemy import text
        from shared_services.database import get_engine, Base
    except Exception as e:
        logger.error("Failed to import database: %s", e)
        return False

    engine = get_engine()
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

    # Apply initial schema (create_all is idempotent: existing tables are left unchanged)
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

    logger.info("Migration completed successfully (version %s).", SCHEMA_VERSION_INITIAL)
    return True


def main():
    if not os.getenv("DATABASE_URL"):
        logger.error("DATABASE_URL is not set. Set it in environment or .env.")
        sys.exit(1)
    if run_migrate():
        sys.exit(0)
    sys.exit(1)


if __name__ == "__main__":
    main()
