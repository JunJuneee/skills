# Investment Skills for Claude Code

한국 주식 포트폴리오 자동 분석 시스템. Claude Code Skill + Python 자동화 + 메모리 기반 의사결정.

## 🎯 핵심 기능

| 기능 | 트리거 | 결과 |
|---|---|---|
| **포트폴리오 통합 분석** | "포트폴리오 분석해줘" | 가격 + 기술분석 + Watchlist + 수급 한번에 |
| **KRX 수급 입력** | "/krx-flow [데이터]" | 토스/HTS 캡처 → DB 저장 |
| **프리마켓 분석** | "프리마켓 어때?" | 보유/WL 예상체결 + 시장 급등락 TOP |
| **재무 분석** | "/financial-analyst [종목]" | DART 데이터 기반 CFA 리포트 |
| **차트 분석 (외부)** | "/chart-analyst [종목]" | chart-analyst v1.8 5단계 분석 |

## 📁 구조

```
skills/
├── skills/                          # Claude Code Skills (SKILL.md)
│   ├── portfolio-analyst/           # 4가지 통합 분석 (chart-analyst v1.8 기반)
│   ├── krx-flow/                    # 수급 입력/분석
│   ├── premarket-analyst/           # 프리마켓 분석
│   ├── financial-analyst/           # CFA 재무 분석 (dart-insight 사용)
│   ├── finance-bot-automation/      # 정기 잡 진단·복구 (launchd)
│   └── external/                    # 외부 제공 스킬 (백업)
│       └── chart-analyst/           # 5단계 차트 분석 v1.8
├── dart-insight/                    # DART 재무 분석 엔진 (financial-analyst 의존)
│   ├── app.py
│   ├── src/                         # analyzer, db, dart_client 등
│   └── requirements.txt
├── scripts/                         # Python 실행 파일
│   ├── portfolio_report.py  # 통합 리포트
│   ├── premarket.py         # 프리마켓 조회
│   ├── auto_collect.py      # KIS API 수급 수집
│   ├── manual_input.py      # 토스 수동 입력
│   ├── analyze_flow.py      # 수급 패턴 분석
│   └── ...
├── memory_templates/        # 메모리 템플릿 (개인정보 제외)
├── automation/              # launchd 자동화 (스케줄 전체: automation/SCHEDULES.md)
├── docs/                    # 사용법 / 아키텍처
└── data/                    # DB 스키마
```

## 🚀 빠른 시작

### 1. 설치
```bash
git clone [repo-url] ~/Desktop/skills
cd ~/Desktop/skills
bash automation/setup.sh    # Skills 심볼릭 링크 + venv 생성
```

### 2. KIS API 설정
```bash
# ~/KIS/config/kis_devlp.yaml 생성 (API 키)
# 한국투자증권 OpenAPI 신청 필요
```

### 3. financial-analyst 설치 (선택)
```bash
cd ~/Desktop/skills/dart-insight
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # DART API 키 입력
```

### 4. 메모리 초기화
```bash
# memory_templates/ → ~/.claude/projects/.../memory/ 복사
# 본인 포트폴리오 정보로 채우기
```

### 5. 사용
- Claude Code에서 "포트폴리오 분석해줘" 입력
- 또는 `python scripts/portfolio_report.py` 직접 실행

### 6. 자동 실행 (선택)
프리마켓 08:01 · 마감 15:40 · 5분 가격 모니터 등 정기 잡을 켜려면
[`automation/SCHEDULES.md`](automation/SCHEDULES.md) 참고.
```bash
cp automation/launchd/*.plist ~/Library/LaunchAgents/
for f in ~/Library/LaunchAgents/com.jun.*.plist; do launchctl bootstrap gui/$UID "$f"; done
```

## 🛠️ 의존성

- Python 3.10+
- FinanceDataReader (FDR)
- 한국투자증권 OpenAPI 계정
- Claude Code

## 📜 라이선스

Private — 개인 투자 자동화 용도

## 📊 데이터 소스

- **가격**: FinanceDataReader (한국 주식 일봉)
- **실시간 시세**: KIS API (한국투자증권)
- **수급**: KIS API (가집계) + 토스/HTS (정산값) 병행
- **DB**: SQLite (로컬)

## ⚠️ 주의

- 이 시스템은 투자 조언이 아닙니다
- KIS API "가집계"는 토스/HTS 정산값과 다를 수 있음
- chart-analyst v1.8 메타분석 편향 보정 적용
