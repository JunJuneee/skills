"""
미국 야간 선물 자동 체크 — 매일 아침 자동 실행

기능:
1. 미국 야간 선물 조회 (ES/NQ/YM/RTY)
2. 미국 정규장 vs 야간 선물 비교
3. 한국 반도체 프록시 (MU/NVDA/SMH/TSM)
4. VIX 위험 신호
5. 원자재 (WTI/금)
6. 한국 시장 갭 예측

사용법:
  python us_futures.py          # 즉시 실행 (콘솔 + 로그)
  python us_futures.py --quiet  # 로그만 저장
"""
import sys
import os
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

import FinanceDataReader as fdr

LOG_DIR = os.path.expanduser('~/chikitaka/dart-insight/logs')
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, 'us_futures.log')


def log(msg, quiet=False):
    """콘솔 + 파일 동시 출력"""
    if not quiet:
        print(msg)
    with open(LOG_FILE, 'a') as f:
        f.write(msg + '\n')


def fetch(ticker, name):
    """FDR로 안전하게 조회"""
    try:
        df = fdr.DataReader(ticker, '2026-06-01').sort_index()
        if df.empty:
            return None
        cur = df['Close'].iloc[-1]
        prev = df['Close'].iloc[-2] if len(df) > 1 else cur
        chg = (cur - prev) / prev * 100
        date = df.index[-1].strftime('%Y-%m-%d')
        return {'cur': cur, 'chg': chg, 'date': date}
    except Exception as e:
        return None


def main(quiet=False):
    now = datetime.now()

    # 로그 헤더
    log(f"\n{'='*68}", quiet)
    log(f"  🌙 미국 야간 선물 체크 — {now.strftime('%Y-%m-%d %H:%M:%S')}", quiet)
    log(f"{'='*68}", quiet)

    # ─── 1. 4대 선물 ───
    log(f"\n📈 4대 지수 선물", quiet)
    log(f"  {'자산':<22s} {'가격':>12s}  {'변동':>7s}", quiet)
    log(f"  {'-'*45}", quiet)
    futures = [
        ('ES=F', 'S&P 500 E-mini'),
        ('NQ=F', '나스닥 100'),
        ('YM=F', '다우'),
        ('RTY=F', '러셀 2000'),
    ]
    futures_data = {}
    for ticker, name in futures:
        r = fetch(ticker, name)
        if r:
            futures_data[ticker] = r
            emoji = '🚀' if r['chg'] >= 2 else '🟢' if r['chg'] >= 0.5 else '🔴' if r['chg'] <= -1 else '⬜'
            log(f"  {emoji} {name:<20s} {r['cur']:>12,.2f}  {r['chg']:>+6.2f}%", quiet)

    # ─── 2. 한국 반도체 프록시 ───
    log(f"\n🔬 한국 반도체 프록시 (MU = SK하이닉스 직접 영향)", quiet)
    log(f"  {'자산':<22s} {'가격':>12s}  {'변동':>7s}", quiet)
    log(f"  {'-'*45}", quiet)
    semis = [
        ('MU', '마이크론 (MU)'),
        ('NVDA', 'NVIDIA'),
        ('SMH', 'SMH ETF'),
        ('TSM', 'TSMC ADR'),
        ('AVGO', '브로드컴'),
        ('AMD', 'AMD'),
    ]
    semi_data = {}
    for ticker, name in semis:
        r = fetch(ticker, name)
        if r:
            semi_data[ticker] = r
            emoji = '🚀' if r['chg'] >= 3 else '🟢' if r['chg'] >= 1 else '🔴' if r['chg'] <= -2 else '⬜'
            log(f"  {emoji} {name:<20s} ${r['cur']:>11,.2f}  {r['chg']:>+6.2f}%", quiet)

    # ─── 3. VIX 위험 신호 ───
    log(f"\n⚠️ VIX 위험 신호", quiet)
    vix = fetch('^VIX', 'VIX')
    if vix:
        zone = '극단 패닉' if vix['cur'] >= 40 else '패닉' if vix['cur'] >= 30 else '경계' if vix['cur'] >= 20 else '안정'
        emoji = '💀' if vix['cur'] >= 30 else '⚠️' if vix['cur'] >= 20 else '🟢'
        log(f"  {emoji} VIX: {vix['cur']:.2f} ({vix['chg']:+.2f}%) — {zone}", quiet)

    # ─── 4. 원자재 ───
    log(f"\n🛢️ 원자재 / 안전자산", quiet)
    log(f"  {'자산':<22s} {'가격':>12s}  {'변동':>7s}", quiet)
    log(f"  {'-'*45}", quiet)
    commodities = [
        ('CL=F', 'WTI 원유'),
        ('GC=F', '금'),
        ('SI=F', '은'),
        ('DX-Y.NYB', 'DXY (달러지수)'),
    ]
    for ticker, name in commodities:
        r = fetch(ticker, name)
        if r:
            emoji = '🚀' if r['chg'] >= 2 else '🟢' if r['chg'] >= 0.5 else '🔴' if r['chg'] <= -1 else '⬜'
            log(f"  {emoji} {name:<20s} ${r['cur']:>11,.2f}  {r['chg']:>+6.2f}%", quiet)

    # ─── 5. 한국 시장 갭 예측 ───
    log(f"\n🎯 한국 시장 갭 예측 (오늘 09:00 시초가)", quiet)

    if 'ES=F' in futures_data and 'NQ=F' in futures_data:
        es_chg = futures_data['ES=F']['chg']
        nq_chg = futures_data['NQ=F']['chg']

        # KOSPI: ES × 0.8
        kospi_gap = es_chg * 0.8
        # 반도체: NQ × 1.0 + MU 가중
        mu_chg = semi_data.get('MU', {}).get('chg', 0)
        semi_gap = nq_chg * 0.6 + mu_chg * 0.4

        log(f"  KOSPI 예상 갭   : {kospi_gap:+.2f}%  (ES {es_chg:+.2f}% × 0.8)", quiet)
        log(f"  반도체 예상 갭   : {semi_gap:+.2f}%  (NQ × 0.6 + MU × 0.4)", quiet)
        log(f"    └ SK하이닉스/삼전 시초가 영향 시사", quiet)

        # 종합 판단
        if kospi_gap >= 2:
            log(f"\n  🚀 강한 갭업 예상 — 정규장 진입 가능 / 추격 매수 주의", quiet)
        elif kospi_gap >= 0.5:
            log(f"\n  🟢 갭업 예상 — 회복 모드", quiet)
        elif kospi_gap <= -2:
            log(f"\n  🔴 강한 갭다운 예상 — 손절선 점검 / 매수 자제", quiet)
        elif kospi_gap <= -0.5:
            log(f"\n  🟡 갭다운 예상 — 신중 관망", quiet)
        else:
            log(f"\n  ⬜ 박스권 시초 예상", quiet)

    log(f"\n{'='*68}", quiet)
    log(f"  실행 종료: {datetime.now().strftime('%H:%M:%S')}", quiet)
    log(f"  로그 저장: {LOG_FILE}", quiet)
    log(f"{'='*68}\n", quiet)


if __name__ == '__main__':
    quiet = '--quiet' in sys.argv
    main(quiet=quiet)
