"""장 마감 알림 (15:40 평일 cron, 쓰레드 분리).

흐름:
  1. KIS `kis/closing.py` 실행 → 보유 종목 종가/등락/RSI/이격도
  2. `codex exec prompts/portfolio.md` 실행 → v1.8 5단계 분석 (한줄요약 + 상세)
  3. 봇 API로 메인 채널에 헤더(한줄요약) → message_id
  4. 그 message_id에 쓰레드 생성
  5. 쓰레드에 시황 상세 + 보유 종목 종가 분할 전송

기존 `premarket_send.py`와 동일 패턴 — 프롬프트/KIS 모듈만 다름.
"""
import os, sys, subprocess, traceback
from datetime import datetime
sys.path.insert(0, "/Users/jun/claude-agents/lib")
from bot_send import send_message, create_thread, send_thread

BASE = "/Users/jun/claude-agents"
WORK_DIR = "/Users/jun/Desktop"


def _load_env():
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
    sys.stderr.write(f"[closing_send] {msg}\n")
    sys.stderr.flush()


def run_kis_closing():
    """kis/closing.py 실행 → 보유 종목 종가/지표 텍스트."""
    venv = f"{BASE}/.venv/bin/python"
    try:
        out = subprocess.check_output(
            [venv, f"{BASE}/kis/closing.py"],
            cwd=BASE, timeout=120, stderr=subprocess.STDOUT,
        )
        return out.decode("utf-8", "replace").strip()
    except subprocess.CalledProcessError as e:
        return f"⚠️ KIS closing 종료코드 {e.returncode}\n{e.output.decode('utf-8','replace')[-1000:]}"
    except Exception as e:
        return f"⚠️ KIS closing 실행 실패: {e}"


def run_codex_portfolio():
    """codex exec로 prompts/portfolio.md 실행 → 포트폴리오 분석 텍스트."""
    prompt_file = f"{BASE}/prompts/portfolio.md"
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


def split_summary_detail(text):
    """결과 텍스트를 (요약, 상세) 두 부분으로 분리. premarket과 동일 로직."""
    if not text:
        return "", ""
    lines = text.split("\n")
    summary, detail = [], []
    seen_section = False
    for line in lines:
        st = line.lstrip()
        is_section = (st.startswith("**📊") or st.startswith("**💼") or
                      st.startswith("**🎯") or st.startswith("**🧭") or
                      st.startswith("**🌎") or
                      st.startswith("## ") or st.startswith("### "))
        if is_section:
            seen_section = True
        if seen_section:
            detail.append(line)
        else:
            summary.append(line)
    summary = "\n".join(summary).strip()
    detail = "\n".join(detail).strip()
    if not detail:
        summary = "\n".join(lines[:3]).strip()
        detail = text
    if not summary:
        summary = "📌 상세는 쓰레드 참고"
    return summary, detail


def main():
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = f"{LOG_DIR}/closing_{stamp}.md"

    _log(f"시작 {today}")

    # 1. 시황 (Codex)
    _log("Codex 포트폴리오 분석 생성 중...")
    codex_out = run_codex_portfolio()
    summary, detail = split_summary_detail(codex_out)

    # 2. 보유 종목 종가 (KIS)
    _log("KIS 보유 종목 종가/지표 조회 중...")
    holdings = run_kis_closing()

    # 디버그용 로그 파일
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"# closing {today}\n\n## 요약\n{summary}\n\n## 상세\n{detail}\n\n## 보유 종가\n```\n{holdings}\n```\n")
    except Exception:
        pass

    # 3. 헤더 메시지 (봇 API)
    header = f"📊 **[{today}] 장 마감 포트폴리오**\n{summary}"
    _log("헤더 전송 중 (봇 API)...")
    ids = send_message(header)
    message_id = ids[0] if ids else None
    if not message_id:
        _log("헤더 전송 실패")
        return 1

    # 4. 쓰레드 생성
    thread_name = f"💼 {today} 상세"
    _log(f"쓰레드 생성: msg={message_id}")
    thread_id = create_thread(message_id, thread_name)
    if not thread_id:
        _log("쓰레드 생성 실패 — 메인 채널 폴백")

    # 5. 상세 + 종가
    sections = []
    if detail:
        sections.append(f"📰 **포트폴리오 분석**\n{detail}")
    if holdings:
        sections.append(f"💼 **보유 종목 종가/지표**\n```\n{holdings}\n```")

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
