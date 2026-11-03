# Jun Skills

Claude·Codex에서 함께 사용하는 스킬 모음. AI 작업 운영, 투자 분석, SEO·발행, 영상 제작을 지원합니다.

## 공용 AI 작업 규약

[`agent-workflow`](skills/agent-workflow/SKILL.md)는 대화에서 승인한 목표를 작업 카드 → 격리 구현 → 독립 리뷰·완료 증거 → 결과물 전달로 연결합니다. 기존 Linear 상태·자동 실행 규칙을 읽어 유지하며 사용자 결정만 모읍니다. PR 작성·병합·배포의 승인 범위를 구분합니다.

Claude·Codex 공용 본문은 `skills/agent-workflow/SKILL.md` 한곳에서 관리합니다. 기존 플러그인의 `skills/` 배포에 포함되며 설치된 클라이언트가 새 버전을 로드한 뒤 사용할 수 있습니다. 이 저장소에 커밋했다고 현재 실행 중인 세션이 갱신된 것으로 보지는 않습니다.

호출할 때 `agent-workflow` 스킬 이름과 승인된 목표를 함께 적습니다. 예:

> agent-workflow를 사용해서 이 프로젝트의 승인된 목표를 카드로 나누고, 기존 runner 규칙을 유지하며 작업물과 완료 증거까지 만들어줘. 새 완료·전달 게이트는 observe로 시작해줘.

> agent-workflow를 사용해서 PR #12·#13을 검토하고 충돌 해결·검증 후 병합해줘. 다른 PR과 배포는 제외해줘.

상세 규약은 [Linear·runner](skills/agent-workflow/references/linear-and-runner.md), [완료 증거](skills/agent-workflow/references/completion-evidence.md), [결과물·미리보기](skills/agent-workflow/references/delivery-and-preview.md), [검토·병합](skills/agent-workflow/references/review-and-merge.md)에 나뉩니다. 프로젝트별 경로·라벨·명령은 [작업 계약 템플릿](skills/agent-workflow/assets/work-contract.md)에 확인해 채우며, [에이전트 작업 지시](skills/agent-workflow/assets/agent-brief.md)로 같은 규약을 하위 작업에 전달합니다.

이 스킬은 규약입니다. 백그라운드 runner 설치·기동, API 키 공유, 운영 모드 변경을 자동으로 수행하는 도구는 아닙니다. 실제 자동 실행은 각 프로젝트의 기존 실행기에 연결합니다.

## Linear 이슈의 Traycer 실행

[`linear-traycer-workflow`](skills/linear-traycer-workflow/SKILL.md)는 Linear 이슈를 Traycer에서 실행할 때 쓰는 구체적인 작업 흐름입니다. 구현 모델의 반대 계열 5명이 계획 critique합니다(Codex 구현 → Claude, Claude 구현 → Codex). 조율자가 필요한 내용을 반영하고 지정한 구현 계열의 작업자들이 구현·TC·테스트를 맡으며, 조율자 한 명이 PR 게시와 외부 갱신을 담당합니다. 별도 Opus가 코드 리뷰하고 그 결과를 조율자가 PR에 남기며 수정·검증·재리뷰를 반복합니다. 실제 진행에 따라 Linear 상태를 갱신하고, 병합·배포는 현재 승인 범위를 따릅니다. 계획 후 재승인 단계는 없습니다. 제이지 봇으로 프로젝트 채널에 시작 설명·Linear 링크를 남기고 같은 스레드에 진행과 완료 PR·요청자 멘션을 이어갑니다. 최종 수정·리뷰와 원격 보존을 확인한 뒤 작업 소유 worktree를 정리합니다. 환경변수와 제이지 토큰은 Doppler `jay/shared`에서 우선 찾고 필요한 프로세스에만 주입합니다.

> $linear-traycer-workflow를 사용해서 지정한 Linear 이슈를 구현하고, 필수 TC·테스트와 Opus 리뷰를 마친 PR까지 만들어줘.

이 스킬은 기존 `agent-workflow`를 대체하거나 감시 실행기를 설치하지 않습니다. 역할별 모델·하위 위임은 [모델 계약](skills/linear-traycer-workflow/references/models-and-delegation.md), TC·PR 댓글·Linear 상태 전환은 [검증과 진행 기록](skills/linear-traycer-workflow/references/evidence-and-linear.md)을 따릅니다.

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
├── automation/              # launchd 자동화
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
