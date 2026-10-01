"""Alert notifications behind a small interface (stretch goal).

Notifications are sent *after* the database transaction commits. Sending inside the
transaction would risk notifying about an alert that is then rolled back. The trade-off
is that a crash between commit and send loses a notification; the durable fix is a
transactional outbox table, noted in the README as a known gap.
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.request
from typing import Any, Protocol

log = logging.getLogger("inventory.alerts")


class AlertNotifier(Protocol):
    def alert_opened(self, alert: dict[str, Any]) -> None: ...


class LogNotifier:
    def alert_opened(self, alert: dict[str, Any]) -> None:
        item = alert["item"]
        log.warning(
            "LOW STOCK alert #%s opened: %s (%s) at %s %s, threshold %s",
            alert["id"], item["sku"], item["name"], alert["triggered_stock"], item["unit"],
            alert["threshold_at_trigger"],
        )


class WebhookNotifier:
    """POSTs the alert JSON to a URL on a background thread so requests never wait on it."""

    def __init__(self, url: str):
        self.url = url

    def alert_opened(self, alert: dict[str, Any]) -> None:
        threading.Thread(target=self._send, args=(alert,), daemon=True).start()

    def _send(self, alert: dict[str, Any]) -> None:
        body = json.dumps({"event": "alert.opened", "alert": alert}).encode()
        req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=5).close()
        except Exception:  # noqa: BLE001 - a failed webhook must never break the app
            log.exception("Webhook notification failed for alert #%s", alert["id"])


def build_notifier(kind: str, webhook_url: str = "") -> AlertNotifier:
    if kind == "webhook" and webhook_url:
        return WebhookNotifier(webhook_url)
    return LogNotifier()
