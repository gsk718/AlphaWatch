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


def _is_production() -> bool:
    """Recognize Render and conventional production environment markers."""
    import os

    return os.getenv("RENDER", "").strip().lower() in {"1", "true", "yes"} or any(
        os.getenv(name, "").strip().lower() == "production"
        for name in ("ENVIRONMENT", "APP_ENV")
    )


def _database_url() -> URL:
    """Read DATABASE_URL, with a local-only AlphaWatch development fallback.

    PostgreSQL URLs without an explicit driver are directed to Psycopg 3,
    so installations do not accidentally fall back to the Psycopg 2 driver.
    """
    import os

    raw_url = os.getenv("DATABASE_URL", "").strip()
    if not raw_url:
        if _is_production():
            raise RuntimeError(
                "DATABASE_URL must be set to a non-blank value in production."
            )
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
