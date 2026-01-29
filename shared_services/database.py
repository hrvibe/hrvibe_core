"""
Shared database models and configuration for manager_bot and applicant_bot.
Pure importable module: no schema creation or migrations at import time.
Both services use this module for DB access only. Run migrations via scripts/migrate.py.
"""
import os
import logging
from sqlalchemy import (
    create_engine,
    Column,
    String,
    Boolean,
    BigInteger,
    TIMESTAMP,
    ForeignKey,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func

logger = logging.getLogger(__name__)

# --- Configuration from environment (no config.py dependency for DB-only usage) ---
def _get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url or not url.strip():
        raise ValueError(
            "DATABASE_URL environment variable is not set. "
            "Set it for DB connection (e.g. on Render: Postgres connection string)."
        )
    url = url.strip().rstrip("%")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def _engine_config():
    pool_size = int(os.getenv("DB_POOL_SIZE", "5"))
    max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "10"))
    pool_timeout = int(os.getenv("DB_POOL_TIMEOUT", "30"))
    return {
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_size": pool_size,
        "max_overflow": max_overflow,
        "pool_timeout": pool_timeout,
        "echo": False,
    }


# Lazy engine/session: created on first use so env can be set before import side-effects
_engine = None
_SessionLocal = None


def get_engine():
    """Return the shared SQLAlchemy engine. Creates it on first call."""
    global _engine
    if _engine is None:
        _engine = create_engine(_get_database_url(), **_engine_config())
    return _engine


def get_session_factory():
    """Return the sessionmaker (SessionLocal). Creates it on first call."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
        )
    return _SessionLocal


def get_session():
    """Return a new DB session. Use as context manager or call .close() when done."""
    return get_session_factory()()


Base = declarative_base()


class Managers(Base):
    __tablename__ = "managers"

    id = Column(String, primary_key=True)
    username = Column(String)
    first_name = Column(String)
    last_name = Column(String)
    first_time_seen = Column(TIMESTAMP(timezone=True), default=func.now())
    privacy_policy_confirmed = Column(Boolean, default=False, nullable=False)
    privacy_policy_confirmation_time = Column(TIMESTAMP(timezone=True))
    access_token_recieved = Column(Boolean, default=False, nullable=False)
    access_token = Column(String)
    access_token_expires_at = Column(BigInteger)
    hh_data = Column(JSONB)
    vacancy_selected = Column(Boolean, default=False, nullable=False)
    messages_with_keyboards = Column(JSONB, default=list)
    created_at = Column(TIMESTAMP(timezone=True), default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), default=func.now(), onupdate=func.now())


class Vacancies(Base):
    __tablename__ = "vacancies"

    id = Column(String, primary_key=True)
    manager_id = Column(String, ForeignKey("managers.id"), nullable=False)
    name = Column(String)
    video_sending_confirmed = Column(Boolean, default=False, nullable=False)
    video_received = Column(Boolean, default=False, nullable=False)
    video_path = Column(String)
    description_recieved = Column(Boolean, default=False, nullable=False)
    description_json = Column(JSONB)
    sourcing_criterias_recieved = Column(Boolean, default=False, nullable=False)
    sourcing_criterias_json = Column(JSONB)
    sourcing_criterias_confirmed = Column(Boolean, default=False, nullable=False)
    sourcing_criterias_confirmation_time = Column(TIMESTAMP(timezone=True))
    created_at = Column(TIMESTAMP(timezone=True), default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), default=func.now(), onupdate=func.now())


class Negotiations(Base):
    __tablename__ = "negotiations"

    id = Column(String, primary_key=True)
    vacancy_id = Column(String, ForeignKey("vacancies.id"), nullable=False)
    resume_id = Column(String)

    hh_first_name = Column(String)
    hh_last_name = Column(String)
    hh_phone = Column(String)
    hh_email = Column(String)

    link_to_tg_bot_sent = Column(Boolean, default=False, nullable=False)
    link_to_tg_bot_sent_time = Column(TIMESTAMP(timezone=True))

    applicant_visited_bot = Column(Boolean, default=False, nullable=False)
    first_time_seen = Column(TIMESTAMP(timezone=True), default=func.now())

    tg_user_id = Column(String)
    tg_first_name = Column(String)
    tg_last_name = Column(String)
    tg_username = Column(String)

    privacy_policy_confirmed = Column(Boolean, default=False, nullable=False)
    privacy_policy_confirmation_time = Column(TIMESTAMP(timezone=True))
    welcome_video_shown = Column(Boolean, default=False, nullable=False)
    video_sending_confirmed = Column(Boolean, default=False, nullable=False)
    video_received = Column(Boolean, default=False, nullable=False)
    video_path = Column(String)

    resume_json = Column(JSONB)
    resume_ai_analysis = Column(JSONB)
    resume_ai_score = Column(String)
    resume_sorting_status = Column(String, default="new")

    resume_recommended = Column(Boolean, default=False, nullable=False)
    resume_recommended_time = Column(TIMESTAMP(timezone=True))
    resume_accepted = Column(Boolean, default=False, nullable=False)
    resume_decision_time = Column(TIMESTAMP(timezone=True))
    created_at = Column(TIMESTAMP(timezone=True), default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), default=func.now(), onupdate=func.now())


# Ensure engine and session factory are created on first import (for backward-compat names below)
def _bind_engine_and_session():
    get_engine()
    get_session_factory()


def db_healthcheck() -> bool:
    """Return True if DB is reachable, False otherwise. Does not create schema."""
    try:
        eng = get_engine()
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.warning("db_healthcheck failed: %s", e)
        return False


# Module-level engine and SessionLocal for backward compatibility (used by db_service, admin, local_db, etc.)
_bind_engine_and_session()
engine = _engine
SessionLocal = _SessionLocal
