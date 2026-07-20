---
name: krx-flow
description: KRX 수급 데이터 입력 & 분석 — 토스/HTS 캡처를 SQLite DB로 입력, KIS API 자동 수집, 외국인/기관 매매 패턴 분석. "/krx-flow [데이터]" 트리거.
type: skill
version: 1.0
---

# KRX Flow — 수급 데이터 입력 & 분석

## 트리거 조건

- 사용자가 토스/HTS 캡처 + 날짜 제공
- "/krx-flow" 명령 + 데이터 첨부
- 키워드: "수급", "외국인 매수/매도", "기관 매매"

## DB 스키마

`~/chikitaka/dart-insight/data/krx_flow.db`

```sql
CREATE TABLE net_purchases (
    date TEXT,           -- YYYYMMDD
    market TEXT,         -- KOSPI / KOSDAQ
    investor TEXT,       -- 외국인_buy/sell, 기관_buy/sell, 개인_buy/sell
    ticker TEXT,         -- 종목코드 (6자리)
    name TEXT,           -- 종목명
    net_value INTEGER,   -- 금액 (원)
    rank INTEGER,        -- TOP30 순위
    UNIQUE(date, market, investor, ticker, rank)
);
```

## 데이터 형식

```python
DATA_MMDD = {
    '외국인_buy':  [(순위, '종목명', 금액_억), ...],   # 최대 30개
    '외국인_sell': [(순위, '종목명', 금액_억), ...],
    '기관_buy':    [...],
    '기관_sell':   [...],
    '개인_buy':    [...],
    '개인_sell':   [...],
}
```

- 금액 단위: **억원** (정수 또는 소수)
- 종목명: FDR 검증 후 코드 자동 매핑
- 최대 30개까지

## 작업 절차

### 1. 날짜 파싱
- "5/13", "오늘", "어제" → `YYYYMMDD`
- 오늘 날짜는 시스템 시간 기준

### 2. manual_input.py 업데이트
새 DATA 블록 추가 + main() 루프에 날짜 추가

### 3. DB 저장 실행
```bash
python scripts/manual_input.py
```

### 4. 포트폴리오 알림 즉시 체크
사용자 보유/watchlist 종목이 TOP30에 있는지 매칭:

```
🚨 포트폴리오 알림 [날짜]
  🟢🟢 [ISA] SK하이닉스 — 외국인 2위(+5,230억) + 기관 3위(+2,100억)
  🔴   [WL] 효성중공업 — 외국인 8위(-610억)
```

**우선순위:**
- 🟢🟢 외국인 + 기관 동시 순매수 → 강한 매수
- 🔴🔴 외국인 + 기관 동시 순매도 → 매도 압력
- 🟢 / 🔴 단일 → 참고

### 5. 분석 실행 (옵션)
```bash
python scripts/analyze_flow.py week
```

## KIS API 자동 수집

`scripts/auto_collect.py`:
- KIS `foreign_institution_total` API 호출 (HTS [0440])
- 매일 18:00 launchd 자동 실행
- 단점: **가집계** (토스 정산값과 차이 가능)

## 데이터 한계

### KIS 가집계 vs 토스 정산값
- KIS는 09:30, 11:20, 13:20, 14:30 가집계
- 토스는 장 마감 후 정산값 (18:00 이후)
- **종목/금액 순위 다를 수 있음** (한미반도체 가집계 449억 vs 정산 706억 사례)

### 권장 방식
- 정상 분석: 토스 캡처 → manual_input.py (가장 정확)
- 자동 알림: KIS API 보조 (큰 흐름만)
- 6/3, 6/9 등 미수집 날짜 → 종목별 재구성 (backfill.py)

## 종목코드 검증

- ETF는 반드시 FDR 검증
- 추측 절대 금지 — 모르면 `'?'` 저장
- 검증 기록: `project_verified_tickers.md`

**자주 혼동:**
- 현대차우 (005385, 1우) vs 현대차2우B (005387)
- TIGER 미국필라델피아반도체나스닥 (381180) vs 레버리지 (423920)
- PLUS K방산 (449450) — KODEX 아님!
- TSMC파운드리 (453950) — 488500은 다른 종목

## 출력 형식

```
📊 [YYYYMMDD] 수급 데이터 저장 완료
💾 외국인_buy N건 / 외국인_sell N건 / 기관_buy N건 / 기관_sell N건

🚨 포트폴리오 알림:
  [매칭된 보유/WL 종목]

📈 시장 핵심 TOP5:
  [외매수/외매도/기매수/기매도]
```

## 자동화 (launchd)

`automation/launchd/com.jun.krx-flow-collect.plist`:
- 매일 18:00 실행
- `auto_collect.py` 호출
- 로그: `logs/auto_collect.log`

### 설치
```bash
cp automation/launchd/com.jun.krx-flow-collect.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.jun.krx-flow-collect.plist
```

## 주의사항

- ⚠️ 6/3, 6/8 등 휴장일 자동수집 실패 가능 → 수동 backfill
- ⚠️ 가집계는 14:30 마감 후 더 이상 업데이트 안 됨
- ⚠️ 토스 캡처는 18:00 이후 정확 (그 전엔 KIS와 비슷)
- ⚠️ 토요일/일요일 launchd 실행되지만 데이터 없음 (예외 처리)

## Why

토스/HTS에서 본 수급을 매번 다시 보기 번거로움 → DB에 저장하고 포트폴리오/WL 종목 자동 매칭 알림.

## How to apply

캡처 + 날짜 입력 → DB 저장 → 보유/WL 매칭 → 알림 즉시 출력.
