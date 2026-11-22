"""Fixtures for explicitly enabled PostgreSQL integration tests."""

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .postgres_config import validate_opt_in


def _enabled() -> bool:
    return os.getenv("RUN_POSTGRES_TESTS") == "1"


def pytest_collection_modifyitems(config, items):
    """Skip marked tests by default; reject invalid explicit opt-in early."""
    postgres_items = [item for item in items if item.get_closest_marker("postgres")]
    if not postgres_items:
        return

    if not _enabled():
        skip = pytest.mark.skip(reason="PostgreSQL integration tests require RUN_POSTGRES_TESTS=1.")
        for item in postgres_items:
            item.add_marker(skip)
        return

    # Validate at collection time, before any fixture can create an engine.
    validate_opt_in(True, os.getenv("TEST_DATABASE_URL"))


@pytest.fixture(scope="session")
def postgres_engine():
    """Create an engine only for a valid, explicitly enabled run."""
    url = validate_opt_in(_enabled(), os.getenv("TEST_DATABASE_URL"))
    if url is None:
        pytest.skip("PostgreSQL integration tests require RUN_POSTGRES_TESTS=1.")
    engine = create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def postgres_session_factory(postgres_engine):
    return sessionmaker(bind=postgres_engine, autoflush=False, autocommit=False)


@pytest.fixture
def postgres_dependency_override(postgres_session_factory):
    """Install the test session dependency and restore prior state on teardown."""
    from app.main import app
    from database.session import get_db

    had_previous = get_db in app.dependency_overrides
    previous = app.dependency_overrides.get(get_db)

    def override_get_db():
        db = postgres_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield app
    finally:
        if had_previous:
            app.dependency_overrides[get_db] = previous
        else:
            app.dependency_overrides.pop(get_db, None)
