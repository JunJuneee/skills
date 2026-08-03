"""스쿼드 자율 토론 가드 + 레지스트리 + 멘션 유틸.

양방향 봇이 #squad에서 서로 멘션하면 무한루프/토큰 폭증 위험이 있다.
가드 핵심:
  - 본인 메시지 무시 (role_bot에서 처리)
  - 멘션 없는 메시지엔 무반응 (role_bot에서 처리)
  - 연속 봇-턴 상한: 사람 개입 없이 봇-대-봇 N턴 초과 시 정지 + "사람 결정 필요"
  - 봇당 응답 최소 간격(레이트리밋)
레지스트리(registry.json): 각 봇이 on_ready 때 {role: discord_user_id} 를 기록 →
  멘션 대상 봇의 user_id 를 알아내고(@role → <@id>), 알려진 스쿼드 봇끼리만 상호 트리거 허용.
"""
import json
import os
import re
import time
from pathlib import Path

ROLES = ["po", "designer", "frontend", "backend", "qa", "blog"]

# ── 가드 설정 ────────────────────────────────────────────────
MAX_BOT_TURNS = 6        # 사람 개입 없이 허용되는 #squad 봇-대-봇 연속 메시지 수
HISTORY_FETCH = 25       # 가드 판정 시 조회할 최근 메시지 수
MIN_REPLY_GAP = 4.0      # 같은 봇의 연속 응답 최소 간격(초)

RUNTIME_STATE_DIR = Path(os.environ.get("SQUAD_STATE_DIR", "/Users/jun/Library/Application Support/JunClaudeAgents/squad"))
REGISTRY = RUNTIME_STATE_DIR / "registry.json"
STOP_FLAG = RUNTIME_STATE_DIR / "squad_stopped.flag"  # 정지 시 중복 안내 방지


# ── 레지스트리 ───────────────────────────────────────────────
def register(role, user_id):
    """on_ready 때 자기 role→user_id 를 레지스트리에 병합 기록."""
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    data = load_registry()
    data[role] = str(user_id)
    REGISTRY.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_registry():
    try:
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    except Exception:
        return {}


def known_bot_ids():
    """알려진 스쿼드 봇 user_id 집합 (상호 트리거 허용 대상)."""
    return {str(v) for v in load_registry().values()}


def owner_id():
    """사람(오너) Discord ID — ALLOWED_USER_IDS 의 첫 번째. 확인 요청 멘션 대상."""
    ids = [x.strip() for x in os.environ.get("ALLOWED_USER_IDS", "").split(",") if x.strip()]
    return ids[0] if ids else ""


def mentionify(text):
    """응답 텍스트의 @role / @사용자 토큰을 실제 Discord 멘션 <@id> 로 치환.
    레지스트리에 없는 역할은 그대로 둠."""
    reg = load_registry()
    def repl(m):
        role = m.group(1).lower()
        uid = reg.get(role)
        return f"<@{uid}>" if uid else m.group(0)
    text = re.sub(r"@(po|designer|frontend|backend|qa|blog)\b", repl, text, flags=re.IGNORECASE)
    oid = owner_id()
    if oid:
        text = re.sub(r"@(사용자|오너|owner|jun|준|관리자)\b", f"<@{oid}>", text, flags=re.IGNORECASE)
    return text


# ── 가드 ─────────────────────────────────────────────────────
def trailing_bot_turns(messages):
    """가장 최근 사람 메시지 이후의 (사람 아닌) 메시지 수.
    messages: 시간 오름차순(과거→현재) discord.Message 리스트."""
    count = 0
    for m in reversed(messages):
        if m.author.bot:
            count += 1
        else:
            break
    return count


def should_stop(messages):
    """봇-대-봇 연속 턴이 상한을 넘었으면 True (응답 중단해야 함)."""
    return trailing_bot_turns(messages) >= MAX_BOT_TURNS


def clear_stop():
    try:
        STOP_FLAG.unlink()
    except FileNotFoundError:
        pass


def mark_stopped_once():
    """정지 안내를 채널당 1회만 보내도록. 이미 보냈으면 False."""
    if STOP_FLAG.exists():
        return False
    STOP_FLAG.write_text(str(int(time.time())), encoding="utf-8")
    return True
