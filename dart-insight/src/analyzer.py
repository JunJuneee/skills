"""Financial analysis engine - comparisons, trend detection, new item alerts."""
from __future__ import annotations

import logging

import pandas as pd

from src import db

logger = logging.getLogger(__name__)


def analyze_company(corp_code: str) -> dict:
    """기업의 전체 재무 분석을 수행.

    Returns:
        dict with keys: summary, changes, new_items, trends
    """
    financials = db.get_financials(corp_code)
    if not financials:
        return {"summary": {}, "changes": [], "new_items": [], "trends": {}}

    df = pd.DataFrame(financials)

    return {
        "summary": _build_summary(df),
        "changes": _detect_significant_changes(df),
        "new_items": _find_new_items(df),
        "trends": _calculate_trends(df),
        "ratios": _calculate_ratios(df),
        "quality_signals": _assess_earnings_quality(df),
    }


def compare_periods(corp_code: str, year1: int, q1: str,
                    year2: int, q2: str) -> list[dict]:
    """두 기간의 재무제표를 비교."""
    conn = db.get_connection()
    rows1 = conn.execute(
        "SELECT account_name, report_type, amount FROM financials WHERE corp_code=? AND year=? AND quarter=?",
        (corp_code, year1, q1),
    ).fetchall()
    rows2 = conn.execute(
        "SELECT account_name, report_type, amount FROM financials WHERE corp_code=? AND year=? AND quarter=?",
        (corp_code, year2, q2),
    ).fetchall()
    conn.close()

    prev_map = {(r["account_name"], r["report_type"]): r["amount"] for r in rows1}
    curr_map = {(r["account_name"], r["report_type"]): r["amount"] for r in rows2}

    all_keys = set(prev_map.keys()) | set(curr_map.keys())
    comparisons = []

    for key in sorted(all_keys):
        account_name, report_type = key
        prev_val = prev_map.get(key)
        curr_val = curr_map.get(key)

        change_rate = None
        if prev_val and curr_val and prev_val != 0:
            change_rate = ((curr_val - prev_val) / abs(prev_val)) * 100

        is_new = key not in prev_map
        is_removed = key not in curr_map

        comparisons.append({
            "account_name": account_name,
            "report_type": report_type,
            "prev_amount": prev_val,
            "curr_amount": curr_val,
            "change_rate": round(change_rate, 2) if change_rate is not None else None,
            "is_new": is_new,
            "is_removed": is_removed,
        })

    return comparisons


def get_importance_report(corp_code: str) -> dict:
    """중요 변동사항 요약 리포트 생성."""
    analysis = analyze_company(corp_code)

    high_changes = [c for c in analysis["changes"] if abs(c.get("change_rate", 0) or 0) >= 20]
    new_items = analysis["new_items"]

    importance = "LOW"
    if high_changes or new_items:
        importance = "HIGH"
    elif analysis["changes"]:
        importance = "MEDIUM"

    return {
        "importance": importance,
        "high_changes": high_changes,
        "new_items": new_items,
        "trends": analysis["trends"],
        "summary": analysis["summary"],
    }


def _build_summary(df: pd.DataFrame) -> dict:
    """최신 분기 재무 요약."""
    if df.empty:
        return {}

    latest = df.sort_values(["year", "quarter"], ascending=False)
    latest_year = latest.iloc[0]["year"]
    latest_quarter = latest.iloc[0]["quarter"]

    latest_data = latest[(latest["year"] == latest_year) & (latest["quarter"] == latest_quarter)]

    key_accounts = ["매출액", "영업이익", "당기순이익", "자산총계", "부채총계", "자본총계"]
    summary = {"period": f"{latest_year} {latest_quarter}"}

    for _, row in latest_data.iterrows():
        if row["account_name"] in key_accounts:
            summary[row["account_name"]] = {
                "amount": row["amount"],
                "prev_amount": row["prev_amount"],
                "change_rate": _calc_change_rate(row["amount"], row["prev_amount"]),
            }

    return summary


def _detect_significant_changes(df: pd.DataFrame) -> list[dict]:
    """전기 대비 significant 변동 탐지 (±20% 이상)."""
    if df.empty:
        return []

    latest = df.sort_values(["year", "quarter"], ascending=False)
    latest_year = latest.iloc[0]["year"]
    latest_quarter = latest.iloc[0]["quarter"]

    latest_data = latest[(latest["year"] == latest_year) & (latest["quarter"] == latest_quarter)]

    changes = []
    for _, row in latest_data.iterrows():
        rate = _calc_change_rate(row["amount"], row["prev_amount"])
        if rate is not None and abs(rate) >= 20:
            changes.append({
                "account_name": row["account_name"],
                "report_type": row["report_type"],
                "amount": row["amount"],
                "prev_amount": row["prev_amount"],
                "change_rate": rate,
            })

    return sorted(changes, key=lambda x: abs(x["change_rate"]), reverse=True)


def _find_new_items(df: pd.DataFrame) -> list[dict]:
    """신규 등장 계정과목."""
    new_items_df = df[df["is_new_item"] == 1]
    return new_items_df[["year", "quarter", "report_type", "account_name", "amount"]].to_dict("records")


def _calculate_trends(df: pd.DataFrame) -> dict:
    """주요 계정의 분기별 추이."""
    key_accounts = ["매출액", "영업이익", "당기순이익"]
    trends = {}

    for account in key_accounts:
        account_data = df[df["account_name"] == account].sort_values(["year", "quarter"])
        if account_data.empty:
            continue
        trends[account] = [
            {
                "period": f"{row['year']} {row['quarter']}",
                "amount": row["amount"],
            }
            for _, row in account_data.iterrows()
            if row["amount"] is not None
        ]

    return trends


def _calculate_ratios(df: pd.DataFrame) -> dict:
    """주요 재무비율 계산 (최신 분기 기준)."""
    if df.empty:
        return {}

    latest = df.sort_values(["year", "quarter"], ascending=False)
    latest_year = latest.iloc[0]["year"]
    latest_quarter = latest.iloc[0]["quarter"]
    data = latest[(latest["year"] == latest_year) & (latest["quarter"] == latest_quarter)]

    accounts = {}
    for _, row in data.iterrows():
        accounts[row["account_name"]] = row["amount"]

    ratios = {"period": f"{latest_year} {latest_quarter}"}

    revenue = accounts.get("매출액")
    op_income = accounts.get("영업이익")
    net_income = accounts.get("당기순이익")
    total_assets = accounts.get("자산총계")
    total_debt = accounts.get("부채총계")
    total_equity = accounts.get("자본총계")
    cost_of_sales = accounts.get("매출원가")
    operating_cf = accounts.get("영업활동현금흐름") or accounts.get("영업활동으로인한현금흐름")

    # 수익성 비율
    if revenue and revenue != 0:
        if op_income is not None:
            ratios["영업이익률"] = round(op_income / revenue * 100, 2)
        if net_income is not None:
            ratios["순이익률"] = round(net_income / revenue * 100, 2)
        if cost_of_sales is not None:
            ratios["매출원가율"] = round(cost_of_sales / revenue * 100, 2)
            ratios["매출총이익률"] = round((revenue - cost_of_sales) / revenue * 100, 2)

    # 안정성 비율
    if total_equity and total_equity != 0:
        if total_debt is not None:
            ratios["부채비율"] = round(total_debt / total_equity * 100, 2)
        if net_income is not None:
            ratios["ROE"] = round(net_income / total_equity * 100, 2)

    if total_assets and total_assets != 0:
        if net_income is not None:
            ratios["ROA"] = round(net_income / total_assets * 100, 2)
        if total_equity is not None:
            ratios["자기자본비율"] = round(total_equity / total_assets * 100, 2)

    # 현금흐름 품질
    if op_income and op_income != 0 and operating_cf is not None:
        ratios["현금흐름_영업이익_비율"] = round(operating_cf / op_income * 100, 2)

    return ratios


def _assess_earnings_quality(df: pd.DataFrame) -> list[dict]:
    """이익의 질(quality) 시그널 감지 - 애널리스트 관점."""
    if df.empty:
        return []

    signals = []
    latest = df.sort_values(["year", "quarter"], ascending=False)
    latest_year = latest.iloc[0]["year"]
    latest_quarter = latest.iloc[0]["quarter"]
    data = latest[(latest["year"] == latest_year) & (latest["quarter"] == latest_quarter)]

    accounts = {}
    prev_accounts = {}
    for _, row in data.iterrows():
        accounts[row["account_name"]] = row["amount"]
        prev_accounts[row["account_name"]] = row["prev_amount"]

    revenue = accounts.get("매출액")
    prev_revenue = prev_accounts.get("매출액")
    op_income = accounts.get("영업이익")
    prev_op_income = prev_accounts.get("영업이익")
    net_income = accounts.get("당기순이익")
    receivables = accounts.get("매출채권") or accounts.get("매출채권및기타채권")
    prev_receivables = prev_accounts.get("매출채권") or prev_accounts.get("매출채권및기타채권")
    inventory = accounts.get("재고자산")
    prev_inventory = prev_accounts.get("재고자산")
    operating_cf = accounts.get("영업활동현금흐름") or accounts.get("영업활동으로인한현금흐름")

    # 매출채권 증가율 > 매출 증가율 → 매출 quality 의심
    if all(v and v != 0 for v in [revenue, prev_revenue, receivables, prev_receivables]):
        rev_growth = (revenue - prev_revenue) / abs(prev_revenue) * 100
        recv_growth = (receivables - prev_receivables) / abs(prev_receivables) * 100
        if recv_growth > rev_growth + 10:
            signals.append({
                "type": "WARNING",
                "signal": "매출채권 과다 증가",
                "detail": f"매출채권 증가율({recv_growth:.1f}%)이 매출 증가율({rev_growth:.1f}%)을 크게 상회. "
                          "대손 리스크 또는 공격적 매출 인식 가능성.",
            })

    # 재고자산 급증 → 수요 둔화 또는 비효율
    if all(v and v != 0 for v in [inventory, prev_inventory]):
        inv_growth = (inventory - prev_inventory) / abs(prev_inventory) * 100
        if inv_growth > 30:
            signals.append({
                "type": "WARNING",
                "signal": "재고자산 급증",
                "detail": f"재고자산이 {inv_growth:.1f}% 증가. 수요 둔화, 과잉 생산, "
                          "또는 재고 평가손실 리스크 점검 필요.",
            })

    # 영업이익 증가인데 영업CF 감소 → 이익의 질 저하
    if all(v is not None for v in [op_income, prev_op_income, operating_cf]):
        if op_income > prev_op_income and operating_cf < op_income * 0.5:
            signals.append({
                "type": "WARNING",
                "signal": "이익의 질 저하 의심",
                "detail": "영업이익이 증가했지만 영업현금흐름이 영업이익의 50% 미만. "
                          "운전자본 변동, 미수금 증가 등 확인 필요.",
            })

    # 매출 성장 + 영업이익 감소 → 수익성 악화
    if all(v and v != 0 for v in [revenue, prev_revenue, op_income, prev_op_income]):
        if revenue > prev_revenue and op_income < prev_op_income:
            signals.append({
                "type": "CAUTION",
                "signal": "외형 성장 vs 수익성 악화",
                "detail": "매출은 성장했지만 영업이익이 감소. 원가 상승, "
                          "판관비 증가, 또는 저마진 사업 비중 확대 가능성.",
            })

    # 당기순이익 >> 영업이익 → 일회성 이익 의심
    if all(v is not None and v != 0 for v in [net_income, op_income]):
        if net_income > op_income * 1.5 and net_income > 0:
            signals.append({
                "type": "INFO",
                "signal": "영업외이익 과다",
                "detail": f"당기순이익이 영업이익의 {net_income/op_income:.1f}배. "
                          "자산매각, 환차익 등 일회성 이익 포함 가능성. 지속가능성 점검.",
            })

    # 긍정 시그널: 영업CF > 당기순이익
    if all(v is not None and v > 0 for v in [operating_cf, net_income]):
        if operating_cf > net_income:
            signals.append({
                "type": "POSITIVE",
                "signal": "현금흐름 우수",
                "detail": "영업현금흐름이 당기순이익을 상회. 이익의 현금 창출력이 양호하며, "
                          "실질적 수익 품질이 높음.",
            })

    return signals


def _calc_change_rate(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return round(((current - previous) / abs(previous)) * 100, 2)
