import pytest
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User

pytestmark = pytest.mark.django_db


def test_register_creates_a_customer(api_client):
    response = api_client.post(
        "/api/auth/register/",
        {
            "username": "newcustomer",
            "email": "new@example.com",
            "password": "s3cure-Pass",
            "role": "admin",
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.data["role"] == User.Role.CUSTOMER
    assert response.data["username"] == "newcustomer"
    assert "password" not in response.data
    user = User.objects.get(username="newcustomer")
    assert user.role == User.Role.CUSTOMER
    assert user.check_password("s3cure-Pass")


def test_register_rejects_a_short_password(api_client):
    response = api_client.post(
        "/api/auth/register/",
        {"username": "shorty", "password": "short"},
        format="json",
    )
    assert response.status_code == 400


def test_register_rejects_a_duplicate_username(api_client, customer):
    response = api_client.post(
        "/api/auth/register/",
        {"username": customer.username, "password": "s3cure-Pass"},
        format="json",
    )
    assert response.status_code == 400


def test_token_contains_role_and_refresh_issues_a_new_access_token(api_client, customer):
    response = api_client.post(
        "/api/auth/token/",
        {"username": "alice", "password": "s3cure-Pass"},
        format="json",
    )
    assert response.status_code == 200
    access = AccessToken(response.data["access"])
    assert access["role"] == User.Role.CUSTOMER
    assert access["username"] == "alice"

    refreshed = api_client.post(
        "/api/auth/token/refresh/",
        {"refresh": response.data["refresh"]},
        format="json",
    )
    assert refreshed.status_code == 200
    assert refreshed.data["access"]


def test_invalid_login_is_rejected(api_client, customer):
    response = api_client.post(
        "/api/auth/token/",
        {"username": "alice", "password": "wrong-pass"},
        format="json",
    )
    assert response.status_code == 401


def test_me_requires_authentication(api_client, customer_client, customer):
    anonymous = api_client.get("/api/auth/me/")
    assert anonymous.status_code == 401

    me = customer_client.get("/api/auth/me/")
    assert me.status_code == 200
    assert me.data == {
        "id": customer.id,
        "username": "alice",
        "email": "alice@example.com",
        "role": User.Role.CUSTOMER,
    }


def test_login_is_rate_limited(api_client, customer):
    from django.core.cache import cache

    from accounts.throttles import AuthRateThrottle

    cache.clear()
    original = AuthRateThrottle.THROTTLE_RATES["auth"]
    AuthRateThrottle.THROTTLE_RATES["auth"] = "1/min"
    payload = {"username": "alice", "password": "s3cure-Pass"}
    try:
        first = api_client.post("/api/auth/token/", payload, format="json")
        second = api_client.post("/api/auth/token/", payload, format="json")
    finally:
        AuthRateThrottle.THROTTLE_RATES["auth"] = original
        cache.clear()
    assert first.status_code == 200
    assert second.status_code == 429
