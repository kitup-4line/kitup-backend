import json
from copy import deepcopy

from django.test import SimpleTestCase

from orders.serializers import SamplePackageSerializer
from orders.services.import_service import SAMPLE_PATH, load_sample_package


class SampleMetadataTests(SimpleTestCase):
    def test_loader_retains_kitchen_name_and_period(self):
        raw = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        package = load_sample_package()
        self.assertEqual(package["kitchen_name"], raw["kitchen_name"])
        self.assertEqual(package["period"]["start_date"].isoformat(), raw["period"]["start_date"])
        self.assertEqual(package["period"]["end_date"].isoformat(), raw["period"]["end_date"])
        self.assertEqual(package["period"]["operating_days"], raw["period"]["operating_days"])

    def test_invalid_metadata_is_rejected(self):
        raw = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        edits = (
            lambda p: p.pop("kitchen_name"),
            lambda p: p.update(kitchen_name="  "),
            lambda p: p.pop("period"),
            lambda p: p["period"].update(start_date="not-a-date"),
            lambda p: p["period"].update(operating_days=0),
            lambda p: p["period"].update(operating_days=13),
            lambda p: p["period"].update(operating_days=15, end_date="2026-11-11"),
            lambda p: p["period"].update(end_date="2020-01-01"),
            lambda p: p["orders"][0].update(created_at="2000-01-01T12:00:00+09:00"),
        )
        for edit in edits:
            package = deepcopy(raw)
            edit(package)
            with self.subTest(package=package.get("period")):
                self.assertFalse(SamplePackageSerializer(data=package).is_valid())
