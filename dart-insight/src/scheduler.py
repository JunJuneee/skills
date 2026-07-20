"""Daily scheduler - runs after market close."""
from __future__ import annotations

import logging
import os
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

from src.dart_client import DartClient
from src.collector import check_new_disclosures, collect_financials
from src.analyzer import get_importance_report
from src.blog_generator import generate_blog_post
from src.telegram_bot import TelegramNotifier
from src import db

load_dotenv()
logger = logging.getLogger(__name__)


def daily_job() -> None:
    """장 마감 후 일일 작업."""
    logger.info("=== Daily job started ===")
    today = datetime.now().strftime("%Y%m%d")

    dart_key = os.environ["DART_API_KEY"]
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    tg_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    client = DartClient(dart_key)
    notifier = TelegramNotifier(tg_token, tg_chat_id) if tg_token and tg_chat_id else None

    # 1. 신규 공시 확인
    disclosures = check_new_disclosures(client, today)
    high_disclosures = [d for d in disclosures if d.get("importance_score") == "HIGH"]

    logger.info(f"Found {len(disclosures)} disclosures, {len(high_disclosures)} HIGH importance")

    # 2. HIGH 공시 기업의 재무데이터 업데이트 + 분석 + 블로그 생성
    for disc in high_disclosures:
        corp_code = disc.get("corp_code", "")
        corp_name = disc.get("corp_name", "")
        report_nm = disc.get("report_nm", "")
        rcept_no = disc.get("rcept_no", "")

        try:
            # 재무데이터 수집
            collect_financials(client, corp_code, corp_name)

            # 분석
            report = get_importance_report(corp_code)

            # 블로그 포스트 생성
            blog_result = {}
            if anthropic_key:
                blog_result = generate_blog_post(
                    corp_code, corp_name, anthropic_key, disclosure_ref=rcept_no
                )

            # Telegram 알림
            if notifier:
                notifier.send_disclosure_alert(
                    corp_name=corp_name,
                    report_nm=report_nm,
                    importance=report["importance"],
                    changes=report.get("high_changes", []),
                    new_items=report.get("new_items", []),
                    blog_summary=blog_result.get("summary", ""),
                )

            db.mark_disclosure_processed(rcept_no)
            logger.info(f"Processed: {corp_name} - {report_nm}")

        except Exception as e:
            logger.error(f"Failed to process {corp_name}: {e}")

    # 3. 일일 요약 Telegram 전송
    if notifier and disclosures:
        notifier.send_daily_summary(today, disclosures)

    logger.info("=== Daily job completed ===")


def run_scheduler() -> None:
    """스케줄러 실행 - 매일 16:30 KST."""
    db.init_db()

    scheduler = BlockingScheduler(timezone="Asia/Seoul")
    scheduler.add_job(daily_job, "cron", hour=16, minute=30, id="daily_dart")

    logger.info("Scheduler started. Daily job at 16:30 KST.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_scheduler()
