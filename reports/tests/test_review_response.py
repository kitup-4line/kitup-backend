import json
from copy import deepcopy
from unittest.mock import patch

import httpx2
from django.test import SimpleTestCase, override_settings

from ai.prompts import review_analysis as review_prompt
from core.exceptions import AIServiceError
from reports import ai_client
from reports.services import review_analysis
from reports.tests.test_ai import mock_http, provider_response


@override_settings(
    REPORT_REVIEW_PROVIDER="anthropic", REPORT_REVIEW_MODEL="claude-sonnet-5-5",
    REPORT_REVIEW_API_KEY="review-key", REPORT_AI_TIMEOUT_SECONDS=1,
    REPORT_IMPROVEMENT_PROVIDER="anthropic", REPORT_IMPROVEMENT_MODEL="claude-sonnet-5-5",
    REPORT_IMPROVEMENT_API_KEY="improvement-key",
)
class CompactReviewResponseTests(SimpleTestCase):
    def setUp(self):
        self.reviews = [{"review_id": 1, "content": "맛있지만 식어서 왔어요."}]
        self.payload = {
            "reviews": [{"i": 1, "s": "M", "t": "P", "q": None, "h": "N", "p": None}],
            "quotes": [
                {"i": 1, "a": "t", "s": "P", "x": "맛있지만"},
                {"i": 1, "a": "h", "s": "N", "x": "식어서 왔어요."},
            ],
        }

    def analyze(self, payload):
        with patch("reports.ai_client.request_json", return_value=payload):
            return review_analysis.analyze(self.reviews)

    def test_normal_entry_point_decodes_response_and_keeps_existing_validation(self):
        requests = []

        def handle(request):
            requests.append(request)
            return httpx2.Response(200, json=provider_response("anthropic", json.dumps(self.payload)))

        with mock_http(handle):
            result = review_analysis.analyze(self.reviews)
        self.assertEqual(result["reviews"], [{
            "review_id": 1, "sentiment": "MIXED", "taste_sentiment": "POSITIVE",
            "portion_sentiment": None, "temperature_sentiment": "NEGATIVE",
            "packaging_sentiment": None,
        }])
        self.assertEqual(result["quotes"], [
            {"review_id": 1, "aspect": "taste", "sentiment": "POSITIVE", "quote": "맛있지만"},
            {"review_id": 1, "aspect": "temperature", "sentiment": "NEGATIVE", "quote": "식어서 왔어요."},
        ])
        body = json.loads(requests[0].content)
        self.assertEqual(body["output_config"], {"effort": "medium"})
        self.assertEqual(body["system"], review_prompt.COMPACT_SYSTEM_PROMPT)
        self.assertEqual(json.loads(body["messages"][0]["content"]), self.reviews)

    def test_invalid_review_shapes_and_codes_are_rejected(self):
        invalid_rows = [
            {"i": True, "s": "P", "t": None, "q": None, "h": None, "p": None},
            {"i": 1, "s": "P", "t": "M", "q": None, "h": None, "p": None},
            {"i": 1, "s": None, "t": None, "q": None, "h": None, "p": None},
            {"i": 1, "s": "P"},
            {**self.payload["reviews"][0], "unknown": None},
            None,
        ]
        for row in invalid_rows:
            with self.subTest(row=row), self.assertRaises(AIServiceError):
                self.analyze({"reviews": [row], "quotes": []})
        for payload in (None, [], {}, {"reviews": {}, "quotes": []}):
            with self.subTest(payload=payload), self.assertRaises(AIServiceError):
                self.analyze(payload)

    def test_missing_duplicate_and_foreign_review_ids_are_rejected(self):
        row = self.payload["reviews"][0]
        for rows in ([], [row, row], [{**row, "i": 999}]):
            with self.subTest(rows=rows), self.assertRaises(AIServiceError):
                self.analyze({"reviews": rows, "quotes": []})

    def test_malformed_quotes_do_not_discard_valid_classifications(self):
        payload = deepcopy(self.payload)
        payload["quotes"] += [
            None,
            {"i": True, "a": "t", "s": "P", "x": "맛있지만"},
            {"i": 1, "a": "bad", "s": "P", "x": "맛있지만"},
            {"i": 1, "a": "t", "s": "M", "x": "맛있지만"},
            {"i": 1, "a": "t", "s": "P", "x": []},
            {"i": 1, "a": "t", "s": "P", "x": "없는 인용"},
            {"i": 999, "a": "t", "s": "P", "x": "맛있지만"},
            {"i": 1, "a": "h", "s": "P", "x": "식어서 왔어요."},
            payload["quotes"][0],
        ]
        result = self.analyze(payload)
        self.assertEqual(len(result["reviews"]), 1)
        self.assertEqual(len(result["quotes"]), 2)
        payload["quotes"] = None
        self.assertEqual(self.analyze(payload)["quotes"], [])

    def test_other_models_keep_original_response_contract(self):
        expected = {
            "reviews": [{
                "review_id": 1, "sentiment": "MIXED", "taste_sentiment": "POSITIVE",
                "portion_sentiment": None, "temperature_sentiment": "NEGATIVE",
                "packaging_sentiment": None,
            }],
            "quotes": [],
        }
        for provider, model in (("anthropic", "claude-opus-5-5"), ("openai", "model"), ("gemini", "model")):
            with self.subTest(provider=provider), override_settings(
                REPORT_REVIEW_PROVIDER=provider, REPORT_REVIEW_MODEL=model,
            ), patch("reports.ai_client.request_json", return_value=expected) as request:
                self.assertEqual(review_analysis.analyze(self.reviews), expected)
                self.assertEqual(request.call_args.args[1], review_prompt.SYSTEM_PROMPT)

    def test_effort_does_not_apply_to_improvements_or_other_providers_and_models(self):
        for stage, provider, model in (
            ("IMPROVEMENT", "anthropic", "claude-sonnet-5-5"),
            ("REVIEW", "anthropic", "claude-opus-5-5"),
            ("REVIEW", "openai", "claude-sonnet-5-5"),
            ("REVIEW", "gemini", "claude-sonnet-5-5"),
        ):
            requests = []

            def handle(request):
                requests.append(request)
                return httpx2.Response(200, json=provider_response(provider))

            with self.subTest(stage=stage, provider=provider), override_settings(**{
                f"REPORT_{stage}_PROVIDER": provider, f"REPORT_{stage}_MODEL": model,
            }), mock_http(handle):
                ai_client.request_json(stage, "system", "input", max_tokens=100)
            body = json.loads(requests[0].content)
            self.assertNotIn("output_config", body)
