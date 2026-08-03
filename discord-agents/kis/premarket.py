"""장전 프리마켓(NXT/통합) 현황 + 수급(외국인/기관 일별) 스냅샷.

08:01 cron 시점에 호출. KIS UN(KRX+NXT 통합) 시장 구분으로 NXT 프리마켓 가격 우선,
없으면 KRX 예상체결가 폴백.

2026-06-19 매매 반영 — HOLD + WATCH(관심) 두 섹션.
"""
import sys, os
import pandas as pd

R = "/Users/jun/Desktop/open-trading-api/examples_llm"
for s in ["", "domestic_stock/inquire_asking_price_exp_ccn", "domestic_stock/inquire_investor"]:
    p = os.path.join(R, s)
    if p not in sys.path: sys.path.insert(0, p)
import kis_auth as ka
from inquire_asking_price_exp_ccn import inquire_asking_price_exp_ccn as exp
from inquire_investor import inquire_investor as inv
ka.auth(svr="prod")


# 보유 (ISA / 연금) — 2026-06-30 매매 반영, KODEX 인버스 전량 매도로 위탁 0
HOLD = [
    ("000660", "SK하이닉스", "ISA"),
    ("005385", "현대차우", "ISA"),
    ("423920", "TIGER 필라델피아반도체레버리지", "ISA"),
    ("000720", "현대건설", "ISA"),
    ("381180", "TIGER 필라델피아반도체나스닥", "ISA"),
    ("449450", "PLUS K방산", "ISA"),
    ("487240", "KODEX AI전력핵심설비", "ISA"),
    ("453950", "TIGER TSMC파운드리", "연금"),
    ("379810", "KODEX 미국나스닥100", "연금"),
]

# Watchlist — 한국 종목 (US 종목은 KIS 도메스틱 API로 조회 불가, premarket에 미포함)
WATCH = [
    ("267260", "HD현대일렉트릭"),
    ("298040", "효성중공업"),
    ("010120", "LS ELECTRIC"),
    ("396270", "넥스트칩"),
    ("403870", "HPSP"),
    ("240810", "원익IPS"),
    ("042700", "한미반도체"),
]


def f(s):
    try: return float(str(s).replace(",", ""))
    except: return 0.0


def _print_premarket(code, name, tag, include_supply=True):
    """종목 1개 프리마켓 출력. include_supply=True면 외국인/기관 수급도."""
    print(f"\n#### {code} {name} [{tag}]")
    try:
        o1, o2 = exp(env_dv="real", fid_cond_mrkt_div_code="UN", fid_input_iscd=code)
        r1 = o1.iloc[0].to_dict() if o1 is not None and len(o1) else {}
        r2 = o2.iloc[0].to_dict() if o2 is not None and len(o2) else {}
        prpr = f(r2.get("stck_prpr")); sdpr = f(r2.get("stck_sdpr"))
        antc = f(r2.get("antc_cnpr"))
        px = prpr if prpr > 0 else antc
        oprc = f(r2.get("stck_oprc")); hg = f(r2.get("stck_hgpr")); lw = f(r2.get("stck_lwpr"))
        bid = f(r1.get("bidp1")); ask = f(r1.get("askp1"))
        if px > 0 and sdpr > 0:
            chg = px - sdpr; ctrt = chg / sdpr * 100
            src = "NXT프리마켓" if prpr > 0 else "KRX예상"
            print(f"  💹 {src}: {px:,.0f}원  전일대비 {chg:+,.0f} ({ctrt:+.2f}%)  [전일종가 {sdpr:,.0f}]")
            if hg > 0:
                print(f"     시 {oprc:,.0f} / 고 {hg:,.0f} / 저 {lw:,.0f}  |  매수1 {bid:,.0f} 매도1 {ask:,.0f}")
        else:
            print(f"  💤 프리마켓 거래 없음 (전일종가 {sdpr:,.0f})")
    except Exception as e:
        print("  프리마켓 err:", str(e)[:90])

    if include_supply:
        try:
            df = inv(env_dv="real", fid_cond_mrkt_div_code="J", fid_input_iscd=code)
            if df is not None and len(df):
                shown = 0
                for _, rr in df.iterrows():
                    d = rr.to_dict()
                    if f(d.get("frgn_shnu_vol")) == 0 and f(d.get("frgn_seln_vol")) == 0 and f(d.get("frgn_ntby_qty")) == 0:
                        continue
                    frgn = f(d.get("frgn_ntby_qty")); orgn = f(d.get("orgn_ntby_qty")); prsn = f(d.get("prsn_ntby_qty"))
                    frgn_a = f(d.get("frgn_ntby_tr_pbmn")) / 100  # 백만→억
                    orgn_a = f(d.get("orgn_ntby_tr_pbmn")) / 100
                    print(f"  📊 {d.get('stck_bsop_date')} 외 {frgn:+,.0f}주({frgn_a:+,.0f}억) / 기 {orgn:+,.0f}주({orgn_a:+,.0f}억) / 개 {prsn:+,.0f}주")
                    shown += 1
                    if shown >= 3: break
        except Exception as e:
            print("  수급 err:", str(e)[:90])


print("═══ 💼 보유 종목 프리마켓 ═══")
for code, name, acct in HOLD:
    _print_premarket(code, name, acct, include_supply=True)

print("\n\n═══ 👀 Watchlist 프리마켓 ═══")
for code, name in WATCH:
    _print_premarket(code, name, "WL", include_supply=False)  # WL은 수급 생략(메시지 길이 절약)
