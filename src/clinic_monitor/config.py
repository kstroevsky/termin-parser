"""Configuration loaded from environment / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Config:
    telegram_token: str
    telegram_chat_id: str
    clinic_url: str
    no_slots_text: str
    queue_text: str
    queue_max_wait_s: int
    window_start: str
    window_end: str
    interval_minutes: int
    jitter_seconds: int
    tz: ZoneInfo
    state_path: Path
    capture_dir: Path
    headless: bool
    nav_timeout_ms: int
    user_agent: str
    browser_locale: str
    browser_timezone: str


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(
            f"Missing required environment variable: {name}\n"
            f"Copy .env.example to .env and fill it in, or set it in the environment."
        )
    return value


def _resolve_tz() -> ZoneInfo:
    name = os.getenv("MONITOR_TZ", "").strip()
    if name:
        return ZoneInfo(name)
    local = datetime.now().astimezone().tzinfo
    return ZoneInfo(str(local)) if isinstance(local, ZoneInfo) else ZoneInfo("UTC")


def load_config() -> Config:
    return Config(
        telegram_token=_require("TELEGRAM_TOKEN"),
        telegram_chat_id=_require("TELEGRAM_CHAT_ID"),
        clinic_url=_require("CLINIC_URL"),
        # When this German text is on the schedule step, nothing is bookable.
        no_slots_text=os.getenv("NO_SLOTS_TEXT", "keine freien Termine").strip(),
        # The virtual waiting room headline (distinct from the no-slots hint,
        # which says "hohen Buchungsaufkommens"). When present, wait it out.
        queue_text=os.getenv("QUEUE_TEXT", "erhöhtes Buchungsaufkommen").strip(),
        queue_max_wait_s=int(os.getenv("QUEUE_MAX_WAIT_S", "180")),
        window_start=os.getenv("WINDOW_START", "08:00").strip(),
        window_end=os.getenv("WINDOW_END", "21:00").strip(),
        # Base cadence and ± random jitter so checks don't land on a fixed clock.
        interval_minutes=int(os.getenv("INTERVAL_MINUTES", "5")),
        jitter_seconds=int(os.getenv("JITTER_SECONDS", "120")),
        tz=_resolve_tz(),
        state_path=Path(os.getenv("STATE_PATH", "state.json")),
        capture_dir=Path(os.getenv("CAPTURE_DIR", "captures")),
        headless=os.getenv("HEADLESS", "true").lower() not in ("0", "false", "no"),
        nav_timeout_ms=int(os.getenv("NAV_TIMEOUT_MS", "30000")),
        # Blank user-agent → pick a realistic one at random per run (see checker).
        user_agent=os.getenv("USER_AGENT", "").strip(),
        browser_locale=os.getenv("BROWSER_LOCALE", "de-DE").strip(),
        browser_timezone=os.getenv("BROWSER_TIMEZONE", "Europe/Berlin").strip(),
    )
