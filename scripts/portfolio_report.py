"""
포트폴리오 통합 분석 리포트 — chart-analyst v1.8 5단계 프레임워크 기반

⚠️ 점수 시스템 사용 금지. v1.8 종합 판단 매트릭스만 사용.

1. 보유 종목 v1.8 5단계
2. Watchlist v1.8 5단계
3. 외국인/기관 수급
4. 매크로 바로미터

사용법:
  python portfolio_report.py           # 오늘
  python portfolio_report.py 20260615  # 특정 날짜 수급 기준
"""
import sys
import os
import sqlite3
import warnings
from datetime import datetime
import pandas as pd
import numpy as np

warnings.filterwarnings('ignore')

import FinanceDataReader as fdr

DB_PATH = os.path.expanduser('~/chikitaka/dart-insight/data/krx_flow.db')


# ──────────────────── 포트폴리오 정의 ────────────────────
PORTFOLIO = [
    ('000660', 'SK하이닉스', '한국반도체', 'ISA', 1030733, 15),
    ('442580', 'PLUS HBM반도체', 'HBM ETF', 'ISA', 122472, 174),
    ('005385', '현대차우', '자동차 우선주', 'ISA', 273000, 20),
    ('423920', 'TIGER 필라 레버리지', '미국SOX 2x', 'ISA', 137325, 16),
    ('000720', '현대건설', '건설', 'ISA', 169015, 33),
    ('381180', 'TIGER 필라 나스닥', '미국SOX', 'ISA', 46530, 3),
    ('449450', 'PLUS K방산', '방산 ETF', 'ISA', 76560, 13),
    ('487240', 'KODEX AI전력', 'AI전력 ETF', 'ISA', 48718, 147),
    ('009150', '삼성전기', 'MLCC/전장', 'ISA', 2033000, 2),
    ('453950', 'TIGER TSMC', '파운드리 ETF', '연금', 33720, 30),
    ('379810', 'KODEX 나스닥100', '나스닥100', '연금', 27375, 37),
]

WATCHLIST = [
    ('064350', '현대로템', '방산+철도'),
    ('012450', '한화에어로스페이스', '방산 대장'),
    ('082740', '한화엔진', '조선/엔진'),
    ('000880', '한화', '지주'),
    ('267260', 'HD현대일렉트릭', '전력+원전'),
    ('298040', '효성중공업', '전력+방산'),
    ('005490', 'POSCO홀딩스', '철강+배터리'),
    ('010120', 'LS ELECTRIC', '전선/전력'),
    ('396270', '넥스트칩', '자율주행ADAS'),
]

KR_SEMI_SECTORS = {'한국반도체', 'HBM ETF', 'MLCC/전장'}  # v1.8 메타 편향 보정 대상


# ──────────────────── 기술 지표 ────────────────────
def calc_rsi(s, p=14):
    d = s.diff()
    g = d.clip(lower=0).rolling(p).mean()
    l = (-d.clip(upper=0)).rolling(p).mean()
    return 100 - 100 / (1 + g / l)


def calc_macd(s):
    ef = s.ewm(span=12).mean()
    es = s.ewm(span=26).mean()
    macd = ef - es
    sig = macd.ewm(span=9).mean()
    return macd, sig, macd - sig


def analyze_v18(code, name, sector, buy=None, qty=None):
    """chart-analyst v1.8 5단계 분석"""
    try:
        df = fdr.DataReader(code, '2025-02-01', datetime.today().strftime('%Y-%m-%d')).sort_index()
        if len(df) < 50:
            return None
        c = df['Close']; h = df['High']; l = df['Low']; v = df['Volume']

        # ─── Step 1: 가격 현황 ───
        cur = c.iloc[-1]; prev = c.iloc[-2]
        chg = (cur - prev) / prev * 100
        ret_1w = (cur / c.iloc[-6] - 1) * 100 if len(c) >= 6 else 0
        ret_1m = (cur / c.iloc[-22] - 1) * 100 if len(c) >= 22 else 0
        ret_3m = (cur / c.iloc[-66] - 1) * 100 if len(c) >= 66 else 0
        ytd_data = df[df.index >= '2026-01-01']['Close']
        ret_ytd = (cur / ytd_data.iloc[0] - 1) * 100 if len(ytd_data) > 0 else 0

        high_52 = h.tail(252).max()
        low_52 = l.tail(252).min()
        pos_52 = (cur - low_52) / (high_52 - low_52) * 100

        # ─── Step 2: 추세 분석 ───
        ma20 = c.rolling(20).mean().iloc[-1]
        ma50 = c.rolling(50).mean().iloc[-1]
        ma200 = c.rolling(200).mean().iloc[-1] if len(c) >= 200 else c.mean()

        cross_state = '🟢 골든크로스' if ma50 > ma200 else '🔴 데드크로스'
        ma200_gap = (cur / ma200 - 1) * 100

        # 거래량
        vol_avg20 = v.rolling(20).mean().iloc[-1]
        vol_ratio = v.iloc[-1] / vol_avg20

        # 음봉 빈도 (20일)
        neg_days = sum(1 for i in range(-20, 0) if c.iloc[i] < c.iloc[i - 1])

        # 추세
        if cur > ma20 > ma50 > ma200:
            trend = '정배열▲'
        elif cur < ma20 < ma50 < ma200:
            trend = '역배열▼'
        elif ma50 > ma200 and cur < ma20:
            trend = '장기강세/단기조정'
        else:
            trend = '혼조'

        # ─── Step 3: 모멘텀 ───
        rsi = calc_rsi(c).iloc[-1]
        rsi_prev = calc_rsi(c).iloc[-2]
        rsi_dir = '↑' if rsi > rsi_prev else '↓'
        rsi_zone = '과매수' if rsi >= 70 else '과매도' if rsi <= 30 else '중립'

        macd_, sig_, hist = calc_macd(c)
        hist_now, hist_prev = hist.iloc[-1], hist.iloc[-2]
        macd_above = macd_.iloc[-1] > sig_.iloc[-1]
        if hist_now > 0 and hist_now > hist_prev:
            macd_st = '상승가속'
        elif hist_now > 0 and hist_now < hist_prev:
            macd_st = '상승둔화'
        elif hist_now < 0 and abs(hist_now) < abs(hist_prev):
            macd_st = '개선중'
        else:
            macd_st = '하락가속'

        # ─── Step 4: 지지/저항 ───
        fib_618 = high_52 - (high_52 - low_52) * 0.618
        fib_500 = high_52 - (high_52 - low_52) * 0.500
        fib_382 = high_52 - (high_52 - low_52) * 0.382

        # ATH 트랩 (52주 95%+)
        ath_trap = ''
        if pos_52 >= 95:
            trap_signals = []
            if rsi >= 70: trap_signals.append('RSI 70+')
            if vol_ratio < 0.8: trap_signals.append('거래량 감소')
            if len(trap_signals) >= 1:
                ath_trap = f'⚠️ ATH 트랩 의심 ({", ".join(trap_signals)})'
            else:
                ath_trap = '✓ 건강한 ATH'

        # ─── Step 5: 종합 판단 (v1.8 매트릭스) ───
        # 매트릭스 카운트
        bullish = 0
        bearish = 0

        # 가격 vs 200MA
        if cur > ma200: bullish += 1
        else: bearish += 1
        # 50MA vs 200MA
        if ma50 > ma200: bullish += 1
        else: bearish += 1
        # RSI 30~50 반등 vs 70+ 하락
        if 30 <= rsi <= 50 and rsi_dir == '↑': bullish += 1
        elif rsi >= 70 and rsi_dir == '↓': bearish += 1
        # MACD
        if macd_above and macd_st in ('상승가속', '상승둔화'): bullish += 1
        elif not macd_above and macd_st == '하락가속': bearish += 1
        # 거래량 (상승 시 증가 = 강세)
        if chg > 0 and vol_ratio > 1.2: bullish += 1
        elif chg < 0 and vol_ratio > 1.2: bearish += 1
        # 음봉 빈도 (12+ = 약세)
        if neg_days <= 8: bullish += 1
        elif neg_days >= 13: bearish += 1

        # v1.8 메타 편향 보정 (한국 반도체)
        bias_applied = False
        if sector in KR_SEMI_SECTORS and bearish > bullish:
            bearish = max(0, bearish - 1)  # 약세 신호 1점 감소
            bias_applied = True

        # 방향 결정
        diff = bullish - bearish
        if diff >= 4:
            direction, conf, prob = '강세', '높음', '85:15'
        elif diff >= 2:
            direction, conf, prob = '강세', '중상', '70:30'
        elif diff >= 0:
            direction, conf, prob = '중립', '중', '55:45'
        elif diff >= -2:
            direction, conf, prob = '약세', '중상', '35:65'
        else:
            direction, conf, prob = '약세', '높음', '20:80'

        # 종목 등급 (왼쪽 저점 사수 = MA200 위 + MA50 > MA200)
        if cur > ma200 and ma50 > ma200:
            grade = 'A급'
        else:
            grade = 'B급'

        # 포지션 레짐
        if trend == '정배열▲' and macd_st in ('상승가속', '상승둔화'):
            regime = '롱 only'
        elif trend == '역배열▼' and macd_st == '하락가속':
            regime = '관망 (또는 숏)'
        elif macd_st == '개선중':
            regime = '롱 only (회복 베팅)'
        elif diff == 0:
            regime = '관망'
        else:
            regime = '양방향'

        # 조정 유형
        if direction == '강세' and ret_1m < -10:
            adjust_type = '기간조정 (강세장)'
        elif direction == '약세':
            adjust_type = '가격조정 진행 중'
        else:
            adjust_type = '복합'

        # 근거
        bases = []
        if cur > ma200: bases.append(f'MA200 +{ma200_gap:.1f}%')
        if ma50 > ma200: bases.append('골든크로스')
        bases.append(f'RSI {rsi:.1f} ({rsi_zone})')
        bases.append(f'MACD {macd_st}')

        # 손익
        pnl = (cur / buy - 1) * 100 if buy else None
        pnl_amt = (cur - buy) * qty if buy and qty else None
        val_now = cur * qty if qty else None

        return {
            'code': code, 'name': name, 'sector': sector,
            # Step 1
            'cur': int(cur), 'chg': round(chg, 2),
            'ret_1w': round(ret_1w, 1), 'ret_1m': round(ret_1m, 1),
            'ret_3m': round(ret_3m, 1), 'ret_ytd': round(ret_ytd, 1),
            'pos_52': int(pos_52), 'high_52': int(high_52), 'low_52': int(low_52),
            'pnl': round(pnl, 2) if pnl is not None else None,
            'pnl_amt': int(pnl_amt) if pnl_amt is not None else None,
            'val_now': int(val_now) if val_now is not None else None,
            # Step 2
            'trend': trend, 'cross_state': cross_state,
            'ma20': int(ma20), 'ma50': int(ma50), 'ma200': int(ma200),
            'ma200_gap': round(ma200_gap, 1),
            'vol_ratio': round(vol_ratio, 2), 'neg_days': neg_days,
            # Step 3
            'rsi': round(rsi, 1), 'rsi_dir': rsi_dir, 'rsi_zone': rsi_zone,
            'macd_st': macd_st, 'hist': round(hist_now, 1),
            # Step 4
            'fib_382': int(fib_382), 'fib_500': int(fib_500), 'fib_618': int(fib_618),
            'ath_trap': ath_trap,
            # Step 5 (v1.8)
            'direction': direction, 'confidence': conf, 'probability': prob,
            'grade': grade, 'regime': regime, 'adjust_type': adjust_type,
            'bases': bases, 'bias_applied': bias_applied,
            'matrix': f'{bullish}/{bullish+bearish}',
        }
    except Exception as e:
        print(f"  ⚠️ {name}: {e}")
        return None


def print_5step(r, account='', is_holding=False):
    """v1.8 5단계 출력"""
    tag = f' [{account}]' if account else ''
    pnl_str = ''
    if is_holding and r['pnl'] is not None:
        pnl_str = f' | 손익 {r["pnl"]:+.2f}% ({r["pnl_amt"]:+,}원)'

    print(f"\n▶ {r['name']} ({r['code']}) — {r['sector']}{tag}")
    print(f"  [Step 1] {r['cur']:,}원 ({r['chg']:+.2f}%) | "
          f"1W {r['ret_1w']:+.1f}% / 1M {r['ret_1m']:+.1f}% / YTD {r['ret_ytd']:+.1f}% | "
          f"52주 {r['pos_52']}%{pnl_str}")
    print(f"  [Step 2] {r['trend']} | {r['cross_state']} | "
          f"MA200 {r['ma200_gap']:+.1f}% | 거래량 {r['vol_ratio']}배 | 음봉 {r['neg_days']}/20")
    print(f"  [Step 3] RSI {r['rsi']}{r['rsi_dir']} ({r['rsi_zone']}) | MACD {r['macd_st']} (Hist {r['hist']})")
    print(f"  [Step 4] 저항 MA20 {r['ma20']:,} → 52주고 {r['high_52']:,} | "
          f"지지 MA50 {r['ma50']:,} → MA200 {r['ma200']:,} → 피보 50% {r['fib_500']:,}")
    if r['ath_trap']:
        print(f"           {r['ath_trap']}")
    print(f"  [Step 5] 방향 {r['direction']} (신뢰도 {r['confidence']}, 확률 {r['probability']})")
    print(f"           등급 {r['grade']} | 포지션 {r['regime']} | 조정 {r['adjust_type']}")
    print(f"           근거: {' + '.join(r['bases'])}")
    if r['bias_applied']:
        print(f"           ⚠️ v1.8 한국반도체 메타 편향 보정 적용 (매도 신호 보수적 해석)")


def get_macro():
    """매크로 바로미터 (Step 4.7)"""
    result = {}
    for ticker, name in [('NVDA', 'NVIDIA'), ('SMH', 'SMH'), ('MU', '마이크론'),
                         ('TSM', 'TSM'), ('SPY', 'S&P500')]:
        try:
            df = fdr.DataReader(ticker, '2025-02-01', datetime.today().strftime('%Y-%m-%d')).sort_index()
            cur = df['Close'].iloc[-1]
            chg = (cur / df['Close'].iloc[-2] - 1) * 100
            ret_1m = (cur / df['Close'].iloc[-22] - 1) * 100 if len(df) >= 22 else 0
            result[name] = (cur, chg, ret_1m)
        except:
            pass
    return result


def get_supply_demand(date_str, all_codes):
    """수급 데이터"""
    conn = sqlite3.connect(DB_PATH)
    result = {'alerts': {}, 'top5': {}}
    for inv in ['외국인_buy', '외국인_sell', '기관_buy', '기관_sell']:
        rows = conn.execute(
            "SELECT rank, name, ticker, abs(net_value)/100000000 "
            "FROM net_purchases WHERE date=? AND investor=? ORDER BY rank",
            (date_str, inv)
        ).fetchall()
        result['alerts'][inv] = [r for r in rows if r[2] in all_codes]
        result['top5'][inv] = rows[:5]
    conn.close()
    return result


# ──────────────────── 메인 ────────────────────
def run(date_str=None):
    if date_str is None:
        # 가장 최근 수급 데이터 날짜 사용
        conn = sqlite3.connect(DB_PATH)
        date_str = conn.execute("SELECT MAX(date) FROM net_purchases WHERE investor='외국인_buy'").fetchone()[0]
        conn.close()
        if not date_str:
            date_str = datetime.today().strftime('%Y%m%d')

    print(f"\n{'='*120}")
    print(f"  📊 포트폴리오 통합 분석 — chart-analyst v1.8 (점수 시스템 미사용)")
    print(f"{'='*120}")

    # ─── 매크로 바로미터 ───
    print(f"\n{'━'*60}")
    print(f"  🌍 매크로 바로미터 (Step 4.7)")
    print(f"{'━'*60}")
    macro = get_macro()
    for name, (cur, chg, ret_1m) in macro.items():
        print(f"  {name:<10s} ${cur:>8.2f}  전일 {chg:+5.2f}% | 1M {ret_1m:+5.1f}%")
    if '마이크론' in macro:
        mu_chg = macro['마이크론'][1]
        if mu_chg < -3:
            print(f"\n  ⚠️ 마이크론 -{abs(mu_chg):.1f}% → 한국 반도체 익일 갭다운 시사")
        elif mu_chg > 3:
            print(f"\n  🚀 마이크론 +{mu_chg:.1f}% → 한국 반도체 익일 갭업 시사")

    # ─── 보유 종목 v1.8 5단계 ───
    print(f"\n{'━'*60}")
    print(f"  📁 보유 종목 v1.8 5단계 분석")
    print(f"{'━'*60}")
    pf_results = []
    isa_total, pen_total, total_pnl = 0, 0, 0
    for code, name, sector, acct, buy, qty in PORTFOLIO:
        r = analyze_v18(code, name, sector, buy, qty)
        if r:
            r['account'] = acct
            pf_results.append(r)
            if r['val_now']:
                if acct == 'ISA':
                    isa_total += r['val_now']
                else:
                    pen_total += r['val_now']
                total_pnl += r['pnl_amt']
            print_5step(r, account=acct, is_holding=True)

    print(f"\n  💰 ISA 평가액: {isa_total:,}원 / 연금: {pen_total:,}원")
    print(f"  💰 총 평가액: {isa_total + pen_total:,}원 / 누적 손익: {total_pnl:+,}원")

    # ─── 손익률 순위 ───
    print(f"\n{'━'*60}")
    print(f"  📈 손익률 순위")
    print(f"{'━'*60}")
    for r in sorted(pf_results, key=lambda x: -(x['pnl'] or 0)):
        emoji = '🚀' if r['pnl'] > 50 else '🟢' if r['pnl'] > 10 else '⬜' if r['pnl'] > 0 else '🟡' if r['pnl'] > -10 else '🔴'
        print(f"  {emoji} {r['name']:<22s} {r['pnl']:+7.2f}% ({r['pnl_amt']:+10,}원) | 방향 {r['direction']} ({r['probability']})")

    # ─── Watchlist v1.8 5단계 ───
    print(f"\n{'━'*60}")
    print(f"  ⭐ Watchlist v1.8 5단계 분석")
    print(f"{'━'*60}")
    wl_results = []
    for code, name, sector in WATCHLIST:
        r = analyze_v18(code, name, sector)
        if r:
            wl_results.append(r)
            print_5step(r, account='WL')

    # ─── 수급 ───
    print(f"\n{'━'*60}")
    print(f"  💰 외국인/기관 수급 ({date_str})")
    print(f"{'━'*60}")
    portfolio_codes = {c for c, *_ in PORTFOLIO}
    all_codes = portfolio_codes | {c for c, *_ in WATCHLIST}
    sd = get_supply_demand(date_str, all_codes)

    print(f"\n🚨 보유/Watchlist 진입:")
    for inv, label in [('외국인_buy', '🟢 외매수'), ('외국인_sell', '🔴 외매도'),
                       ('기관_buy', '🟢 기매수'), ('기관_sell', '🔴 기매도')]:
        if sd['alerts'][inv]:
            print(f"\n  {label}:")
            for r in sd['alerts'][inv]:
                tag = '[보유]' if r[2] in portfolio_codes else '[WL]'
                print(f"    {r[0]:>2}위 {tag} {r[1]:<22s} {int(r[3]):>5,}억")

    print(f"\n📊 시장 TOP5:")
    for inv, label in [('외국인_buy', '🟢 외매수'), ('외국인_sell', '🔴 외매도'),
                       ('기관_buy', '🟢 기매수'), ('기관_sell', '🔴 기매도')]:
        print(f"\n  {label}:")
        for r in sd['top5'][inv]:
            print(f"    {r[0]:>2}위 {r[1]:<22s} {int(r[3]):>5,}억")

    # ─── 종합 분류 (v1.8 방향 기준) ───
    print(f"\n{'━'*60}")
    print(f"  🎯 v1.8 종합 분류 (방향 + 신뢰도)")
    print(f"{'━'*60}")
    all_results = [(r, '보유') for r in pf_results] + [(r, 'WL') for r in wl_results]

    print(f"\n🟢🟢 강세 (신뢰도 높음):")
    for r, src in all_results:
        if r['direction'] == '강세' and r['confidence'] == '높음':
            print(f"  [{src}] {r['name']:<22s} {r['probability']} | 등급 {r['grade']} | {r['regime']}")

    print(f"\n🟢 강세 (신뢰도 중상):")
    for r, src in all_results:
        if r['direction'] == '강세' and r['confidence'] == '중상':
            print(f"  [{src}] {r['name']:<22s} {r['probability']} | 등급 {r['grade']} | {r['regime']}")

    print(f"\n⬜ 중립:")
    for r, src in all_results:
        if r['direction'] == '중립':
            print(f"  [{src}] {r['name']:<22s} {r['probability']} | 등급 {r['grade']} | {r['regime']}")

    print(f"\n🟡 약세:")
    for r, src in all_results:
        if r['direction'] == '약세':
            bias_note = ' ⚠️ v1.8 보정' if r['bias_applied'] else ''
            print(f"  [{src}] {r['name']:<22s} {r['probability']} | 등급 {r['grade']} | {r['regime']}{bias_note}")


if __name__ == '__main__':
    date_str = sys.argv[1] if len(sys.argv) > 1 else None
    run(date_str)
