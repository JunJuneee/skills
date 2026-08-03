"""Discord 봇 API 메시지 헬퍼 (webhook 완전 대체, 2026-06-19부터).

사용자 정책: webhook 사용 안 함. 모든 알림은 양방향 봇(Charlie Munger#1021) 계정으로 발송 →
  • 봇 이름/아바타 일관성
  • Cloudflare(1010) 차단 문제 우회
  • 쓰레드 생성/메시지 전송 동일 권한 모델

환경변수 (secrets.env):
  DISCORD_BOT_TOKEN — 봇 토큰
  DISCORD_CHANNEL_ID — 기본 대상 채널 ID

import 예시:
  from bot_send import send_message, create_thread, send_thread
"""
import os, json, subprocess
from pathlib import Path

BASE = Path("/Users/jun/claude-agents")
API = "https://discord.com/api/v10"


def _load_env():
    for path in (BASE / "secrets.env", BASE / "config.sh"):
        if not path.exists():
            continue
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line.startswith("export "):
                line = line[7:]
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()


def _token():
    return os.environ.get("DISCORD_BOT_TOKEN", "")


def _channel():
    return os.environ.get("DISCORD_CHANNEL_ID", "")


def _api(method, path, data=None):
    """Discord API 호출. curl 사용 (Python urllib은 Cloudflare에 막힘 이력)."""
    if not _token():
        return ""
    args = ["curl", "-sS", "-X", method,
            "-H", f"Authorization: Bot {_token()}",
            "-H", "Content-Type: application/json"]
    if data is not None:
        args += ["--data-binary", json.dumps(data)]
    args.append(f"{API}{path}")
    try:
        out = subprocess.check_output(args, timeout=15, stderr=subprocess.STDOUT)
        return out.decode("utf-8", "replace")
    except subprocess.CalledProcessError as e:
        return f"__ERR__ rc={e.returncode} {e.output.decode('utf-8','replace')[:200]}"
    except Exception as e:
        return f"__ERR__ {e}"


def _chunk(content, limit=1900):
    """긴 텍스트를 줄 단위로 분할."""
    chunks = []
    cur = ""
    for line in content.split("\n"):
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) + 1 > limit:
            if cur:
                chunks.append(cur)
            cur = line
        else:
            cur = cur + "\n" + line if cur else line
    if cur:
        chunks.append(cur)
    return chunks


def send_message(content, channel_id=None, suppress_embeds=True):
    """채널/쓰레드에 메시지 전송. 1900자 초과 시 자동 분할.
    Returns: 전송된 message_id 리스트 (분할 시 여러 개)."""
    cid = channel_id or _channel()
    if not cid:
        return []
    ids = []
    for ch in _chunk(content):
        payload = {"content": ch}
        if suppress_embeds:
            payload["flags"] = 4  # SUPPRESS_EMBEDS
        res = _api("POST", f"/channels/{cid}/messages", payload)
        try:
            ids.append(json.loads(res).get("id"))
        except Exception:
            pass
    return ids


def create_thread(message_id, name, channel_id=None, auto_archive=1440):
    """기존 메시지에 쓰레드 생성. Returns: thread_id 또는 None."""
    cid = channel_id or _channel()
    if not cid or not message_id:
        return None
    res = _api("POST", f"/channels/{cid}/messages/{message_id}/threads",
               {"name": str(name)[:90], "auto_archive_duration": auto_archive})
    try:
        return json.loads(res).get("id")
    except Exception:
        return None


def send_thread(content, thread_id, suppress_embeds=True):
    """쓰레드에 메시지 전송 (send_message의 thread_id 지정 별칭)."""
    return send_message(content, channel_id=thread_id, suppress_embeds=suppress_embeds)


def send_embed(content, embeds, channel_id=None):
    """임베드(embeds 리스트) 포함 메시지 전송.
    Discord 임베드는 메시지당 10개 제한, 1개 임베드 6000자 제한.
    Returns: 전송된 message_id 리스트."""
    cid = channel_id or _channel()
    if not cid:
        return []
    ids = []
    # 임베드는 분할 못 하므로 10개씩 묶어 여러 메시지로
    for i in range(0, len(embeds), 10):
        batch = embeds[i:i + 10]
        payload = {"content": content if i == 0 else "", "embeds": batch}
        res = _api("POST", f"/channels/{cid}/messages", payload)
        try:
            ids.append(json.loads(res).get("id"))
        except Exception:
            pass
    return ids


# CLI 테스트: python -m bot_send "메시지"
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        msg = " ".join(sys.argv[1:])
        ids = send_message(msg)
        print(f"sent: {ids}")
    else:
        print("Usage: python bot_send.py <message>")
