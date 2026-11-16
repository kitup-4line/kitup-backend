import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-insecure-key")
DEBUG = False
ALLOWED_HOSTS = [h for h in os.getenv("DJANGO_ALLOWED_HOSTS", "").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third party
    "rest_framework",
    "drf_spectacular",
    "corsheaders",
    "django_q",
    # local
    "core",
    "menu_tests",
    "orders",
    "dashboard",
    "reports",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "core.exceptions.custom_exception_handler",
    "DEFAULT_PAGINATION_CLASS": "core.pagination.DefaultPagination",
    "PAGE_SIZE": 20,
    "COERCE_DECIMAL_TO_STRING": False,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "KitUp API",
    "VERSION": "0.1.0",
}

CORS_ALLOWED_ORIGINS = [o for o in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if o]

AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "")
AI_TIMEOUT_SECONDS = int(os.getenv("AI_TIMEOUT_SECONDS", "30"))
# 로컬 개발용. DEBUG일 때만 AI 대신 목업 결과 저장
AI_MOCK_ENABLED = os.getenv("AI_MOCK_ENABLED", "False").lower() in ("1", "true", "yes")

# 리포트는 재료 추정의 AI_* 설정을 사용하지 않는다.
REPORT_REVIEW_PROVIDER = os.getenv("REPORT_REVIEW_PROVIDER", "")
REPORT_REVIEW_MODEL = os.getenv("REPORT_REVIEW_MODEL", "")
REPORT_REVIEW_API_KEY = os.getenv("REPORT_REVIEW_API_KEY", "")
REPORT_IMPROVEMENT_PROVIDER = os.getenv("REPORT_IMPROVEMENT_PROVIDER", "")
REPORT_IMPROVEMENT_MODEL = os.getenv("REPORT_IMPROVEMENT_MODEL", "")
REPORT_IMPROVEMENT_API_KEY = os.getenv("REPORT_IMPROVEMENT_API_KEY", "")
REPORT_AI_TIMEOUT_SECONDS = int(os.getenv("REPORT_AI_TIMEOUT_SECONDS", "120"))

# 한 번에 한 리포트 처리. 내부 대기 작업까지 고려해 재전달 간격을 둔다.
Q_CLUSTER = {
    "name": "reports",
    "orm": "default",
    "workers": 1,
    "queue_limit": 1,
    "bulk": 1,
    "timeout": 300,
    # 실행 1개 + 메모리 대기 1개 + pusher가 선점한 1개의 최대 처리 시간보다 길게.
    "retry": 960,
    "max_attempts": 3,
    "poll": 1,
    "sync": False,
    "save_limit": 100,
    "scheduler": False,
}
