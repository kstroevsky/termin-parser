"""Regression test against a *real* Terminland "available" page.

The fixture in tests/fixtures/terminland_available.html is a frozen snapshot
of a live Terminland schedule that had open slots (same software version as
the clinic). It proves our detection works on real availability — the one
state we can't observe on the clinic's own page until slots open.

Needs a browser; auto-skips where Playwright/Chromium isn't available.
"""

import pathlib
from types import SimpleNamespace

import pytest

from clinic_monitor.checker import AVAILABLE, TIME_RE, classify

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "terminland_available.html"
CFG = SimpleNamespace(
    no_slots_text="keine freien Termine",
    queue_text="erhöhtes Buchungsaufkommen",
)


def test_real_available_markup_is_detected():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"playwright not importable: {exc}")

    html = FIXTURE.read_text(encoding="utf-8")
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"chromium unavailable: {exc}")
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="domcontentloaded")
            status, slots = classify(page, CFG)
        finally:
            browser.close()

    assert status == AVAILABLE
    assert slots, "expected at least one parsed time slot from real markup"
    assert all(TIME_RE.search(s.label) for s in slots)
