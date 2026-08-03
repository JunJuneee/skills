"""종목 해석(이름→코드) + 단일종목 분석.
   - 이름→코드 해석: FDR StockListing (가벼움)
   - 시세/지표: KIS 데이터 (kis_data) — 실데이터"""
import sys
sys.path.insert(0, "/Users/jun/claude-agents/kis")
import kis_data as kd

# 보유 종목 매입가 (손익 표시용). 실계좌 연동 대신 수동 맵 사용.
HOLDINGS = {
    "000660": (15, 1030733), "442580": (174, 122472), "423920": (16, 137325),
    "381180": (3, 46530), "000720": (33, 169015), "005385": (20, 273000),
    "449450": (13, 76560), "487240": (3, 49200), "453950": (30, 33720),
    "379810": (37, 27375),
}

_listing = None
def load_listing():
    global _listing
    if _listing is not None:
        return _listing
    import FinanceDataReader as fdr
    name2code, code2name = {}, {}
    for src, csym, cname in [("KRX", "Code", "Name"), ("ETF/KR", "Symbol", "Name")]:
        try:
            df = fdr.StockListing(src)
            for _, r in df.iterrows():
                code = str(r[csym]).zfill(6); nm = str(r[cname]).strip()
                if code and nm and code != "nan":
                    name2code.setdefault(nm, code); code2name.setdefault(code, nm)
        except Exception:
            pass
    _listing = (name2code, code2name)
    return _listing

def resolve(query):
    """종목명 또는 6자리 코드 -> (code, name) | None"""
    q = query.strip()
    name2code, code2name = load_listing()
    if q.isdigit() and len(q) == 6:
        return (q, code2name.get(q, q))
    if q in name2code:
        return (name2code[q], q)
    cands = [(n, c) for n, c in name2code.items() if q in n]
    if cands:
        cands.sort(key=lambda x: len(x[0]))
        return (cands[0][1], cands[0][0])
    return None

def analyze(code, name):
    """KIS 데이터 기반 분석 + 보유 시 손익 + 간단 종합판단."""
    a = kd.analyze(code, name)
    if "err" in a:
        return a
    if code in HOLDINGS:
        qty, buy = HOLDINGS[code]
        a["held"] = True; a["qty"] = qty; a["buy"] = buy
        a["pl"] = qty*(a["last"]-buy); a["plpct"] = (a["last"]/buy-1)*100
    else:
        a["held"] = False
    score = 0
    if a.get("ma200") and a["last"] > a["ma200"]: score += 1
    if a["last"] > a["ma50"]: score += 1
    if a["align"] == "정배열": score += 1
    if 40 <= a["rsi"] <= 70: score += 1
    if a["rsi"] > 78: score -= 1
    a["verdict"] = "강세" if score >= 3 else ("약세" if score <= 1 else "중립")
    return a
