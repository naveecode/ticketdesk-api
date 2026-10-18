import pytest
from django.db.utils import OperationalError

from config.views import database_ok

pytestmark = pytest.mark.django_db


def test_health_reports_database_and_a_down_broker(api_client):
    response = api_client.get("/api/health/")
    assert response.status_code == 200
    assert response.data["status"] == "ok"
    assert response.data["database"] is True
    assert response.data["redis"] is False


def test_health_is_degraded_when_the_database_is_down(api_client, monkeypatch):
    monkeypatch.setattr("config.views.database_ok", lambda: False)
    response = api_client.get("/api/health/")
    assert response.status_code == 503
    assert response.data == {"status": "degraded", "database": False, "redis": False}


def test_database_ok_returns_false_on_operational_error(monkeypatch):
    def boom():
        raise OperationalError("down")

    monkeypatch.setattr("config.views.connection.ensure_connection", boom)
    assert database_ok() is False


def test_health_reports_redis_when_ping_succeeds(api_client, monkeypatch):
    class FakeRedis:
        def ping(self):
            return True

    monkeypatch.setattr("redis.Redis.from_url", lambda *args, **kwargs: FakeRedis())
    response = api_client.get("/api/health/")
    assert response.status_code == 200
    assert response.data["redis"] is True


def test_openapi_schema_lists_the_ticket_api(api_client):
    response = api_client.get("/api/schema/")
    assert response.status_code == 200
    body = response.content.decode()
    assert "Ticketdesk API" in body
    assert "/api/tickets/" in body
    assert "/api/auth/token/" in body


def test_admin_login_page_loads(client):
    response = client.get("/admin/login/")
    assert response.status_code == 200
