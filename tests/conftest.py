import pytest
from rest_framework.test import APIClient

from accounts.models import User
from tickets.models import Ticket

PASSWORD = "s3cure-Pass"


@pytest.fixture(autouse=True)
def _celery_eager():
    from config.celery import app

    app.conf.task_always_eager = True
    app.conf.task_eager_propagates = True


@pytest.fixture(autouse=True)
def _disable_triage_enqueue(monkeypatch):
    monkeypatch.setattr("tickets.signals.triage_ticket.delay", lambda *args, **kwargs: None)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def customer(db):
    return User.objects.create_user(
        username="alice",
        password=PASSWORD,
        email="alice@example.com",
        role=User.Role.CUSTOMER,
    )


@pytest.fixture
def other_customer(db):
    return User.objects.create_user(
        username="bob",
        password=PASSWORD,
        role=User.Role.CUSTOMER,
    )


@pytest.fixture
def agent(db):
    return User.objects.create_user(username="sam", password=PASSWORD, role=User.Role.AGENT)


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        username="ada",
        password=PASSWORD,
        role=User.Role.ADMIN,
        is_staff=True,
        is_superuser=True,
    )


@pytest.fixture
def auth_client(db):
    def _auth(user):
        client = APIClient()
        response = client.post(
            "/api/auth/token/",
            {"username": user.username, "password": PASSWORD},
            format="json",
        )
        assert response.status_code == 200, response.content
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        return client

    return _auth


@pytest.fixture
def customer_client(customer, auth_client):
    return auth_client(customer)


@pytest.fixture
def other_client(other_customer, auth_client):
    return auth_client(other_customer)


@pytest.fixture
def agent_client(agent, auth_client):
    return auth_client(agent)


@pytest.fixture
def admin_client(admin_user, auth_client):
    return auth_client(admin_user)


@pytest.fixture
def make_ticket(db):
    def _make(requester, **kwargs):
        payload = {
            "title": "Printer jam on floor 2",
            "description": "The printer is jammed and the queue is stuck.",
            "requester": requester,
        }
        payload.update(kwargs)
        return Ticket.objects.create(**payload)

    return _make
