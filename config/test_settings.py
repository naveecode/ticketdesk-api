from pathlib import Path

from config.settings import *  # noqa: F403
from config.settings import REST_FRAMEWORK as _REST_FRAMEWORK

DEBUG = False
SECRET_KEY = "test-secret-key-that-is-long-enough-32b"
_STATIC_ROOT = Path("/tmp/ticketdesk-test-static")
_STATIC_ROOT.mkdir(parents=True, exist_ok=True)
STATIC_ROOT = _STATIC_ROOT
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "redis://127.0.0.1:6399/0"
CELERY_RESULT_BACKEND = "cache+memory://"
LLM_API_KEY = ""
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
REST_FRAMEWORK = {
    **_REST_FRAMEWORK,
    "DEFAULT_THROTTLE_CLASSES": [],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "1000/min",
        "user": "1000/min",
        "auth": "1000/min",
    },
}
