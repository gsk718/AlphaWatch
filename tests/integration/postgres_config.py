"""Safe configuration parsing for opt-in PostgreSQL integration tests."""

import os
import re

from sqlalchemy.engine import URL, make_url


class PostgresTestConfigurationError(ValueError):
    """Raised when integration-test database configuration is unsafe."""


def validate_test_database_url(raw_url: str | None) -> URL:
    """Parse and validate a dedicated PostgreSQL/Psycopg 3 test URL.

    Error messages deliberately describe only the failed check; they never
    include the supplied URL, which may contain credentials.
    """
    if not raw_url or not raw_url.strip():
        raise PostgresTestConfigurationError("TEST_DATABASE_URL is required for PostgreSQL integration tests.")

    candidate = raw_url.strip()
    if re.search(r"%(?![0-9a-fA-F]{2})", candidate):
        raise PostgresTestConfigurationError("TEST_DATABASE_URL is malformed.")

    try:
        url = make_url(candidate)
    except Exception as exc:
        raise PostgresTestConfigurationError("TEST_DATABASE_URL is malformed.") from None

    if url.drivername != "postgresql+psycopg":
        raise PostgresTestConfigurationError(
            "TEST_DATABASE_URL must use PostgreSQL with the Psycopg 3 driver (postgresql+psycopg)."
        )
    if url.database != "alphawatch_test":
        raise PostgresTestConfigurationError(
            "TEST_DATABASE_URL must target the dedicated alphawatch_test database."
        )
    host = url.host
    if not host:
        raise PostgresTestConfigurationError("TEST_DATABASE_URL must specify an approved database host.")
    allowed_hosts = {"localhost", "127.0.0.1", "::1"}
    allowed_hosts.update(
        allowed.strip().casefold()
        for allowed in os.getenv("TEST_DATABASE_ALLOWED_HOSTS", "").split(",")
        if allowed.strip()
    )
    if host.casefold() not in allowed_hosts:
        raise PostgresTestConfigurationError("TEST_DATABASE_URL must specify an approved database host.")
    return url


def validate_opt_in(enabled: bool, raw_url: str | None) -> URL | None:
    """Return a validated URL when enabled; otherwise leave tests disabled."""
    if not enabled:
        return None
    return validate_test_database_url(raw_url)
