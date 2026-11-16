from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from time import monotonic, sleep

from django.db import connection, connections, transaction
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from menu_tests.models import MenuTest
from menu_tests.tests.helpers import make_test, url
from orders.models import Order, Review
from orders.services.import_service import import_sample


class OrderImportConcurrencyTests(TransactionTestCase):
    """별도 PostgreSQL 연결이 실제 행 잠금을 기다리는 것을 확인한다."""

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL 행 잠금 검증")
        self.test = make_test(total_ingredient_cost=4500)
        self.pids = Queue()
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.addCleanup(self.pool.shutdown, wait=True)

    def request_in_thread(self, action):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '10s'")
                cursor.execute("SELECT pg_backend_pid()")
                self.pids.put(cursor.fetchone()[0])
            client = APIClient()
            if action == "delete":
                return client.delete(url("test-detail", self.test.pk))
            return client.post(url("order-import-sample", self.test.pk))
        finally:
            connections.close_all()

    def wait_for_lock(self):
        pid = self.pids.get(timeout=5)
        deadline = monotonic() + 5
        while monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_stat_clear_snapshot()")
                cursor.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", [pid])
                row = cursor.fetchone()
            if row and row[0] == "Lock":
                return
            sleep(0.02)
        self.fail("다른 DB 연결이 행 잠금을 기다리지 않았습니다.")

    def test_concurrent_import_creates_only_one_package(self):
        with transaction.atomic():
            MenuTest.objects.select_for_update().get(pk=self.test.pk)
            future = self.pool.submit(self.request_in_thread, "import")
            self.wait_for_lock()
            import_sample(self.test.pk)
        res = future.result(timeout=10)
        self.assertEqual(res.status_code, 409, res.content)
        self.assertEqual(res.json()["error"]["code"], "already_imported")
        self.assertEqual((Order.objects.count(), Review.objects.count()), (60, 48))

    def test_delete_commits_before_import(self):
        with transaction.atomic():
            locked = MenuTest.objects.select_for_update().get(pk=self.test.pk)
            future = self.pool.submit(self.request_in_thread, "import")
            self.wait_for_lock()
            locked.delete()
        res = future.result(timeout=10)
        self.assertEqual(res.status_code, 404, res.content)
        self.assertEqual((Order.objects.count(), Review.objects.count()), (0, 0))

    def test_import_reads_price_after_waiting_for_update(self):
        with transaction.atomic():
            locked = MenuTest.objects.select_for_update().get(pk=self.test.pk)
            future = self.pool.submit(self.request_in_thread, "import")
            self.wait_for_lock()
            locked.selling_price = 17000
            locked.save(update_fields=["selling_price", "updated_at"])
        res = future.result(timeout=10)
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(set(Order.objects.values_list("sales_amount", flat=True)), {17000})

    def test_import_commits_before_delete(self):
        with transaction.atomic():
            MenuTest.objects.select_for_update().get(pk=self.test.pk)
            future = self.pool.submit(self.request_in_thread, "delete")
            self.wait_for_lock()
            import_sample(self.test.pk)
        res = future.result(timeout=10)
        self.assertEqual(res.status_code, 409, res.content)
        self.assertEqual(res.json()["error"]["code"], "not_draft")
        self.assertEqual((Order.objects.count(), Review.objects.count()), (60, 48))
