"""KIS(한국투자증권) 데이터 모듈 — 현재가/일봉/잔고. open-trading-api 공식 모듈 재사용.
   일봉은 호출당 100행 제한 → 페이지네이션으로 16개월치 확보(MA200 계산용)."""
import sys, os
import pandas as pd
from datetime import datetime, timedelta

KIS_REPO = "/Users/jun/Desktop/open-trading-api/examples_llm"
for _p in [KIS_REPO,
           os.path.join(KIS_REPO, "domestic_stock/inquire_price"),
           os.path.join(KIS_REPO, "domestic_stock/inquire_daily_itemchartprice"),
           os.path.join(KIS_REPO, "domestic_stock/inquire_balance")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import kis_auth as ka
from inquire_price import inquire_price
from inquire_daily_itemchartprice import inquire_daily_itemchartprice as _daily
from inquire_balance import inquire_balance as _balance

_authed = False
def _ensure_auth():
    global _authed
    if not _authed:
        ka.auth(svr="prod")
        _authed = True

def daily_closes(code, min_days=340):
    """code의 일봉 종가/거래량을 min_days 이상 확보해 날짜오름차순 DataFrame(close,vol)로 반환."""
    _ensure_auth()
    frames = []; end = datetime.today(); got = 0
    for _ in range(6):  # 최대 6회 (~600 거래일)
        d2 = end.strftime("%Y%m%d"); d1 = (end - timedelta(days=160)).strftime("%Y%m%d")
        _, o2 = _daily("real", "J", code, d1, d2, "D", "1")
        if o2 is None or len(o2) == 0:
            break
        frames.append(o2[["stck_bsop_date", "stck_clpr", "acml_vol"]].copy())
        oldest = o2["stck_bsop_date"].iloc[-1]; got += len(o2)
        if got >= min_days:
            break
        end = datetime.strptime(oldest, "%Y%m%d") - timedelta(days=1)
    if not frames:
        return pd.DataFrame(columns=["close", "vol"])
    df = pd.concat(frames).drop_duplicates("stck_bsop_date")
    df = df[df["stck_clpr"].astype(str).str.len() > 0]
    df["d"] = pd.to_datetime(df["stck_bsop_date"], format="%Y%m%d")
    df = df.sort_values("d")
    df["close"] = df["stck_clpr"].astype(float)
    df["vol"] = df["acml_vol"].astype(float)
    return df.set_index("d")[["close", "vol"]]

def current_price(code):
    """현재가/전일대비율 snapshot (실시간)."""
    _ensure_auth()
    p = inquire_price("real", "J", code)
    if p is None or len(p) == 0:
        return None
    return {"price": float(p["stck_prpr"].iloc[0]), "chg": float(p["prdy_ctrt"].iloc[0])}

def _rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return (100 - 100/(1 + up/dn)).iloc[-1]

def analyze(code, name):
    """KIS 일봉 기반 기술지표. (현재가는 일봉 최신=장중 현재가 반영)"""
    df = daily_closes(code)
    if len(df) < 30:
        return {"code": code, "name": name, "err": "데이터 부족"}
    c = df["close"]; last = float(c.iloc[-1]); prev = float(c.iloc[-2])
    ma20 = float(c.rolling(20).mean().iloc[-1]); ma50 = float(c.rolling(50).mean().iloc[-1])
    ma200 = float(c.rolling(200).mean().iloc[-1]) if len(c) >= 200 else None
    rsi = float(_rsi(c)); hi52 = float(c.tail(252).max())
    vr = float(df["vol"].iloc[-1]) / float(df["vol"].tail(20).mean()) if df["vol"].tail(20).mean() else None
    align = "정배열" if (ma200 and last > ma20 > ma50 > ma200) else ("역배열" if (ma200 and last < ma20 < ma50 < ma200) else "혼조")
    # 현재가는 실시간 snapshot 우선
    cp = current_price(code)
    chg = cp["chg"] if cp else (last/prev-1)*100
    if cp: last = cp["price"]
    disp50 = last/ma50*100  # 이격도(disparity) = 현재가 / MA50 × 100
    if disp50 >= 140: zone = "극단(140%+)"
    elif disp50 >= 130: zone = "과열(130%+)"
    elif disp50 >= 120: zone = "경계(120%+)"
    elif disp50 <= 80: zone = "과매도(80%-)"
    else: zone = "정상"
    return {"code": code, "name": name, "last": last, "chg": chg,
            "ma20": ma20, "ma50": ma50, "ma200": ma200,
            "vs_ma20": (last/ma20-1)*100, "vs_ma50": (last/ma50-1)*100,
            "vs_ma200": (last/ma200-1)*100 if ma200 else None,
            "disp20": last/ma20*100, "disp50": disp50,
            "disp200": last/ma200*100 if ma200 else None, "disp50_zone": zone,
            "rsi": rsi, "align": align, "hi52": hi52, "from_hi": (last/hi52-1)*100,
            "vol_ratio": vr, "asof": str(df.index[-1].date())}

def balance():
    """실계좌 보유종목 + 손익 (계좌번호가 yaml에 설정돼야 작동)."""
    _ensure_auth()
    tr = ka.getTREnv()
    d1, d2 = _balance(env_dv="real", cano=tr.my_acct, acnt_prdt_cd=tr.my_prod,
                      afhr_flpr_yn="N", inqr_dvsn="02", unpr_dvsn="01",
                      fund_sttl_icld_yn="N", fncg_amt_auto_rdpt_yn="N", prcs_dvsn="00")
    return d1, d2
