"""
KIS API 수급 자동 수집 → krx_flow.db 저장
실행: 장마감 후 (15:30 이후)

  python auto_collect.py              # 오늘 날짜
  python auto_collect.py 20260601     # 날짜 지정
"""
import sys
import os
import sqlite3
from datetime import datetime
import pandas as pd
import time

sys.path.insert(0, os.path.expanduser('~/Desktop/open-trading-api/examples_llm'))
import kis_auth as ka

DB_PATH = os.path.expanduser('~/chikitaka/dart-insight/data/krx_flow.db')
API_URL = "/uapi/domestic-stock/v1/quotations/foreign-institution-total"


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS net_purchases (
            date TEXT, market TEXT, investor TEXT,
            ticker TEXT, name TEXT,
            net_value INTEGER, rank INTEGER,
            UNIQUE(date, market, investor, ticker, rank)
        )
    ''')
    conn.commit()
    return conn


def fetch_ranking(investor_code: str, buy_sell_code: str) -> pd.DataFrame:
    """
    investor_code: '1'=외국인, '2'=기관계
    buy_sell_code: '0'=순매수상위, '1'=순매도상위
    반환: 최대 30행 DataFrame
    """
    params = {
        "FID_COND_MRKT_DIV_CODE": "V",
        "FID_COND_SCR_DIV_CODE": "16449",
        "FID_INPUT_ISCD": "0001",      # 코스피
        "FID_DIV_CLS_CODE": "1",       # 금액 정렬
        "FID_RANK_SORT_CLS_CODE": buy_sell_code,
        "FID_ETC_CLS_CODE": investor_code,
    }
    res = ka._url_fetch(API_URL, "FHPTJ04400000", "", params)
    if res.isOK():
        return pd.DataFrame(res.getBody().output)
    res.printError(url=API_URL)
    return pd.DataFrame()


def save_ranking(conn, date: str, investor: str, kind: str, df: pd.DataFrame, value_col: str):
    """
    investor: '외국인' | '기관'
    kind:     'buy' | 'sell'
    value_col: API 금액 컬럼명 (백만원 단위)
    """
    sign = 1 if kind == 'buy' else -1
    saved = 0
    for rank, row in enumerate(df.itertuples(index=False), start=1):
        ticker = getattr(row, 'mksc_shrn_iscd', '?')
        name   = getattr(row, 'hts_kor_isnm', '?')
        raw    = getattr(row, value_col, '0')
        try:
            # 백만원 → 원
            net_value = sign * abs(int(float(raw) * 1_000_000))
        except (ValueError, TypeError):
            net_value = 0

        try:
            conn.execute('''
                INSERT OR REPLACE INTO net_purchases
                (date, market, investor, ticker, name, net_value, rank)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (date, 'KOSPI', f'{investor}_{kind}', ticker, name, net_value, rank))
            saved += 1
        except Exception as e:
            print(f"  ERR ({name}): {e}")

    conn.commit()
    return saved


def collect(date: str):
    print(f"\n{'='*50}")
    print(f"수급 자동 수집: {date}")
    print(f"{'='*50}")

    ka.auth()
    conn = init_db()

    # (investor_code, buy_sell_code, investor_label, kind, value_col)
    tasks = [
        ('1', '0', '외국인', 'buy',  'frgn_ntby_tr_pbmn'),
        ('1', '1', '외국인', 'sell', 'frgn_ntby_tr_pbmn'),
        ('2', '0', '기관',   'buy',  'orgn_ntby_tr_pbmn'),
        ('2', '1', '기관',   'sell', 'orgn_ntby_tr_pbmn'),
    ]

    labels = {'1': '외국인', '2': '기관'}
    bs_labels = {'0': '순매수', '1': '순매도'}

    for inv_code, bs_code, investor, kind, val_col in tasks:
        label = f"{labels[inv_code]} {bs_labels[bs_code]} 상위"
        df = fetch_ranking(inv_code, bs_code)
        if df.empty:
            print(f"  ⚠️ {label}: 데이터 없음")
            continue
        n = save_ranking(conn, date, investor, kind, df, val_col)
        top3 = ', '.join(df['hts_kor_isnm'].head(3).tolist()) if 'hts_kor_isnm' in df.columns else ''
        print(f"  ✅ {label}: {n}건 저장  [{top3}...]")
        time.sleep(0.2)  # API rate limit

    conn.close()

    # 저장 확인
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute(
        "SELECT COUNT(*) FROM net_purchases WHERE date=?", (date,)
    ).fetchone()[0]
    conn.close()
    print(f"\n완료: {date} 총 {total}건 DB 저장")


if __name__ == '__main__':
    target_date = sys.argv[1] if len(sys.argv) > 1 else datetime.today().strftime('%Y%m%d')
    collect(target_date)
