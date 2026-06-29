"""Drive the Terminland booking wizard and classify slot availability.

The clinic uses Terminland (an ASP.NET WebForms wizard that *requires*
JavaScript), so we drive it with a headless browser. The flow is:

    1. "Fragen"        → pick the service radio, click *Weiter*
    2. "Terminauswahl" → either a schedule of free slots, OR a hint card
                         (#fsHinweis) reading "…keine freien Termine…" when
                         nothing is open.

Because we have only ever observed the *empty* state, detection is a
deliberately conservative 3-state machine:

    NONE       the definitive "keine freien Termine" hint is present.
    AVAILABLE  the hint is absent AND we found concrete time slots (HH:MM).
    UNKNOWN    the hint is absent but we could not recognise a schedule
               (error page, layout change, or a slot format we haven't seen).

NONE stays silent. AVAILABLE sends the real alert. UNKNOWN sends an honest
"couldn't read the page — check manually" alert rather than a false positive
or silence. Whenever the state is not NONE we also save the page HTML + a
screenshot, so the very first real opening is captured as ground truth to
verify and tune against.

This is the one site-specific file. If the clinic ever changes booking
systems, this is what you rewrite — scheduling, dedup and Telegram are
all site-agnostic.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import Config

log = logging.getLogger("clinic_monitor")

NONE = "none"
AVAILABLE = "available"
UNKNOWN = "unknown"
ERROR = "error"

TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):[0-5]\d\b")

# Element layers to try, most specific first. The first layer that yields
# time-bearing elements wins, which avoids double-counting nested nodes.
_SLOT_LAYERS = (
    "#tl_form a",
    "#tl_form button",
    "#tl_form [data-date]",
    "#tl_form [data-time]",
    "#tl_form td",
    "#tl_form li",
)


@dataclass(frozen=True)
class Slot:
    id: str
    label: str


@dataclass(frozen=True)
class CheckResult:
    status: str  # NONE | AVAILABLE | UNKNOWN
    slots: tuple[Slot, ...] = ()
    artifact_dir: str | None = None


def _slot_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _extract_slots(page) -> list[Slot]:
    """Best-effort extraction of concrete time slots from the schedule step."""
    for selector in _SLOT_LAYERS:
        found: dict[str, Slot] = {}
        for el in page.query_selector_all(selector):
            text = _normalize(el.inner_text() or "")
            if not text or not TIME_RE.search(text):
                continue
            found.setdefault(text, Slot(id=_slot_id(text), label=text))
        if found:
            return list(found.values())
    return []


def classify(page, cfg: Config) -> tuple[str, list[Slot]]:
    """Pure decision logic (no browser side-effects) — unit-testable.

    Biased toward alerting: a false positive (you look and there's nothing)
    is acceptable; a false negative (a missed slot) is not. So the *only*
    silent outcome is a positively-confirmed-empty page with no parseable
    times. Parsed times always win — even if an empty-notice also appears,
    we trust the times and alert.
    """
    slots = _extract_slots(page)
    if slots:
        return AVAILABLE, slots
    # No times found. Stay silent only if the page positively says "empty".
    body = (page.inner_text("body") or "").lower()
    confirmed_empty = cfg.no_slots_text.lower() in body or bool(
        page.query_selector("#fsHinweis")
    )
    if confirmed_empty:
        return NONE, []
    # Not confirmed empty and no times recognised → don't assume empty; alert.
    return UNKNOWN, []


def _capture(page, cfg: Config, status: str) -> str | None:
    """Save HTML + screenshot so a non-empty state can be verified later."""
    try:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = Path(cfg.capture_dir) / f"{stamp}-{status}"
        out.mkdir(parents=True, exist_ok=True)
        (out / "page.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(out / "page.png"), full_page=True)
        log.info("Saved capture to %s", out)
        return str(out)
    except Exception:  # capture is diagnostic, never fatal
        log.exception("Failed to save capture")
        return None


def check(cfg: Config) -> CheckResult:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=cfg.headless)
        try:
            page = browser.new_page(
                user_agent=cfg.user_agent,
                viewport={"width": 1280, "height": 1600},
            )
            page.set_default_timeout(cfg.nav_timeout_ms)
            page.goto(cfg.clinic_url, wait_until="domcontentloaded")

            # Step 1 — pick the service and advance (skipped if not shown).
            label = page.query_selector("label.tl-radio")
            if label:
                label.click()
                page.wait_for_timeout(150)
                next_btn = page.query_selector("#btnGo")
                if next_btn:
                    next_btn.click()
                    page.wait_for_load_state("domcontentloaded")

            # Let the Terminauswahl step settle (it loads the calendar via JS).
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1200)

            status, slots = classify(page, cfg)
            artifact = _capture(page, cfg, status) if status != NONE else None
            return CheckResult(status=status, slots=tuple(slots), artifact_dir=artifact)
        finally:
            browser.close()
