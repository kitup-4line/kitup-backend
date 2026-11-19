"""짧은 리뷰 분류 응답을 기존 서비스 계약으로 복원한다."""

from collections.abc import Mapping

POLARITY = {"P": "POSITIVE", "N": "NEGATIVE"}
OVERALL = {**POLARITY, "M": "MIXED"}
ASPECTS = {"t": "taste", "q": "portion", "h": "temperature", "p": "packaging"}


class ReviewResponseError(ValueError):
    pass


def _row(value, keys):
    if not isinstance(value, Mapping) or set(value) != set(keys) or type(value["i"]) is not int:
        raise ReviewResponseError("Invalid compact response row")


def _code(value, choices):
    if not isinstance(value, str) or value not in choices:
        raise ReviewResponseError("Invalid compact response code")
    return choices[value]


def decode_compact_response(payload):
    if not isinstance(payload, Mapping) or set(payload) != {"reviews", "quotes"}:
        raise ReviewResponseError("Invalid compact response fields")
    if not isinstance(payload["reviews"], list):
        raise ReviewResponseError("Invalid compact review list")

    reviews = []
    for row in payload["reviews"]:
        _row(row, "istqhp")
        labels = {"review_id": row["i"], "sentiment": _code(row["s"], OVERALL)}
        for code, aspect in ASPECTS.items():
            labels[f"{aspect}_sentiment"] = None if row[code] is None else _code(row[code], POLARITY)
        reviews.append(labels)

    quotes = []
    candidates = payload["quotes"] if isinstance(payload["quotes"], list) else []
    for row in candidates:
        try:
            _row(row, "iasx")
            if not isinstance(row["x"], str):
                continue
            quotes.append({
                "review_id": row["i"], "aspect": _code(row["a"], ASPECTS),
                "sentiment": _code(row["s"], POLARITY), "quote": row["x"],
            })
        except ReviewResponseError:
            # 분류는 보존하고 잘못된 인용만 버리는 기존 검증 동작을 유지한다.
            continue
    return {"reviews": reviews, "quotes": quotes}
