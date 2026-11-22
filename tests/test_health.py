from sqlalchemy.exc import OperationalError
from fastapi.testclient import TestClient

from app import main
from database.session import get_db


def _with_db_override(override):
    previous = main.app.dependency_overrides.get(get_db)
    main.app.dependency_overrides[get_db] = override
    return previous


def _restore_db_override(previous):
    if previous is None:
        main.app.dependency_overrides.pop(get_db, None)
    else:
        main.app.dependency_overrides[get_db] = previous


def test_health_and_live_are_liveness_checks_without_database_access():
    calls = []

    def broken_database_dependency():
        calls.append("called")
        raise RuntimeError("database dependency must not run")

    previous = _with_db_override(broken_database_dependency)
    try:
        with TestClient(main.app) as client:
            for path in ("/health", "/health/live"):
                response = client.get(path)
                assert response.status_code == 200
                assert response.json() == {"status": "ok"}
        assert calls == []
    finally:
        _restore_db_override(previous)


def test_health_ready_executes_select_and_closes_session():
    class FakeSession:
        closed = False

        def execute(self, statement):
            assert str(statement) == "SELECT 1"
            return 1

        def close(self):
            self.closed = True

    session = FakeSession()

    def database_dependency():
        try:
            yield session
        finally:
            session.close()

    previous = _with_db_override(database_dependency)
    try:
        response = TestClient(main.app).get("/health/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert session.closed is True
    finally:
        _restore_db_override(previous)


def test_health_ready_returns_safe_unavailable_response_and_closes_session():
    sensitive_detail = "postgresql://user:secret@private-db.example/portfolio"

    class FakeSession:
        closed = False

        def execute(self, statement):
            raise OperationalError(str(statement), {}, RuntimeError(sensitive_detail))

        def close(self):
            self.closed = True

    session = FakeSession()

    def database_dependency():
        try:
            yield session
        finally:
            session.close()

    previous = _with_db_override(database_dependency)
    try:
        response = TestClient(main.app).get("/health/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "unavailable"}
        assert sensitive_detail not in response.text
        assert "private-db.example" not in response.text
        assert "secret" not in response.text
        assert session.closed is True
    finally:
        _restore_db_override(previous)
