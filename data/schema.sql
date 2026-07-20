-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
-- KRX Flow DB Schema
-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CREATE TABLE IF NOT EXISTS net_purchases (
    date TEXT NOT NULL,           -- YYYYMMDD (예: 20260617)
    market TEXT NOT NULL,         -- KOSPI / KOSDAQ
    investor TEXT NOT NULL,       -- 외국인_buy/sell, 기관_buy/sell, 개인_buy/sell
    ticker TEXT NOT NULL,         -- 종목코드 (6자리)
    name TEXT NOT NULL,           -- 종목명
    net_value INTEGER NOT NULL,   -- 금액 (원, 양수=순매수, 음수=순매도)
    rank INTEGER NOT NULL,        -- TOP30 순위 (1~30)
    UNIQUE(date, market, investor, ticker, rank)
);

CREATE INDEX IF NOT EXISTS idx_date ON net_purchases(date);
CREATE INDEX IF NOT EXISTS idx_ticker ON net_purchases(ticker);
CREATE INDEX IF NOT EXISTS idx_investor_date ON net_purchases(investor, date);

-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
-- 예제 쿼리
-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

-- 특정 날짜 외국인 매수 TOP10
-- SELECT rank, name, abs(net_value)/100000000 as 억원
-- FROM net_purchases
-- WHERE date='20260617' AND investor='외국인_buy'
-- ORDER BY rank LIMIT 10;

-- 특정 종목 3일 외국인 흐름
-- SELECT date, investor, abs(net_value)/100000000 as 억원
-- FROM net_purchases
-- WHERE ticker='000660' AND date >= '20260615'
-- ORDER BY date, investor;

-- 외+기 동시 매수 종목 찾기
-- SELECT a.name, a.net_value as 외국인, b.net_value as 기관
-- FROM net_purchases a, net_purchases b
-- WHERE a.date=b.date AND a.ticker=b.ticker
--   AND a.investor='외국인_buy' AND b.investor='기관_buy'
--   AND a.date='20260617';
