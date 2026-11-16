#!/usr/bin/env bash
# EC2에서 실행. GitHub Actions가 배포 때마다 이 파일과 compose.prod.yaml을 복사함
#   ./deploy.sh <이미지 태그>   새 버전 배포 (pull → migrate → 재시작)
#   ./deploy.sh rollback        직전 버전으로 되돌림 (migrate는 되돌리지 않음)
set -euo pipefail
cd "$(dirname "$0")"

COMPOSE=(docker compose -f compose.prod.yaml)

if [ "${1:-}" = "rollback" ]; then
  if [ ! -f .image_tag.previous ]; then
    echo "되돌릴 이전 버전이 없습니다." >&2
    exit 1
  fi
  export IMAGE_TAG="$(cat .image_tag.previous)"
  "${COMPOSE[@]}" up -d --remove-orphans
  echo "$IMAGE_TAG" > .image_tag
  echo "rollback: $IMAGE_TAG"
  exit 0
fi

export IMAGE_TAG="${1:?이미지 태그가 필요합니다}"

"${COMPOSE[@]}" pull
"${COMPOSE[@]}" run --rm -T web python manage.py migrate --noinput
[ -f .image_tag ] && cp .image_tag .image_tag.previous
"${COMPOSE[@]}" up -d --remove-orphans
echo "$IMAGE_TAG" > .image_tag

# 3일 넘게 쓰지 않은 이미지 정리 (직전 버전은 복구용으로 남김)
docker image prune -af --filter "until=72h" > /dev/null
echo "deployed: $IMAGE_TAG"
