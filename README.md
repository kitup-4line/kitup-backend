# kitup-backend
멋쟁이사자처럼 4호선톤 kitup 백엔드 레포지토리입니다.

## 처음 설정

`.python-version`에 적힌 버전의 [Python](https://www.python.org/downloads/)과 Docker Desktop을 먼저 설치합니다.

DB 설정은 `.env.example`의 개발용 기본값을 그대로 사용합니다.

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1     # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
Copy-Item .env.example .env       # macOS/Linux: cp .env.example .env (기존 .env가 있으면 생략)
```

## 실행

Docker Desktop을 켠 뒤 실행합니다.

```powershell
.\.venv\Scripts\Activate.ps1     # macOS/Linux: source .venv/bin/activate
docker compose -f compose.dev.yaml up -d --wait db
python manage.py migrate
python manage.py runserver
```

## 개발 DB

PostgreSQL 18.6은 `compose.dev.yaml`로, Django는 PC의 가상환경에서 실행합니다.

- 접속 설정: `.env`
- 종료: `docker compose -f compose.dev.yaml stop db`
- DB를 종료해도 데이터는 유지됩니다.
- `docker compose -f compose.dev.yaml down -v`는 데이터를 삭제합니다.

## 샘플 데이터

[sample_package.json](orders/fixtures/sample_package.json)은 **후라이드 반 / 양념 반** 메뉴의 실제 리뷰 48개와 가상 주문 60개로 구성한 시연용 데이터입니다.

출처: Hyunggu Jung, Hyunmin Lee, SeungYoung Oh, JinHyun Han, [Mendeley 요기요 리뷰 v2](https://data.mendeley.com/datasets/rnyrpzyw3h/2), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

재생성: 위 Mendeley v2에서 `Korean Reviews.csv` 다운로드 → `downloads/`에 저장 → 프로젝트 루트에서 실행 (`--check`: 검증만).

```powershell
python scripts/build_sample_package.py --source "downloads/Korean Reviews.csv"
```

## 구조

```
kitup-backend/
├── manage.py
├── requirements.txt
├── .env.example
│
├── config/
│   ├── settings/
│   │   ├── base.py                 # 공통 설정
│   │   ├── local.py                # 개발 (PostgreSQL)
│   │   └── prod.py                 # 배포 (postgres)
│   ├── urls.py                     # 루트 URL
│   ├── asgi.py
│   └── wsgi.py
│
├── core/                           # 공통 모듈
│   ├── models.py                   # TimeStampedModel
│   ├── choices.py                  # TestStatus(계산용), CostMethod, CostSource,
│   │                               # Channel, OrderStatus, RecommendationStatus
│   ├── constants.py                # 수수료 9.8%, 배달비 3,200, 포장비 1,000,
│   │                               # 운영 시간·재료 단위 선택지
│   ├── responses.py                # 공통 응답 포맷
│   ├── exceptions.py               # 커스텀 예외(409 등) + 핸들러
│   ├── pagination.py
│   └── calc/                       # 순수 계산 함수 (FE와 같은 공식)
│       ├── margin.py               # 채널별 변동비·건당 공헌이익
│       └── aggregate.py            # 시간대별/일별/채널별 집계
│
├── ai/                             # LLM 호출 래퍼 (앱 아님)
│   ├── client.py
│   ├── schemas.py                  # AI 응답 JSON 검증
│   └── prompts/
│       ├── ingredient_estimate.py  # 재료·원가 추정
│       ├── review_analysis.py      # 리뷰 분류
│       └── recommendation.py       # 보고서 형태 개선안
│
├── menu_tests/                     # 테스트 생성, 재료, 원가
│   ├── models.py                   # MenuTest, Ingredient
│   ├── services/
│   │   ├── cost_service.py         # 식재료비 합산, 원가 수정, Freeze 검사
│   │   └── ai_estimate_service.py  # AI 재료 원가 추정
│   ├── serializers.py / views.py / urls.py
│   └── tests/
│
├── orders/                         # 주문·리뷰
│   ├── models.py                   # Order, Review
│   ├── fixtures/
│   │   └── sample_package.json     # 가상 주문·리뷰, 공유주방·운영 기간
│   ├── services/
│   │   └── import_service.py       # 데이터 불러오기 (= 운영 시작)
│   ├── serializers.py / views.py / urls.py
│   └── tests/
│
├── dashboard/                      # 대시보드 (모델 없음, 집계만)
│   ├── services/
│   │   └── metrics.py
│   ├── serializers.py / views.py / urls.py
│   └── tests/
│
└── reports/                        # 리포트
    ├── models.py                   # Report
    ├── services/
    │   ├── report_builder.py       # 리포트 생성 순서 관리
    │   ├── review_analysis.py      # 리뷰 분류 -> Review 칼럼 저장
    │   └── recommendation.py       # 개선안 생성·저장, retry
    ├── serializers.py / views.py / urls.py
    └── tests/
```

## URL

```
/api/tests/                          → menu_tests.urls
/api/tests/{test_id}/orders/         → orders.urls
/api/tests/{test_id}/dashboard/      → dashboard.urls
/api/tests/{test_id}/report/         → reports.urls
```

## 협업 규칙

### 브랜치 전략

```text
main                       # 배포 브랜치
develop                    # 통합 브랜치
{type}/{이슈번호}-{내용}     # 작업 브랜치
```

GitHub 기본 브랜치는 `develop`입니다. 작업 브랜치는 실제 이슈 번호를 사용합니다.

```text
feat/12-analysis           # 기능 추가
fix/18-analysis-owner      # 오류 수정
hotfix/23-login            # 운영 긴급 수정
docs/24-readme             # 문서 수정
settings/25-ci             # 설정·의존성·CI/CD 변경
refactor/26-analysis       # 기능을 유지하며 코드 정리
```

- 개발: 이슈 생성 → `develop`에서 작업 브랜치 생성 → 작업 → `develop` 대상 PR → 팀원 1명 승인 → Squash merge
- 배포: `develop` → `main` PR → 작성자가 Merge commit으로 병합
- 긴급 수정: `main`에서 `hotfix` 브랜치 생성 → PR → 팀원 1명 승인 → `main` 병합 → 변경 내용을 `develop`에도 반영
- 병합된 작업 브랜치는 자동 삭제합니다. 저장소의 `Automatically delete head branches`를 활성화하고, `main`과 `develop`에는 삭제 제한을 설정합니다.

### 커밋 컨벤션

```text
<이모지> <Type>: <변경 대상 및 변경 내용>

✨ Feat: 분석 요청 저장 기능 추가
🐛 Fix: 분석 실패 시 중복 호출 방지
♻️ Refactor: 분석 결과 변환 코드 분리
🔧 Settings: AI 응답 대기 시간 설정
📝 Docs: 로컬 실행 방법 추가
✅ Test: 타인 분석 조회 차단 검증
👷 CI: PR 테스트 자동 실행 추가
🚀 Deploy: 배포 후 상태 확인 추가
⏪ Revert: 분석 결과 캐시 적용 취소
```

| 이모지 | 타입 | 설명 |
| --- | --- | --- |
| ✨ | Feat | 새 기능 추가 |
| 🐛 | Fix | 버그 수정 |
| ♻️ | Refactor | 기능을 바꾸지 않고 코드 정리 |
| 🔧 | Settings | 일반 설정, 의존성 변경 |
| 📝 | Docs | 문서, 주석, AI 지침 변경 |
| ✅ | Test | 테스트 추가 및 수정 |
| 👷 | CI | PR 검사 및 빌드 자동화 변경 |
| 🚀 | Deploy | 배포, 상태 확인, 복귀 절차 변경 |
| ⏪ | Revert | 변경 되돌리기 |
| 🔖 | Release | 버전 기록 변경 |
| ⚡ | Perf | 성능 개선, 측정 근거와 수치 기재 |

- 1커밋에는 같은 목적의 코드와 관련 테스트를 묶습니다.
- GitHub 자동 생성 커밋은 형식 예외입니다.
- 배포 이미지 태그에는 `main`의 커밋 SHA를 사용합니다.

### PR 규칙

- 제목은 커밋과 같은 형식을 사용합니다.
- 1 PR은 1목적으로 작성합니다.
- [PR 템플릿](.github/pull_request_template.md)의 요약, 유형, 작업 내용, 관련 이슈를 직접 작성합니다. `develop`과 `main` 대상 PR 모두 같은 양식을 사용합니다.
