# Usage Guide

## 자연어 트리거 (Claude Code)

### 포트폴리오 분석
```
사용자: 포트폴리오 분석해줘
사용자: 오늘 포트폴리오 확인
사용자: 내 포트폴리오 정리해줘
```

→ 자동으로 4가지 통합:
1. 보유 종목 가격/손익
2. 기술적 분석
3. Watchlist
4. 외국인/기관 수급

### 수급 입력
```
사용자: /krx-flow
[토스 캡처 첨부]

또는:

사용자: 오늘 6/17 수급 입력해줘
[데이터 텍스트 첨부]
```

### 프리마켓 분석 (08:30~09:00)
```
사용자: 프리마켓 어때?
사용자: 장 시작 전 시장 흐름
```

### 차트 분석 (외부 skill)
```
사용자: /chart-analyst SK하이닉스
사용자: 효성중공업 차트 분석
```

## 직접 스크립트 실행

### 통합 리포트 (오늘)
```bash
cd ~/Desktop/skills
.venv/bin/python scripts/portfolio_report.py
```

### 특정 날짜 수급 기준
```bash
.venv/bin/python scripts/portfolio_report.py 20260615
```

### 프리마켓
```bash
.venv/bin/python scripts/premarket.py
```

### 수급 수동 입력
```bash
# 1. scripts/manual_input.py 파일에 DATA 블록 추가
# 2. main() 함수의 for 루프에 새 날짜 추가
# 3. 실행
.venv/bin/python scripts/manual_input.py
```

### 수급 자동 수집 (특정 날짜)
```bash
.venv/bin/python scripts/auto_collect.py 20260617
```

### 수급 분석 (주간/월간)
```bash
.venv/bin/python scripts/analyze_flow.py week
.venv/bin/python scripts/analyze_flow.py month
```

## 메모리 관리

### 보유 종목 변경
1. `~/.claude/projects/[프로젝트]/memory/project_portfolio.md` 열기
2. 매수/매도 반영
3. 변동 이력 추가
4. `scripts/portfolio_report.py` 내 `PORTFOLIO` 리스트도 동기화

### Watchlist 추가
1. `project_watchlist.md`에 행 추가
2. `scripts/portfolio_report.py` 내 `WATCHLIST` 리스트 동기화

## 점수 시그널 해석

| 점수 | 시그널 | 의미 |
|---|---|---|
| +5 이상 | 🟢🟢 강매수 | 적극 매수/유지 |
| +2 ~ +4 | 🟢 매수 | 매수 우위 |
| 0 ~ +1 | ⬜ 중립 | 관망 |
| -1 ~ -2 | 🟡 약세 | 매도 검토 |
| -3 이하 | 🔴 회피 | 손절 결단 |

### ⚠️ 점수 시스템의 한계
- 강매수 점수 ≠ 무조건 매수 (NAVER 단명 사례)
- 외국인 1일 매수 < 3일 연속 매수
- 만기일 (6/11 등) 변동성 극대화
- KIS 가집계 ≠ 토스 정산값

## 트러블슈팅

### `ModuleNotFoundError: No module named 'kis_auth'`
- `cd ~/Desktop/open-trading-api/examples_llm`에서 실행
- 또는 `kis_auth.py`를 scripts/ 에 복사

### `Permission denied: /Users/jun/Desktop/open-trading-api`
- macOS Sandbox/TCC 권한 차단
- `PYTHONPATH=$HOME/Desktop/open-trading-api/examples_llm` 환경변수 시도
- 안 되면 `kis_auth.py` 직접 복사

### `KIS API 가집계와 토스 데이터가 다름`
- 정상 (가집계는 추정치)
- 토스 정산값을 manual_input.py로 입력 권장

### `FDR이 오늘 데이터 없음`
- 정상 (장 마감 후 ~30분 지연)
- KIS API로 현재가 보완 (portfolio_report.py 자동 처리)
