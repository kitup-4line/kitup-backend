"""선별한 실제 리뷰와 가상 주문을 결합. 외부 API 호출이나 DB 저장은 하지 않는다."""

import argparse
import collections
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random


FIXTURES = Path(__file__).resolve().parents[1] / "orders" / "fixtures"
SELECTION_PATH = Path(__file__).with_name("sample_selection.json")
KST = timezone(timedelta(hours=9))
START = date(2026, 10, 28)


def load_source(path, expected_sha256):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise ValueError("원본 CSV 해시가 다릅니다. 데이터 버전을 확인하세요.")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return dict(enumerate(csv.DictReader(stream), start=2))


def make_package(source, selection):
    rng = random.Random(297729)
    selected = [record for group in selection["groups"].values() for record in group]
    rng.shuffle(selected)

    # 12시/18시 각각21건, 나머지3시간대 각각6건. 날짜도 가상이다.
    times = []
    for hour, count in ((11, 6), (12, 21), (15, 6), (18, 21), (19, 6)):
        for index in range(count):
            day = (index * 3 + hour) % 14
            minute = (index * 17 + hour) % 60
            times.append(datetime.combine(START + timedelta(days=day), datetime.min.time(), KST)
                         + timedelta(hours=hour, minutes=minute))
    times.sort()

    reviewed_positions = [i for i in range(1, 61) if i % 5]
    record_by_order = dict(zip(reviewed_positions, selected, strict=True))
    pickups = {order for order, record in record_by_order.items()
               if record in selection["explicit_pickup_records"]}
    # 원문에 명시된 픽업을 유지하고, 리뷰 없는 주문으로 총12건을 맞춘다.
    unreviewed = [i for i in range(1, 61) if i not in record_by_order]
    assert len(pickups) <= 12
    pickups.update(unreviewed[:12 - len(pickups)])
    orders, reviews, records = [], [], []
    for order_id, ordered_at in enumerate(times, start=1):
        orders.append({
            "sample_order_id": order_id,
            "order_type": "PICKUP" if order_id in pickups else "DELIVERY",
            "created_at": ordered_at.isoformat(),
        })
        if order_id not in record_by_order:
            continue
        record = record_by_order[order_id]
        row = source[record]
        # 원본 행 연결은 검증 중에만 사용한다.
        reviews.append({
            "sample_review_id": len(reviews) + 1,
            "sample_order_id": order_id,
            "content": row["Review"],
            "written_at": (ordered_at + timedelta(hours=4)).isoformat(),
        })
        records.append({
            "sample_review_id": len(reviews),
            "source_csv_record": record,
        })
    return {
        "kitchen_name": "킷업 샘플 공유주방 (가상)",
        "period": {
            "start_date": START.isoformat(),
            "end_date": (START + timedelta(days=13)).isoformat(),
            "operating_days": 14,
        },
        "orders": orders,
        "reviews": reviews,
    }, records


def validate(package, source, selection, records):
    orders, reviews = package["orders"], package["reviews"]
    assert len(orders) == 60 and len(reviews) == 48
    by_order = {row["sample_order_id"]: row for row in orders}
    assert len(by_order) == 60
    assert len({row["sample_review_id"] for row in reviews}) == 48
    assert len({row["sample_order_id"] for row in reviews}) == 48
    assert len({row["content"] for row in reviews}) == 48
    by_review = {row["sample_review_id"]: row for row in records}
    assert len(records) == len(by_review) == 48
    assert set(by_review) == {row["sample_review_id"] for row in reviews}
    assert len({row["source_csv_record"] for row in records}) == 48
    expected = {n for records in selection["groups"].values() for n in records}
    assert sum(map(len, selection["groups"].values())) == len(expected) == 48
    assert set(selection["explicit_pickup_records"]) <= expected
    assert {row["source_csv_record"] for row in records} == expected
    assert set(package) == {"kitchen_name", "period", "orders", "reviews"}
    assert len({row["created_at"][:10] for row in orders}) == 14
    for row in orders:
        assert row["order_type"] in ("DELIVERY", "PICKUP")
        assert set(row) == {"sample_order_id", "order_type", "created_at"}
        ordered = datetime.fromisoformat(row["created_at"])
        assert START <= ordered.date() <= START + timedelta(days=13)
        assert ordered.utcoffset() == timedelta(hours=9)
    for review in reviews:
        original = by_review[review["sample_review_id"]]
        row = source[original["source_csv_record"]]
        assert row["RestaurantID"] == selection["restaurant_id"]
        assert row["Menu"] == selection["source_menu"], "다른 메뉴의 리뷰가 섞여 있습니다."
        assert review["content"] == row["Review"] and review["content"].strip()
        assert datetime.fromisoformat(review["written_at"]) > datetime.fromisoformat(by_order[review["sample_order_id"]]["created_at"])
        assert set(review) == {"sample_review_id", "sample_order_id", "content", "written_at"}
        if original["source_csv_record"] in selection["explicit_pickup_records"]:
            assert by_order[review["sample_order_id"]]["order_type"] == "PICKUP"
    return {
        "orders": 60, "reviews": 48, "orders_without_review": 12,
        "channels": dict(collections.Counter(row["order_type"] for row in orders)),
        "hours": dict(sorted(collections.Counter(datetime.fromisoformat(row["created_at"]).hour for row in orders).items())),
        "selection_groups": {key: len(value) for key, value in selection["groups"].items()},
        "source_text_exact_match": True,
        "single_menu_exact_match": selection["source_menu"],
        "analysis_results_unfilled": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="원본 Korean Reviews.csv 경로")
    parser.add_argument("--check", action="store_true", help="파일을 수정하지 않고 재현 결과와 비교")
    args = parser.parse_args()
    selection = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
    source = load_source(args.source, selection["source_sha256"])
    package, records = make_package(source, selection)
    result = validate(package, source, selection, records)
    target = FIXTURES / "sample_package.json"
    if args.check:
        assert json.loads(target.read_text(encoding="utf-8")) == package, "재현 결과와 다릅니다."
    else:
        target.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
