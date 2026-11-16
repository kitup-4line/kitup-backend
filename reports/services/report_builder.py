"""리포트 접수, 단계별 저장, 조회와 재시도."""

import logging
import time

from django.db import DatabaseError, InterfaceError, OperationalError, transaction
from django.db.models import F
from django.dispatch import receiver
from django.utils import timezone
# django-q2는 django_q 모듈을 제공한다. PyCharm의 패키지 이름 매칭 오탐만 제외한다.
# noinspection PyPackageRequirements
from django_q.conf import Conf
# noinspection PyPackageRequirements
from django_q.models import Task
# noinspection PyPackageRequirements
from django_q.signals import pre_execute
# noinspection PyPackageRequirements
from django_q.tasks import async_task
from rest_framework.exceptions import NotFound, ValidationError

from core.choices import RecommendationStatus as Improvement
from core.choices import ReviewAnalysisStatus as Analysis
from core.exceptions import ReportNotReadyError
from menu_tests.models import MenuTest
from menu_tests.services.menu_test_service import get_test_or_404
from orders.models import Review
from reports import ai_client

from . import quantitative_service, recommendation, review_analysis

logger = logging.getLogger(__name__)


@receiver(pre_execute)
def pass_task_id(func, task, **_kwargs):
    # Q2가 발급한 ID를 전달해 이전 작업의 늦은 저장을 막는다.
    if func is build_ai_sections:
        task["kwargs"]["task_id"] = task["id"]


def _enqueue(test):
    # ORM 큐와 테스트 변경은 같은 default DB 트랜잭션에 참여한다.
    test.report_task_id = async_task(
        "reports.services.report_builder.build_ai_sections", test.pk,
        hook="reports.services.report_builder.finish_task",
    )
    test.save(update_fields=["report_task_id", "updated_at"])


def _response(test, quantitative=None):
    result = {
        "review_analysis_status": test.review_analysis_status,
        "improvement_status": test.improvement_status,
    }
    if quantitative is not None:
        result["quantitative"] = quantitative
    return result


def _failed_stage(test):
    if test.review_analysis_status not in (Analysis.SUCCEEDED, Analysis.NOT_REQUIRED):
        return "review_analysis_status"
    return "improvement_status"


def _read_task_failure(test):
    # 마지막 실패 hook의 저장이 끊겨도 Q2의 결과로 실패를 확인한다. GET은 DB를 수정하지 않는다.
    if test.review_analysis_status == Analysis.FAILED or test.improvement_status in (
        Improvement.SUCCEEDED, Improvement.FAILED,
    ):
        return
    if Task.objects.filter(
        pk=test.report_task_id, success=False, attempt_count__gte=Conf.MAX_ATTEMPTS,
    ).exists():
        setattr(test, _failed_stage(test), "FAILED")


# PyCharm이 null=True 날짜를 항상 값이 있는 것으로 추론하는 오탐을 억제한다.
# noinspection unreachable-code
@transaction.atomic
def start_report(test_id: int, *, additional_fixed_cost: int | None = None) -> dict:
    test = get_test_or_404(test_id, for_update=True)
    if test.ended_at is not None:
        _read_task_failure(test)
        quantitative = quantitative_service.build_report(test)
        if test.review_analysis_status == Analysis.FAILED or test.improvement_status == Improvement.FAILED:
            if test.review_analysis_status == Analysis.FAILED:
                test.review_analysis_status = Analysis.PENDING
            test.improvement_status = Improvement.PENDING
            test.save(update_fields=["review_analysis_status", "improvement_status", "updated_at"])
            _enqueue(test)
        return _response(test, quantitative)
    if additional_fixed_cost is None:
        raise ValidationError({"additional_fixed_cost": "처음 생성할 때는 추가 고정비를 입력해주세요."})
    if test.started_at is None or not test.orders.exists():
        raise ReportNotReadyError()
    test.additional_fixed_cost = additional_fixed_cost
    quantitative = quantitative_service.build_report(test)
    review_count = quantitative["analysis_conditions"]["analysis_data"]["linked_review_count"]
    test.ended_at = timezone.now()
    test.review_analysis_status = Analysis.PENDING if review_count else Analysis.NOT_REQUIRED
    test.improvement_status = Improvement.PENDING
    test.save(update_fields=[
        "additional_fixed_cost", "ended_at", "review_analysis_status", "improvement_status", "updated_at",
    ])
    _enqueue(test)
    return _response(test, quantitative)


def _reviews(test_id, *, fields=("content", *review_analysis.LABEL_FIELDS)):
    return list(Review.objects.filter(order__test_id=test_id).order_by("pk").values(
        *fields, review_id=F("pk"),
    ))


def get_report(test_id: int, *, include_quantitative: bool = True) -> dict:
    """정량 결과는 요청할 때만 계산하고 AI 결과는 저장된 값만 읽는다."""
    test = get_test_or_404(test_id)
    if test.ended_at is None:
        raise NotFound("생성 요청한 리포트가 없습니다.")
    _read_task_failure(test)
    quantitative = quantitative_service.build_report(test) if include_quantitative else None
    result = _response(test, quantitative)
    result["review_analysis"] = (
        review_analysis.summarize(_reviews(test_id, fields=review_analysis.LABEL_FIELDS), test.review_quotes)
        if test.review_analysis_status == Analysis.SUCCEEDED else None
    )
    result["improvements"] = (
        test.improvement_result["items"]
        if test.improvement_status == Improvement.SUCCEEDED else None
    )
    return result


@transaction.atomic
def _mark_failed(test_id, task_id):
    test = MenuTest.objects.select_for_update().get(pk=test_id)
    if test.report_task_id != task_id or test.improvement_status == Improvement.SUCCEEDED:
        return
    setattr(test, _failed_stage(test), "FAILED")
    test.save(update_fields=["review_analysis_status", "improvement_status", "updated_at"])


def _is_retryable_db_error(exc):
    if not isinstance(exc, (DatabaseError, InterfaceError)):
        return False
    sqlstate = getattr(exc.__cause__, "sqlstate", None)
    if sqlstate:
        # 연결 단절, 트랜잭션 충돌, 잠금 경합, 접속 초과·서버 재시작만 재전달한다.
        return sqlstate in {
            "08000", "08001", "08003", "08006", "08007",
            "40001", "40P01", "55P03", "53300", "57P01", "57P02", "57P03",
        }
    # 연결 단계에서 실패하면 서버 오류 코드가 없을 수 있다. Q2의 횟수 제한은 유지한다.
    return isinstance(exc, (OperationalError, InterfaceError))


def build_ai_sections(test_id: int, *, task_id: str) -> None:
    started = time.monotonic()
    test = MenuTest.objects.get(pk=test_id)
    if test.report_task_id != task_id or test.improvement_status == Improvement.SUCCEEDED:
        return
    token = ai_client.report_task_context.set({
        "test_id": test_id, "task_id": task_id, "deadline": started + Conf.TIMEOUT,
    })
    try:
        if test.review_analysis_status not in (Analysis.SUCCEEDED, Analysis.NOT_REQUIRED):
            updated = MenuTest.objects.filter(pk=test_id, report_task_id=task_id).exclude(
                review_analysis_status__in=(Analysis.SUCCEEDED, Analysis.NOT_REQUIRED),
            ).exclude(improvement_status=Improvement.SUCCEEDED).update(
                review_analysis_status=Analysis.RUNNING, updated_at=timezone.now(),
            )
            if not updated:
                return
            reviews = _reviews(test_id, fields=("content",))
            if reviews:
                analysis = review_analysis.analyze(reviews)
            else:
                analysis = {"reviews": [], "quotes": []}
            labels = analysis["reviews"]
            with transaction.atomic():
                test = get_test_or_404(test_id, for_update=True)
                if test.report_task_id != task_id:
                    return
                updates = []
                for row in labels:
                    fields = {field: row[field] for field in review_analysis.LABEL_FIELDS}
                    updates.append(Review(pk=row["review_id"], **fields))
                Review.objects.bulk_update(updates, review_analysis.LABEL_FIELDS)
                test.review_quotes = analysis["quotes"]
                test.review_analysis_status = Analysis.SUCCEEDED if labels else Analysis.NOT_REQUIRED
                test.save(update_fields=["review_quotes", "review_analysis_status", "updated_at"])

        updated = MenuTest.objects.filter(
            pk=test_id, report_task_id=task_id,
            review_analysis_status__in=(Analysis.SUCCEEDED, Analysis.NOT_REQUIRED),
        ).exclude(improvement_status=Improvement.SUCCEEDED).update(
            improvement_status=Improvement.RUNNING, updated_at=timezone.now(),
        )
        if not updated:
            return
        result = recommendation.generate(quantitative_service.build_report(test), _reviews(test_id))
        with transaction.atomic():
            test = get_test_or_404(test_id, for_update=True)
            if test.report_task_id != task_id:
                return
            test.improvement_result = result
            test.improvement_status = Improvement.SUCCEEDED
            test.save(update_fields=["improvement_result", "improvement_status", "updated_at"])
    except Exception as exc:
        if _is_retryable_db_error(exc):
            raise
        # HTTP 공통 예외 처리가 실행되지 않는 worker의 경계.
        logger.exception("리포트 AI 처리 실패: test_id=%s", test_id)
        _mark_failed(test_id, task_id)
    finally:
        ai_client.report_task_context.reset(token)


def finish_task(task) -> None:
    """Q2의 자동 복구 횟수까지 소진되면 수동 재시도를 허용한다."""
    if not task.success and task.attempt_count >= Conf.MAX_ATTEMPTS:
        _mark_failed(task.args[0], task.id)
