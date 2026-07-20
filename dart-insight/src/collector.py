"""KOSPI financial data collector."""
from __future__ import annotations

import logging
from datetime import datetime

from src.dart_client import DartClient
from src import db

logger = logging.getLogger(__name__)

# KOSPI 시장 구분을 위한 stock_code 범위 (6자리)
# DART API는 시장 구분을 직접 제공하지 않으므로, corp_code 목록에서 필터링


def collect_kospi_companies(client: DartClient) -> list[dict]:
    """KOSPI 상장 기업 목록을 수집하고 DB에 저장."""
    logger.info("Fetching all listed company codes from DART...")
    all_corps = client.get_corp_codes()
    logger.info(f"Total listed companies: {len(all_corps)}")

    kospi_corps = []
    for corp in all_corps:
        try:
            info = client.get_company_info(corp["corp_code"])
            market = info.get("stock_name", "")
            # DART company API에서 jurir_no 등으로 시장 구분
            # 실제로는 corp_cls 필드로 구분: Y=유가증권(KOSPI), K=코스닥, N=코넥스
            corp_cls = info.get("corp_cls", "")
            if corp_cls == "Y":  # KOSPI
                db.upsert_company(
                    corp_code=corp["corp_code"],
                    corp_name=corp["corp_name"],
                    stock_code=corp["stock_code"],
                    market="KOSPI",
                    sector=info.get("induty_code", ""),
                )
                kospi_corps.append({**corp, "market": "KOSPI"})
                logger.info(f"  KOSPI: {corp['corp_name']} ({corp['stock_code']})")
        except Exception as e:
            logger.warning(f"  Skip {corp['corp_name']}: {e}")
            continue

    logger.info(f"KOSPI companies collected: {len(kospi_corps)}")
    return kospi_corps


def collect_kospi_companies_fast(client: DartClient) -> list[dict]:
    """KOSPI 기업 목록을 빠르게 수집 (개별 API 호출 없이 corp_code 목록만 사용).

    실제 시장 구분은 이후 financial statement 수집 시 확인.
    상장사 중 stock_code가 있는 기업만 포함.
    """
    logger.info("Fetching all listed company codes from DART (fast mode)...")
    all_corps = client.get_corp_codes()

    for corp in all_corps:
        db.upsert_company(
            corp_code=corp["corp_code"],
            corp_name=corp["corp_name"],
            stock_code=corp["stock_code"],
            market="LISTED",  # 시장 구분은 나중에 업데이트
        )

    logger.info(f"Listed companies saved: {len(all_corps)}")
    return all_corps


def collect_financials(client: DartClient, corp_code: str, corp_name: str,
                       start_year: int = 2024) -> dict:
    """특정 기업의 재무제표를 수집하고 DB에 저장.

    Returns:
        dict with counts: {"collected": int, "new_items": int}
    """
    current_year = datetime.now().year
    quarters = ["1Q", "2Q", "3Q", "4Q"]
    collected = 0
    new_items = 0

    for year in range(start_year, current_year + 1):
        for quarter in quarters:
            # 미래 분기는 건너뛰기
            if _is_future_quarter(year, quarter):
                continue

            try:
                statements = client.get_financial_statements(
                    corp_code=corp_code, year=year, quarter=quarter
                )
                if not statements:
                    # 연결 재무제표 없으면 별도 재무제표 시도
                    statements = client.get_financial_statements(
                        corp_code=corp_code, year=year, quarter=quarter, fs_div="OFS"
                    )

                if not statements:
                    continue

                # 이전 분기 계정과목 목록 조회 (신규 항목 탐지용)
                prev_accounts = _get_previous_accounts(corp_code, year, quarter)

                for item in statements:
                    account_name = item.get("account_nm", "")
                    if not account_name:
                        continue

                    amount = _parse_amount(item.get("thstrm_amount", ""))
                    prev_amount = _parse_amount(item.get("frmtrm_amount", ""))
                    report_type = item.get("sj_nm", "")  # 재무제표 구분명

                    is_new = account_name not in prev_accounts if prev_accounts else False

                    db.upsert_financial(
                        corp_code=corp_code,
                        year=year,
                        quarter=quarter,
                        report_type=report_type,
                        account_name=account_name,
                        amount=amount,
                        prev_amount=prev_amount,
                        is_new_item=is_new,
                    )
                    collected += 1
                    if is_new:
                        new_items += 1

                logger.info(f"  {corp_name} {year} {quarter}: {len(statements)} items")

            except Exception as e:
                logger.warning(f"  {corp_name} {year} {quarter} failed: {e}")
                continue

    return {"collected": collected, "new_items": new_items}


def collect_all_kospi_financials(client: DartClient, start_year: int = 2024) -> dict:
    """모든 KOSPI 기업의 재무제표를 수집."""
    conn = db.get_connection()
    companies = conn.execute(
        "SELECT corp_code, corp_name FROM companies WHERE market IN ('KOSPI', 'LISTED')"
    ).fetchall()
    conn.close()

    total_collected = 0
    total_new_items = 0
    errors = 0

    logger.info(f"Collecting financials for {len(companies)} companies...")

    for i, company in enumerate(companies, 1):
        corp_code = company["corp_code"]
        corp_name = company["corp_name"]
        logger.info(f"[{i}/{len(companies)}] {corp_name}")

        try:
            result = collect_financials(client, corp_code, corp_name, start_year)
            total_collected += result["collected"]
            total_new_items += result["new_items"]
        except Exception as e:
            logger.error(f"  Error: {e}")
            errors += 1

    summary = {
        "companies": len(companies),
        "total_collected": total_collected,
        "total_new_items": total_new_items,
        "errors": errors,
    }
    logger.info(f"Collection complete: {summary}")
    return summary


def check_new_disclosures(client: DartClient, date: str | None = None) -> list[dict]:
    """오늘의 신규 공시를 확인하고 DB에 저장.

    Args:
        date: 조회 날짜 (YYYYMMDD). None이면 오늘.
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")

    logger.info(f"Checking new disclosures for {date}...")
    disclosures = client.get_disclosures(bgn_de=date, end_de=date)

    saved = []
    for disc in disclosures:
        corp_code = disc.get("corp_code", "")
        # DB에 있는 기업(KOSPI)만 처리
        conn = db.get_connection()
        company = conn.execute(
            "SELECT 1 FROM companies WHERE corp_code=?", (corp_code,)
        ).fetchone()
        conn.close()

        if not company:
            continue

        importance = _score_importance(disc)
        db.upsert_disclosure(
            rcept_no=disc.get("rcept_no", ""),
            corp_code=corp_code,
            corp_name=disc.get("corp_name", ""),
            report_nm=disc.get("report_nm", ""),
            rcept_dt=disc.get("rcept_dt", ""),
            importance_score=importance,
        )
        saved.append({**disc, "importance_score": importance})

    logger.info(f"New disclosures saved: {len(saved)} (of {len(disclosures)} total)")
    return saved


def _is_future_quarter(year: int, quarter: str) -> bool:
    now = datetime.now()
    # 보고서 제출 기한 기준 (분기 종료 후 약 45일)
    quarter_deadlines = {
        "1Q": (year, 5, 15),
        "2Q": (year, 8, 14),
        "3Q": (year, 11, 14),
        "4Q": (year + 1, 3, 31),
    }
    deadline = quarter_deadlines.get(quarter)
    if not deadline:
        return True
    return now < datetime(*deadline)


def _get_previous_accounts(corp_code: str, year: int, quarter: str) -> set[str]:
    """이전 동일 분기의 계정과목 목록을 가져옴 (YoY 비교용)."""
    prev_year = year - 1
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT DISTINCT account_name FROM financials WHERE corp_code=? AND year=? AND quarter=?",
        (corp_code, prev_year, quarter),
    ).fetchall()
    conn.close()
    return {r["account_name"] for r in rows}


def _parse_amount(value: str) -> float | None:
    if not value or value == "-":
        return None
    try:
        return float(value.replace(",", ""))
    except (ValueError, TypeError):
        return None


def _score_importance(disclosure: dict) -> str:
    """공시의 중요도를 판단."""
    report_nm = disclosure.get("report_nm", "")

    high_keywords = [
        "사업보고서", "분기보고서", "반기보고서",
        "주요사항보고서", "합병", "분할",
        "유상증자", "무상증자", "전환사채",
        "최대주주변경", "임원변동",
    ]
    medium_keywords = [
        "기업설명회", "공정공시",
        "타법인주식", "자기주식",
        "소송", "조회공시",
    ]

    for kw in high_keywords:
        if kw in report_nm:
            return "HIGH"
    for kw in medium_keywords:
        if kw in report_nm:
            return "MEDIUM"
    return "LOW"
