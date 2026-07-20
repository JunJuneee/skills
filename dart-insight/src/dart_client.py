"""DART Open API client wrapper."""
from __future__ import annotations

import io
import time
import zipfile
from xml.etree import ElementTree

import requests

BASE_URL = "https://opendart.fss.or.kr/api"

# 재무제표 report_code 매핑
REPORT_CODES = {
    "1Q": "11013",  # 1분기
    "2Q": "11012",  # 반기
    "3Q": "11014",  # 3분기
    "4Q": "11011",  # 사업보고서 (연간)
}

# 재무제표 구분
FS_DIVS = {
    "CFS": "재무제표(연결)",
    "OFS": "재무제표(별도)",
}


class DartClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._last_request_time = 0.0
        self._min_interval = 0.15  # ~7 req/sec to stay under limits

    def _request(self, endpoint: str, params: dict | None = None) -> dict:
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

        params = params or {}
        params["crtfc_key"] = self.api_key

        resp = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=30)
        resp.raise_for_status()
        self._last_request_time = time.time()

        return resp.json()

    def _request_raw(self, endpoint: str, params: dict | None = None) -> bytes:
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

        params = params or {}
        params["crtfc_key"] = self.api_key

        resp = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=60)
        resp.raise_for_status()
        self._last_request_time = time.time()

        return resp.content

    def get_corp_codes(self) -> list[dict]:
        """DART 고유번호 전체 목록 다운로드 (XML ZIP)."""
        raw = self._request_raw("corpCode.xml")
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            xml_name = zf.namelist()[0]
            with zf.open(xml_name) as f:
                tree = ElementTree.parse(f)

        corps = []
        for el in tree.findall(".//list"):
            corp_code = el.findtext("corp_code", "")
            corp_name = el.findtext("corp_name", "")
            stock_code = el.findtext("stock_code", "").strip()
            if stock_code:  # 상장사만
                corps.append({
                    "corp_code": corp_code,
                    "corp_name": corp_name,
                    "stock_code": stock_code,
                })
        return corps

    def get_company_info(self, corp_code: str) -> dict:
        """기업 개황 조회."""
        data = self._request("company.json", {"corp_code": corp_code})
        if data.get("status") != "000":
            raise ValueError(f"DART API error: {data.get('message', 'Unknown')}")
        return data

    def get_disclosures(self, bgn_de: str, end_de: str,
                        corp_code: str = "",
                        pblntf_ty: str = "A") -> list[dict]:
        """공시 검색.

        Args:
            bgn_de: 시작일 (YYYYMMDD)
            end_de: 종료일 (YYYYMMDD)
            corp_code: 기업 고유번호 (빈 문자열이면 전체)
            pblntf_ty: 공시유형 (A=정기, B=주요, C=발행, D=지분, E=기타, F=외부, G=기타)
        """
        params = {
            "bgn_de": bgn_de,
            "end_de": end_de,
            "pblntf_ty": pblntf_ty,
            "page_count": 100,
            "sort": "date",
            "sort_mth": "desc",
        }
        if corp_code:
            params["corp_code"] = corp_code

        all_items = []
        page = 1
        while True:
            params["page_no"] = page
            data = self._request("list.json", params)
            if data.get("status") != "000":
                break
            items = data.get("list", [])
            if not items:
                break
            all_items.extend(items)
            total_page = int(data.get("total_page", 1))
            if page >= total_page:
                break
            page += 1

        return all_items

    def get_financial_statements(self, corp_code: str, year: int,
                                quarter: str, fs_div: str = "CFS") -> list[dict]:
        """단일회사 전체 재무제표 조회.

        Args:
            corp_code: 기업 고유번호
            year: 사업연도 (e.g. 2024)
            quarter: 분기 ("1Q", "2Q", "3Q", "4Q")
            fs_div: "CFS" (연결) 또는 "OFS" (별도)
        """
        reprt_code = REPORT_CODES.get(quarter)
        if not reprt_code:
            raise ValueError(f"Invalid quarter: {quarter}")

        data = self._request("fnlttSinglAcntAll.json", {
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": reprt_code,
            "fs_div": fs_div,
        })

        if data.get("status") != "000":
            return []

        return data.get("list", [])

    def get_financial_summary(self, corp_code: str, year: int,
                              quarter: str, fs_div: str = "CFS") -> list[dict]:
        """단일회사 주요 재무제표 조회 (요약)."""
        reprt_code = REPORT_CODES.get(quarter)
        if not reprt_code:
            raise ValueError(f"Invalid quarter: {quarter}")

        data = self._request("fnlttSinglAcnt.json", {
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": reprt_code,
            "fs_div": fs_div,
        })

        if data.get("status") != "000":
            return []

        return data.get("list", [])
