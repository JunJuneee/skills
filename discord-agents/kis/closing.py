"""장 마감 후(15:40) 보유 종목 종가/지표 한 줄 요약.

KIS inquire_price (정규장 J) + kis_data.analyze로 종가 + RSI + 이격도 + 정/역배열 + MA200 거리.
수급은 미반영 — 15:40 시점엔 KRX 수급 데이터 아직 미확정.
"""
import sys, os
sys.path.insert(0, "/Users/jun/claude-agents")
from kis.kis_data import analyze

# 2026-06-30 매매 반영 보유 종목 (메모리와 동기화) — KODEX 인버스 6/30 전량 매도로 위탁 보유 0
HOLDINGS = [
    # ISA
    ("000660", "SK하이닉스", "ISA", 7, 1030733),
    ("423920", "TIGER 필라델피아반도체레버리지", "ISA", 16, 137325),
    ("381180", "TIGER 필라델피아반도체나스닥", "ISA", 3, 46530),
    ("449450", "PLUS K방산", "ISA", 13, 76560),
    ("000720", "현대건설", "ISA", 33, 169015),
    ("005385", "현대차우", "ISA", 20, 273000),
    ("487240", "KODEX AI전력핵심설비", "ISA", 144, 48718),
    # 연금
    ("453950", "TIGER TSMC파운드리", "연금", 30, 33720),
    ("379810", "KODEX 미국나스닥100", "연금", 37, 27375),
]


def main():
    print("💼 보유 종목 종가 (KIS 정규장)")
    print()
    total_pnl = 0
    total_value = 0
    total_cost = 0
    for code, name, acct, qty, avg in HOLDINGS:
        try:
            a = analyze(code, name)
            if a.get("err"):
                print(f"  → {name} [{acct}] 데이터 부족")
                continue
            last = a["last"]
            chg = a["chg"]
            rsi = a.get("rsi", 0)
            align = a.get("align", "-")
            vs_ma200 = a.get("vs_ma200")
            disp50 = a.get("disp50")
            zone = a.get("disp50_zone", "")
            from_hi = a.get("from_hi", 0)

            value = last * qty
            cost = avg * qty
            pnl_amt = value - cost
            pnl_pct = (last / avg - 1) * 100
            total_value += value
            total_cost += cost
            total_pnl += pnl_amt

            arrow = "🔴" if chg >= 0 else "🔵"
            ma200_str = f"MA200 {vs_ma200:+.1f}%" if vs_ma200 is not None else "MA200 N/A"
            print(f"  → {arrow} {name} [{acct}] {last:,.0f}원 ({chg:+.2f}%)")
            print(f"     평단 {avg:,} × {qty}주 | 손익 {pnl_pct:+.2f}% ({pnl_amt:+,.0f}원)")
            print(f"     {align} | {ma200_str} | RSI {rsi:.1f} | 이격50 {disp50:.1f} ({zone}) | 52주고점 {from_hi:+.1f}%")
        except Exception as e:
            print(f"  → {name} [{acct}] err: {str(e)[:80]}")

    print()
    print("📊 전체 평가")
    if total_cost > 0:
        pct = (total_value / total_cost - 1) * 100
        print(f"  → 매입원금 {total_cost:,.0f}원 → 평가 {total_value:,.0f}원")
        print(f"  → 손익 {pct:+.2f}% ({total_pnl:+,.0f}원)")


if __name__ == "__main__":
    main()
