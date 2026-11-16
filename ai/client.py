"""LLM 호출 래퍼. 응답은 ai/schemas.py로 검증한다."""

import json
import logging
import re

import anthropic
from django.conf import settings

from core.exceptions import AIServiceError

logger = logging.getLogger(__name__)

_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def request_json(system: str, user: str) -> dict:
    if not settings.AI_API_KEY or not settings.AI_MODEL:
        raise AIServiceError("AI 설정이 없습니다.")

    # 재시도 1회로 제한 (최대 대기 = timeout x 2)
    client = anthropic.Anthropic(
        api_key=settings.AI_API_KEY,
        timeout=settings.AI_TIMEOUT_SECONDS,
        max_retries=1,
    )
    try:
        response = client.messages.create(
            model=settings.AI_MODEL,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.APIError as exc:
        logger.warning("AI 호출 실패: %s", exc)
        raise AIServiceError() from exc

    if response.stop_reason in ("max_tokens", "refusal"):
        logger.warning("AI 응답 중단: stop_reason=%s", response.stop_reason)
        raise AIServiceError()

    text = "".join(block.text for block in response.content if block.type == "text")
    text = _CODE_FENCE.sub("", text.strip())
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("AI 응답 JSON 파싱 실패: %s", text[:200])
        raise AIServiceError() from exc

    if not isinstance(payload, dict):
        raise AIServiceError()
    return payload
