"""KIS 데이터 기준 장마감 차트 분석 리포트 → Discord 봇 임베드 전송.
   실행: .venv/bin/python reports/daily_report.py
   (현재가/지표 = KIS 실데이터. 손익 = 매입가 맵 기준. webhook 사용 안 함 — 봇 API 전용 2026-06-19~)"""
import sys, os, json, subprocess
sys.path.insert(0, "/Users/jun/claude-agents/kis")
sys.path.insert(0, "/Users/jun/claude-agents/lib")
import kis_data as k
from bot_send import send_embed

# 보유: 코드 -> (수량, 매입단가, 표시명, 그룹, 비고오버라이드)
# 2026-06-30 매매 반영: KODEX 인버스(위탁) 전량 매도, ISA/연금만 유지
H = [
 ("000660", 7, 1030733, "SK하이닉스", "반도체", "절반 익절 후 잔여"),
 ("423920", 16, 137325, "필라델피아레버리지(2x)", "반도체", ""),
 ("381180", 3, 46530, "필라델피아나스닥(1x)", "반도체", ""),
 ("453950", 30, 33720, "TSMC파운드리(연금)", "반도체", ""),
 ("449450", 13, 76560, "PLUS K방산", "방산건설", ""),
 ("000720", 33, 169015, "현대건설", "방산건설", ""),
 ("005385", 20, 273000, "현대차우", "부진", ""),
 ("487240", 144, 48718, "KODEX AI전력핵심설비", "부진", ""),
 ("379810", 37, 27375, "KODEX 미국나스닥100", "연금", "장기 보유"),
]
def W(n): return f"{int(round(n)):,}"
def pls(n): return f"+₩{W(n)}" if n >= 0 else f"-₩{W(abs(n))}"
def pct(n): return f"+{n:.1f}%" if n >= 0 else f"{n:.1f}%"
def kem(v): return "🔴" if v >= 0 else "🔵"   # 한국식: 상승=빨강 / 하락=파랑

def autonote(a, override):
    if override: return override
    notes = []
    if a["from_hi"] >= -0.5: notes.append("신고가")
    if a["rsi"] >= 72: notes.append("RSI 과열 ⚠️")
    if a.get("vol_ratio") and a["vol_ratio"] >= 1.8: notes.append(f"거래량 {a['vol_ratio']:.1f}x")
    return " · ".join(notes) if notes else a["align"]

def macd_hist_sign(code):
    df = k.daily_closes(code); c = df["close"]
    ema12 = c.ewm(span=12, adjust=False).mean(); ema26 = c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26; sig = macd.ewm(span=9, adjust=False).mean()
    return float((macd - sig).iloc[-1])

def main():
    data = {c[0]: k.analyze(c[0], c[3]) for c in H}
    def fld(code, qty, buy, name, override):
        a = data[code]; cur = a["last"]; pl = int(qty*(cur-buy)); plpct = (cur/buy-1)*100
        return {"name": f"{kem(a['chg'])} {name}  ({pct(a['chg'])})",
                "value": f"💵 ₩{W(cur)}\n{kem(plpct)} **{pct(plpct)}** ({pls(pl)})\n{a['align']} · RSI {a['rsi']:.1f} · {autonote(a, override)}",
                "inline": True}
    tot_buy = sum(q*b for _, q, b, _, _, _ in H)
    tot_val = sum(q*data[c]["last"] for c, q, b, _, _, _ in H)
    isa = [h for h in H if h[0] not in ("453950", "379810")]
    pen = [h for h in H if h[0] in ("453950", "379810")]
    def sub(rows):
        return sum(q*b for _, q, b, _, _, _ in rows), sum(q*data[c]["last"] for c, q, b, _, _, _ in rows)
    ib, iv = sub(isa); pb, pv = sub(pen); tpl = int(tot_val-tot_buy)

    embeds = [
     {"title": "📊 오늘의 차트 분석 · 2026-06-16 (KIS 데이터)", "color": 0x1F3A8A,
      "description": ("**반도체 슈퍼사이클 주도** — 보유 핵심 신고가 행진.\n약점: AI전력(조정)\n_색상: 🔴상승 / 🔵하락 · 데이터: 한국투자증권 KIS_")},
     {"title": "💰 전체 평가손익 (매입가 기준)", "color": 0x9B59B6, "fields": [
       {"name": "총 합계", "value": f"매입 ₩{W(tot_buy)} → 평가 ₩{W(tot_val)}\n{kem(tpl)} **{pls(tpl)} ({pct((tot_val/tot_buy-1)*100)})**", "inline": False},
       {"name": "ISA 계좌", "value": f"{kem(iv-ib)} {pls(int(iv-ib))} ({pct((iv/ib-1)*100)})", "inline": True},
       {"name": "연금저축", "value": f"{kem(pv-pb)} {pls(int(pv-pb))} ({pct((pv/pb-1)*100)})", "inline": True}]},
     {"title": "🔥 반도체 — 신고가 행진 (강세)", "color": 0x2ECC71, "fields": [fld(c, q, b, n, o) for c, q, b, n, g, o in H if g == "반도체"]},
     {"title": "⚔️ 방산·건설", "color": 0x1ABC9C, "fields": [fld(c, q, b, n, o) for c, q, b, n, g, o in H if g == "방산건설"]},
     {"title": "⚠️ 부진·조정 구간", "color": 0xE67E22, "fields": [fld(c, q, b, n, o) for c, q, b, n, g, o in H if g == "부진"]},
     {"title": "🛡️ 헤지 (위탁)", "color": 0x95A5A6, "fields": [fld(c, q, b, n, o) for c, q, b, n, g, o in H if g == "헤지"]},
     {"title": "🇺🇸 연금 (미국 장기)", "color": 0x3498DB, "fields": [fld(c, q, b, n, o) for c, q, b, n, g, o in H if g == "연금"]},
     {"title": "🎯 트리거 점검 & 액션", "color": 0xF1C40F, "fields": [
       {"name": "💰 ETF 분할매수", "value": "TSMC파운드리·PLUS K방산 분할매수/익절 트리거 점검 (MA20·MA50 도달 시 추가, ATH 돌파 시 익절)", "inline": False}],
      "footer": {"text": "데이터: 한국투자증권 KIS"}},
    ]
    # 봇 API로 임베드 전송 (webhook 사용 X)
    ids = send_embed("📈 **장 마감 차트 분석** (KIS 데이터 기준)", embeds)
    print("Discord 봇 메시지 ID:", ids)

if __name__ == "__main__":
    main()
