"""
주간/월간 매매동향 분석
SQLite DB에서 누적 순매수/순매도 분석

사용법:
  python analyze_flow.py [기간]

  기간:
    week    - 최근 7일
    month   - 최근 30일
    YYYYMMDD-YYYYMMDD - 사용자 지정 기간
    (생략)  - 전체
"""
import sqlite3
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict

DB_PATH = os.path.expanduser('~/chikitaka/dart-insight/data/krx_flow.db')

# 사용자 보유/watchlist 종목
USER_HOLDINGS = {
    'ISA': {
        '000660': 'SK하이닉스', '005930': '삼성전자', '005385': '현대차우',
        '000720': '현대건설', '009540': 'HD한국조선해양', '010955': 'S-Oil우',
        '449450': 'PLUS K방산',
    },
    '연금': {
        '453950': 'TIGER TSMC파운드리', '379810': 'KODEX 미국나스닥100',
    },
    'watchlist': {
        '012450': '한화에어로스페이스', '064350': '현대로템', '082740': '한화엔진',
        '010120': 'LS ELECTRIC', '000880': '한화', '267260': 'HD현대일렉트릭',
        '298040': '효성중공업', '381180': 'TIGER 미국필라델피아반도체나스닥',
    }
}


def parse_period(arg):
    """기간 인자 파싱"""
    if arg is None or arg == '':
        return None, None  # 전체
    if arg == 'week':
        end = datetime.now()
        start = end - timedelta(days=7)
        return start.strftime('%Y%m%d'), end.strftime('%Y%m%d')
    if arg == 'month':
        end = datetime.now()
        start = end - timedelta(days=30)
        return start.strftime('%Y%m%d'), end.strftime('%Y%m%d')
    if '-' in arg:
        s, e = arg.split('-')
        return s, e
    return arg, arg  # 단일 일자


def get_cumulative_top(conn, start, end, investor, top_n=20):
    """기간 내 누적 순매수 TOP / 순매도 TOP"""
    where = ""
    params = []
    if start and end:
        where = "WHERE date BETWEEN ? AND ?"
        params = [start, end]

    # investor: '외국인', '기관', '개인'
    sql = f'''
        SELECT ticker, name,
               SUM(net_value) as total_value,
               COUNT(*) as appear_count,
               GROUP_CONCAT(DISTINCT date) as dates
        FROM net_purchases
        WHERE investor IN (?, ?)
              {('AND date BETWEEN ? AND ?' if start and end else '')}
        GROUP BY ticker, name
        ORDER BY total_value DESC
    '''
    params2 = [f'{investor}_buy', f'{investor}_sell']
    if start and end:
        params2.extend([start, end])

    rows = conn.execute(sql, params2).fetchall()
    top_buy = [r for r in rows if r[2] > 0][:top_n]
    top_sell = [r for r in rows if r[2] < 0][-top_n:][::-1]
    return top_buy, top_sell


def find_strong_signals(conn, start, end):
    """외국인+기관 동시 매수/매도 종목"""
    foreign_buy, foreign_sell = get_cumulative_top(conn, start, end, '외국인', 50)
    inst_buy, inst_sell = get_cumulative_top(conn, start, end, '기관', 50)

    fb_set = {r[0]: r for r in foreign_buy}
    ib_set = {r[0]: r for r in inst_buy}
    fs_set = {r[0]: r for r in foreign_sell}
    is_set = {r[0]: r for r in inst_sell}

    strong_buy = []
    for ticker in set(fb_set.keys()) & set(ib_set.keys()):
        f, i = fb_set[ticker], ib_set[ticker]
        strong_buy.append((ticker, f[1], f[2] + i[2], f[2], i[2]))
    strong_buy.sort(key=lambda x: -x[2])

    strong_sell = []
    for ticker in set(fs_set.keys()) & set(is_set.keys()):
        f, i = fs_set[ticker], is_set[ticker]
        strong_sell.append((ticker, f[1], f[2] + i[2], f[2], i[2]))
    strong_sell.sort(key=lambda x: x[2])

    return strong_buy, strong_sell


def user_holdings_flow(conn, start, end):
    """사용자 보유/watchlist 종목의 누적 매매 동향"""
    all_user_codes = {}
    for cat, items in USER_HOLDINGS.items():
        for code, name in items.items():
            all_user_codes[code] = (cat, name)

    where = ""
    params = []
    if start and end:
        where = "WHERE ticker IN ({}) AND date BETWEEN ? AND ?".format(
            ','.join(['?'] * len(all_user_codes)))
        params = list(all_user_codes.keys()) + [start, end]
    else:
        where = "WHERE ticker IN ({})".format(','.join(['?'] * len(all_user_codes)))
        params = list(all_user_codes.keys())

    sql = f'''
        SELECT ticker, name, investor,
               SUM(net_value) as total_value,
               COUNT(*) as appear_count
        FROM net_purchases
        {where}
        GROUP BY ticker, name, investor
        ORDER BY ticker, investor
    '''
    rows = conn.execute(sql, params).fetchall()

    # 종목별 정리
    by_ticker = defaultdict(dict)
    for ticker, name, investor, value, count in rows:
        # investor format: '외국인_buy' or '외국인_sell'
        kind = investor.split('_')[1]  # buy/sell
        inv = investor.split('_')[0]   # 외국인/기관/개인
        by_ticker[ticker]['name'] = name
        by_ticker[ticker][f'{inv}_{kind}'] = value
        by_ticker[ticker][f'{inv}_count'] = by_ticker[ticker].get(f'{inv}_count', 0) + count

    # 순매수 합계 계산
    for ticker, data in by_ticker.items():
        for inv in ['외국인', '기관', '개인']:
            buy = data.get(f'{inv}_buy', 0)
            sell = data.get(f'{inv}_sell', 0)
            data[f'{inv}_net'] = buy + sell
        data['cat'] = all_user_codes[ticker][0]

    return by_ticker


def main():
    if not os.path.exists(DB_PATH):
        print(f"❌ DB 없음: {DB_PATH}")
        print(f"먼저 manual_input.py 실행하세요.")
        return

    period_arg = sys.argv[1] if len(sys.argv) > 1 else None
    start, end = parse_period(period_arg)
    period_label = f"{start}~{end}" if start else "전체"

    conn = sqlite3.connect(DB_PATH)

    print("=" * 90)
    print(f"📊 매매동향 분석 [{period_label}]")
    print("=" * 90)

    # 1. 투자자별 누적 TOP 10
    for investor in ['외국인', '기관', '개인']:
        top_buy, top_sell = get_cumulative_top(conn, start, end, investor, 10)
        print(f"\n[{investor}]")
        print(f"  🟢 누적 순매수 TOP 10")
        for i, (ticker, name, value, cnt, dates) in enumerate(top_buy, 1):
            print(f"    {i:2d}. {name:<35} ({ticker}) +{value/1e8:>8,.0f}억  ({cnt}회)")
        print(f"  🔴 누적 순매도 TOP 10")
        for i, (ticker, name, value, cnt, dates) in enumerate(top_sell, 1):
            print(f"    {i:2d}. {name:<35} ({ticker}) {value/1e8:>+8,.0f}억  ({cnt}회)")

    # 2. 외국인+기관 동시 매수/매도
    print(f"\n{'='*90}")
    print(f"🎯 외국인+기관 동시 매매 (강한 시그널)")
    print(f"{'='*90}")
    strong_buy, strong_sell = find_strong_signals(conn, start, end)

    print(f"\n🟢🟢 강한 매수 (외국인+기관 동시 매수): {len(strong_buy)}종목")
    for i, (ticker, name, total, f, k) in enumerate(strong_buy[:15], 1):
        print(f"  {i:2d}. {name:<35} ({ticker}) 합계 +{total/1e8:>6,.0f}억 (외{f/1e8:+.0f}/기{k/1e8:+.0f})")

    print(f"\n🔴🔴 강한 매도 (외국인+기관 동시 매도): {len(strong_sell)}종목")
    for i, (ticker, name, total, f, k) in enumerate(strong_sell[:15], 1):
        print(f"  {i:2d}. {name:<35} ({ticker}) 합계 {total/1e8:>+6,.0f}억 (외{f/1e8:+.0f}/기{k/1e8:+.0f})")

    # 3. 사용자 보유/watchlist 종목 매매 동향
    print(f"\n{'='*90}")
    print(f"👤 사용자 보유/Watchlist 종목 누적 매매 동향")
    print(f"{'='*90}")
    user_flow = user_holdings_flow(conn, start, end)

    if not user_flow:
        print("  (TOP 20 진입 없음)")
    else:
        print(f"\n{'카테고리':<10} {'종목':<25} {'코드':<8} {'외국인':<12} {'기관':<12} {'개인':<12}")
        print('-' * 90)
        # 정렬: 외국인+기관 합계 큰 순
        sorted_tickers = sorted(user_flow.items(), key=lambda x: -(x[1].get('외국인_net', 0) + x[1].get('기관_net', 0)))
        for ticker, data in sorted_tickers:
            f = data.get('외국인_net', 0) / 1e8
            i = data.get('기관_net', 0) / 1e8
            p = data.get('개인_net', 0) / 1e8
            f_str = f"+{f:.0f}억" if f > 0 else f"{f:.0f}억"
            i_str = f"+{i:.0f}억" if i > 0 else f"{i:.0f}억"
            p_str = f"+{p:.0f}억" if p > 0 else f"{p:.0f}억"
            print(f"{data.get('cat', '?'):<10} {data['name']:<25} {ticker:<8} {f_str:<12} {i_str:<12} {p_str:<12}")

    conn.close()
    print()


if __name__ == '__main__':
    main()
