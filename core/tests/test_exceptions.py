from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import SimpleTestCase
from rest_framework.exceptions import Throttled, ValidationError

from core.exceptions import AlreadyImportedError, custom_exception_handler


class ExceptionHandlerTests(SimpleTestCase):
    def test_django_and_application_errors_keep_specific_codes(self):
        for exc, status, code in (
            (Http404("대상이 없습니다."), 404, "not_found"),
            (PermissionDenied("권한이 없습니다."), 403, "permission_denied"),
            (AlreadyImportedError(), 409, "already_imported"),
        ):
            with self.subTest(exception=type(exc).__name__):
                response = custom_exception_handler(exc, {})
                self.assertEqual(response.status_code, status)
                self.assertFalse(response.data["success"])
                self.assertEqual(response.data["error"]["code"], code)
                self.assertTrue(response.data["error"]["message"])

    def test_nested_validation_errors_skip_empty_rows(self):
        response = custom_exception_handler(
            ValidationError({"ingredients": [{}, {"quantity": ["1 이상이어야 합니다."]}]}), {},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "invalid")
        self.assertEqual(response.data["error"]["message"], "1 이상이어야 합니다.")
        self.assertEqual(len(response.data["error"]["detail"]["ingredients"]), 2)

    def test_throttling_keeps_retry_after_header(self):
        response = custom_exception_handler(Throttled(wait=5), {})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "5")
        self.assertEqual(response.data["error"]["code"], "throttled")

    def test_unexpected_error_is_logged_and_hidden_from_response(self):
        with patch("core.exceptions.set_rollback") as rollback, self.assertLogs("core.exceptions", level="ERROR"):
            response = custom_exception_handler(RuntimeError("private connection details"), {})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data["error"]["code"], "server_error")
        self.assertIsNone(response.data["error"]["detail"])
        self.assertNotIn("private connection details", str(response.data))
        rollback.assert_called_once()
