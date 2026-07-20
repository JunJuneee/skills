"""
누락 날짜 backfill: KOSPI 상위 100종목 investor_trade_by_stock_daily → DB 저장
- 외국인/기관 순매수 TOP30 재구성 (개인 미포함)
실행: python backfill.py
"""
import sys, os, sqlite3, time
from datetime import date, timedelta
import pandas as pd

sys.path.insert(0, os.path.expanduser('~/Desktop/open-trading-api/examples_llm'))
import kis_auth as ka
import FinanceDataReader as fdr

DB_PATH = os.path.expanduser('~/chikitaka/dart-insight/data/krx_flow.db')
API_URL = "/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily"

HOLIDAYS_2026 = {'20260101','20260301','20260505','20260506','20260815'}

def get_missing_dates():
    conn = sqlite3.connect(DB_PATH)
    existing = {r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM net_purchases WHERE investor LIKE '외국인%'"
    ).fetchall()}
    conn.close()

    missing = []
    d = date(2026, 4, 1)
    end = date(2026, 5, 31)
    while d <= end:
        ds = d.strftime('%Y%m%d')
        if d.weekday() < 5 and ds not in existing and ds not in HOLIDAYS_2026:
            missing.append(ds)
        d += timedelta(days=1)
    return missing


def fetch_stock_investor(code, ref_date):
    """종목별 투자자매매동향 조회 (ref_date 기준 ~30영업일치)"""
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": code,
        "FID_INPUT_DATE_1": ref_date,
        "FID_ORG_ADJ_PRC": "",
        "FID_ETC_CLS_CODE": "",
    }
    res = ka._url_fetch(API_URL, "FHPTJ04160001", "", params)
    if not res.isOK():
        return pd.DataFrame()
    body = res.getBody()
    if hasattr(body, 'output2') and body.output2:
        return pd.DataFrame(body.output2)
    return pd.DataFrame()


def save_rankings(conn, date_str, investor_label, kind, ranked_df, value_col):
    sign = 1 if kind == 'buy' else -1
    saved = 0
    for rank, row in enumerate(ranked_df.head(30).itertuples(index=False), start=1):
        ticker = getattr(row, 'ticker', '?')
        name   = getattr(row, 'name', '?')
        raw    = getattr(row, value_col, 0)
        try:
            net_value = sign * abs(int(float(raw) * 1_000_000))
        except:
            net_value = 0
        try:
            conn.execute('''
                INSERT OR REPLACE INTO net_purchases
                (date, market, investor, ticker, name, net_value, rank)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (date_str, 'KOSPI', f'{investor_label}_{kind}', ticker, name, net_value, rank))
            saved += 1
        except Exception as e:
            pass
    conn.commit()
    return saved


def main():
    missing = get_missing_dates()
    if not missing:
        print("누락 날짜 없음.")
        return

    print(f"누락 날짜 {len(missing)}일 backfill 시작")

    # KOSPI 상위 100종목
    print("KOSPI 상위 100종목 조회 중...")
    ks = fdr.StockListing('KOSPI')
    ks = ks[ks['Marcap'].notna()].sort_values('Marcap', ascending=False).head(100)
    stocks = [(str(r['Code']).zfill(6), r['Name']) for _, r in ks.iterrows()]
    print(f"  {len(stocks)}종목 선정")

    ka.auth()

    # ref_date별 그룹: 4월 → 20260430, 5월 → 20260601
    ref_dates = {
        '20260430': [d for d in missing if d <= '20260430'],
        '20260601': [d for d in missing if d > '20260430'],
    }

    conn = sqlite3.connect(DB_PATH)

    for ref_date, target_dates in ref_dates.items():
        if not target_dates:
            continue
        print(f"\n[ref={ref_date}] 대상 날짜: {target_dates}")

        # 모든 종목의 날짜별 데이터 수집
        # date → {ticker: {frgn, orgn, name}}
        daily: dict = {}

        for i, (code, name) in enumerate(stocks):
            df = fetch_stock_investor(code, ref_date)
            time.sleep(0.12)

            if df.empty:
                continue

            for _, row in df.iterrows():
                ds = str(row.get('stck_bsop_date', ''))
                if ds not in target_dates:
                    continue
                if ds not in daily:
                    daily[ds] = []
                try:
                    daily[ds].append({
                        'ticker': code,
                        'name': name,
                        'frgn_ntby_tr_pbmn': float(row.get('frgn_ntby_tr_pbmn', 0) or 0),
                        'orgn_ntby_tr_pbmn': float(row.get('orgn_ntby_tr_pbmn', 0) or 0),
                    })
                except:
                    pass

            if (i + 1) % 20 == 0:
                print(f"  진행: {i+1}/{len(stocks)} 종목 처리")

        # 날짜별 랭킹 저장
        for ds, rows in daily.items():
            df_day = pd.DataFrame(rows)
            if df_day.empty:
                continue

            tasks = [
                ('외국인', 'buy',  'frgn_ntby_tr_pbmn'),
                ('외국인', 'sell', 'frgn_ntby_tr_pbmn'),
                ('기관',   'buy',  'orgn_ntby_tr_pbmn'),
                ('기관',   'sell', 'orgn_ntby_tr_pbmn'),
            ]
            for investor, kind, col in tasks:
                ascending = (kind == 'sell')
                ranked = df_day.sort_values(col, ascending=ascending).reset_index(drop=True)
                n = save_rankings(conn, ds, investor, kind, ranked, col)

            print(f"  ✅ {ds}: {len(df_day)}종목 데이터 → 랭킹 저장")

    conn.close()

    # 최종 확인
    conn = sqlite3.connect(DB_PATH)
    remaining = []
    for ds in missing:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM net_purchases WHERE date=? AND investor='외국인_buy'",
            (ds,)
        ).fetchone()[0]
        if cnt == 0:
            remaining.append(ds)
    conn.close()

    print(f"\n완료. 여전히 누락: {len(remaining)}일 {remaining if remaining else ''}")


if __name__ == '__main__':
    main()
