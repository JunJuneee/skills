# dart-insight

DART 전자공시시스템 기반 재무 분석 엔진. **financial-analyst skill의 데이터 소스**.

## 구조

```
dart-insight/
├── app.py                # FastAPI 진입점
├── requirements.txt
├── .env.example          # DART API 키 템플릿
└── src/
    ├── __init__.py
    ├── analyzer.py       # 재무 분석 엔진 ⭐
    ├── db.py             # SQLite DB 작업 ⭐
    ├── dart_client.py    # DART API 클라이언트
    ├── collector.py      # 데이터 수집
    ├── blog_generator.py # 블로그 자동 생성
    ├── scheduler.py      # 스케줄러
    └── telegram_bot.py   # 텔레그램 봇
```

## 설치

```bash
cd ~/Desktop/skills/dart-insight

# 1. venv 생성
python3 -m venv .venv
source .venv/bin/activate

# 2. 패키지 설치
pip install -r requirements.txt

# 3. DART API 키 설정
cp .env.example .env
# .env 파일 편집 — DART_API_KEY 입력
# 발급: https://opendart.fss.or.kr/
```

## 사용 (financial-analyst skill에서 호출)

```python
from src.analyzer import analyze_company
from src.db import search_companies, get_financials, insert_blog_post

# 기업 검색
results = search_companies('삼성전자')
corp_code = results[0]['corp_code']

# 재무 분석
analysis = analyze_company(corp_code)

# 리포트 저장
insert_blog_post(
    corp_code=corp_code,
    corp_name='삼성전자',
    title='2026 Q1 실적 분석',
    content='리포트 본문...',
    summary='요약',
    tags='재무분석,애널리스트리포트',
)
```

## 데이터 수집

```bash
# 전체 기업 리스트 수집
python3 -c "from src.collector import collect_corp_list; collect_corp_list()"

# 특정 기업 재무 데이터 수집
python3 -c "from src.collector import collect_financials; collect_financials('00126380')"  # 삼성전자
```

## ⚠️ 주의

- **DART API 키 필수** (`.env`에 `DART_API_KEY` 설정)
- **DB는 별도 수집 필요** (`dart_insight.db`는 .gitignore)
- **financial-analyst skill 호출 시** 이 디렉토리 활성화 필요

## API 키 발급

1. https://opendart.fss.or.kr/ 가입
2. 인증 API 신청
3. 개인용 키 발급 (무료, 일 10,000건)
4. `.env`에 `DART_API_KEY=발급키` 입력
