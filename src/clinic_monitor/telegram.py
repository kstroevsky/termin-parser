"""Telegram notifications via the Bot API."""

from __future__ import annotations

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

API = "https://api.telegram.org"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
def send_message(token: str, chat_id: str, text: str) -> dict:
    """Send an HTML-formatted message. Retries transient failures."""
    resp = httpx.post(
        f"{API}/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()
