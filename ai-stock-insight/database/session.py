"""SQLAlchemy engine and request-scoped session dependency."""

from collections.abc import Generator
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from .base import Base

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

_DEFAULT_DATABASE_URL = "postgresql+psycopg:///alphawatch"


def _database_url() -> URL:
    """Read DATABASE_URL, defaulting to the local AlphaWatch database.

    PostgreSQL URLs without an explicit driver are directed to Psycopg 3,
    so installations do not accidentally fall back to the Psycopg 2 driver.
    """
    import os

    raw_url = os.getenv("DATABASE_URL", _DEFAULT_DATABASE_URL).strip()
    if not raw_url:
        raw_url = _DEFAULT_DATABASE_URL
    url = make_url(raw_url)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    return url


DATABASE_URL = _database_url()
engine: Engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    """Yield a session and always close it after the request finishes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


__all__ = ["Base", "DATABASE_URL", "SessionLocal", "engine", "get_db"]
