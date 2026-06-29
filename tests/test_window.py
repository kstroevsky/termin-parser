from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from clinic_monitor.monitor import within_window

TZ = ZoneInfo("Europe/Berlin")


def cfg(start="08:00", end="21:00"):
    return SimpleNamespace(window_start=start, window_end=end, tz=TZ)


def at(h, m=0):
    return datetime(2026, 6, 29, h, m, tzinfo=TZ)


def test_inside_window():
    assert within_window(at(8, 0), cfg())
    assert within_window(at(14, 30), cfg())
    assert within_window(at(21, 0), cfg())


def test_outside_window():
    assert not within_window(at(7, 59), cfg())
    assert not within_window(at(21, 1), cfg())
    assert not within_window(at(3, 0), cfg())


def test_window_crossing_midnight():
    c = cfg(start="21:00", end="08:00")
    assert within_window(at(23, 0), c)
    assert within_window(at(2, 0), c)
    assert not within_window(at(12, 0), c)
