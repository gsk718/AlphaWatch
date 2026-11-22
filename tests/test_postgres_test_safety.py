import pytest
from sqlalchemy.engine import URL

from integration.postgres_config import (
    PostgresTestConfigurationError,
    validate_opt_in,
    validate_test_database_url,
)


def test_missing_test_url_rejected_when_opted_in():
    with pytest.raises(PostgresTestConfigurationError, match="TEST_DATABASE_URL is required"):
        validate_opt_in(True, None)


@pytest.mark.parametrize(
    "database",
    ["alphawatch", "some_other_database"],
)
def test_non_dedicated_database_rejected(database):
    with pytest.raises(PostgresTestConfigurationError, match="alphawatch_test"):
        validate_test_database_url(f"postgresql+psycopg://user:secret@localhost/{database}")


def test_sqlite_rejected():
    with pytest.raises(PostgresTestConfigurationError, match="PostgreSQL"):
        validate_test_database_url("sqlite+pysqlite:///alphawatch_test")


def test_malformed_url_rejected_without_echoing_input():
    malformed = "postgresql+psycopg://alice:secret@%zz/alphawatch_test"

    with pytest.raises(PostgresTestConfigurationError, match="malformed") as error:
        validate_test_database_url(malformed)

    assert "secret" not in str(error.value)
    assert malformed not in str(error.value)


def test_postgres_with_unsupported_driver_rejected():
    with pytest.raises(PostgresTestConfigurationError, match="Psycopg 3"):
        validate_test_database_url("postgresql+psycopg2://user:secret@localhost/alphawatch_test")


def test_valid_psycopg3_test_url_accepted():
    url = validate_test_database_url("postgresql+psycopg://user:secret@localhost/alphawatch_test")

    assert url == URL.create(
        "postgresql+psycopg", username="user", password="secret", host="localhost", database="alphawatch_test"
    )


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_localhost_and_loopback_hosts_accepted(host):
    assert validate_test_database_url(
        f"postgresql+psycopg://user:secret@{host}/alphawatch_test"
    ).database == "alphawatch_test"


def test_unapproved_remote_host_rejected_without_leaking_host_or_credentials():
    with pytest.raises(PostgresTestConfigurationError) as error:
        validate_test_database_url(
            "postgresql+psycopg://alice:very-secret@db.internal.example/alphawatch_test"
        )

    message = str(error.value)
    assert "alice" not in message
    assert "very-secret" not in message
    assert "db.internal.example" not in message


def test_missing_host_rejected():
    with pytest.raises(PostgresTestConfigurationError, match="approved database host"):
        validate_test_database_url("postgresql+psycopg:///alphawatch_test")


def test_explicitly_allowed_host_from_environment(monkeypatch):
    monkeypatch.setenv("TEST_DATABASE_ALLOWED_HOSTS", "db.internal.example, other.internal")
    url = validate_test_database_url(
        "postgresql+psycopg://user:secret@db.internal.example/alphawatch_test"
    )
    assert url.host == "db.internal.example"


def test_host_matching_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("TEST_DATABASE_ALLOWED_HOSTS", "DB.INTERNAL.EXAMPLE")
    url = validate_test_database_url(
        "postgresql+psycopg://user:secret@db.internal.example/alphawatch_test"
    )
    assert url.host == "db.internal.example"


def test_validation_errors_do_not_expose_credentials():
    secret_url = "postgresql+psycopg://alice:very-secret@localhost/alphawatch"

    with pytest.raises(PostgresTestConfigurationError) as error:
        validate_test_database_url(secret_url)

    assert "very-secret" not in str(error.value)
    assert "alice" not in str(error.value)
    assert secret_url not in str(error.value)


def test_opt_out_does_not_parse_url_or_create_postgres_engine(monkeypatch):
    import integration.conftest as integration_fixtures

    def unexpected(*args, **kwargs):
        raise AssertionError("PostgreSQL setup must not run in ordinary tests")

    monkeypatch.setattr(integration_fixtures, "create_engine", unexpected)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://localhost/alphawatch")
    monkeypatch.delenv("RUN_POSTGRES_TESTS", raising=False)

    assert validate_opt_in(False, None) is None
    assert integration_fixtures._enabled() is False

    class MarkedItem:
        def __init__(self):
            self.markers = [pytest.mark.postgres]

        def get_closest_marker(self, name):
            return next((marker for marker in self.markers if marker.name == name), None)

        def add_marker(self, marker):
            self.markers.append(marker)

    item = MarkedItem()
    integration_fixtures.pytest_collection_modifyitems(None, [item])
    assert any(marker.name == "skip" for marker in item.markers)
