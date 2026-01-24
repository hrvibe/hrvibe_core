# database.py
"""
Shared database models and configuration for all bots.
"""
from sqlalchemy import create_engine, Column, Integer, String, Boolean, JSON, BigInteger, TIMESTAMP, ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func

# Import DATABASE_URL from shared config
from config import DATABASE_URL

# Strip whitespace and special characters that might be accidentally included
DATABASE_URL = DATABASE_URL.strip().rstrip('%')

# Fix: Render использует postgresql+psycopg2, но URL может быть с postgres://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Создаём engine
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

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
    video_record_agreed = Column(Boolean, default=False, nullable=False)
    video_sending_confirmed = Column(Boolean, default=False, nullable=False)
    video_received = Column(Boolean, default=False, nullable=False)
    video_path = Column(String)
    description_recieved = Column(Boolean, default=False, nullable=False)
    description_json = Column(JSONB)
    sourcing_criterias_recieved = Column(Boolean, default=False, nullable=False)
    sourcing_criterias_json = Column(JSONB)
    sourcing_criterias_confirmed = Column(Boolean, default=False, nullable=False)
    sourcing_criterias_confirmation_time = Column(TIMESTAMP(timezone=True))
    negotiations_collection_recieved = Column(Boolean, default=False, nullable=False)
    negotiations_collection_path = Column(String)
    created_at = Column(TIMESTAMP(timezone=True), default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), default=func.now(), onupdate=func.now())


class Negotiations(Base):
    __tablename__ = "negotiations"

    id = Column(String, primary_key=True)
    vacancy_id = Column(String, ForeignKey("vacancies.id"), nullable=False)
    resume_id = Column(String)
    applicant_first_name = Column(String)
    applicant_last_name = Column(String)
    applicant_phone = Column(String)
    applicant_email = Column(String)
    resume_ai_analysis = Column(JSONB)
    resume_sorting_status = Column(String, default="new")
    link_to_tg_bot_sent = Column(Boolean, default=False, nullable=False)
    video_received = Column(Boolean, default=False, nullable=False)
    video_path = Column(String)
    resume_recommended = Column(Boolean, default=False, nullable=False)
    resume_accepted = Column(Boolean, default=False, nullable=False)
    interview_invitation_sent = Column(Boolean, default=False, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), default=func.now(), onupdate=func.now())


def init_db():
    """
    Создаёт таблицы, если их ещё нет.
    Вызывай при старте приложения.
    """
    Base.metadata.create_all(bind=engine)
    print("✅ Таблицы созданы или уже существуют")
