import json
from email.utils import formatdate
from types import MappingProxyType
from unittest.mock import Mock, patch

import httpx2
from django.test import SimpleTestCase, override_settings

from core.exceptions import AIServiceError
from reports import ai_client, providers
from reports.serializers import ReviewAnalysisResultSerializer
from reports.services import recommendation, review_analysis


def review_label(review_id, sentiment="POSITIVE", **aspects):
    return {"review_id": review_id, "sentiment": sentiment,
            **{field: aspects.get(field) for field in review_analysis.ASPECT_FIELDS}}


class LocalReviewAnalyzer:
    def analyze(self, reviews):
        return MappingProxyType({
            "reviews": [review_label(row["review_id"], taste_sentiment="POSITIVE") for row in reviews],
            "quotes": [],
        })


class LocalImprovementGenerator:
    def generate(self, quantitative, reviews):
        return {"items": [{"title": "점검", "action": "준비 시간을 확인하세요.",
                           "verification": "다음 테스트와 비교하세요.", "evidence_review_ids": []}]}


class ReportProviderTests(SimpleTestCase):
    @patch("reports.providers.get_review_analyzer", return_value=LocalReviewAnalyzer())
    @patch("reports.providers.get_improvement_generator", return_value=LocalImprovementGenerator())
    @patch("reports.services.recommendation.QuantitativeReportSerializer")
    def test_local_backends_replace_apis_without_changing_validation(self, quantitative_serializer, _generator, _analyzer):
        quantitative_serializer.return_value.data = {}
        with patch("reports.ai_client.httpx2.Client", side_effect=AssertionError("external request")), patch(
            "ai.client.request_json", side_effect=AssertionError("ingredient API must not be used"),
        ):
            result = review_analysis.analyze([{"review_id": 1, "content": "맛있어요"}])
            self.assertEqual(result["reviews"][0]["taste_sentiment"], "POSITIVE")
            self.assertEqual(result["quotes"], [])
            self.assertEqual(len(recommendation.generate({}, [])["items"]), 1)

            class InvalidAnalyzer:
                def analyze(self, reviews):
                    return {"reviews": [review_label(999)], "quotes": []}

            with self.assertRaises(AIServiceError):
                review_analysis.analyze([{"review_id": 1, "content": "맛있어요"}], analyzer=InvalidAnalyzer())

    def test_default_backends_use_report_apis(self):
        self.assertIsInstance(providers.get_review_analyzer(), providers.APIReviewAnalyzer)
        self.assertIsInstance(providers.get_improvement_generator(), providers.APIImprovementGenerator)

    @patch("reports.services.recommendation.QuantitativeReportSerializer")
    def test_services_reject_invalid_raw_results_before_returning_typed_results(self, quantitative_serializer):
        quantitative_serializer.return_value.data = {}
        reviews = [{"review_id": 1, "content": "맛있어요"}]
        for payload in (None, [], "invalid", {}, {"reviews": "invalid", "items": "invalid"}):
            with self.subTest(payload=payload):
                analyzer = Mock(analyze=Mock(return_value=payload))
                generator = Mock(generate=Mock(return_value=payload))
                with self.assertRaises(AIServiceError):
                    review_analysis.analyze(reviews, analyzer=analyzer)
                with self.assertRaises(AIServiceError):
                    recommendation.generate({}, reviews, generator=generator)

    def test_quotes_require_original_text_and_matching_review_and_aspect(self):
        reviews = [{"review_id": 1, "content": "맛있어요. 식어서 왔어요."}]
        labels = [review_label(1, "MIXED", taste_sentiment="POSITIVE", temperature_sentiment="NEGATIVE")]
        quote = {"review_id": 1, "aspect": "taste", "sentiment": "POSITIVE", "quote": "맛있어요."}
        cold = {**quote, "aspect": "temperature", "sentiment": "NEGATIVE", "quote": "식어서 왔어요."}
        invalid = [
            {**quote, "review_id": 99}, {**quote, "sentiment": "NEGATIVE"},
            {**quote, "aspect": "portion"}, {**quote, "aspect": "unknown"},
            {**quote, "quote": "정말 맛있어요."}, {**quote, "quote": "맛있어요. 왔어요."},
            {**quote, "quote": ""}, {**quote, "quote": " "}, {**quote, "quote": "맛" * 161},
            None, "invalid", {}, [],
        ]
        with patch("reports.ai_client.request_json", return_value={"reviews": labels, "quotes": [quote, cold, *invalid]}) as ai:
            result = review_analysis.analyze(reviews)
        ai.assert_called_once()
        self.assertEqual(result, {"reviews": labels, "quotes": [quote, cold]})

    def test_missing_or_malformed_quotes_do_not_discard_valid_classification(self):
        labels = [review_label(1, taste_sentiment="POSITIVE")]
        for extra in ({}, {"quotes": None}, {"quotes": "invalid"}, {"quotes": {}}):
            with self.subTest(extra=extra), patch("reports.ai_client.request_json", return_value={"reviews": labels, **extra}):
                result = review_analysis.analyze([{"review_id": 1, "content": "맛있어요"}])
            self.assertEqual(result, {"reviews": labels, "quotes": []})

    def test_quotes_limit_each_group_to_two_distinct_reviews_and_texts(self):
        reviews = [{"review_id": i, "content": text} for i, text in enumerate(
            ("맛있어요. 양도 좋아요.", "맛있어요.", "간이 좋아요.", "고소해요."), start=1,
        )]
        labels = [review_label(row["review_id"], taste_sentiment="POSITIVE", portion_sentiment="POSITIVE")
                  for row in reviews]
        quotes = [{"review_id": i, "aspect": "taste", "sentiment": "POSITIVE", "quote": text}
                  for i, text in ((1, "맛있어요."), (1, "맛있어요"), (2, "맛있어요."), (3, "간이 좋아요."), (4, "고소해요."))]
        portion = {"review_id": 1, "aspect": "portion", "sentiment": "POSITIVE", "quote": "양도 좋아요."}
        with patch("reports.ai_client.request_json", return_value={"reviews": labels, "quotes": [*quotes, portion]}):
            result = review_analysis.analyze(reviews)
        self.assertEqual(result["quotes"], [quotes[0], quotes[3], portion])

    def test_cards_use_top_two_nonzero_counts_and_mixed_is_only_grouped_in_overall_summary(self):
        reviews = [
            review_label(1, "MIXED", taste_sentiment="POSITIVE", portion_sentiment="POSITIVE", temperature_sentiment="NEGATIVE"),
            review_label(2, "MIXED", taste_sentiment="POSITIVE", portion_sentiment="POSITIVE", packaging_sentiment="NEGATIVE"),
            review_label(3, "POSITIVE", temperature_sentiment="POSITIVE", packaging_sentiment="POSITIVE"),
            review_label(4, "NEGATIVE", temperature_sentiment="NEGATIVE", portion_sentiment="NEGATIVE"),
        ]
        quotes = [{"review_id": 1, "aspect": "taste", "sentiment": "POSITIVE", "quote": "맛있어요."}]
        data = ReviewAnalysisResultSerializer(review_analysis.summarize(reviews, quotes)).data
        self.assertEqual([(item["sentiment"], item["count"], item["review_percentage"]) for item in data["sentiments"]],
                         [("POSITIVE", 1, 25), ("IMPROVEMENT_REQUIRED", 3, 75)])
        self.assertEqual([(item["aspect"], item["review_count"], item["review_percentage"]) for item in data["strengths"]],
                         [("taste", 2, 50), ("portion", 2, 50)])
        self.assertEqual([(item["aspect"], item["review_percentage"]) for item in data["improvement_candidates"]],
                         [("temperature", 50), ("portion", 25)])
        self.assertEqual(data["strengths"][0]["quotes"], [{"review_id": 1, "quote": "맛있어요."}])
        self.assertEqual(data["strengths"][1]["quotes"], [])
        one = review_analysis.summarize([review_label(1, taste_sentiment="POSITIVE")], [])
        self.assertEqual(len(one["strengths"]), 1)
        self.assertEqual(one["improvement_candidates"], [])
        empty = ReviewAnalysisResultSerializer(review_analysis.summarize([], [])).data
        self.assertEqual(empty["strengths"], [])
        self.assertEqual(empty["improvement_candidates"], [])
        self.assertIsNone(empty["sentiments"][0]["review_percentage"])

    def test_labels_require_every_requested_id_once_and_valid_values(self):
        valid = {"review_id": 1, "sentiment": "POSITIVE", "taste_sentiment": "POSITIVE",
                 "portion_sentiment": None, "temperature_sentiment": None, "packaging_sentiment": None}
        for labels in ([], [valid, valid], [{**valid, "review_id": 2}], [{**valid, "sentiment": "UNKNOWN"}]):
            with self.subTest(labels=labels), patch("reports.ai_client.request_json", return_value={"reviews": labels}):
                with self.assertRaises(AIServiceError):
                    review_analysis.analyze([{"review_id": 1, "content": "맛있다"}])

    @patch("reports.services.recommendation.QuantitativeReportSerializer")
    def test_improvements_cannot_cite_missing_or_duplicate_reviews(self, quantitative_serializer):
        quantitative_serializer.return_value.data = {}
        item = {"title": "확인", "action": "준비 시간 확인", "verification": "다음 주문과 비교"}
        for ids in ([99], [1, 1]):
            generator = Mock(generate=Mock(return_value={"items": [{**item, "evidence_review_ids": ids}]}))
            with self.subTest(ids=ids), self.assertRaises(AIServiceError):
                recommendation.generate({}, [{"review_id": 1}], generator=generator)
        generator = Mock(generate=Mock(return_value={"items": [{**item, "evidence_review_ids": []}]}))
        self.assertEqual(len(recommendation.generate({}, [], generator=generator)["items"]), 1)


def provider_response(provider, text='{"ok": true}'):
    if provider == "anthropic":
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": text}]}
    if provider == "openai":
        return {"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": text},
        ]}]}
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}]}


def mock_http(handler):
    client = httpx2.Client(transport=httpx2.MockTransport(handler), timeout=1)
    return patch("reports.ai_client.httpx2.Client", return_value=client)


@override_settings(
    REPORT_REVIEW_PROVIDER="anthropic", REPORT_REVIEW_MODEL="review-model", REPORT_REVIEW_API_KEY="review-key",
    REPORT_IMPROVEMENT_PROVIDER="gemini", REPORT_IMPROVEMENT_MODEL="improvement-model",
    REPORT_IMPROVEMENT_API_KEY="improvement-key", REPORT_AI_TIMEOUT_SECONDS=1,
    AI_API_KEY="ingredient-key", AI_MODEL="ingredient-model",
)
class ReportAPIClientTests(SimpleTestCase):
    def test_server_retry_delay_is_respected_for_headers_and_gemini_details(self):
        retry_info = {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "36.1s"}
        cases = (
            ("anthropic", {"retry-after": "20"}, {}, 20, 20),
            ("openai", {"retry-after-ms": "20000"}, {}, 20, 20),
            ("openai", {"retry-after-ms": "20000.5"}, {}, 21, 21),
            ("openai", {"retry-after-ms": "0"}, {}, 0, 1),
            ("openai", {"retry-after-ms": "20000", "retry-after": "30"}, {}, 30, 30),
            ("openai", {"retry-after-ms": "20000", "retry-after": "10"}, {}, 20, 20),
            ("openai", {"retry-after-ms": "invalid", "retry-after": "20"}, {}, 20, 20),
            ("openai", {"retry-after": formatdate(1700000020, usegmt=True)}, {}, 20, 20),
            ("anthropic", {"retry-after": formatdate(1699999990, usegmt=True)}, {}, 0, 1),
            ("gemini", {}, {"error": {"details": [retry_info]}}, 37, 37),
            ("gemini", {"retry-after": "40"}, {"error": {"details": [retry_info]}}, 40, 40),
        )
        for provider, headers, body, server_delay, delay in cases:
            requests = []
            def handle(request):
                requests.append(request)
                if len(requests) == 1:
                    return httpx2.Response(429, headers=headers, json=body)
                return httpx2.Response(200, json=provider_response(provider))
            with self.subTest(provider=provider, headers=headers), override_settings(REPORT_REVIEW_PROVIDER=provider), mock_http(handle), patch(
                "reports.ai_client.time.time", return_value=1700000000,
            ), patch("reports.ai_client.time.sleep") as sleep, self.assertLogs("reports.ai_client", level="WARNING") as logs:
                self.assertEqual(ai_client.request_json("REVIEW", "JSON", "input", max_tokens=100), {"ok": True})
            self.assertEqual(len(requests), 2)
            sleep.assert_called_once_with(delay)
            self.assertIn(f"server_retry_seconds={server_delay}", logs.output[0])
            self.assertIn(f"retry_in_seconds={delay}", logs.output[0])
            self.assertIn("event=retry", logs.output[0])

    def test_invalid_retry_hints_fall_back_to_existing_backoff(self):
        for header, body in (
            ("invalid-date", {}), ("-20", []), ("NaN", {"error": None}),
            ("", {"error": {"details": {}}}),
            ("", {"error": {"details": [None, {"@type": "other", "retryDelay": "36s"}]}}),
            ("", {"error": {"details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "Infinitys"}]}}),
        ):
            responses = iter([httpx2.Response(429, headers={"retry-after": header}, json=body),
                              httpx2.Response(200, json=provider_response("gemini"))])
            with self.subTest(header=header, body=body), override_settings(REPORT_REVIEW_PROVIDER="gemini"), mock_http(
                lambda request: next(responses),
            ), patch("reports.ai_client.time.sleep") as sleep, self.assertLogs("reports.ai_client", level="WARNING") as logs:
                self.assertEqual(ai_client.request_json("REVIEW", "JSON", "input", max_tokens=100), {"ok": True})
            sleep.assert_called_once_with(1)
            self.assertIn("server_retry_seconds=-", logs.output[0])

    def test_invalid_millisecond_retry_hints_fall_back_to_existing_backoff(self):
        for value in ("invalid", "-20", "NaN", "Infinity"):
            responses = iter([
                httpx2.Response(429, headers={"retry-after-ms": value}, json={}),
                httpx2.Response(200, json=provider_response("openai")),
            ])
            with self.subTest(value=value), override_settings(REPORT_REVIEW_PROVIDER="openai"), mock_http(
                lambda request: next(responses),
            ), patch("reports.ai_client.time.sleep") as sleep, self.assertLogs("reports.ai_client"):
                self.assertEqual(ai_client.request_json("REVIEW", "JSON", "input", max_tokens=100), {"ok": True})
            sleep.assert_called_once_with(1)

    def test_millisecond_retry_delay_exceeding_budget_does_not_sleep_or_retry(self):
        requests = []
        def handle(request):
            requests.append(request)
            return httpx2.Response(429, headers={"retry-after-ms": "400000"}, json={})
        with override_settings(REPORT_REVIEW_PROVIDER="openai", Q_CLUSTER={"timeout": 300}), mock_http(handle), patch(
            "reports.ai_client.time.monotonic", return_value=0,
        ), patch("reports.ai_client.time.sleep") as sleep, self.assertLogs("reports.ai_client") as logs:
            with self.assertRaises(AIServiceError):
                ai_client.request_json("REVIEW", "JSON", "input", max_tokens=100)
        self.assertEqual(len(requests), 1)
        sleep.assert_not_called()
        self.assertIn("server_retry_seconds=400", logs.output[0])
        self.assertIn("retry_stop=time_budget", logs.output[0])

    def test_retry_budget_is_shared_between_stages_and_logs_report_identity(self):
        clock = [0]
        token = ai_client.report_task_context.set({"test_id": 17, "task_id": "task-17", "deadline": 100})
        try:
            def review_response(request):
                clock[0] = 80
                return httpx2.Response(200, json=provider_response("anthropic"))
            requests = []
            def improvement_response(request):
                requests.append(request)
                return httpx2.Response(429, headers={"retry-after": "20"}, json={})
            with patch("reports.ai_client.time.monotonic", side_effect=lambda: clock[0]):
                with mock_http(review_response):
                    self.assertEqual(ai_client.request_json("REVIEW", "JSON", "input", max_tokens=100), {"ok": True})
                with mock_http(improvement_response), patch("reports.ai_client.time.sleep") as sleep:
                    with self.assertLogs("reports.ai_client", level="WARNING") as logs, self.assertRaises(AIServiceError):
                        ai_client.request_json("IMPROVEMENT", "JSON", "input", max_tokens=100)
            sleep.assert_not_called()
            self.assertEqual(len(requests), 1)
            for value in ("test_id=17", "task_id=task-17", "event=failed", "retry_stop=time_budget",
                          "server_retry_seconds=20", "retry_in_seconds=-", "timestamp="):
                self.assertIn(value, logs.output[0])
        finally:
            ai_client.report_task_context.reset(token)

    def test_expired_budget_does_not_send_a_request(self):
        token = ai_client.report_task_context.set({"test_id": 17, "task_id": "task-17", "deadline": 5})
        try:
            with patch("reports.ai_client.time.monotonic", return_value=0), mock_http(
                lambda request: self.fail("must not send request"),
            ), self.assertLogs("reports.ai_client", level="WARNING") as logs, self.assertRaises(AIServiceError):
                ai_client.request_json("REVIEW", "JSON", "input", max_tokens=100)
            self.assertIn("reason=time_budget_exhausted", logs.output[0])
        finally:
            ai_client.report_task_context.reset(token)

    def test_all_providers_send_report_credentials_and_parse_json(self):
        for provider, host in (
            ("anthropic", "api.anthropic.com"), ("openai", "api.openai.com"),
            ("gemini", "generativelanguage.googleapis.com"),
        ):
            requests = []
            def handle(request):
                requests.append(request)
                return httpx2.Response(200, json=provider_response(provider))
            with self.subTest(provider=provider), override_settings(REPORT_REVIEW_PROVIDER=provider), mock_http(handle), patch(
                "ai.client.request_json", side_effect=AssertionError("ingredient API must not be used"),
            ):
                self.assertEqual(ai_client.request_json("REVIEW", "JSON system", "input", max_tokens=123), {"ok": True})
            self.assertEqual(len(requests), 1)
            request = requests[0]
            self.assertEqual(request.url.host, host)
            self.assertNotIn("ingredient-key", str(request.headers))
            self.assertNotIn("ingredient-model", request.content.decode())
            body = json.loads(request.content)
            if provider == "anthropic":
                self.assertEqual(request.headers["x-api-key"], "review-key")
                self.assertEqual((body["model"], body["system"], body["max_tokens"]), ("review-model", "JSON system", 123))
            elif provider == "openai":
                self.assertEqual(request.headers["Authorization"], "Bearer review-key")
                self.assertEqual((body["model"], body["instructions"], body["max_output_tokens"]), ("review-model", "JSON system", 123))
                self.assertFalse(body["store"])
            else:
                self.assertEqual(request.headers["x-goog-api-key"], "review-key")
                self.assertIn("/review-model:generateContent", request.url.path)
                self.assertEqual(body["systemInstruction"]["parts"], [{"text": "JSON system"}])
                self.assertEqual(body["generationConfig"]["maxOutputTokens"], 123)

    def test_review_and_improvement_choose_independent_provider_model_and_key(self):
        requests = []
        def handle(request):
            requests.append(request)
            provider = "openai" if request.url.host == "api.openai.com" else "gemini"
            return httpx2.Response(200, json=provider_response(provider))
        with override_settings(REPORT_REVIEW_PROVIDER="openai"), mock_http(handle):
            ai_client.request_json("REVIEW", "JSON", "reviews", max_tokens=100)
        with mock_http(handle):
            ai_client.request_json("IMPROVEMENT", "JSON", "report", max_tokens=100)
        self.assertEqual(json.loads(requests[0].content)["model"], "review-model")
        self.assertEqual(requests[0].headers["Authorization"], "Bearer review-key")
        self.assertIn("/improvement-model:generateContent", requests[1].url.path)
        self.assertEqual(requests[1].headers["x-goog-api-key"], "improvement-key")

    def test_missing_or_unknown_report_configuration_does_not_fall_back_to_ingredient_api(self):
        for config in (
            {"REPORT_REVIEW_API_KEY": ""}, {"REPORT_REVIEW_MODEL": ""},
            {"REPORT_REVIEW_PROVIDER": "unknown"}, {"REPORT_AI_TIMEOUT_SECONDS": 0},
        ):
            with self.subTest(config=config), override_settings(**config), patch("reports.ai_client.httpx2.Client") as client:
                with self.assertRaises(AIServiceError):
                    ai_client.request_json("REVIEW", "JSON", "input", max_tokens=100)
                client.assert_not_called()

    def test_transient_status_retries_three_times_and_permanent_errors_once(self):
        for status, expected in ((408, 3), (429, 3), (500, 3), (503, 3), (400, 1), (401, 1), (403, 1), (404, 1)):
            requests = []
            def handle(request):
                requests.append(request)
                return httpx2.Response(status, json={"message": "secret response must not be logged"})
            with self.subTest(status=status), mock_http(handle), patch("reports.ai_client.time.sleep") as sleep:
                with self.assertLogs("reports.ai_client", level="WARNING") as logs, self.assertRaises(AIServiceError):
                    ai_client.request_json("REVIEW", "JSON", "input", max_tokens=100)
            self.assertEqual(len(requests), expected)
            self.assertEqual(sleep.call_count, expected - 1)
            self.assertEqual(len(logs.output), expected)
            for attempt, log in enumerate(logs.output, start=1):
                self.assertIn(f"attempt={attempt}", log)
                delay = 2 ** (attempt - 1) if attempt < expected else "-"
                self.assertIn(f"retry_in_seconds={delay}", log)
                self.assertIn("event=retry" if attempt < expected else "event=failed", log)
            self.assertNotIn("secret response", " ".join(logs.output))

    def test_network_failure_is_bounded_and_transient_failure_can_recover(self):
        for recover in (True, False):
            requests = []
            def handle(request):
                requests.append(request)
                if recover and len(requests) == 3:
                    return httpx2.Response(200, json=provider_response("anthropic"))
                raise httpx2.ReadTimeout("simulated timeout", request=request)
            with self.subTest(recover=recover), mock_http(handle), patch("reports.ai_client.time.sleep"), self.assertLogs(
                "reports.ai_client", level="WARNING",
            ) as logs:
                if recover:
                    self.assertEqual(ai_client.request_json("REVIEW", "JSON", "input", max_tokens=100), {"ok": True})
                else:
                    with self.assertRaises(AIServiceError):
                        ai_client.request_json("REVIEW", "JSON", "input", max_tokens=100)
            self.assertEqual(len(requests), 3)
            self.assertEqual(len(logs.output), 2 if recover else 3)
            self.assertIn("reason=ReadTimeout", logs.output[0])
            self.assertIn("retry_in_seconds=1", logs.output[0])
            self.assertIn("retry_in_seconds=2", logs.output[1])
            self.assertNotIn("simulated timeout", " ".join(logs.output))

    def test_gemini_rate_limit_retries_are_logged_even_when_last_attempt_succeeds(self):
        requests = []
        def handle(request):
            requests.append(request)
            if len(requests) == 3:
                return httpx2.Response(200, json=provider_response("gemini"))
            return httpx2.Response(429, json={"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}})
        with override_settings(REPORT_REVIEW_PROVIDER="gemini"), mock_http(handle), patch(
            "reports.ai_client.time.sleep",
        ) as sleep, self.assertLogs("reports.ai_client", level="WARNING") as logs:
            self.assertEqual(ai_client.request_json("REVIEW", "JSON", "input", max_tokens=100), {"ok": True})
        self.assertEqual(len(requests), 3)
        self.assertEqual(len(logs.output), 2)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])
        for attempt, log in enumerate(logs.output, start=1):
            self.assertIn(f"attempt={attempt}", log)
            self.assertIn("error_code=RESOURCE_EXHAUSTED", log)

    def test_http_failure_logs_identifiers_without_messages_or_credentials(self):
        for provider, error, expected_code, expected_param in (
            ("anthropic", {"type": "invalid_request_error"}, "invalid_request_error", "-"),
            ("openai", {"code": "unsupported_parameter", "type": "invalid_request_error", "param": "tools[0].type"},
             "unsupported_parameter", "tools[0].type"),
            ("openai", {"code": "invalid_value", "param": "private-param\nprivate-text"}, "invalid_value", "-"),
            ("gemini", {"code": 400, "status": "INVALID_ARGUMENT"}, "INVALID_ARGUMENT", "-"),
        ):
            def handle(request):
                return httpx2.Response(400, headers={"request-id": "req-test-123", "x-private": "private-header"}, json={
                    "error": {**error, "message": "private-message review-key"}, "content": "private-review",
                })
            with self.subTest(provider=provider), override_settings(REPORT_REVIEW_PROVIDER=provider), mock_http(handle):
                with self.assertLogs("reports.ai_client", level="WARNING") as logs, self.assertRaises(AIServiceError):
                    ai_client.request_json("REVIEW", "private-system", "private-user", max_tokens=100)
            log = logs.output[0]
            for value in ("stage=REVIEW", f"provider={provider}", "model=review-model", "http_status=400",
                          "request_id=req-test-123", f"error_code={expected_code}", f"param={expected_param}"):
                self.assertIn(value, log)
            for value in ("private-", "review-key", "ingredient-key"):
                self.assertNotIn(value, log)

    def test_response_failure_logs_distinguish_limits_refusal_and_json_errors(self):
        cases = (
            ("anthropic", {**provider_response("anthropic"), "stop_reason": "max_tokens"},
             "incomplete_response", "finish_reason=max_tokens"),
            ("openai", {**provider_response("openai"), "status": "incomplete",
                        "incomplete_details": {"reason": "max_output_tokens"}},
             "incomplete_response", "finish_reason=max_output_tokens"),
            ("openai", {"status": "completed", "output": [{"type": "message", "content": [
                {"type": "refusal", "refusal": "private-refusal"}]}]}, "refusal", "response_status=completed"),
            ("gemini", {"candidates": [{"finishReason": "SAFETY"}]},
             "incomplete_response", "finish_reason=SAFETY"),
            ("gemini", {"promptFeedback": {"blockReason": "SAFETY", "blockReasonMessage": "private-message"}},
             "prompt_blocked", "block_reason=SAFETY"),
            ("gemini", {"candidates": [], "promptFeedback": {"blockReason": "BLOCKLIST"}},
             "prompt_blocked", "block_reason=BLOCKLIST"),
            ("anthropic", provider_response("anthropic", "private-invalid-json"), "generated_json", "finish_reason=end_turn"),
            ("anthropic", provider_response("anthropic", "[]"), "expected_object", "finish_reason=end_turn"),
            ("anthropic", [], "response_structure", "finish_reason=-"),
            ("anthropic", None, "response_json", "finish_reason=-"),
        )
        for provider, body, reason, metadata in cases:
            requests = []
            def handle(request):
                requests.append(request)
                return httpx2.Response(200, json=body) if body is not None else httpx2.Response(200, text="private-html")
            with self.subTest(provider=provider, reason=reason), override_settings(REPORT_REVIEW_PROVIDER=provider), mock_http(handle):
                with self.assertLogs("reports.ai_client", level="WARNING") as logs, self.assertRaises(AIServiceError) as raised:
                    ai_client.request_json("REVIEW", "private-system", "private-user", max_tokens=100)
            self.assertIn(f"reason={reason}", logs.output[0])
            self.assertEqual(len(requests), 1)
            self.assertIn(metadata, logs.output[0])
            self.assertNotIn("private-", logs.output[0])
            self.assertEqual(str(raised.exception), "리포트 AI 응답 형식이 올바르지 않습니다.")

    def test_rejected_truncated_or_malformed_responses_do_not_retry(self):
        cases = [
            ("anthropic", {**provider_response("anthropic"), "stop_reason": "max_tokens"}),
            ("anthropic", {**provider_response("anthropic"), "stop_reason": "refusal"}),
            ("openai", {**provider_response("openai"), "status": "incomplete"}),
            ("openai", {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal"}]}]}),
            ("gemini", {"candidates": []}),
            ("gemini", {"candidates": [{"finishReason": "SAFETY"}]}),
        ]
        for provider in ("anthropic", "openai", "gemini"):
            cases.extend((provider, body) for body in ({}, [], provider_response(provider, "not json"), provider_response(provider, "[]")))
        for provider, body in cases:
            requests = []
            def handle(request):
                requests.append(request)
                return httpx2.Response(200, json=body)
            with self.subTest(provider=provider, body=body), override_settings(REPORT_REVIEW_PROVIDER=provider), mock_http(handle):
                with self.assertLogs("reports.ai_client", level="WARNING"), self.assertRaises(AIServiceError):
                    ai_client.request_json("REVIEW", "JSON", "input", max_tokens=100)
            self.assertEqual(len(requests), 1)
