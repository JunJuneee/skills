"""
KRX 외국인/기관/개인 매매동향 일별 수집
TOP 20 순매수/순매도 + 사용자 보유/watchlist 종목 알림

실행:
  python ~/chikitaka/dart-insight/src/krx_flow/daily_flow.py [날짜YYYYMMDD]

예:
  python daily_flow.py            # 어제 (자동)
  python daily_flow.py 20260507   # 특정 날짜
"""

import sys
import os
from datetime import datetime, timedelta
from pykrx import stock
import pandas as pd
import sqlite3
import json

# 사용자 보유/watchlist 종목
USER_HOLDINGS = {
    'ISA': {
        '000660': 'SK하이닉스',
        '005930': '삼성전자',
        '005385': '현대차우',
        '000720': '현대건설',
        '009540': 'HD한국조선해양',
        '010955': 'S-Oil우',
        '449450': 'PLUS K방산',
    },
    '연금': {
        '453950': 'TIGER TSMC파운드리',
        '379810': 'KODEX 미국나스닥100',
    },
    'watchlist': {
        '012450': '한화에어로스페이스',
        '064350': '현대로템',
        '082740': '한화엔진',
        '010120': 'LS ELECTRIC',
        '000880': '한화',
        '267260': 'HD현대일렉트릭',
        '298040': '효성중공업',
        '381180': 'TIGER 미국필라델피아반도체나스닥',
    }
}

DB_PATH = os.path.expanduser('~/chikitaka/dart-insight/data/krx_flow.db')
INVESTORS = ['외국인', '기관합계', '개인']
MARKETS = ['KOSPI', 'KOSDAQ']
TOP_N = 20


def init_db():
    """SQLite DB 초기화"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS net_purchases (
            date TEXT, market TEXT, investor TEXT,
            ticker TEXT, name TEXT,
            net_value INTEGER, net_volume INTEGER,
            rank INTEGER,
            UNIQUE(date, market, investor, ticker)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS daily_summary (
            date TEXT PRIMARY KEY,
            kospi_foreign_total INTEGER,
            kospi_inst_total INTEGER,
            kospi_indi_total INTEGER,
            collected_at TEXT
        )
    ''')
    conn.commit()
    return conn


def get_top_n(date, market, investor, top_n=20):
    """투자자별 순매수/순매도 TOP N 수집"""
    df = stock.get_market_net_purchases_of_equities(date, date, market, investor)
    if df.empty:
        return None, None

    # 컬럼명: 종목명, 매도거래량, 매수거래량, 순매수거래량, 매도거래대금, 매수거래대금, 순매수거래대금
    df = df.reset_index()  # 티커 컬럼 추가
    df.columns = ['ticker'] + list(df.columns[1:])

    # 순매수 TOP / 순매도 TOP (절대값 큰 것)
    if '순매수거래대금' in df.columns:
        col = '순매수거래대금'
    elif 'net_purchase_value' in df.columns:
        col = 'net_purchase_value'
    else:
        col = df.columns[-1]

    top_buy = df.nlargest(top_n, col)
    top_sell = df.nsmallest(top_n, col)
    return top_buy, top_sell


def save_to_db(conn, date, market, investor, df, kind):
    """DB 저장"""
    if df is None or df.empty:
        return
    for rank, (_, row) in enumerate(df.iterrows(), 1):
        ticker = row['ticker']
        name = row.get('종목명', '?')
        col = '순매수거래대금' if '순매수거래대금' in row else df.columns[-1]
        net_value = int(row[col])
        try:
            conn.execute('''
                INSERT OR REPLACE INTO net_purchases
                (date, market, investor, ticker, name, net_value, net_volume, rank)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (date, market, investor, ticker, name, net_value, 0, rank))
        except Exception as e:
            print(f"  DB 저장 오류: {e}")
    conn.commit()


def detect_user_alerts(date, market, investor, top_buy, top_sell):
    """사용자 보유/watchlist 종목 알림"""
    alerts = []
    all_user_codes = {}
    for cat, items in USER_HOLDINGS.items():
        for code, name in items.items():
            all_user_codes[code] = (cat, name)

    if top_buy is not None:
        for rank, (_, row) in enumerate(top_buy.head(20).iterrows(), 1):
            ticker = row['ticker']
            if ticker in all_user_codes:
                cat, uname = all_user_codes[ticker]
                col = '순매수거래대금' if '순매수거래대금' in row else row.index[-1]
                value = int(row[col])
                alerts.append(f"🟢 [{cat}] {uname} ({ticker}) {investor} 순매수 {rank}위 (+{value/1e8:.1f}억)")

    if top_sell is not None:
        for rank, (_, row) in enumerate(top_sell.head(20).iterrows(), 1):
            ticker = row['ticker']
            if ticker in all_user_codes:
                cat, uname = all_user_codes[ticker]
                col = '순매수거래대금' if '순매수거래대금' in row else row.index[-1]
                value = int(row[col])
                alerts.append(f"🔴 [{cat}] {uname} ({ticker}) {investor} 순매도 {rank}위 ({value/1e8:.1f}억)")
    return alerts


def detect_strong_signals(top_buy_data):
    """외국인+기관 동시 매수/매도 = 강한 시그널"""
    foreign_buy = set(top_buy_data.get('KOSPI', {}).get('외국인', set()))
    inst_buy = set(top_buy_data.get('KOSPI', {}).get('기관합계', set()))
    foreign_sell = set(top_buy_data.get('KOSPI_SELL', {}).get('외국인', set()))
    inst_sell = set(top_buy_data.get('KOSPI_SELL', {}).get('기관합계', set()))

    strong_buy = foreign_buy & inst_buy
    strong_sell = foreign_sell & inst_sell
    return strong_buy, strong_sell


def main(date=None):
    if date is None:
        # 어제 (한국 시장 기준)
        yesterday = datetime.now() - timedelta(days=1)
        date = yesterday.strftime('%Y%m%d')

    print(f"\n{'='*70}")
    print(f"📊 KRX 매매동향 수집 [{date}]")
    print(f"{'='*70}")

    conn = init_db()
    all_alerts = []
    top_buy_data = {}

    for market in MARKETS:
        print(f"\n[{market}]")
        for investor in INVESTORS:
            print(f"  {investor}: ", end='', flush=True)
            try:
                top_buy, top_sell = get_top_n(date, market, investor, TOP_N)
                if top_buy is None or top_buy.empty:
                    print(f"⚠️ 데이터 없음 (휴일 또는 미수신)")
                    continue

                save_to_db(conn, date, market, investor, top_buy, 'buy')
                save_to_db(conn, date, market, investor, top_sell, 'sell')

                # TOP 5 출력
                col = '순매수거래대금' if '순매수거래대금' in top_buy.columns else top_buy.columns[-1]
                print(f"✅ TOP5 매수")
                for i, (_, row) in enumerate(top_buy.head(5).iterrows(), 1):
                    print(f"    {i}. {row.get('종목명', '?')} ({row['ticker']}) +{int(row[col])/1e8:.0f}억")

                # 사용자 종목 알림
                alerts = detect_user_alerts(date, market, investor, top_buy, top_sell)
                all_alerts.extend(alerts)

                # 강한 시그널용 데이터 저장
                if market == 'KOSPI':
                    top_buy_data.setdefault(market, {})[investor] = set(top_buy['ticker'].head(20))
                    top_buy_data.setdefault('KOSPI_SELL', {})[investor] = set(top_sell['ticker'].head(20))
            except Exception as e:
                print(f"❌ ERR: {e}")

    # 강한 시그널 (외국인+기관 동시)
    print(f"\n{'='*70}")
    print(f"🎯 강한 시그널 (KOSPI 외국인+기관 동시 매매)")
    print(f"{'='*70}")
    if 'KOSPI' in top_buy_data and len(top_buy_data['KOSPI']) >= 2:
        strong_buy, strong_sell = detect_strong_signals(top_buy_data)
        print(f"\n🟢 강한 매수 (외국인+기관 동시 매수): {len(strong_buy)}종목")
        for ticker in list(strong_buy)[:10]:
            try:
                name = stock.get_market_ticker_name(ticker)
                print(f"  ⭐ {name} ({ticker})")
            except: pass
        print(f"\n🔴 강한 매도 (외국인+기관 동시 매도): {len(strong_sell)}종목")
        for ticker in list(strong_sell)[:10]:
            try:
                name = stock.get_market_ticker_name(ticker)
                print(f"  ⚠️ {name} ({ticker})")
            except: pass

    # 사용자 종목 알림
    print(f"\n{'='*70}")
    print(f"🚨 사용자 보유/watchlist 종목 매매 동향 알림")
    print(f"{'='*70}")
    if all_alerts:
        for alert in all_alerts:
            print(f"  {alert}")
    else:
        print("  (사용자 종목 TOP 20 진입 없음)")

    conn.close()
    print(f"\n💾 DB 저장: {DB_PATH}")
    print(f"\n✅ 완료")


if __name__ == '__main__':
    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        main()
