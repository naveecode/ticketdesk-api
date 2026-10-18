from django.conf import settings
from django.db import connection
from django.db.utils import OperationalError
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from config.serializers import HealthSerializer


def database_ok() -> bool:
    try:
        connection.ensure_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except OperationalError:
        return False
    return True


def redis_ok() -> bool:
    try:
        import redis

        client = redis.Redis.from_url(
            settings.CELERY_BROKER_URL,
            socket_connect_timeout=0.3,
            socket_timeout=0.3,
        )
        return bool(client.ping())
    except Exception:
        return False


class HealthView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(responses=HealthSerializer, tags=["meta"], auth=[])
    def get(self, request):
        database = database_ok()
        payload = {
            "status": "ok" if database else "degraded",
            "database": database,
            "redis": redis_ok(),
        }
        return Response(payload, status=200 if database else 503)
