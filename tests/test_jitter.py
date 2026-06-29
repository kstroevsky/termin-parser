import random
from types import SimpleNamespace

from clinic_monitor.monitor import next_sleep_seconds


def cfg(interval=5, jitter=120):
    return SimpleNamespace(interval_minutes=interval, jitter_seconds=jitter)


def test_jitter_stays_within_bounds():
    rng = random.Random(1)
    c = cfg(interval=5, jitter=120)  # 300s ± 120s
    samples = [next_sleep_seconds(c, rng) for _ in range(2000)]
    assert min(samples) >= 180.0
    assert max(samples) <= 420.0
    # And it actually varies (not a constant).
    assert len(set(round(s) for s in samples)) > 100


def test_never_hammers_even_with_large_jitter():
    rng = random.Random(2)
    c = cfg(interval=1, jitter=120)  # 60s ± 120s could go negative → clamp
    assert all(next_sleep_seconds(c, rng) >= 60.0 for _ in range(2000))
