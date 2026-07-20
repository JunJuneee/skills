# Setup Guide

## 사전 요구사항

### 1. 한국투자증권 OpenAPI 계정
- https://apiportal.koreainvestment.com 가입
- 모의/실전 앱 등록 후 APP_KEY / APP_SECRET 발급
- `~/KIS/config/kis_devlp.yaml` 생성 (아래 형식)

```yaml
my_app: "발급받은_APP_KEY"
my_sec: "발급받은_APP_SECRET"
my_htsid: "본인_HTS_ID"
my_acct_stock: "계좌번호_8자리"
my_acct_future: "계좌번호_8자리"
my_prod: "01"   # 종합계좌
prod: "https://openapi.koreainvestment.com:9443"
ops: "https://openapi.koreainvestment.com:9443"
vps: "https://openapivts.koreainvestment.com:29443"
my_token: ""
my_agent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
```

### 2. Python 3.10+
```bash
python3 --version  # 3.10 이상 확인
```

### 3. Claude Code
- https://claude.ai/code 설치
- macOS 권장 (launchd 사용)

## 설치 단계

### 1. Repo 클론
```bash
cd ~/Desktop
git clone [repo-url] skills
cd skills
```

### 2. 설치 스크립트 실행
```bash
chmod +x automation/setup.sh
bash automation/setup.sh
```

자동으로:
- `~/.claude/skills/` 에 심볼릭 링크
- Python venv 생성 + 패키지 설치
- DB 디렉토리 + 스키마 생성

### 3. KIS API 패키지 (open-trading-api) 설치
```bash
cd ~/Desktop
git clone https://github.com/koreainvestment/open-trading-api.git
```

`open-trading-api/examples_llm/kis_auth.py`가 KIS API 호출에 필요.

### 4. 메모리 초기화
```bash
# 본인 Claude 프로젝트 디렉토리 확인
ls ~/.claude/projects/

# 메모리 디렉토리 생성
mkdir -p ~/.claude/projects/[프로젝트명]/memory/

# 템플릿 복사
cp memory_templates/feedback_portfolio_analysis_default.md \
   ~/.claude/projects/[프로젝트명]/memory/

cp memory_templates/feedback_data_verification_policy.md \
   ~/.claude/projects/[프로젝트명]/memory/

cp memory_templates/project_portfolio.md.template \
   ~/.claude/projects/[프로젝트명]/memory/project_portfolio.md
# → 본인 보유 종목 입력

cp memory_templates/project_watchlist.md.template \
   ~/.claude/projects/[프로젝트명]/memory/project_watchlist.md
# → 본인 관심 종목 입력
```

### 5. MEMORY.md 인덱스 생성
```bash
cat > ~/.claude/projects/[프로젝트명]/memory/MEMORY.md << 'EOF'
# Memory Index

- [project_portfolio.md](project_portfolio.md) — ISA 보유
- [project_watchlist.md](project_watchlist.md) — 관심 종목
- [feedback_portfolio_analysis_default.md](feedback_portfolio_analysis_default.md) — 자동 분석 규칙
- [feedback_data_verification_policy.md](feedback_data_verification_policy.md) — 검증 의무
EOF
```

### 6. launchd 자동 수집 (선택)
```bash
# plist 파일 내 경로 본인 환경 맞게 수정
nano automation/launchd/com.jun.krx-flow-collect.plist

# 설치
cp automation/launchd/com.jun.krx-flow-collect.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.jun.krx-flow-collect.plist

# 확인
launchctl list | grep krx-flow
```

매일 18:00 자동 수급 수집.

### 7. 테스트

#### Python 스크립트
```bash
cd ~/Desktop/skills
.venv/bin/python scripts/portfolio_report.py
```

#### Claude Code
1. Claude Code 재시작
2. 입력: "포트폴리오 분석해줘"
3. 4가지 통합 분석 출력 확인

## 권한 문제 해결

### macOS Desktop 접근 차단
```bash
# 시스템 환경설정 → 보안 및 개인정보보호 → 개인정보 → 전체 디스크 접근
# → 터미널/iTerm/VS Code 추가
```

### KIS API 토큰 발급 실패
- `~/KIS/config/kis_devlp.yaml` 권한 확인 (chmod 600)
- APP_KEY/APP_SECRET 재발급

## 디렉토리 구조 최종

```
~/Desktop/skills/                    # 이 repo
├── skills/                          # SKILL.md
├── scripts/                         # Python
├── memory_templates/                # 메모리 템플릿
├── automation/                      # launchd
└── data/schema.sql                  # DB 스키마

~/.claude/skills/                    # 심볼릭 링크 (setup.sh가 생성)
├── portfolio-analyst → repo/skills/portfolio-analyst
├── krx-flow → repo/skills/krx-flow
└── premarket-analyst → repo/skills/premarket-analyst

~/.claude/projects/[프로젝트명]/memory/  # 실제 메모리 (개인정보)
├── project_portfolio.md             # 보유 (private)
├── project_watchlist.md             # 관심 (private)
└── feedback_*.md                    # 규칙

~/KIS/config/                        # KIS API
└── kis_devlp.yaml                   # API 키

~/Library/LaunchAgents/              # 자동화
└── com.jun.krx-flow-collect.plist
```
