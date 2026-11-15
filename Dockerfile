FROM python:3.14-slim

# GHCR 패키지를 레포에 연결 (Actions 토큰으로 push·pull 가능)
LABEL org.opencontainers.image.source=https://github.com/kitup-4line/kitup-backend

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    # gunicorn 워커 수. EC2 사양에 맞춰 .env.prod에서 변경 가능
    WEB_CONCURRENCY=2

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# 관리자 화면 정적 파일을 이미지에 포함. 빌드 전용 키라 운영 키와 무관
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput

RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8000

# AI 재료 추정이 최대 약 60초 걸릴 수 있어 timeout 90초
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--timeout", "90", "--access-logfile", "-"]
