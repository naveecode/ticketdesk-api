from rest_framework.throttling import AnonRateThrottle


class AuthRateThrottle(AnonRateThrottle):
    """Stricter anonymous limit for login and registration."""

    scope = "auth"
