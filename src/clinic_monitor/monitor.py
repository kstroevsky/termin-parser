"""Orchestration: check -> diff against memory -> notify -> persist."""

from __future__ import annotations

import logging
from datetime import datetime, time

from .checker import AVAILABLE, ERROR, NONE, UNKNOWN, CheckResult, Slot, check
from .config import Config
from .state import load_seen, save_seen
from .telegram import send_message

log = logging.getLogger("clinic_monitor")

# Synthetic slots used to dedup the non-empty "go check" alerts so each pings
# at most once per episode (cleared when the page reads cleanly again).
_UNKNOWN = Slot(id="alert-unknown", label="schedule unrecognised")
_ERROR = Slot(id="alert-error", label="page unreadable")


def _safe_check(cfg: Config) -> CheckResult:
    """Run a check, retrying once to absorb transient browser/network blips.

    A persistent failure returns ERROR (which alerts) rather than staying
    silent — a broken scraper must not hide a real opening.
    """
    try:
        return check(cfg)
    except Exception:
        log.warning("check failed, retrying once", exc_info=True)
    try:
        return check(cfg)
    except Exception:
        log.exception("check failed twice")
        return CheckResult(ERROR)


def _parse_hhmm(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


def within_window(now: datetime, cfg: Config) -> bool:
    """True if `now` (in cfg.tz) is inside the daily check window."""
    local = now.astimezone(cfg.tz).time()
    start = _parse_hhmm(cfg.window_start)
    end = _parse_hhmm(cfg.window_end)
    if start <= end:
        return start <= local <= end
    # Window crosses midnight (e.g. 21:00–08:00).
    return local >= start or local <= end


def _format_available(new_slots: list[Slot], cfg: Config) -> str:
    lines = [f"🟢 <b>{len(new_slots)} appointment slot(s) just opened</b>", ""]
    for slot in new_slots[:25]:
        lines.append(f"• {slot.label}")
    if len(new_slots) > 25:
        lines.append(f"… and {len(new_slots) - 25} more")
    lines.append("")
    lines.append(f'<a href="{cfg.clinic_url}">Open booking page</a>')
    return "\n".join(lines)


def _format_unknown(cfg: Config) -> str:
    return (
        "🟡 <b>Possible appointment availability — check now</b>\n\n"
        "The page did <i>not</i> show the usual \"no free slots\" notice, but "
        "I also couldn't read a list of times. There may be an opening in a "
        "layout I haven't seen — better to look than miss it.\n\n"
        f'<a href="{cfg.clinic_url}">Open booking page</a>'
    )


def _format_error(cfg: Config) -> str:
    return (
        "🛠️ <b>Couldn't load the booking page — check manually</b>\n\n"
        "The monitor failed to read the page twice in a row (it may have "
        "changed or be temporarily down). Please check it yourself so a slot "
        "isn't missed while I'm blind.\n\n"
        f'<a href="{cfg.clinic_url}">Open booking page</a>'
    )


def run_once(cfg: Config, *, notify: bool = True) -> list[Slot]:
    """Run a single check. Returns the newly-notified items (possibly empty)."""
    result = _safe_check(cfg)

    if result.status == AVAILABLE:
        items = list(result.slots)
    elif result.status == UNKNOWN:
        items = [_UNKNOWN]
    elif result.status == ERROR:
        items = [_ERROR]
    else:  # NONE
        items = []

    current_ids = {s.id for s in items}
    seen = load_seen(cfg.state_path)
    new = [s for s in items if s.id not in seen]

    if new and notify:
        if result.status == AVAILABLE:
            text = _format_available(new, cfg)
        elif result.status == UNKNOWN:
            text = _format_unknown(cfg)
        else:  # ERROR
            text = _format_error(cfg)
        send_message(cfg.telegram_token, cfg.telegram_chat_id, text)

    log.info(
        "status=%s items=%d new=%d%s",
        result.status,
        len(items),
        len(new),
        f" artifact={result.artifact_dir}" if result.artifact_dir else "",
    )

    # Remember exactly what's present now: unchanged states won't re-notify,
    # and anything that vanishes is forgotten so it can alert again on return.
    save_seen(cfg.state_path, current_ids)
    return new
