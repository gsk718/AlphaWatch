from sqlalchemy.engine import URL

from database import session as database_session


def test_database_url_uses_local_alphawatch_fallback(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    url = database_session._database_url()

    assert url == URL.create("postgresql+psycopg", database="alphawatch")
    assert url.username is None
    assert url.password is None


def test_database_url_loads_environment_value_and_uses_psycopg3(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://db.example/alpha")

    url = database_session._database_url()

    assert url.drivername == "postgresql+psycopg"
    assert url.username is None
    assert url.password is None
    assert url.host == "db.example"
    assert url.database == "alpha"


def test_database_engine_enables_pre_ping():
    assert database_session.engine.pool._pre_ping is True


def test_get_db_closes_session_even_when_dependency_throws(monkeypatch):
    class FakeSession:
        closed = False

        def close(self):
            self.closed = True

    fake = FakeSession()
    monkeypatch.setattr(database_session, "SessionLocal", lambda: fake)
    dependency = database_session.get_db()

    assert next(dependency) is fake
    try:
        dependency.throw(RuntimeError("request failed"))
    except RuntimeError as exc:
        assert str(exc) == "request failed"
    else:
        raise AssertionError("expected the dependency error to propagate")

    assert fake.closed is True
