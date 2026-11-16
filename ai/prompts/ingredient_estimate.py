"""재료·원가 추정 프롬프트."""

import json

SYSTEM_PROMPT = (
    "당신은 한국 배달 음식점의 식재료 원가를 추정하는 전문가입니다. "
    "응답은 JSON 객체 하나만 출력합니다. 설명 문장이나 코드펜스(```)는 쓰지 않습니다."
)


def build_user_prompt(menu_name, selling_price, ingredient_names, unit_values) -> str:
    example = {
        "ingredients": [
            {"ingredient_name": "돼지고기", "quantity": 150, "unit": "g", "ingredient_cost": 2400}
        ]
    }
    return "\n".join(
        [
            f"메뉴: {menu_name}",
            f"예상 판매가: {selling_price}원",
            f"재료 목록: {json.dumps(ingredient_names, ensure_ascii=False)}",
            "",
            "이 메뉴 1인분을 만들 때 재료별 사용량과, 그 사용량만큼의 비용(원)을 추정해주세요.",
            "- 비용은 한국 도매·마트 시세 기준으로 추정합니다.",
            "- ingredient_cost는 단가가 아니라 1인분에 쓰는 양의 비용입니다.",
            f"- unit은 다음 중에서만 고릅니다: {', '.join(unit_values)}",
            "- 재료 목록의 재료를 빠짐없이, 이름을 바꾸지 않고, 추가 재료 없이 반환합니다.",
            "",
            "출력 형식:",
            json.dumps(example, ensure_ascii=False),
        ]
    )
