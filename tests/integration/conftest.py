"""Fixtures for explicitly enabled PostgreSQL integration tests."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

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
def postgres_migrated_url():
    """Apply forward migrations to the validated dedicated test database."""
    url = validate_opt_in(_enabled(), os.getenv("TEST_DATABASE_URL"))
    if url is None:
        pytest.skip("PostgreSQL integration tests require RUN_POSTGRES_TESTS=1.")
    project_root = Path(__file__).resolve().parents[2] / "ai-stock-insight"
    alembic_config = Config(str(project_root / "alembic.ini"))
    alembic_config.set_main_option("sqlalchemy.url", str(url).replace("%", "%%"))
    try:
        command.upgrade(alembic_config, "head")
    except Exception as exc:
        raise RuntimeError(
            "PostgreSQL integration setup could not migrate the validated alphawatch_test database. "
            "Check that it is reachable and that its schema can be upgraded."
        ) from exc
    return url


@pytest.fixture(scope="session")
def postgres_engine(postgres_migrated_url):
    """Create an engine only after the dedicated database is migrated."""
    engine = create_engine(postgres_migrated_url, hide_parameters=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def postgres_session_factory(postgres_engine):
    return sessionmaker(bind=postgres_engine, autoflush=False, autocommit=False)


@pytest.fixture
def postgres_session(postgres_engine):
    """Give each test an isolated transaction that is rolled back on teardown."""
    connection = postgres_engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        autoflush=False,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture
def postgres_dependency_override(postgres_engine):
    """Share one rollbackable test transaction across HTTP request sessions."""
    from app.main import app
    from database.session import get_db

    had_previous = get_db in app.dependency_overrides
    previous = app.dependency_overrides.get(get_db)

    connection = postgres_engine.connect()
    transaction = connection.begin()

    def override_get_db():
        # Session.commit() flushes its work but leaves this externally managed
        # transaction open, making it visible to the next request on connection.
        db = Session(
            bind=connection,
            autoflush=False,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
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
        if transaction.is_active:
            transaction.rollback()
        connection.close()
