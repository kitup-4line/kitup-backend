import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["*"]
CORS_ALLOW_ALL_ORIGINS = True


def _required_env(name):
    value = os.getenv(name)
    if value is None or not value.strip():
        raise ImproperlyConfigured(f"{name} is required for the local database")
    return value


try:
    _db_port = int(os.getenv("DB_PORT", "5432"))
except ValueError:
    raise ImproperlyConfigured("DB_PORT must be an integer") from None
if not 1 <= _db_port <= 65535:
    raise ImproperlyConfigured("DB_PORT must be between 1 and 65535")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _required_env("DB_NAME"),
        "USER": _required_env("DB_USER"),
        "PASSWORD": _required_env("DB_PASSWORD"),
        "HOST": _required_env("DB_HOST"),
        "PORT": _db_port,
        "CONN_MAX_AGE": 0,
        "OPTIONS": {"connect_timeout": 5, "sslmode": "disable"},
    }
}
