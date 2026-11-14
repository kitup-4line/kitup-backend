"""문서용 가상 응답 예시. 실제 API의 계산이나 응답에는 사용하지 않는다."""

from drf_spectacular.utils import OpenApiExample


_QUANTITATIVE_EXAMPLE = {
    "analysis_conditions": {
        "operating_period": {
            "start_date": "2026-10-30",
            "end_date": "2026-11-12",
            "operating_days": 14,
        },
        "kitchen_name": "성수 공유주방 A - 가상공간",
        "analysis_data": {
            "completed_order_count": 60,
            "linked_review_count": 48,
            "channels": [
                {
                    "order_type": "DELIVERY",
                    "order_count": 30,
                    "order_percentage": 50,
                },
                {
                    "order_type": "PICKUP",
                    "order_count": 30,
                    "order_percentage": 50,
                },
            ],
        },
        "sales_conditions": {
            "selling_price": 12000,
            "business_start_time": "11:00",
            "business_end_time": "20:00",
            "total_operating_hours": 126,
            "orders_per_hour": 0.4762,
        },
    },
    "profit_analysis": {
        "summary": {
            "total_revenue": 720000,
            "total_contribution_margin": 288720,
            "contribution_margin_percentage": 40.1,
            "contribution_margin_per_order": 4812,
            "applied_fixed_cost": 120000,
            "estimated_operating_profit": 168720,
            "operating_profit_percentage": 23.43,
        },
        "per_order_structure": {
            "average_revenue": 12000,
            "ingredient_cost": {
                "amount": 4000,
                "revenue_percentage": 33.33,
            },
            "packaging_cost": {
                "amount": 1000,
                "revenue_percentage": 8.33,
            },
            "delivery_fee": {
                "amount": 1600,
                "revenue_percentage": 13.33,
            },
            "delivery_commission": {
                "amount": 588,
                "revenue_percentage": 4.9,
            },
            "contribution_margin": {
                "amount": 4812,
                "revenue_percentage": 40.1,
            },
        },
    },
    "sales_pattern": {
        "time_buckets": [
            {
                "key": "1100",
                "label": "11:00~13:00",
                "start_time": "11:00",
                "end_time": "13:00",
                "order_count": 24,
                "order_percentage": 40,
                "revenue": 288000,
            },
            {
                "key": "1500",
                "label": "15:00~17:00",
                "start_time": "15:00",
                "end_time": "17:00",
                "order_count": 12,
                "order_percentage": 20,
                "revenue": 144000,
            },
            {
                "key": "other",
                "label": "기타 시간대",
                "start_time": None,
                "end_time": None,
                "order_count": 24,
                "order_percentage": 40,
                "revenue": 288000,
            },
        ],
        "peak_summary": {
            "peak_order_count": 36,
            "peak_revenue": 432000,
            "peak_revenue_percentage": 60,
        },
        "insights": {
            "result": "주문이 많은 구간은 11:00~13:00, 15:00~17:00이며 총 36건입니다.",
            "meaning": "영업 시작 기준 2시간 구간의 주문 건수를 비교한 결과입니다.",
            "recommended_action": "주문이 집중된 구간의 재료 준비와 작업 배치를 점검하세요.",
            "limitation": "가상 주문 분석으로 실제 수요를 보장하지 않습니다. 마지막 구간은 2시간보다 짧을 수 있으며, 구간 길이를 보정하지 않은 주문 건수 순위입니다. 영업시간 밖 주문은 기타에 포함합니다.",
        },
    },
}


_REVIEW_RESULT_EXAMPLE = {
    "review_count": 1,
    "sentiments": [
        {"sentiment": "POSITIVE", "count": 1, "review_percentage": 100},
        {"sentiment": "IMPROVEMENT_REQUIRED", "count": 0, "review_percentage": 0},
    ],
    "strengths": [{
        "aspect": "taste", "sentiment": "POSITIVE", "review_count": 1,
        "review_percentage": 100, "quotes": [{"review_id": 1, "quote": "맛있어요"}],
    }],
    "improvement_candidates": [],
}


REPORT_CREATE_EXAMPLES = [
    OpenApiExample(
        name, summary=name, description=description,
        value={"success": True, "message": None, "data": {
            "quantitative": {
                **_QUANTITATIVE_EXAMPLE,
                "analysis_conditions": {
                    **_QUANTITATIVE_EXAMPLE["analysis_conditions"],
                    "analysis_data": {
                        **_QUANTITATIVE_EXAMPLE["analysis_conditions"]["analysis_data"],
                        "linked_review_count": 0 if review_status == "NOT_REQUIRED" else 48,
                    },
                },
            },
            "review_analysis_status": review_status,
            "improvement_status": improvement_status,
        }},
    )
    for name, description, review_status, improvement_status in [
        ("리뷰 분석 시작 대기", "가상 데이터. 최초 요청 또는 리뷰 분석 재시도가 접수되어 분석 시작을 기다립니다.", "PENDING", "PENDING"),
        ("개선안 생성 시작 대기", "가상 데이터. 리뷰 분석은 완료되었고 개선안 생성 시작을 기다립니다.", "SUCCEEDED", "PENDING"),
        ("리뷰 없음", "가상 데이터. 연결된 리뷰가 없어 리뷰 분석을 생략합니다.", "NOT_REQUIRED", "PENDING"),
        ("진행 중", "가상 데이터. 작업 진행 중 같은 POST를 보내면 현재 상태를 반환합니다.", "RUNNING", "PENDING"),
        ("이미 완료", "가상 데이터. 완료 후 같은 POST를 보내면 현재 상태를 반환합니다. AI 결과는 GET으로 조회합니다.", "SUCCEEDED", "SUCCEEDED"),
    ]
]


REPORT_DETAIL_EXAMPLES = [
    OpenApiExample(
        name, summary=name,
        description="가상 데이터, include_quantitative=false 응답입니다.",
        value={"success": True, "message": None, "data": {
            "review_analysis_status": review_status,
            "improvement_status": improvement_status,
            "review_analysis": _REVIEW_RESULT_EXAMPLE if review_status == "SUCCEEDED" else None,
            "improvements": [{
                "title": "맛 유지", "action": "현재 조리법과 재료 양을 기록하세요.",
                "verification": "다음 테스트에서도 맛 관련 리뷰를 확인하세요.",
                "evidence_review_ids": [1],
            }] if improvement_status == "SUCCEEDED" else None,
        }},
    )
    for name, review_status, improvement_status in [
        ("리뷰 분석 중", "RUNNING", "PENDING"),
        ("개선안 생성 중", "SUCCEEDED", "RUNNING"),
        ("리뷰 분석 실패", "FAILED", "PENDING"),
        ("개선안 생성 실패", "SUCCEEDED", "FAILED"),
        ("전체 완료", "SUCCEEDED", "SUCCEEDED"),
        ("리뷰 없음", "NOT_REQUIRED", "RUNNING"),
    ]
]


EVIDENCE_REVIEW_EXAMPLES = [
    OpenApiExample(
        name, summary=name, description=description,
        value={"success": True, "message": None, "data": reviews},
    )
    for name, description, reviews in [
        (
            "긍정 리뷰", "가상 리뷰. `aspect=taste&sentiment=POSITIVE`",
            [
                {
                    "review_id": 1, "content": "맛있어요. 다음에도 주문할게요.",
                    "written_at": "2026-11-12T12:30:00+09:00",
                },
                {
                    "review_id": 2, "content": "양념 맛이 좋았어요.",
                    "written_at": "2026-11-11T18:20:00+09:00",
                },
            ],
        ),
        (
            "부정 리뷰", "가상 리뷰. `aspect=temperature&sentiment=NEGATIVE`",
            [
                {
                    "review_id": 3, "content": "음식이 식어서 도착했어요.",
                    "written_at": "2026-11-12T19:10:00+09:00",
                },
            ],
        ),
        (
            "빈 목록", "가상 리뷰. 리뷰가 없거나 선택한 조건에 맞는 리뷰가 없습니다.",
            [],
        ),
        (
            "작성 시각 없음", "가상 리뷰. 작성 시각이 없는 리뷰는 목록 마지막에 표시합니다.",
            [
                {
                    "review_id": 1, "content": "맛있어요. 다음에도 주문할게요.",
                    "written_at": "2026-11-12T12:30:00+09:00",
                },
                {
                    "review_id": 4, "content": "맛있게 먹었습니다.",
                    "written_at": None,
                },
            ],
        ),
    ]
]
