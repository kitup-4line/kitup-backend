"""리포트 전용 API 호출. 제공자 형식 변환과 최초 포함 최대 3회 재시도."""

import json
import logging
import re
import time
# contextvars는 Python 표준 라이브러리다.
# noinspection PyPackageRequirements
from contextvars import ContextVar
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from math import ceil
from typing import TypedDict
from urllib.parse import quote

import httpx2
from django.conf import settings

from core.exceptions import AIServiceError

logger = logging.getLogger(__name__)
_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


class ReportTaskContext(TypedDict):
    test_id: int
    task_id: str
    deadline: float


report_task_context: ContextVar[ReportTaskContext | None] = ContextVar("report_task_context", default=None)


class _ResponseError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _server_retry_seconds(response: httpx2.Response, provider: str) -> int | None:
    """헤더와 Gemini RetryInfo 중 더 긴 대기 시간을 사용한다."""
    delays: list[int] = []
    try:
        milliseconds = float(response.headers.get("retry-after-ms", ""))
        if milliseconds >= 0:
            delays.append(ceil(milliseconds / 1000))
    except (ValueError, OverflowError):
        pass
    value = response.headers.get("retry-after", "").strip()
    if value:
        try:
            if re.fullmatch(r"[0-9]+", value):
                delays.append(int(value))
            else:
                date = parsedate_to_datetime(value)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                delays.append(max(0, ceil(date.timestamp() - time.time())))
        except (TypeError, ValueError, OverflowError):
            pass
    if provider == "gemini":
        try:
            error = response.json().get("error", {})
            details = error.get("details", [])
        except (ValueError, AttributeError):
            details = []
        for detail in details if isinstance(details, list) else []:
            if not isinstance(detail, dict) or detail.get("@type") != "type.googleapis.com/google.rpc.RetryInfo":
                continue
            value = detail.get("retryDelay")
            if isinstance(value, str) and re.fullmatch(r"[0-9]{1,12}(?:\.[0-9]{1,9})?s", value):
                delays.append(ceil(float(value[:-1])))
    return max(delays, default=None)


def _log_failure(
    stage, provider, model, reason, *, response=None, payload=None, attempt=None,
    retry_in_seconds=None, server_retry_seconds=None, retry_stop=None,
):
    """원문·오류 메시지·헤더 전체 대신 진단용 식별자만 기록한다."""
    if response is not None and payload is None:
        try:
            payload = response.json()
        except ValueError:
            pass
    payload = payload if isinstance(payload, dict) else {}
    error = payload.get("error")
    error = error if isinstance(error, dict) else {}
    incomplete = payload.get("incomplete_details")
    incomplete = incomplete if isinstance(incomplete, dict) else {}
    candidates = payload.get("candidates")
    candidate = candidates[0] if isinstance(candidates, list) and candidates else {}
    candidate = candidate if isinstance(candidate, dict) else {}
    feedback = payload.get("promptFeedback")
    feedback = feedback if isinstance(feedback, dict) else {}
    context = report_task_context.get() or {}
    request_id = None
    if response is not None:
        request_id = response.headers.get("request-id") or response.headers.get("x-request-id")
    request_id = request_id or payload.get("request_id") or payload.get("responseId")
    metadata = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": "retry" if retry_in_seconds is not None else "failed",
        "test_id": context.get("test_id"),
        "task_id": context.get("task_id"),
        "stage": stage, "provider": provider, "model": model, "reason": reason,
        "http_status": response.status_code if response is not None else None,
        "error_code": error.get("status") or error.get("code") or error.get("type"),
        "param": error.get("param"),
        "attempt": attempt, "retry_in_seconds": retry_in_seconds,
        "server_retry_seconds": server_retry_seconds, "retry_stop": retry_stop,
        "response_status": payload.get("status"),
        "finish_reason": payload.get("stop_reason") or incomplete.get("reason") or candidate.get("finishReason"),
        "block_reason": feedback.get("blockReason"),
        "request_id": request_id,
    }
    # 외부 값의 개행·긴 문자열·중첩 객체가 로그에 섞이지 않게 한다.
    fields = " ".join(
        f"{key}={value}" if isinstance(value, (str, int)) and re.fullmatch(r"[A-Za-z0-9_.:/\[\]-]{1,160}", str(value))
        else f"{key}=-" for key, value in metadata.items()
    )
    logger.warning("리포트 AI 요청: %s", fields)


def _request(provider, model, api_key, system, user, max_tokens):
    if provider == "anthropic":
        return "https://api.anthropic.com/v1/messages", {
            "x-api-key": api_key, "anthropic-version": "2026-10-21",
        }, {
            "model": model, "system": system, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": user}],
        }
    if provider == "openai":
        return "https://api.openai.com/v1/responses", {"Authorization": f"Bearer {api_key}"}, {
            "model": model, "instructions": system, "input": user, "max_output_tokens": max_tokens,
            "text": {"format": {"type": "json_object"}}, "store": False,
        }
    return f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model, safe='')}:generateContent", {
        "x-goog-api-key": api_key,
    }, {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": max_tokens},
    }


def _response_text(provider, payload):
    # 거절·잘린 응답·미완료 응답은 일부 JSON이 있어도 성공으로 사용하지 않는다.
    if provider == "anthropic":
        if payload["stop_reason"] not in ("end_turn", "stop_sequence"):
            raise _ResponseError("incomplete_response")
        return "".join(block["text"] for block in payload["content"] if block["type"] == "text")
    if provider == "openai":
        if payload["status"] != "completed" or payload.get("error"):
            raise _ResponseError("incomplete_response")
        text = []
        for item in payload["output"]:
            if item["type"] != "message":
                continue
            for block in item["content"]:
                if block["type"] == "refusal":
                    raise _ResponseError("refusal")
                if block["type"] == "output_text":
                    text.append(block["text"])
        return "".join(text)
    feedback = payload.get("promptFeedback")
    if isinstance(feedback, dict) and feedback.get("blockReason") not in (None, "", "BLOCK_REASON_UNSPECIFIED"):
        raise _ResponseError("prompt_blocked")
    candidate, = payload["candidates"]
    if candidate["finishReason"] != "STOP":
        raise _ResponseError("incomplete_response")
    return "".join(part["text"] for part in candidate["content"]["parts"]
                   if "text" in part and not part.get("thought"))


def request_json(stage: str, system: str, user: str, *, max_tokens: int) -> dict[str, object]:
    if stage not in ("REVIEW", "IMPROVEMENT"):
        raise AIServiceError("리포트 AI 단계 설정이 올바르지 않습니다.")
    prefix = f"REPORT_{stage}"
    provider = getattr(settings, f"{prefix}_PROVIDER").strip().lower()
    model = getattr(settings, f"{prefix}_MODEL").strip()
    api_key = getattr(settings, f"{prefix}_API_KEY").strip()
    timeout = settings.REPORT_AI_TIMEOUT_SECONDS
    if provider not in ("anthropic", "openai", "gemini") or not model or not api_key or timeout <= 0:
        raise AIServiceError("리포트 AI 제공자·모델·API 키·시간 제한을 확인해주세요.")
    url, headers, body = _request(provider, model, api_key, system, user, max_tokens)
    context = report_task_context.get()
    deadline = context["deadline"] if context else time.monotonic() + settings.Q_CLUSTER["timeout"]
    # 호출 시작 여부를 판단할 때 timeout에 저장 여유 5초를 더한다. 저장 완료를 보장하지는 않는다.
    required_seconds = timeout + 5
    with httpx2.Client(timeout=timeout) as client:
        for attempt in range(3):
            if time.monotonic() + required_seconds >= deadline:
                _log_failure(stage, provider, model, "time_budget_exhausted", attempt=attempt + 1)
                raise AIServiceError()
            failure_response = None
            server_retry_seconds = None
            try:
                response = client.post(url, headers=headers, json=body)
                response.raise_for_status()
                break
            except httpx2.HTTPStatusError as exc:
                failure_response = exc.response
                code = exc.response.status_code
                reason = "http_error"
                retryable = code in (408, 429) or 500 <= code < 600
                server_retry_seconds = _server_retry_seconds(exc.response, provider)
            except httpx2.TransportError as exc:
                reason = type(exc).__name__
                retryable = True
            retry_in_seconds = max(2 ** attempt, server_retry_seconds or 0)
            retry_stop = None
            if not retryable:
                retry_stop = "not_retryable"
            elif attempt == 2:
                retry_stop = "attempt_limit"
            elif time.monotonic() + retry_in_seconds + required_seconds >= deadline:
                retry_stop = "time_budget"
            _log_failure(
                stage, provider, model, reason, response=failure_response, attempt=attempt + 1,
                retry_in_seconds=None if retry_stop else retry_in_seconds,
                server_retry_seconds=server_retry_seconds, retry_stop=retry_stop,
            )
            if retry_stop:
                raise AIServiceError() from None
            time.sleep(retry_in_seconds)

    response_payload = None
    reason = "response_json"
    try:
        response_payload = response.json()
        reason = "response_structure"
        text = _response_text(provider, response_payload)
        reason = "generated_json"
        payload = json.loads(_CODE_FENCE.sub("", text.strip()))
        if not isinstance(payload, dict):
            raise _ResponseError("expected_object")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        if isinstance(exc, _ResponseError):
            reason = exc.reason
        _log_failure(stage, provider, model, reason, response=response, payload=response_payload, attempt=attempt + 1)
        raise AIServiceError("리포트 AI 응답 형식이 올바르지 않습니다.") from None
    return payload
