"""Unit tests for slot classification, using a fake Playwright page."""

from types import SimpleNamespace

from clinic_monitor.checker import AVAILABLE, NONE, QUEUE, UNKNOWN, classify


class FakeEl:
    def __init__(self, text=""):
        self._text = text

    def inner_text(self):
        return self._text


class FakePage:
    """Minimal stand-in for a Playwright page."""

    def __init__(self, body, *, hinweis=False, layers=None):
        self._body = body
        self._hinweis = hinweis
        self._layers = layers or {}

    def inner_text(self, _selector):
        return self._body

    def query_selector(self, selector):
        if selector == "#fsHinweis":
            return FakeEl() if self._hinweis else None
        return None

    def query_selector_all(self, selector):
        return [FakeEl(t) for t in self._layers.get(selector, [])]


CFG = SimpleNamespace(
    no_slots_text="keine freien Termine",
    queue_text="erhöhtes Buchungsaufkommen",
)


def test_none_via_text():
    page = FakePage("… stehen derzeit keine freien Termine zur Verfügung.")
    assert classify(page, CFG) == (NONE, [])


def test_none_via_hint_card():
    page = FakePage("anything", hinweis=True)
    assert classify(page, CFG) == (NONE, [])


def test_available_with_concrete_times():
    page = FakePage(
        "Terminauswahl 30.06.2026",
        layers={"#tl_form a": ["Mo 30.06. 09:00", "Mo 30.06. 09:30", "kein Treffer"]},
    )
    status, slots = classify(page, CFG)
    assert status == AVAILABLE
    assert sorted(s.label for s in slots) == ["Mo 30.06. 09:00", "Mo 30.06. 09:30"]
    assert len({s.id for s in slots}) == 2  # stable, distinct ids


def test_unknown_when_no_marker_and_no_times():
    # Not confirmed empty and no times -> alert (don't assume empty).
    page = FakePage("Terminauswahl with a calendar but no parseable times")
    assert classify(page, CFG) == (UNKNOWN, [])


def test_queue_detected_from_waiting_room_text():
    page = FakePage("Aktuell besteht ein erhöhtes Buchungsaufkommen. Die Wartezeit beträgt: 01")
    assert classify(page, CFG) == (QUEUE, [])


def test_no_slots_hint_is_not_mistaken_for_queue():
    # The empty hint mentions "hohen Buchungsaufkommens" — must NOT read as queue.
    page = FakePage(
        "Aufgrund des hohen Buchungsaufkommens … keine freien Termine zur Verfügung."
    )
    assert classify(page, CFG) == (NONE, [])


def test_times_win_even_if_empty_notice_present():
    # Bias: a parsed time beats a stray "no slots" notice -> never miss.
    page = FakePage(
        "… keine freien Termine … (stale banner elsewhere on page)",
        hinweis=True,
        layers={"#tl_form button": ["10:00", "10:30"]},
    )
    status, slots = classify(page, CFG)
    assert status == AVAILABLE
    assert {s.label for s in slots} == {"10:00", "10:30"}
