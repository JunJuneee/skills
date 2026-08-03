#!/bin/bash
# Discord 전송 헬퍼 (봇 API 전용, 2026-06-19~ webhook 폐기).
# 사용법:  notify_discord "제목" "본문문자열"
#          notify_discord_file "제목" "/경로/리포트.md"
#
# 환경변수 (secrets.env):
#   DISCORD_BOT_TOKEN — 봇 토큰
#   DISCORD_CHANNEL_ID — 대상 채널 ID
# 봇 이름은 봇 자체 계정(Charlie Munger#1021)을 사용하므로 username override 불가.

# 텍스트 메시지 전송 (2000자 초과 시 자동 분할)
notify_discord() {
  local title="$1"
  local body="$2"

  if [[ -z "${DISCORD_BOT_TOKEN:-}" || -z "${DISCORD_CHANNEL_ID:-}" ]]; then
    echo "[notify] DISCORD_BOT_TOKEN 또는 DISCORD_CHANNEL_ID 미설정 — 전송 생략" >&2
    return 1
  fi

  TITLE="$title" BODY="$body" python3 - <<'PY'
import os, sys
sys.path.insert(0, "/Users/jun/claude-agents/lib")
from bot_send import send_message
title = os.environ.get("TITLE", "")
body = os.environ.get("BODY", "")
full = f"**{title}**\n{body}" if title else body
ids = send_message(full)
if not ids:
    print("[notify] 봇 전송 실패", file=sys.stderr)
PY
}

# 파일 첨부 전송 (긴 리포트용). 봇 API multipart 사용.
notify_discord_file() {
  local title="$1"
  local file="$2"

  if [[ -z "${DISCORD_BOT_TOKEN:-}" || -z "${DISCORD_CHANNEL_ID:-}" ]]; then
    echo "[notify] DISCORD_BOT_TOKEN 또는 DISCORD_CHANNEL_ID 미설정 — 전송 생략" >&2
    return 1
  fi

  local cid="${DISCORD_CHANNEL_ID}"
  local content="📄 **${title}** (전문 첨부)"
  local pj
  pj=$(python3 -c "import json,os; print(json.dumps({'content': os.environ['C']}))" C="$content")

  curl -sS \
    -H "Authorization: Bot ${DISCORD_BOT_TOKEN}" \
    -F "payload_json=${pj}" \
    -F "files[0]=@${file};filename=report.md" \
    "https://discord.com/api/v10/channels/${cid}/messages" >/dev/null
}
