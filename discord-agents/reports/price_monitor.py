"""장중 가격 모니터 (5분 주기 polling).

흐름:
  1. data/monitor_rules.json 로드
  2. 평일 09:00~15:30 KST 이외엔 즉시 종료
  3. KIS inquire_price로 각 종목 현재가 조회
  4. 트리거 라인 매칭 (below: 가격 ≤ trigger.price / above: 가격 ≥ trigger.price)
  5. 상태 파일(logs/monitor_state.json) 비교:
       - 오늘 이미 알린 트리거는 차단
       - 가격이 라인 +1% 위로 회복되면 상태 리셋
  6. 새 트리거 → Discord webhook (curl) 단발 메시지

launchd 5분 주기에서 호출. `--dry-run`은 알림 없이 매핑만 출력.
"""
import os, sys, json, subprocess, argparse, traceback
from datetime import datetime, time as dtime
from pathlib import Path

BASE = Path("/Users/jun/claude-agents")
RULES_PATH = BASE / "data" / "monitor_rules.json"
STATE_PATH = BASE / "logs" / "monitor_state.json"
LOG_PATH = BASE / "logs" / "price_monitor.log"

# Discord 봇 API 모듈 (webhook 대체, 2026-06-19~)
sys.path.insert(0, str(BASE / "lib"))
from bot_send import send_message


# ──────────────────── env ────────────────────
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


def _log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    sys.stderr.write(line + "\n")
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ──────────────────── 장 시간 판단 ────────────────────
def is_market_hours(now=None):
    """평일 09:00~15:30 KST. 공휴일은 별도 체크 안 함 (launchd로 평일만 호출)."""
    now = now or datetime.now()
    if now.weekday() >= 5:  # 5=토, 6=일
        return False
    t = now.time()
    return dtime(9, 0) <= t <= dtime(15, 30)


# ──────────────────── KIS 시세 ────────────────────
_KIS_AUTHED = False


def kis_price(code, market="J"):
    """KIS 현재가 조회. market: 'J'=주식/ETF, 'U'=지수(KOSPI 0001 등). dict {price, chg}."""
    global _KIS_AUTHED
    R = "/Users/jun/Desktop/open-trading-api/examples_llm"
    for s in ["", "domestic_stock/inquire_price", "domestic_stock/inquire_index_price"]:
        p = os.path.join(R, s)
        if p not in sys.path:
            sys.path.insert(0, p)
    import kis_auth as ka

    if not _KIS_AUTHED:
        ka.auth(svr="prod")
        _KIS_AUTHED = True

    if market == "U":
        # 업종 지수: inquire_index_price (KOSPI 0001, KOSDAQ 1001, KOSPI200 2001 ...)
        from inquire_index_price import inquire_index_price
        df = inquire_index_price(fid_cond_mrkt_div_code="U", fid_input_iscd=code)
        if df is None or len(df) == 0:
            return None
        return {
            "price": float(df["bstp_nmix_prpr"].iloc[0]),
            "chg": float(df["bstp_nmix_prdy_ctrt"].iloc[0]),
        }
    # 기본: 주식/ETF
    from inquire_price import inquire_price
    df = inquire_price("real", "J", code)
    if df is None or len(df) == 0:
        return None
    return {
        "price": float(df["stck_prpr"].iloc[0]),
        "chg": float(df["prdy_ctrt"].iloc[0]),
    }


# ──────────────────── 상태 파일 ────────────────────
def load_state():
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


# ──────────────────── 트리거 평가 ────────────────────
def evaluate(rule, price):
    """현재가에 대해 룰의 어떤 트리거가 hit 됐는지 리스트로 반환."""
    hits = []
    for t in rule["triggers"]:
        dir_ = t.get("dir", "below")
        if dir_ == "below" and price <= t["price"]:
            hits.append(t)
        elif dir_ == "above" and price >= t["price"]:
            hits.append(t)
    return hits


def should_alert(state, code, line, price, trigger):
    """오늘 이미 알린 트리거는 차단. 단, 가격이 라인 +/-1% 밖으로 회복했으면 리셋."""
    key = f"{code}:{line}"
    prev = state.get(key)
    today = datetime.now().strftime("%Y-%m-%d")
    if not prev:
        return True
    # 회복 체크: below 라인이면 가격이 +1% 위로 회복 시 리셋, above면 -1% 아래 리셋
    dir_ = trigger.get("dir", "below")
    margin = trigger["price"] * 0.01
    if dir_ == "below" and price > trigger["price"] + margin:
        return True  # 회복 후 재이탈 → 재알림
    if dir_ == "above" and price < trigger["price"] - margin:
        return True
    # 같은 날 이미 알림 → 차단
    return prev.get("alerted_at") != today


# ──────────────────── Discord 알림 (봇 API) ────────────────────
def send_discord(content):
    """봇 API로 단발 알림 전송."""
    ids = send_message(content)
    if not ids:
        _log("Discord 봇 전송 실패")


def format_alert(rule, trigger, price):
    """트리거 알림 메시지 포맷."""
    dir_ = trigger.get("dir", "below")
    diff = (price - trigger["price"]) / trigger["price"] * 100
    arrow = "📉 이탈" if dir_ == "below" else "📈 돌파"
    return (
        f"🚨 **[{rule['name']}] {trigger['line']} {trigger['label']} {arrow}**\n"
        f"• 코드: `{rule['code']}` · 종류: {rule['kind']}\n"
        f"• 현재가: **{int(price):,}원** ({diff:+.2f}% vs 라인)\n"
        f"• 트리거 라인: {trigger['color']} {int(trigger['price']):,}원\n"
        f"• 시각: {datetime.now().strftime('%H:%M')} KST\n"
        f"• 💡 액션: {trigger.get('action', '')}"
    )


# ──────────────────── main ────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="알림 없이 현재가/라인 매핑만 출력")
    ap.add_argument("--force", action="store_true",
                    help="장 시간 아니어도 강제 실행 (테스트용)")
    args = ap.parse_args()

    if not args.force and not is_market_hours():
        _log(f"장 시간 아님 ({datetime.now().strftime('%a %H:%M')}) — 종료")
        return 0

    if not RULES_PATH.exists():
        _log(f"룰 파일 없음: {RULES_PATH}")
        return 1
    cfg = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    rules = cfg.get("rules", [])
    if not rules:
        _log("룰 없음 — 종료")
        return 0

    state = load_state()
    today = datetime.now().strftime("%Y-%m-%d")
    new_alerts = 0

    for rule in rules:
        code = rule["code"]
        market = rule.get("market", "J")
        try:
            p = kis_price(code, market=market)
        except Exception as e:
            _log(f"{code} KIS 조회 실패: {e}")
            continue
        if not p:
            _log(f"{code} 가격 데이터 없음")
            continue
        price = p["price"]
        hits = evaluate(rule, price)

        # dry-run: 매핑만 출력
        if args.dry_run:
            line_status = []
            for t in rule["triggers"]:
                hit_mark = "✅HIT" if t in hits else "─"
                dist = (price - t["price"]) / t["price"] * 100
                line_status.append(
                    f"  {hit_mark} {t['line']} {t['color']} {int(t['price']):,} ({dist:+.2f}%) — {t['label']}"
                )
            print(f"\n▶ {rule['name']} ({code}) 현재가 {int(price):,}원 ({p['chg']:+.2f}%)")
            print("\n".join(line_status))
            continue

        # 실제 알림 처리
        for t in hits:
            if not should_alert(state, code, t["line"], price, t):
                continue
            msg = format_alert(rule, t, price)
            _log(f"ALERT {code} {t['line']} @ {int(price):,}")
            send_discord(msg)
            state[f"{code}:{t['line']}"] = {
                "alerted_at": today,
                "last_price": int(price),
                "line_price": t["price"],
            }
            new_alerts += 1

    if not args.dry_run:
        save_state(state)
        _log(f"완료 — 신규 알림 {new_alerts}건, 룰 {len(rules)}개 처리")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        _log(f"FATAL: {e}\n{traceback.format_exc()}")
        sys.exit(1)
