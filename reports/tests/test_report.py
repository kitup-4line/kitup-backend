import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, time
from decimal import Decimal
from threading import Barrier
from unittest.mock import Mock, patch

from django.db import DataError, DatabaseError, IntegrityError, InterfaceError, OperationalError, connection, connections
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from django_q.exceptions import TimeoutException
from django_q.models import OrmQ, Task
from django_q.signals import pre_execute
from django_q.signing import SignedPackage
from psycopg import errors as pg_errors
from rest_framework.renderers import JSONRenderer
from rest_framework.test import APIClient

from core.calc.order_summary import summarize_orders
from core.choices import Channel, RecommendationStatus as Improvement, ReviewAnalysisStatus as Analysis
from core.exceptions import AIServiceError
from menu_tests.models import MenuTest
from menu_tests.tests.helpers import make_test
from orders.models import Order, Review
from reports import ai_client
from reports.serializers import ReportDetailSerializer
from reports.services import quantitative_service, recommendation, report_builder


def make_operating_test():
    return make_test(
        total_ingredient_cost=Decimal("2800.1234"), packaging_cost=Decimal("300.2345"),
        business_start_time=time(11), business_end_time=time(20),
        started_at=timezone.make_aware(datetime(2026, 10, 28)), kitchen_name="성수 공유주방 A - 가상공간",
    )


def add_order(test, hour=12, *, price=9900, channel=Channel.DELIVERY):
    return Order.objects.create(
        test=test, sales_amount=price, order_type=channel,
        created_at=timezone.make_aware(datetime(2026, 10, 28, hour)),
    )


def labels_for(reviews):
    return {
        "reviews": [{"review_id": row["review_id"], "sentiment": "POSITIVE", "taste_sentiment": "POSITIVE",
                     "portion_sentiment": None, "temperature_sentiment": None, "packaging_sentiment": None}
                    for row in reviews],
        "quotes": [{"review_id": row["review_id"], "quote": row["content"],
                    "aspect": "taste", "sentiment": "POSITIVE"} for row in reviews[:2]],
    }


RESULT = {"items": [{"title": "작업 배치 점검", "action": "주문 집중 구간의 준비 시간을 확인하세요.",
                     "verification": "다음 테스트의 준비 시간을 비교하세요.", "evidence_review_ids": []}]}


class ReportTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.test = make_operating_test()
        order = add_order(self.test)
        self.review = Review.objects.create(order=order, content="맛있어요")
        self.url = reverse("report-detail", kwargs={"test_id": self.test.pk})

    def start(self):
        result = report_builder.start_report(self.test.pk, additional_fixed_cost=1200)
        self.test.refresh_from_db()
        return result

    def run_worker(self):
        package = SignedPackage.loads(OrmQ.objects.latest("pk").payload)
        pre_execute.send(sender="django_q", func=report_builder.build_ai_sections, task=package)
        report_builder.build_ai_sections(*package["args"], **package["kwargs"])

    def test_post_returns_quantitative_and_enqueues_without_calling_ai(self):
        with patch("reports.services.review_analysis.analyze") as analyze:
            response = self.client.post(self.url, {"additional_fixed_cost": 1200}, format="json")
        self.assertEqual(response.status_code, 202, response.content)
        analyze.assert_not_called()
        self.test.refresh_from_db()
        self.assertIsNotNone(self.test.ended_at)
        self.assertEqual(self.test.additional_fixed_cost, 1200)
        self.assertEqual(OrmQ.objects.count(), 1)
        package = SignedPackage.loads(OrmQ.objects.get().payload)
        self.assertEqual(package["id"], self.test.report_task_id)
        data = response.json()["data"]
        self.assertEqual(data["review_analysis_status"], "PENDING")
        self.assertEqual(data["quantitative"]["analysis_conditions"]["kitchen_name"], self.test.kitchen_name)

    def test_enqueue_then_failure_rolls_back_queue_cost_and_freeze(self):
        original = report_builder._enqueue

        def fail_after_enqueue(test):
            original(test)
            raise DatabaseError("simulated registration failure")

        fields = ("ended_at", "additional_fixed_cost", "report_task_id",
                  "review_analysis_status", "improvement_status", "review_quotes")
        for failed_stage in (None, "review", "improvement"):
            with self.subTest(failed_stage=failed_stage):
                test = make_operating_test()
                add_order(test)
                if failed_stage:
                    report_builder.start_report(test.pk, additional_fixed_cost=1200)
                    MenuTest.objects.filter(pk=test.pk).update(
                        review_analysis_status=Analysis.FAILED if failed_stage == "review" else Analysis.SUCCEEDED,
                        improvement_status=Improvement.PENDING if failed_stage == "review" else Improvement.FAILED,
                    )
                test.refresh_from_db()
                before = {field: getattr(test, field) for field in fields}
                queue_ids = set(OrmQ.objects.values_list("pk", flat=True))
                with patch.object(report_builder, "_enqueue", side_effect=fail_after_enqueue):
                    with self.assertRaises(DatabaseError):
                        report_builder.start_report(test.pk, additional_fixed_cost=9999)
                test.refresh_from_db()
                self.assertEqual({field: getattr(test, field) for field in fields}, before)
                self.assertEqual(set(OrmQ.objects.values_list("pk", flat=True)), queue_ids)

    def test_input_missing_test_not_started_and_duplicate(self):
        for payload in ({}, {"additional_fixed_cost": -1}, {"additional_fixed_cost": "invalid"}):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post(self.url, payload, format="json").status_code, 400)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        missing = reverse("report-detail", kwargs={"test_id": self.test.pk + 999})
        self.assertEqual(self.client.post(missing, {"additional_fixed_cost": 0}).status_code, 404)
        draft = make_test()
        draft_url = reverse("report-detail", kwargs={"test_id": draft.pk})
        self.assertEqual(self.client.post(draft_url, {"additional_fixed_cost": 0}).status_code, 409)
        self.start()
        self.assertEqual(self.client.post(self.url, {"additional_fixed_cost": 9999}).status_code, 202)
        self.assertEqual(self.client.post(self.url).status_code, 202)
        self.assertEqual(OrmQ.objects.count(), 1)

    def test_success_get_uses_saved_ai_and_recomputes_quantitative(self):
        self.start()
        with patch("reports.services.review_analysis.analyze", side_effect=labels_for), patch(
            "reports.services.recommendation.generate", return_value=RESULT,
        ):
            self.run_worker()
        with patch("reports.ai_client.request_json") as ai:
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.content)
        ai.assert_not_called()
        self.assertEqual(response["Cache-Control"], "no-store")
        data = response.json()["data"]
        self.assertEqual(data["improvement_status"], "SUCCEEDED")
        self.assertEqual(data["review_analysis"]["review_count"], 1)
        self.assertEqual(data["improvements"], RESULT["items"])
        self.assertEqual(data["quantitative"]["profit_analysis"]["summary"]["total_revenue"], 9900)

    def test_worker_saves_only_verified_quotes_and_polling_reuses_them(self):
        self.start()
        payload = labels_for([{"review_id": self.review.pk, "content": self.review.content}])
        valid_quote = payload["quotes"][0].copy()
        payload["quotes"].append({**valid_quote, "quote": "원문에 없는 문장"})
        contexts = []
        responses = iter([payload, RESULT])
        def respond(*args, **kwargs):
            contexts.append(ai_client.report_task_context.get().copy())
            return next(responses)
        with patch("reports.ai_client.request_json", side_effect=respond) as ai:
            self.run_worker()
            self.assertEqual(ai.call_count, 2)  # 리뷰 분석과 개선안 생성만 호출한다.
        self.assertEqual(contexts[0], contexts[1])
        self.assertEqual(contexts[0]["test_id"], self.test.pk)
        self.assertEqual(contexts[0]["task_id"], self.test.report_task_id)
        self.assertIsNone(ai_client.report_task_context.get())
        self.test.refresh_from_db()
        self.review.refresh_from_db()
        self.assertEqual(self.test.review_quotes, [valid_quote])
        self.assertEqual(self.review.sentiment, "POSITIVE")
        with patch("reports.ai_client.request_json") as ai:
            data = self.client.get(self.url, {"include_quantitative": "false"}).json()["data"]
        ai.assert_not_called()
        self.assertNotIn("quantitative", data)
        self.assertEqual(data["review_analysis"]["strengths"][0], {
            "aspect": "taste", "sentiment": "POSITIVE", "review_count": 1, "review_percentage": 100,
            "quotes": [{"review_id": self.review.pk, "quote": self.review.content}],
        })

    def test_improvement_input_matches_response_precision_without_changing_calculation(self):
        result = self.start()
        quantitative = result["quantitative"]
        original = deepcopy(quantitative)
        reviews = [{"review_id": self.review.pk, "content": self.review.content}]
        with patch("reports.ai_client.request_json", return_value=RESULT) as ai:
            recommendation.generate(quantitative, reviews)
        payload = json.loads(ai.call_args.args[2])
        response = self.client.get(self.url).json()["data"]["quantitative"]
        self.assertEqual(payload["quantitative"], response)
        self.assertEqual(payload["reviews"], reviews)
        self.assertEqual(quantitative, original)
        conditions = payload["quantitative"]["analysis_conditions"]["sales_conditions"]
        self.assertEqual(conditions["orders_per_hour"], 0.0079)
        self.assertNotEqual(original["analysis_conditions"]["sales_conditions"]["orders_per_hour"], Decimal("0.0079"))
        generator = Mock(generate=Mock(return_value=RESULT))
        recommendation.generate(quantitative, reviews, generator=generator)
        self.assertEqual(json.loads(JSONRenderer().render(generator.generate.call_args.args[0])), response)
        self.assertEqual(
            generator.generate.call_args.args[0]["analysis_conditions"]["sales_conditions"]["orders_per_hour"],
            Decimal("0.0079"),
        )
        self.assertEqual(quantitative, original)

    def test_polling_skips_quantitative_calculation_and_keeps_ai_results(self):
        self.start()
        for finished in (False, True):
            with self.subTest(finished=finished):
                if finished:
                    with patch("reports.services.review_analysis.analyze", side_effect=labels_for), patch(
                        "reports.services.recommendation.generate", return_value=RESULT,
                    ):
                        self.run_worker()
                expected = self.client.get(self.url).json()["data"]
                expected.pop("quantitative")
                with patch.object(quantitative_service, "build_report") as calculate, patch(
                    "reports.ai_client.request_json",
                ) as ai, CaptureQueriesContext(connection) as queries:
                    response = self.client.get(self.url, {"include_quantitative": "false"})
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(response.json()["data"], expected)
                self.assertEqual(response["Cache-Control"], "no-store")
                calculate.assert_not_called()
                ai.assert_not_called()
                for query in queries:
                    self.assertNotIn('"content"', query["sql"])

    def test_quantitative_option_defaults_to_true_and_rejects_invalid_values(self):
        self.start()
        for query in ({}, {"include_quantitative": "true"}):
            with self.subTest(query=query), patch.object(
                quantitative_service, "build_report", wraps=quantitative_service.build_report,
            ) as calculate:
                response = self.client.get(self.url, query)
                self.assertEqual(response.status_code, 200, response.content)
                self.assertIn("quantitative", response.json()["data"])
                calculate.assert_called_once()
        with patch.object(report_builder, "get_report") as get_report:
            response = self.client.get(self.url, {"include_quantitative": "invalid"})
        self.assertEqual(response.status_code, 400, response.content)
        get_report.assert_not_called()

    def test_polling_still_requires_existing_report(self):
        for test_id in (self.test.pk, self.test.pk + 999):
            with self.subTest(test_id=test_id), patch.object(quantitative_service, "build_report") as calculate:
                response = self.client.get(
                    reverse("report-detail", kwargs={"test_id": test_id}), {"include_quantitative": "false"},
                )
                self.assertEqual(response.status_code, 404)
                calculate.assert_not_called()

    def test_review_failure_preserves_quantitative_and_can_retry(self):
        self.start()
        with patch("reports.services.review_analysis.analyze", side_effect=AIServiceError()), patch(
            "reports.services.recommendation.generate",
        ) as generate, self.assertLogs("reports.services.report_builder", level="ERROR"):
            self.run_worker()
        generate.assert_not_called()
        self.assertIsNone(ai_client.report_task_context.get())
        self.test.refresh_from_db()
        self.assertEqual(self.test.review_analysis_status, Analysis.FAILED)
        self.review.refresh_from_db()
        self.assertIsNone(self.review.sentiment)
        with patch.object(Task.objects, "filter") as task_query:
            self.assertEqual(self.client.get(self.url).status_code, 200)
        task_query.assert_not_called()
        self.assertEqual(self.client.post(self.url).status_code, 202)

    def test_improvement_failure_retry_preserves_review_labels(self):
        self.start()
        with patch("reports.services.review_analysis.analyze", side_effect=labels_for), patch(
            "reports.services.recommendation.generate", side_effect=DataError("invalid report data"),
        ), self.assertLogs("reports.services.report_builder", level="ERROR"):
            self.run_worker()
        self.test.refresh_from_db()
        self.assertEqual(self.test.review_analysis_status, Analysis.SUCCEEDED)
        self.assertEqual(self.test.improvement_status, Improvement.FAILED)
        saved_ended_at = self.test.ended_at
        saved_quotes = self.test.review_quotes
        self.assertEqual(saved_quotes[0]["quote"], self.review.content)
        cards = self.client.get(self.url).json()["data"]["review_analysis"]["strengths"]
        self.assertEqual(cards[0]["quotes"][0]["quote"], self.review.content)
        response = self.client.post(self.url, {"additional_fixed_cost": 9999})
        self.assertEqual(response.status_code, 202)
        self.test.refresh_from_db()
        self.assertEqual(self.test.additional_fixed_cost, 1200)
        self.assertEqual(self.test.ended_at, saved_ended_at)
        with patch("reports.services.review_analysis.analyze") as analyze, patch(
            "reports.services.recommendation.generate", return_value=RESULT,
        ):
            self.run_worker()
        analyze.assert_not_called()
        self.test.refresh_from_db()
        self.assertEqual(self.test.improvement_status, Improvement.SUCCEEDED)
        self.assertEqual(self.test.review_quotes, saved_quotes)
        task_id = self.test.report_task_id
        queue_count = OrmQ.objects.count()
        self.assertEqual(self.client.post(self.url).status_code, 202)
        self.test.refresh_from_db()
        self.assertEqual(self.test.report_task_id, task_id)
        self.assertEqual(OrmQ.objects.count(), queue_count)
        self.assertEqual(self.client.post(self.url + "retry/").status_code, 404)

    def test_no_reviews_skips_analysis_but_generates_improvements(self):
        self.review.delete()
        self.start()
        self.assertEqual(self.test.review_analysis_status, Analysis.NOT_REQUIRED)
        with patch("reports.services.review_analysis.analyze") as analyze, patch(
            "reports.services.recommendation.generate", return_value=RESULT,
        ) as generate:
            self.run_worker()
        analyze.assert_not_called()
        self.assertEqual(generate.call_args.args[1], [])

    def test_terminal_queue_failure_remains_retryable_when_hook_save_was_lost(self):
        self.start()
        MenuTest.objects.filter(pk=self.test.pk).update(review_analysis_status=Analysis.RUNNING)
        Task.objects.create(
            id=self.test.report_task_id, name="reports", func="reports.services.report_builder.build_ai_sections",
            args=(self.test.pk,), kwargs={}, started=timezone.now(), stopped=timezone.now(),
            success=False, attempt_count=3,
        )
        response = self.client.get(self.url)
        self.assertEqual(response.json()["data"]["review_analysis_status"], Analysis.FAILED)
        self.test.refresh_from_db()
        self.assertEqual(self.test.review_analysis_status, Analysis.RUNNING)  # GET은 저장하지 않는다.
        self.assertEqual(self.client.post(self.url).status_code, 202)

    def test_smallest_revenue_and_largest_costs_are_serializable(self):
        self.test.orders.update(sales_amount=1)
        MenuTest.objects.filter(pk=self.test.pk).update(
            selling_price=1, total_ingredient_cost=Decimal("99999999.9999"),
            packaging_cost=Decimal("99999999.9999"),
        )
        response = self.client.post(self.url, {"additional_fixed_cost": 2147483647})
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_label_save_and_success_status_roll_back_together(self):
        self.start()
        original = MenuTest.save
        def fail_status_save(test, *args, **kwargs):
            if test.review_analysis_status == Analysis.SUCCEEDED:
                raise IntegrityError("simulated save failure")
            return original(test, *args, **kwargs)
        with patch("reports.services.review_analysis.analyze", side_effect=labels_for), patch.object(
            MenuTest, "save", fail_status_save,
        ), self.assertLogs("reports.services.report_builder", level="ERROR"):
            self.run_worker()
        self.review.refresh_from_db()
        self.test.refresh_from_db()
        self.assertIsNone(self.review.sentiment)
        self.assertEqual(self.test.review_analysis_status, Analysis.FAILED)
        self.assertEqual(self.test.review_quotes, [])
        self.assertEqual(self.client.post(self.url).status_code, 202)

    def test_recoverable_db_errors_and_worker_timeout_propagate_for_queue_retry(self):
        self.start()
        errors = [OperationalError("connection lost"), InterfaceError("connection closed"), TimeoutException()]
        for cause in (pg_errors.SerializationFailure(), pg_errors.DeadlockDetected(), pg_errors.AdminShutdown()):
            error = OperationalError("temporary database failure")
            error.__cause__ = cause
            errors.append(error)
        for error in errors:
            with self.subTest(error=error, cause=error.__cause__), patch(
                "reports.services.review_analysis.analyze", side_effect=labels_for,
            ), patch.object(Review.objects, "bulk_update", side_effect=error), self.assertRaises(type(error)):
                self.run_worker()
            self.assertIsNone(ai_client.report_task_context.get())
            self.test.refresh_from_db()
            self.review.refresh_from_db()
            self.assertEqual(self.test.review_analysis_status, Analysis.RUNNING)
            self.assertIsNone(self.review.sentiment)
            self.assertEqual(self.test.review_quotes, [])
        with patch("reports.services.review_analysis.analyze", side_effect=labels_for), patch(
            "reports.services.recommendation.generate", return_value=RESULT,
        ):
            self.run_worker()
        self.test.refresh_from_db()
        self.assertEqual(self.test.improvement_status, Improvement.SUCCEEDED)

    def test_canceled_query_marks_failed_instead_of_queue_retry(self):
        self.start()
        error = OperationalError("canceling statement due to statement timeout")
        error.__cause__ = pg_errors.QueryCanceled()
        with patch("reports.services.review_analysis.analyze", side_effect=labels_for), patch.object(
            Review.objects, "bulk_update", side_effect=error,
        ), self.assertLogs(
            "reports.services.report_builder", level="ERROR",
        ):
            self.run_worker()
        self.test.refresh_from_db()
        self.assertEqual(self.test.review_analysis_status, Analysis.FAILED)
        self.assertEqual(self.client.post(self.url).status_code, 202)

    def test_old_task_cannot_overwrite_new_task_or_mark_it_failed(self):
        self.start()
        old_id = self.test.report_task_id
        def replace_task(reviews):
            MenuTest.objects.filter(pk=self.test.pk).update(report_task_id="b" * 32)
            return labels_for(reviews)
        with patch("reports.services.review_analysis.analyze", side_effect=replace_task), patch(
            "reports.services.recommendation.generate",
        ) as generate:
            self.run_worker()
        generate.assert_not_called()
        report_builder._mark_failed(self.test.pk, old_id)
        self.review.refresh_from_db()
        self.assertIsNone(self.review.sentiment)
        self.test.refresh_from_db()
        self.assertEqual(self.test.report_task_id, "b" * 32)
        self.assertEqual(self.test.review_analysis_status, Analysis.RUNNING)
        self.assertEqual(self.test.review_quotes, [])

    def test_running_updates_recheck_task_id_and_success_after_initial_read(self):
        self.start()
        task_id = self.test.report_task_id
        for stage in ("review", "improvement"):
            for change in ("task_id", "succeeded"):
                with self.subTest(stage=stage, change=change):
                    MenuTest.objects.filter(pk=self.test.pk).update(
                        report_task_id=task_id, improvement_status=Improvement.PENDING,
                        review_analysis_status=Analysis.PENDING if stage == "review" else Analysis.SUCCEEDED,
                        improvement_result=None,
                    )
                    stale_test = MenuTest.objects.get(pk=self.test.pk)
                    if change == "task_id":
                        changes = {"report_task_id": "b" * 32}
                    elif stage == "review":
                        changes = {"review_analysis_status": Analysis.SUCCEEDED}
                    else:
                        changes = {"improvement_status": Improvement.SUCCEEDED, "improvement_result": RESULT}
                    MenuTest.objects.filter(pk=self.test.pk).update(**changes)
                    with patch.object(MenuTest.objects, "get", return_value=stale_test), patch(
                        "reports.services.review_analysis.analyze",
                    ) as analyze, patch("reports.services.recommendation.generate") as generate:
                        report_builder.build_ai_sections(self.test.pk, task_id=task_id)
                    analyze.assert_not_called()
                    generate.assert_not_called()
                    self.test.refresh_from_db()
                    for field, value in changes.items():
                        self.assertEqual(getattr(self.test, field), value)

    def test_running_stage_can_resume_after_worker_restart(self):
        self.start()
        MenuTest.objects.filter(pk=self.test.pk).update(review_analysis_status=Analysis.RUNNING)
        with patch("reports.services.review_analysis.analyze", side_effect=labels_for), patch(
            "reports.services.recommendation.generate", return_value=RESULT,
        ):
            self.run_worker()
        MenuTest.objects.filter(pk=self.test.pk).update(
            improvement_status=Improvement.RUNNING, improvement_result=None,
        )
        with patch("reports.services.review_analysis.analyze") as analyze, patch(
            "reports.services.recommendation.generate", return_value=RESULT,
        ) as generate:
            self.run_worker()
        analyze.assert_not_called()
        generate.assert_called_once()
        self.test.refresh_from_db()
        self.assertEqual(self.test.improvement_status, Improvement.SUCCEEDED)

    def test_dashboard_rounding_preserves_actual_order_prices(self):
        add_order(self.test, 13, price=12345, channel=Channel.PICKUP)
        self.test.selling_price = 20000  # 주문 저장 후 메뉴 판매가가 바뀐 경우
        self.test.additional_fixed_cost = 1200
        result = quantitative_service.build_report(self.test)
        summary = result["profit_analysis"]["summary"]
        parts = result["profit_analysis"]["per_order_structure"]
        self.assertEqual(summary["total_revenue"], 22245)
        self.assertEqual(summary["total_contribution_margin"], Decimal("11875"))
        self.assertEqual(summary["estimated_operating_profit"], Decimal("10675"))
        self.assertEqual(sum(parts[key]["amount"] for key in (
            "ingredient_cost", "packaging_cost", "delivery_fee", "delivery_commission", "contribution_margin",
        )), parts["average_revenue"] + Decimal("0.3579"))
        self.assertEqual(sum(parts[key]["revenue_percentage"] for key in (
            "ingredient_cost", "packaging_cost", "delivery_fee", "delivery_commission", "contribution_margin",
        )).quantize(Decimal("0.01")), 100)

    def test_cost_edit_preview_matches_saved_report_without_repricing_orders(self):
        add_order(self.test, 13, price=12345, channel=Channel.PICKUP)
        orders = list(self.test.orders.order_by("pk").values("sales_amount", "order_type"))
        before = quantitative_service.build_report(self.test)["profit_analysis"]["summary"]
        preview = summarize_orders(orders, ingredient_cost=2700, packaging_cost=self.test.packaging_cost)
        response = self.client.put(
            reverse("test-ingredients", kwargs={"test_id": self.test.pk}),
            {"ingredients": [{"ingredient_name": "닭고기", "quantity": 1, "unit": "g", "ingredient_cost": 2700}]},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.test.refresh_from_db()
        after = quantitative_service.build_report(self.test)["profit_analysis"]["summary"]
        self.assertEqual(after["total_contribution_margin"], preview["contribution_margin"])
        self.assertEqual(after["contribution_margin_per_order"], preview["contribution_margin_per_order"])
        self.assertEqual(after["total_contribution_margin"] - before["total_contribution_margin"],
                         Decimal("200"))
        self.assertEqual(after["total_revenue"], before["total_revenue"])
        self.assertEqual(list(self.test.orders.order_by("pk").values("sales_amount", "order_type")), orders)

    def test_two_hour_boundaries_ties_short_last_bucket_and_other(self):
        self.test.orders.all().delete()
        for hour in (10, 11, 12, 13, 14, 17, 18, 19, 20):
            add_order(self.test, hour)
        pattern = quantitative_service.build_report(self.test)["sales_pattern"]
        first, second, other = pattern["time_buckets"]
        self.assertEqual((first["label"], first["order_count"]), ("11:00~13:00", 2))
        self.assertEqual((second["label"], second["order_count"]), ("13:00~15:00", 2))
        self.assertEqual(other["order_count"], 5)
        for _ in range(3):
            add_order(self.test, 19)
        pattern = quantitative_service.build_report(self.test)["sales_pattern"]
        self.assertEqual(pattern["time_buckets"][0]["label"], "19:00~20:00")
        self.assertEqual(sum(item["order_count"] for item in pattern["time_buckets"]), 12)

    def test_empty_or_flat_sales_do_not_claim_a_peak(self):
        self.test.orders.all().delete()
        for hour in (11, 13, 15, 17, 19):
            add_order(self.test, hour)
        report = quantitative_service.build_report(self.test)
        self.assertIsNone(report["sales_pattern"]["insights"]["recommended_action"])
        self.test.orders.all().delete()
        report = quantitative_service.build_report(self.test)
        self.assertIsNone(report["profit_analysis"]["per_order_structure"]["average_revenue"])
        self.assertIsNone(report["profit_analysis"]["summary"]["contribution_margin_percentage"])
        ReportDetailSerializer({"quantitative": report, "review_analysis_status": Analysis.NOT_REQUIRED,
                                "improvement_status": Improvement.PENDING,
                                "review_analysis": None, "improvements": None}).data


class EvidenceReviewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.test = make_operating_test()
        self.test.ended_at = timezone.now()
        self.test.review_analysis_status = Analysis.SUCCEEDED
        self.test.save()
        self.url = reverse("report-evidence-reviews", kwargs={"test_id": self.test.pk})
        self.params = {"aspect": "taste", "sentiment": "POSITIVE"}

    def test_filters_by_test_and_aspect_with_stable_order_and_original_content(self):
        now = timezone.now()
        first = Review.objects.create(
            order=add_order(self.test), content="  맛있지만 식었어요.\n", written_at=now,
            sentiment="MIXED", taste_sentiment="POSITIVE", temperature_sentiment="NEGATIVE",
        )
        second = Review.objects.create(
            order=add_order(self.test), content="맛있어요", written_at=now, taste_sentiment="POSITIVE",
        )
        undated = Review.objects.create(
            order=add_order(self.test), content="맛은 좋아요", taste_sentiment="POSITIVE",
        )
        Review.objects.create(order=add_order(self.test), content="맛이 아쉬워요", taste_sentiment="NEGATIVE")
        Review.objects.create(order=add_order(self.test), content="양이 많아요", portion_sentiment="POSITIVE")
        Review.objects.create(order=add_order(make_operating_test()), content="다른 테스트", taste_sentiment="POSITIVE")
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url, self.params)
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual([row["review_id"] for row in data], [second.pk, first.pk, undated.pk])
        self.assertEqual(data[1], {
            "review_id": first.pk, "content": first.content,
            "written_at": timezone.localtime(now).isoformat(),
        })
        self.assertIsNone(data[2]["written_at"])
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(len(queries), 2)
        self.assertTrue(all(q["sql"].lstrip().startswith("SELECT") for q in queries))

    def test_all_aspects_and_sentiments_match_card_counts(self):
        from reports.services import review_analysis

        for aspect in ("taste", "portion", "temperature", "packaging"):
            for sentiment in ("POSITIVE", "NEGATIVE"):
                with self.subTest(aspect=aspect, sentiment=sentiment):
                    review = Review.objects.create(
                        order=add_order(self.test), content="분류된 리뷰", sentiment=sentiment,
                        **{f"{aspect}_sentiment": sentiment},
                    )
                    response = self.client.get(self.url, {"aspect": aspect, "sentiment": sentiment})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual([r["review_id"] for r in response.json()["data"]], [review.pk])
                    summary = review_analysis.summarize(report_builder._reviews(self.test.pk), [])
                    cards = summary["strengths" if sentiment == "POSITIVE" else "improvement_candidates"]
                    card = next(c for c in cards if c["aspect"] == aspect)
                    self.assertEqual(card["review_count"], len(response.json()["data"]))
                    review.delete()

    def test_missing_or_invalid_filters_return_400(self):
        for params in ({}, {"aspect": "taste"}, {"sentiment": "POSITIVE"},
                       {"aspect": "order__test_id", "sentiment": "POSITIVE"},
                       {"aspect": "taste", "sentiment": "MIXED"}):
            with self.subTest(params=params):
                self.assertEqual(self.client.get(self.url, params).status_code, 400)

    def test_missing_test_or_report_returns_404(self):
        MenuTest.objects.filter(pk=self.test.pk).update(ended_at=None)
        self.assertEqual(self.client.get(self.url, self.params).status_code, 404)
        self.test.delete()
        self.assertEqual(self.client.get(self.url, self.params).status_code, 404)

    def test_analysis_readiness_and_empty_results(self):
        for analysis in (Analysis.PENDING, Analysis.RUNNING, Analysis.FAILED):
            with self.subTest(analysis=analysis):
                MenuTest.objects.filter(pk=self.test.pk).update(review_analysis_status=analysis)
                response = self.client.get(self.url, self.params)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()["error"]["code"], "review_analysis_not_ready")
        for analysis in (Analysis.NOT_REQUIRED, Analysis.SUCCEEDED):
            for improvement in Improvement.values:
                with self.subTest(analysis=analysis, improvement=improvement):
                    MenuTest.objects.filter(pk=self.test.pk).update(
                        review_analysis_status=analysis, improvement_status=improvement,
                        improvement_result=RESULT,
                    )
                    response = self.client.get(self.url, self.params)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["data"], [])


class ReportConcurrencyTests(TransactionTestCase):
    def test_external_ai_calls_run_outside_transactions(self):
        test = make_operating_test()
        Review.objects.create(order=add_order(test), content="맛있어요")
        report_builder.start_report(test.pk, additional_fixed_cost=0)
        test.refresh_from_db()

        def analyze(reviews):
            self.assertFalse(connection.in_atomic_block)
            return labels_for(reviews)

        def generate(*args):
            self.assertFalse(connection.in_atomic_block)
            return RESULT

        analyzer = Mock(analyze=Mock(side_effect=analyze))
        generator = Mock(generate=Mock(side_effect=generate))
        with patch("reports.providers.get_review_analyzer", return_value=analyzer), patch(
            "reports.providers.get_improvement_generator", return_value=generator,
        ):
            report_builder.build_ai_sections(test.pk, task_id=test.report_task_id)
        analyzer.analyze.assert_called_once()
        generator.generate.assert_called_once()
        test.refresh_from_db()
        self.assertEqual(test.improvement_status, Improvement.SUCCEEDED)

    def test_simultaneous_requests_register_only_one_task(self):
        for failed_stage in (None, "review", "improvement"):
            with self.subTest(failed_stage=failed_stage):
                test = make_operating_test()
                add_order(test)
                if failed_stage:
                    report_builder.start_report(test.pk, additional_fixed_cost=1200)
                    MenuTest.objects.filter(pk=test.pk).update(
                        review_analysis_status=Analysis.FAILED if failed_stage == "review" else Analysis.SUCCEEDED,
                        improvement_status=Improvement.PENDING if failed_stage == "review" else Improvement.FAILED,
                    )
                test.refresh_from_db()
                old_task_id = test.report_task_id
                queue_count = OrmQ.objects.count()
                barrier = Barrier(2)

                def request():
                    try:
                        barrier.wait(timeout=5)
                        return APIClient().post(reverse("report-detail", kwargs={"test_id": test.pk}),
                                                {"additional_fixed_cost": 100}).status_code
                    finally:
                        connections.close_all()

                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(lambda _: request(), range(2)))
                self.assertEqual(sorted(results), [202, 202])
                self.assertEqual(OrmQ.objects.count(), queue_count + 1)
                test.refresh_from_db()
                self.assertNotEqual(test.report_task_id, old_task_id)
                self.assertEqual(test.additional_fixed_cost, 1200 if failed_stage else 100)
                expected_analysis = {
                    None: Analysis.NOT_REQUIRED,
                    "review": Analysis.PENDING,
                    "improvement": Analysis.SUCCEEDED,
                }
                self.assertEqual(test.review_analysis_status, expected_analysis[failed_stage])
                self.assertEqual(test.improvement_status, Improvement.PENDING)
