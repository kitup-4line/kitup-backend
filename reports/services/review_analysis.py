"""리뷰 분류 제공자. 저장은 report_builder가 담당한다."""

from collections.abc import Mapping

from core.calc.order_summary import percentage
from core.choices import AspectSentiment, Sentiment
from core.exceptions import AIServiceError
from reports import providers
from reports.serializers import REVIEW_ASPECTS, ReviewLabelSerializer, ReviewQuoteCandidateSerializer

ASPECT_FIELDS = tuple(f"{aspect}_sentiment" for aspect in REVIEW_ASPECTS)
LABEL_FIELDS = ("sentiment", *ASPECT_FIELDS)


def analyze(
    reviews: list[dict], *, analyzer: providers.ReviewAnalyzer | None = None,
) -> providers.ReviewAnalysisResult:
    if analyzer is None:
        analyzer = providers.get_review_analyzer()
    payload = analyzer.analyze(reviews)
    if not isinstance(payload, Mapping):
        raise AIServiceError("리뷰 분석 응답 형식이 올바르지 않습니다.")
    serializer = ReviewLabelSerializer(data=payload.get("reviews"), many=True)
    if not serializer.is_valid():
        raise AIServiceError("리뷰 분석 응답 형식이 올바르지 않습니다.")
    labels = serializer.validated_data
    ids = [row["review_id"] for row in labels]
    if len(ids) != len(set(ids)) or set(ids) != {row["review_id"] for row in reviews}:
        raise AIServiceError("리뷰 분석 결과의 리뷰 목록이 요청과 다릅니다.")
    return {"reviews": labels, "quotes": _validate_quotes(payload.get("quotes"), reviews, labels)}


def _validate_quotes(candidates, reviews, labels) -> list[dict]:
    """잘못된 인용만 제외한다. 유효한 분류 결과까지 실패시키지 않는다."""
    if not isinstance(candidates, list):
        return []
    contents = {row["review_id"]: row["content"] for row in reviews}
    classifications = {row["review_id"]: row for row in labels}
    groups = {}
    quotes = []
    for candidate in candidates:
        serializer = ReviewQuoteCandidateSerializer(data=candidate)
        if not serializer.is_valid():
            continue
        item = serializer.validated_data
        review_id, quote = item["review_id"], item["quote"]
        if review_id not in contents or not quote.strip() or quote not in contents[review_id]:
            continue
        if classifications[review_id][f"{item['aspect']}_sentiment"] != item["sentiment"]:
            continue
        group = groups.setdefault((item["aspect"], item["sentiment"]), [])
        normalized = " ".join(quote.split()).casefold()
        if len(group) >= 2 or any(review_id == old_id or normalized == old_quote for old_id, old_quote in group):
            continue
        group.append((review_id, normalized))
        quotes.append(item)
    return quotes


def summarize(reviews: list[dict], quotes: list[dict]) -> dict:
    total = len(reviews)
    sentiments = []
    for sentiment, values in (
        ("POSITIVE", (Sentiment.POSITIVE,)),
        ("IMPROVEMENT_REQUIRED", (Sentiment.NEGATIVE, Sentiment.MIXED)),
    ):
        count = sum(row["sentiment"] in values for row in reviews)
        sentiments.append({"sentiment": sentiment, "count": count, "review_percentage": percentage(count, total)})

    result = {"review_count": total, "sentiments": sentiments}
    for key, sentiment in (
        ("strengths", AspectSentiment.POSITIVE),
        ("improvement_candidates", AspectSentiment.NEGATIVE),
    ):
        cards = []
        for field in ASPECT_FIELDS:
            count = sum(row[field] == sentiment for row in reviews)
            if not count:
                continue
            aspect = field.removesuffix("_sentiment")
            cards.append({
                "aspect": aspect, "sentiment": sentiment, "review_count": count,
                "review_percentage": percentage(count, total),
                "quotes": [{"review_id": item["review_id"], "quote": item["quote"]}
                           for item in quotes if item["aspect"] == aspect and item["sentiment"] == sentiment],
            })
        # 동률은 맛·양·온도·포장 순서를 유지한다.
        result[key] = sorted(cards, key=lambda card: card["review_count"], reverse=True)[:2]
    return result
