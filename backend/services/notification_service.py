"""
Telegram notification service.

Sends alerts to a Telegram chat via the Bot API using httpx.
Includes per-alert-type cooldown to avoid spamming.
"""
import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    """Send messages to Telegram via Bot API with per-alert cooldown."""

    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self.cooldown_minutes = int(os.getenv("ALERT_COOLDOWN_MINUTES", "240"))
        self._last_sent: dict[str, float] = {}  # alert_type -> epoch timestamp

        if not self.token or not self.chat_id:
            logger.warning(
                "Telegram not configured (TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing)"
            )

    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, message: str) -> bool:
        """Send a message to Telegram. Returns True on success."""
        if not self.is_configured:
            logger.warning("Telegram not configured, skipping send")
            return False

        try:
            url = _TELEGRAM_API.format(token=self.token)
            with httpx.Client(timeout=15) as client:
                resp = client.post(url, json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                })
            if resp.status_code == 200:
                return True
            logger.warning("Telegram API returned %d: %s", resp.status_code, resp.text[:200])
            return False
        except Exception as e:
            logger.warning("Telegram send failed: %s", e)
            return False

    def send_alert(self, alert_type: str, message: str) -> bool:
        """Send an alert with cooldown. Returns True if sent."""
        now = time.time()
        last = self._last_sent.get(alert_type, 0)
        cooldown_secs = self.cooldown_minutes * 60

        if now - last < cooldown_secs:
            remaining = int((cooldown_secs - (now - last)) / 60)
            logger.info(
                "Alert '%s' on cooldown (%dm remaining), skipping",
                alert_type, remaining,
            )
            return False

        sent = self.send(message)
        if sent:
            self._last_sent[alert_type] = now
        return sent


# Module-level singleton
_notifier: TelegramNotifier | None = None


def get_notifier() -> TelegramNotifier:
    """Get or create the module-level TelegramNotifier singleton."""
    global _notifier
    if _notifier is None:
        _notifier = TelegramNotifier()
    return _notifier
