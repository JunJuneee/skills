"""Telegram notification bot for DART alerts."""
from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Telegram 메시지 전송."""
        try:
            resp = requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            resp.raise_for_status()
            logger.info("Telegram message sent successfully")
            return True
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    def send_disclosure_alert(self, corp_name: str, report_nm: str,
                              importance: str, changes: list[dict],
                              new_items: list[dict],
                              blog_summary: str = "") -> bool:
        """공시 알림 메시지 전송."""
        emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(importance, "⚪")

        lines = [
            f"{emoji} *{corp_name}* - 새 공시",
            f"📋 {report_nm}",
            f"중요도: {importance}",
            "",
        ]

        if changes:
            lines.append("📊 *주요 변동*")
            for c in changes[:5]:
                sign = "📈" if c["change_rate"] > 0 else "📉"
                lines.append(
                    f"  {sign} {c['account_name']}: {c['change_rate']:+.1f}%"
                )
            lines.append("")

        if new_items:
            lines.append("🆕 *신규 항목*")
            for item in new_items[:3]:
                lines.append(f"  • {item['account_name']}")
            lines.append("")

        if blog_summary:
            lines.append(f"📝 {blog_summary}")

        return self.send_message("\n".join(lines))

    def send_daily_summary(self, date: str, disclosures: list[dict]) -> bool:
        """일일 요약 메시지."""
        if not disclosures:
            return self.send_message(f"📊 *{date} 일일 요약*\n\n새로운 중요 공시가 없습니다.")

        high = [d for d in disclosures if d.get("importance_score") == "HIGH"]
        medium = [d for d in disclosures if d.get("importance_score") == "MEDIUM"]

        lines = [
            f"📊 *{date} 일일 요약*",
            f"총 {len(disclosures)}건 공시 (🔴 {len(high)}건, 🟡 {len(medium)}건)",
            "",
        ]

        if high:
            lines.append("*🔴 주요 공시*")
            for d in high[:10]:
                lines.append(f"  • {d.get('corp_name', '')} - {d.get('report_nm', '')}")
            lines.append("")

        if medium:
            lines.append("*🟡 관심 공시*")
            for d in medium[:5]:
                lines.append(f"  • {d.get('corp_name', '')} - {d.get('report_nm', '')}")

        return self.send_message("\n".join(lines))
