"""프리마켓 예상체결가 조회 — 보유/Watchlist + 시장 TOP"""
import sys, os, time
from datetime import datetime
sys.path.insert(0, os.path.expanduser('~/Desktop/open-trading-api/examples_llm'))
import kis_auth as ka
import pandas as pd

ka.auth()
print(f"조회 시각: {datetime.now().strftime('%H:%M:%S')}\n")

API_PRICE = "/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn"
API_RANK = "/uapi/domestic-stock/v1/ranking/exp-trans-updown"

TARGETS = [
    ('000660','SK하이닉스 ⭐'),('442580','PLUS HBM ⭐'),('005385','현대차우 ⭐'),
    ('423920','TIGER필라레버리지 ⭐'),('000720','현대건설 ⭐'),('010120','LS ELECTRIC ⭐'),
    ('381180','TIGER필라나스닥 ⭐'),('449450','PLUS K방산 ⭐'),('487240','KODEX AI전력 ⭐'),
    ('453950','TIGER TSMC ⭐'),('379810','KODEX 나스닥100 ⭐'),
    ('064350','현대로템 ⚡'),('012450','한화에어로 ⚡'),('082740','한화엔진 ⚡'),
    ('000880','한화 ⚡'),('267260','HD현대일렉트릭 ⚡'),('298040','효성중공업 ⚡'),
    ('005490','POSCO홀딩스 ⚡'),('009150','삼성전기 ⚡'),
]

print("="*88)
print("  📊 보유 + Watchlist 프리마켓 예상체결")
print("="*88)
print(f"{'종목':<24s} {'예상가':>10s} {'전일대비':>9s} {'예상량':>10s}")
print('-'*60)

for code, name in TARGETS:
    params = {"FID_COND_MRKT_DIV_CODE":"J","FID_INPUT_ISCD":code}
    res = ka._url_fetch(API_PRICE, "FHKST01010200", "", params)
    if res.isOK():
        body = res.getBody()
        if hasattr(body, 'output2'):
            o2 = body.output2
            try:
                price = int(o2.get('antc_cnpr','0'))
                rate = float(o2.get('antc_cntg_vrss_rate','0'))
                vol = int(o2.get('antc_vol','0'))
                marker = ''
                if rate >= 3: marker = ' 🚀'
                elif rate >= 1: marker = ' 🟢'
                elif rate <= -3: marker = ' 🔴'
                elif rate <= -1: marker = ' 🟡'
                else: marker = ' ⬜'
                if price > 0:
                    print(f"  {name:<24s} {price:>10,} {rate:>+7.2f}% {vol:>10,}{marker}")
                else:
                    print(f"  {name:<24s} {'호가 미형성':>10s}")
            except: pass
    time.sleep(0.12)

def fetch_rank(sort_code):
    params = {
        "fid_rank_sort_cls_code": str(sort_code),
        "fid_cond_mrkt_div_code": "J",
        "fid_cond_scr_div_code": "20182",
        "fid_input_iscd": "0000",
        "fid_div_cls_code": "0",
        "fid_aply_rang_prc_1":"","fid_vol_cnt":"","fid_pbmn":"",
        "fid_blng_cls_code": "0","fid_mkop_cls_code": "0",
    }
    res = ka._url_fetch(API_RANK, "FHPST01820000", "", params)
    if res.isOK():
        body = res.getBody()
        if hasattr(body, 'output'):
            return pd.DataFrame(body.output if isinstance(body.output, list) else [body.output])
    return pd.DataFrame()

print("\n"+"="*70)
print("  🚀 프리마켓 예상 상승률 TOP15")
print("="*70)
df = fetch_rank(0)
if not df.empty:
    df = df.rename(columns={'stck_shrn_iscd':'코드','hts_kor_isnm':'종목','stck_prpr':'예상가',
                            'prdy_ctrt':'등락률%','cntg_vol':'체결량'})
    show = df[['종목','코드','예상가','등락률%','체결량']].head(15)
    show['예상가'] = pd.to_numeric(show['예상가'], errors='coerce').astype('Int64')
    show['등락률%'] = pd.to_numeric(show['등락률%'], errors='coerce').round(2)
    print(show.to_string(index=False))

print("\n"+"="*70)
print("  🔻 프리마켓 예상 하락률 TOP15")
print("="*70)
df = fetch_rank(3)
if not df.empty:
    df = df.rename(columns={'stck_shrn_iscd':'코드','hts_kor_isnm':'종목','stck_prpr':'예상가',
                            'prdy_ctrt':'등락률%','cntg_vol':'체결량'})
    show = df[['종목','코드','예상가','등락률%','체결량']].head(15)
    show['예상가'] = pd.to_numeric(show['예상가'], errors='coerce').astype('Int64')
    show['등락률%'] = pd.to_numeric(show['등락률%'], errors='coerce').round(2)
    print(show.to_string(index=False))
