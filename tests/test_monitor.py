"""Behavioural tests for the check→diff→notify→persist cycle (no browser)."""

from types import SimpleNamespace

import clinic_monitor.monitor as monitor
from clinic_monitor.checker import AVAILABLE, NONE, QUEUE, UNKNOWN, CheckResult, Slot


def make_cfg(tmp_path, label=""):
    return SimpleNamespace(
        state_path=tmp_path / "state.json",
        telegram_token="t",
        telegram_chat_id="c",
        clinic_url="https://example.test/book",
        target_label=label,
    )


def run_with(monkeypatch, cfg, result):
    """Run one cycle with `check` stubbed to return `result`; capture sends."""
    sent: list[str] = []
    monkeypatch.setattr(monitor, "check", lambda _cfg: result)
    monkeypatch.setattr(monitor, "send_message", lambda _t, _c, text: sent.append(text))
    new = monitor.run_once(cfg)
    return new, sent


def slot(label):
    return Slot(id=label, label=label)


def test_available_notifies_once_then_dedups(monkeypatch, tmp_path):
    cfg = make_cfg(tmp_path)
    res = CheckResult(AVAILABLE, (slot("09:00"), slot("09:30")))

    new, sent = run_with(monkeypatch, cfg, res)
    assert len(new) == 2 and len(sent) == 1
    assert "just opened" in sent[0]

    # Same slots still open next cycle → no second alert.
    new, sent = run_with(monkeypatch, cfg, res)
    assert new == [] and sent == []


def test_label_appears_in_alert(monkeypatch, tmp_path):
    cfg = make_cfg(tmp_path, label="Autism (GKV)")
    _new, sent = run_with(monkeypatch, cfg, CheckResult(AVAILABLE, (slot("10:00"),)))
    assert len(sent) == 1 and "Autism (GKV) —" in sent[0]


def test_only_new_slot_alerts(monkeypatch, tmp_path):
    cfg = make_cfg(tmp_path)
    run_with(monkeypatch, cfg, CheckResult(AVAILABLE, (slot("09:00"),)))
    new, sent = run_with(
        monkeypatch, cfg, CheckResult(AVAILABLE, (slot("09:00"), slot("10:00")))
    )
    assert [s.label for s in new] == ["10:00"] and len(sent) == 1


def test_reappearing_slot_alerts_again(monkeypatch, tmp_path):
    cfg = make_cfg(tmp_path)
    run_with(monkeypatch, cfg, CheckResult(AVAILABLE, (slot("09:00"),)))  # alert
    run_with(monkeypatch, cfg, CheckResult(NONE))                         # gone, silent
    new, sent = run_with(monkeypatch, cfg, CheckResult(AVAILABLE, (slot("09:00"),)))
    assert [s.label for s in new] == ["09:00"] and len(sent) == 1  # alerts again


def test_none_is_silent(monkeypatch, tmp_path):
    cfg = make_cfg(tmp_path)
    new, sent = run_with(monkeypatch, cfg, CheckResult(NONE))
    assert new == [] and sent == []


def test_unknown_pings_once_to_check(monkeypatch, tmp_path):
    cfg = make_cfg(tmp_path)
    new, sent = run_with(monkeypatch, cfg, CheckResult(UNKNOWN))
    assert len(sent) == 1 and "Possible appointment availability" in sent[0]

    # Still unrecognised next cycle → no repeat ping.
    new, sent = run_with(monkeypatch, cfg, CheckResult(UNKNOWN))
    assert sent == []


def test_queue_pings_once(monkeypatch, tmp_path):
    cfg = make_cfg(tmp_path)
    new, sent = run_with(monkeypatch, cfg, CheckResult(QUEUE))
    assert len(sent) == 1 and "queue is active" in sent[0].lower()

    new, sent = run_with(monkeypatch, cfg, CheckResult(QUEUE))  # still queued → quiet
    assert sent == []


def test_scrape_failure_alerts_once(monkeypatch, tmp_path):
    cfg = make_cfg(tmp_path)
    sent: list[str] = []

    def boom(_cfg):
        raise RuntimeError("navigation timeout")

    monkeypatch.setattr(monitor, "check", boom)  # _safe_check retries, then ERROR
    monkeypatch.setattr(monitor, "send_message", lambda _t, _c, text: sent.append(text))

    monitor.run_once(cfg)
    assert len(sent) == 1 and "Couldn't load" in sent[0]

    sent.clear()
    monitor.run_once(cfg)  # still failing → deduped, silent
    assert sent == []
