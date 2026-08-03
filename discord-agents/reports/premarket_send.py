"""프리마켓 알림 (쓰레드 분리, 봇 API 전용 2026-06-19~)

흐름:
  1. KIS `kis/premarket.py` 실행 → 보유 종목 프리마켓 가격 + 수급
  2. `codex exec prompts/premarket.md` 실행 → 시황 분석 (한줄요약 + 상세)
  3. **봇 API**로 메인 채널에 헤더(시황 한줄요약) 전송 → message_id 반환
  4. 같은 봇 토큰으로 그 message_id에 쓰레드 생성
  5. 쓰레드에 시황 상세 + 보유 종목 프리마켓 분할 전송

사용자 정책(2026-06-19): webhook 사용 안 함. 모든 알림은 양방향 봇(Charlie Munger#1021)으로 통일.
"""
import os, sys, subprocess, json, traceback
from datetime import datetime
sys.path.insert(0, "/Users/jun/claude-agents/lib")
from bot_send import send_message, create_thread, send_thread

BASE = "/Users/jun/claude-agents"
WORK_DIR = "/Users/jun/Desktop"


# ──────────────────── env 로드 ────────────────────
def _load_env():
    """config.sh와 secrets.env에서 환경변수 읽어 os.environ에 주입."""
    for path in (f"{BASE}/secrets.env", f"{BASE}/config.sh"):
        if not os.path.exists(path):
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

CODEX_BIN = os.environ.get("CODEX_BIN", "/opt/homebrew/bin/codex")
CODEX_MODEL = os.environ.get("CODEX_MODEL", "")
LOG_DIR = os.environ.get("LOG_DIR", f"{BASE}/logs")
os.makedirs(LOG_DIR, exist_ok=True)


def _log(msg):
    sys.stderr.write(f"[premarket_send] {msg}\n")
    sys.stderr.flush()


# ──────────────────── 데이터 수집 ────────────────────
def run_kis_premarket():
    """kis/premarket.py 실행 → 보유 종목 프리마켓 가격 + 수급 텍스트."""
    venv = f"{BASE}/.venv/bin/python"
    try:
        out = subprocess.check_output(
            [venv, f"{BASE}/kis/premarket.py"],
            cwd=BASE, timeout=120, stderr=subprocess.STDOUT,
        )
        return out.decode("utf-8", "replace").strip()
    except subprocess.CalledProcessError as e:
        return f"⚠️ KIS premarket 종료 코드 {e.returncode}\n{e.output.decode('utf-8','replace')[-1000:]}"
    except Exception as e:
        return f"⚠️ KIS premarket 실행 실패: {e}"


def run_codex_premarket():
    """codex exec로 prompts/premarket.md 실행 → 시황 분석 텍스트."""
    prompt_file = f"{BASE}/prompts/premarket.md"
    if not os.path.exists(prompt_file):
        return "⚠️ 프롬프트 파일 없음"
    prompt = open(prompt_file, encoding="utf-8").read()
    try:
        cmd = [CODEX_BIN, "exec", "--ephemeral", "--skip-git-repo-check",
               "--sandbox", "read-only", "--ignore-user-config"]
        if CODEX_MODEL:
            cmd.extend(["--model", CODEX_MODEL])
        proc = subprocess.run(
            [*cmd, prompt],
            cwd=WORK_DIR, timeout=600,
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            return f"⚠️ Codex exit {proc.returncode}\n{proc.stderr[-500:]}"
        return proc.stdout.strip()
    except subprocess.TimeoutExpired:
        return "⚠️ Codex 시간 초과(600s)"
    except Exception as e:
        return f"⚠️ Codex 실행 실패: {e}"


# ──────────────────── 요약/상세 분리 ────────────────────
def split_summary_detail(text):
    """결과 텍스트를 (요약, 상세) 두 부분으로 분리.

    프롬프트가 첫 줄에 한줄요약(예: `📌 ...`)을 두고, 그 다음 섹션부터 상세이면 깔끔히 분리됨.
    분리 안 되면 첫 3줄을 요약, 전체를 상세로.
    """
    if not text:
        return "", ""
    lines = text.split("\n")
    # 첫 섹션 헤더(`**🌎`, `**📊`, `## `, `### `)를 만나기 전까지를 요약 후보
    summary, detail = [], []
    seen_section = False
    for line in lines:
        st = line.lstrip()
        is_section = (st.startswith("**🌎") or st.startswith("**📊") or
                      st.startswith("**🎯") or st.startswith("**🧭") or
                      st.startswith("## ") or st.startswith("### "))
        if is_section:
            seen_section = True
        if seen_section:
            detail.append(line)
        else:
            summary.append(line)
    summary = "\n".join(summary).strip()
    detail = "\n".join(detail).strip()
    # 폴백: 섹션 헤더 못 찾으면 첫 3줄 요약
    if not detail:
        summary = "\n".join(lines[:3]).strip()
        detail = text
    if not summary:
        summary = "📌 상세는 쓰레드 참고"
    return summary, detail


# ──────────────────── main ────────────────────
def main():
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = f"{LOG_DIR}/premarket_{stamp}.md"

    _log(f"시작 {today}")

    # 1. 시황 (Codex)
    _log("Codex 시황 생성 중...")
    codex_out = run_codex_premarket()
    summary, detail = split_summary_detail(codex_out)

    # 2. 보유 종목 프리마켓 (KIS)
    _log("KIS 보유 종목 프리마켓 조회 중...")
    holdings = run_kis_premarket()

    # 출력 결과를 파일에도 저장 (디버깅용)
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"# premarket {today}\n\n## 요약\n{summary}\n\n## 상세\n{detail}\n\n## 보유 종목 프리마켓\n```\n{holdings}\n```\n")
    except Exception:
        pass

    # 3. 헤더 메시지 (봇 API) → message_id 즉시 반환
    header = f"🌎 **[{today}] 시황**\n{summary}"
    _log("헤더 메시지 전송 중 (봇 API)...")
    ids = send_message(header)
    message_id = ids[0] if ids else None
    if not message_id:
        _log("헤더 메시지 전송 실패")
        return 1

    # 4. 쓰레드 생성
    thread_name = f"📊 {today} 상세"
    _log(f"쓰레드 생성: msg={message_id}")
    thread_id = create_thread(message_id, thread_name)

    if not thread_id:
        _log("쓰레드 생성 실패 — 메인 채널 폴백 전송")

    # 5. 상세 내용 전송
    sections = []
    if detail:
        sections.append(f"📰 **시황 상세**\n{detail}")
    if holdings:
        # 한글 정렬 깨지는 표가 들어가지 않게 code block으로 감쌈
        sections.append(f"💼 **보유 종목 프리마켓**\n```\n{holdings}\n```")

    for sec in sections:
        if thread_id:
            send_thread(sec, thread_id)
        else:
            send_message(sec)

    _log(f"완료 — 로그: {out_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        _log(f"FATAL: {e}\n{traceback.format_exc()}")
        sys.exit(1)
