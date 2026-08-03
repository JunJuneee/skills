#!/usr/bin/env python3
"""Create Coupang Partners affiliate deep links without exposing credentials."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit


API_HOST = "https://api-gateway.coupang.com"
API_PATH = "/v2/providers/affiliate_open_api/apis/openapi/v1/deeplink"
ACCESS_KEY_ENV = "COUPANG_PARTNERS_ACCESS_KEY"
SECRET_KEY_ENV = "COUPANG_PARTNERS_SECRET_KEY"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert Coupang URLs to Coupang Partners affiliate links."
    )
    parser.add_argument("urls", nargs="+", help="One to twenty Coupang URLs")
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Print the successful API response as JSON",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds (default: 30)",
    )
    return parser.parse_args()


def validate_urls(urls: list[str]) -> None:
    if len(urls) > 20:
        raise ValueError("한 번에 최대 20개의 URL만 처리할 수 있습니다.")

    for url in urls:
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").lower()
        is_coupang = hostname == "coupang.com" or hostname.endswith(".coupang.com")
        if parsed.scheme not in {"http", "https"} or not is_coupang:
            raise ValueError(f"쿠팡 URL이 아닙니다: {url}")


def build_authorization(access_key: str, secret_key: str) -> str:
    signed_date = time.strftime("%y%m%dT%H%M%SZ", time.gmtime())
    message = f"{signed_date}POST{API_PATH}"
    signature = hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return (
        "CEA algorithm=HmacSHA256, "
        f"access-key={access_key}, "
        f"signed-date={signed_date}, "
        f"signature={signature}"
    )


def safe_api_message(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        for key in ("rMessage", "message", "error"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().splitlines()[0]
    return fallback


def request_deeplinks(
    urls: list[str], access_key: str, secret_key: str, timeout: float
) -> tuple[int, dict[str, Any]]:
    body = json.dumps({"coupangUrls": urls}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{API_HOST}{API_PATH}",
        data=body,
        method="POST",
        headers={
            "Authorization": build_authorization(access_key, secret_key),
            "Content-Type": "application/json;charset=UTF-8",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
        message = safe_api_message(payload, error.reason or "HTTP 요청 실패")
        print(f"HTTP {error.code}: {message}", file=sys.stderr)
        raise SystemExit(3) from None
    except urllib.error.URLError as error:
        print(f"네트워크 오류: {error.reason}", file=sys.stderr)
        raise SystemExit(3) from None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print(f"HTTP {status}: JSON 응답이 아닙니다.", file=sys.stderr)
        raise SystemExit(4) from None

    return status, payload


def validate_response(
    status: int, payload: dict[str, Any], expected_count: int
) -> list[dict[str, Any]]:
    result_code = str(payload.get("rCode", ""))
    data = payload.get("data")
    if status != 200 or result_code != "0":
        message = safe_api_message(payload, "API가 성공 결과를 반환하지 않았습니다.")
        print(f"HTTP {status}, rCode {result_code or '(없음)'}: {message}", file=sys.stderr)
        raise SystemExit(4)
    if not isinstance(data, list) or len(data) != expected_count:
        print("API 응답의 변환 결과 개수가 요청과 다릅니다.", file=sys.stderr)
        raise SystemExit(4)
    if any(not isinstance(item, dict) or not item.get("shortenUrl") for item in data):
        print("API 응답에 shortenUrl이 없는 항목이 있습니다.", file=sys.stderr)
        raise SystemExit(4)
    return data


def main() -> int:
    args = parse_args()
    try:
        validate_urls(args.urls)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2

    missing = [
        name
        for name in (ACCESS_KEY_ENV, SECRET_KEY_ENV)
        if not os.environ.get(name)
    ]
    if missing:
        print(f"환경변수가 설정되지 않았습니다: {', '.join(missing)}", file=sys.stderr)
        return 2

    status, payload = request_deeplinks(
        args.urls,
        os.environ[ACCESS_KEY_ENV],
        os.environ[SECRET_KEY_ENV],
        args.timeout,
    )
    data = validate_response(status, payload, len(args.urls))

    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"API 정상: HTTP {status}, rCode {payload['rCode']}")
        for item in data:
            print(f"원본: {item.get('originalUrl', '')}")
            print(f"파트너스 링크: {item['shortenUrl']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
