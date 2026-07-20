---
name: financial-analyst
version: 2.0.0
description: CFA 기준 재무분석 리포트 생성. DART 데이터 기반 애널리스트 수준 분석.
last_updated: 2026-06-17
trigger: 재무분석, 애널리스트 리포트, 기업분석, 실적분석, financial analysis
---

# Financial Analyst Skill

DART 재무데이터를 기반으로 CFA Institute 기준의 Equity Research Report를 생성한다.

## 트리거 조건

- 사용자가 기업명 + "분석해줘", "리포트 작성해줘" 요청
- `/financial-analyst 삼성전자` 형태로 호출

## 분석 프로세스 (Chain-of-Thought)

### Step 1: 데이터 수집

dart-insight는 본 repo의 `dart-insight/` 디렉토리에 포함됨.

```bash
cd ~/Desktop/skills/dart-insight && source .venv/bin/activate
python3 -c "
from src.analyzer import analyze_company
from src.db import search_companies, get_financials
import json

results = search_companies('{기업명}')
corp = results[0]
analysis = analyze_company(corp['corp_code'])
print(json.dumps(analysis, ensure_ascii=False, indent=2, default=str))
"
```

### Step 2: 리포트 작성 (아래 프레임워크 적용)

### Step 3: DB 저장

```bash
cd ~/Desktop/skills/dart-insight && source .venv/bin/activate
python3 -c "
from src.db import insert_blog_post
insert_blog_post(
    corp_code='{corp_code}',
    corp_name='{기업명}',
    title='{제목}',
    content='''{리포트 전문}''',
    summary='{요약}',
    tags='재무분석,애널리스트리포트',
)
"
```

---

## 리포트 프레임워크

> Sources: [CFA Institute Equity Research Report Essentials](https://www.cfainstitute.org/sites/default/files/-/media/documents/support/research-challenge/challenge/rc-equity-research-report-essentials.pdf), [Wall Street Prep Equity Research Report Format](https://www.wallstreetprep.com/knowledge/sample-equity-research-report/), [Corporate Finance Institute CoT Prompting](https://corporatefinanceinstitute.com/resources/financial-modeling/chain-of-thought-prompting-financial-analysis/)

### 형식 규칙

1. **한글** 작성. 숫자는 **억원/조원** 단위 표기
2. 표(table)를 적극 활용하여 가독성 확보
3. 각 섹션에 **핵심 한 줄 요약**을 맨 위에 배치
4. 증감은 화살표(↑↓→)로 직관적 표시
5. 결론 먼저, 근거 나중 (Conclusion-First)
6. 추론 시 "~로 추정된다", "~가능성이 있다" (단정 금지)
7. 긍정/부정을 동시에 제시 (균형 잡힌 시각)

### 리포트 구조

```markdown
# {기업명} | {기간} 실적 분석

> **한 줄 요약**: {가장 중요한 인사이트 1문장}

---

## 📋 기업 스냅샷

| 항목 | 내용 |
|------|------|
| 종목코드 | {code} |
| 시장 | KOSPI |
| 업종 | {sector} |
| 분석 기간 | {period} |

---

## 🎯 핵심 포인트 (Key Takeaways)

1. {핵심 포인트 1 - 숫자 포함}
2. {핵심 포인트 2 - 숫자 포함}
3. {핵심 포인트 3 - 숫자 포함}

---

## 📊 실적 요약 (Performance Summary)

> 핵심: {매출/이익 방향성 한 줄}

| 항목 | 당기 | 전기 | 증감률 | 방향 |
|------|------|------|--------|------|
| 매출액 | | | | ↑/↓ |
| 매출원가 | | | | |
| 매출총이익 | | | | |
| 영업이익 | | | | |
| 당기순이익 | | | | |

### 분기 추이 차트 해석
- {추이에서 읽히는 패턴 설명}
- {전환점/변곡점이 있다면 지적}

---

## 📐 수익성 분석 (Profitability)

> 핵심: {수익성 방향 한 줄}

| 비율 | 당기 | 전기 | 업종 평균* | 평가 |
|------|------|------|-----------|------|
| 매출총이익률 | | | | 양호/주의 |
| 영업이익률 | | | | |
| 순이익률 | | | | |

**분석:**
- {마진 변화의 원인 - 원가? 판관비? 믹스?}
- {지속가능성 판단}

---

## 🏦 재무건전성 (Financial Health)

> 핵심: {재무구조 안정성 한 줄}

| 비율 | 당기 | 전기 | 판단 |
|------|------|------|------|
| 부채비율 | | | |
| 자기자본비율 | | | |
| 유동비율 | | | |

**분석:**
- {차입 구조 변화와 목적}
- {단기 유동성 리스크 유무}

---

## 💰 수익 품질 & 현금흐름 (Earnings Quality)

> 핵심: {이익의 현금 전환력 한 줄}

### DuPont 분석 (ROE 분해)
```
ROE = 순이익률 × 자산회전율 × 재무레버리지
    = {x}% × {y}배 × {z}배
    = {ROE}%
```

### 현금흐름 품질
| 항목 | 금액 | 해석 |
|------|------|------|
| 영업CF | | {영업에서 현금 창출력} |
| 투자CF | | {성장투자 vs 수확} |
| 재무CF | | {차입/상환/배당} |
| **영업CF / 순이익** | | {>100% 양호} |

**Quality Signals:**
- {자동 감지된 시그널 해석}

---

## 🔍 핵심 변동 딥다이브 (Deep Dive)

> 핵심: {가장 눈에 띄는 변동 한 줄}

### ↑ 급증 항목
| 항목 | 전기 → 당기 | 증감률 | Why? |
|------|-------------|--------|------|
| | | | {원인 추론} |

### ↓ 급감 항목
| 항목 | 전기 → 당기 | 증감률 | Why? |
|------|-------------|--------|------|
| | | | {원인 추론} |

**일회성 vs 구조적 판단:**
- {각 변동이 일시적인지 지속적인지 판단}

---

## 🆕 신규 항목 해석 (New Items)

> 핵심: {신규 항목이 시사하는 바 한 줄}

| 항목 | 금액 | 의미 |
|------|------|------|
| | | {사업확장? 구조조정? M&A?} |

---

## ⚠️ 리스크 요인 (Risk Factors)

| 구분 | 리스크 | 영향도 | 발생 가능성 |
|------|--------|--------|------------|
| 산업 | | 높음/중간/낮음 | |
| 기업 | | | |
| 매크로 | | | |

---

## 🔮 향후 전망 (Outlook)

> 핵심: {방향성 한 줄}

| 시나리오 | 조건 | 예상 영업이익 |
|----------|------|--------------|
| 📈 상방 | {촉매} | {금액} |
| ➡️ 기본 | {기본 가정} | {금액} |
| 📉 하방 | {리스크 현실화} | {금액} |

**모니터링 포인트:**
1. {다음 분기 체크할 핵심 지표 1}
2. {핵심 지표 2}
3. {핵심 지표 3}

---

## 💡 투자 시사점 (Investment Implications)

- {밸류에이션 관점}
- {주주환원 정책}
- {catalysts / de-risking 요소}

---

*본 리포트는 DART 공시 재무데이터 기반 자동 분석이며, 투자 권유가 아닙니다.*
*분석일: {날짜} | 데이터 출처: DART 전자공시시스템*
```

---

## 분석 체크리스트

리포트 작성 전 반드시 확인:

- [ ] 연결 vs 별도 재무제표 구분 확인
- [ ] 전기 금액이 NaN이면 YoY 비교 불가 명시
- [ ] 4Q 데이터는 연간 누적인지 분기 단독인지 확인
- [ ] 업종 평균은 추정치임을 표기 (*)
- [ ] 단정적 표현 배제 ("확실히" → "~로 추정")
- [ ] 긍정/부정 균형 (bull case + bear case 모두 제시)
- [ ] DB 저장 완료 확인

---

## 의존성

이 스킬은 본 repo의 `dart-insight/` 디렉토리를 필요로 합니다:

- `dart-insight/src/analyzer.py` — 재무 분석 엔진
- `dart-insight/src/db.py` — DB 작업
- `dart-insight/src/dart_client.py` — DART API 클라이언트
- `dart-insight/dart_insight.db` — 재무 데이터 DB (별도 수집 필요)

설치:
```bash
cd ~/Desktop/skills/dart-insight
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # DART API 키 입력
python3 app.py collect  # 또는 별도 수집 명령
```
