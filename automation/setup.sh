#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Investment Skills 초기 설치 스크립트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_SKILLS_DIR="$HOME/.claude/skills"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Investment Skills Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 1. Claude Code skills 디렉토리에 심볼릭 링크
echo "📁 1. Claude Code Skills 심볼릭 링크 생성..."
mkdir -p "$CLAUDE_SKILLS_DIR"

for skill_dir in "$REPO_DIR/skills"/*/; do
    skill_name=$(basename "$skill_dir")
    target="$CLAUDE_SKILLS_DIR/$skill_name"

    if [ -L "$target" ]; then
        echo "  ⏭️  $skill_name (이미 링크됨)"
    elif [ -e "$target" ]; then
        echo "  ⚠️  $skill_name (이미 존재 — 수동 확인 필요)"
    else
        ln -s "$skill_dir" "$target"
        echo "  ✅ $skill_name → 링크 생성"
    fi
done
echo ""

# 2. Python venv 생성 (선택)
echo "🐍 2. Python venv 확인..."
if [ ! -d "$REPO_DIR/.venv" ]; then
    echo "  venv 생성: $REPO_DIR/.venv"
    python3 -m venv "$REPO_DIR/.venv"
    "$REPO_DIR/.venv/bin/pip" install --upgrade pip
    "$REPO_DIR/.venv/bin/pip" install FinanceDataReader pandas numpy pyyaml websockets pycryptodome
    echo "  ✅ venv 생성 완료"
else
    echo "  ⏭️  venv 이미 존재"
fi
echo ""

# 3. KIS API 설정 확인
echo "🔑 3. KIS API 설정 확인..."
KIS_CONFIG="$HOME/KIS/config/kis_devlp.yaml"
if [ -f "$KIS_CONFIG" ]; then
    echo "  ✅ $KIS_CONFIG 존재"
else
    echo "  ⚠️  $KIS_CONFIG 없음 — 한국투자증권 OpenAPI 신청 후 수동 생성 필요"
    echo "      참고: https://apiportal.koreainvestment.com"
fi
echo ""

# 4. DB 디렉토리 생성
echo "💾 4. DB 디렉토리 생성..."
DB_DIR="$REPO_DIR/data"
mkdir -p "$DB_DIR"
if [ ! -f "$DB_DIR/krx_flow.db" ]; then
    if [ -f "$DB_DIR/schema.sql" ]; then
        sqlite3 "$DB_DIR/krx_flow.db" < "$DB_DIR/schema.sql"
        echo "  ✅ krx_flow.db 생성 (schema.sql 적용)"
    else
        echo "  ⚠️  schema.sql 없음 — DB 미생성"
    fi
else
    echo "  ⏭️  krx_flow.db 이미 존재"
fi
echo ""

# 5. launchd 자동화 설치 (선택)
echo "⏰ 5. launchd 자동 실행 설치 (선택)..."
echo "  등록 가능한 잡 (스케줄 상세: automation/SCHEDULES.md):"
for p in "$REPO_DIR/automation/launchd"/*.plist; do
    echo "    - $(basename "$p" .plist)"
done
echo ""
echo "  전체 등록:"
echo "    cp automation/launchd/*.plist ~/Library/LaunchAgents/"
echo "    for f in ~/Library/LaunchAgents/com.jun.*.plist; do launchctl bootstrap gui/\$UID \"\$f\"; done"
echo ""
echo "  (먼저 plist 내 /Users/jun 경로를 본인 환경에 맞게 수정 필요)"
echo "  ※ 잡이 안 돌면 launchctl print-disabled gui/\$UID | grep com.jun 먼저 확인"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ 설치 완료"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "다음 단계:"
echo "  1. memory_templates/ → ~/.claude/projects/[프로젝트]/memory/ 복사 후 본인 정보 입력"
echo "  2. KIS API 설정 (~/KIS/config/kis_devlp.yaml)"
echo "  3. Claude Code 재시작"
echo "  4. \"포트폴리오 분석해줘\" 테스트"
