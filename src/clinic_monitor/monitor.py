"""Orchestration: check -> diff against memory -> notify -> persist."""

from __future__ import annotations

import logging
import random
from datetime import datetime, time

from .checker import AVAILABLE, ERROR, NONE, QUEUE, UNKNOWN, CheckResult, Slot, check
from .config import Config
from .state import load_seen, save_seen
from .telegram import send_message

log = logging.getLogger("clinic_monitor")

# Synthetic slots used to dedup the non-empty "go check" alerts so each pings
# at most once per episode (cleared when the page reads cleanly again).
_UNKNOWN = Slot(id="alert-unknown", label="schedule unrecognised")
_ERROR = Slot(id="alert-error", label="page unreadable")
_QUEUE = Slot(id="alert-queue", label="waiting room active")


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


def next_sleep_seconds(cfg: Config, rng: random.Random | None = None) -> float:
    """Base interval ± random jitter, so checks don't land on a fixed clock.

    Never returns less than 60s — jitter adds naturalness, it must not turn
    into hammering.
    """
    r = rng or random
    base = cfg.interval_minutes * 60
    offset = r.uniform(-cfg.jitter_seconds, cfg.jitter_seconds)
    return max(60.0, base + offset)


def within_window(now: datetime, cfg: Config) -> bool:
    """True if `now` (in cfg.tz) is inside the daily check window."""
    local = now.astimezone(cfg.tz).time()
    start = _parse_hhmm(cfg.window_start)
    end = _parse_hhmm(cfg.window_end)
    if start <= end:
        return start <= local <= end
    # Window crosses midnight (e.g. 21:00–08:00).
    return local >= start or local <= end


def _label(cfg: Config) -> str:
    """'ADHS (GKV) — ' prefix for alert titles, or '' when no label set."""
    return f"{cfg.target_label} — " if cfg.target_label else ""


def _format_available(new_slots: list[Slot], cfg: Config) -> str:
    lines = [f"🟢 <b>{_label(cfg)}{len(new_slots)} appointment slot(s) just opened</b>", ""]
    for slot in new_slots[:25]:
        lines.append(f"• {slot.label}")
    if len(new_slots) > 25:
        lines.append(f"… and {len(new_slots) - 25} more")
    lines.append("")
    lines.append(f'<a href="{cfg.clinic_url}">Open booking page</a>')
    return "\n".join(lines)


def _format_unknown(cfg: Config) -> str:
    return (
        f"🟡 <b>{_label(cfg)}Possible appointment availability — check now</b>\n\n"
        "The page did <i>not</i> show the usual \"no free slots\" notice, but "
        "I also couldn't read a list of times. There may be an opening in a "
        "layout I haven't seen — better to look than miss it.\n\n"
        f'<a href="{cfg.clinic_url}">Open booking page</a>'
    )


def _format_error(cfg: Config) -> str:
    return (
        f"🛠️ <b>{_label(cfg)}Couldn't load the booking page — check manually</b>\n\n"
        "The monitor failed to read the page twice in a row (it may have "
        "changed or be temporarily down). Please check it yourself so a slot "
        "isn't missed while I'm blind.\n\n"
        f'<a href="{cfg.clinic_url}">Open booking page</a>'
    )


def _format_queue(cfg: Config) -> str:
    return (
        f"⏳ <b>{_label(cfg)}Booking queue is active — check now</b>\n\n"
        "The clinic is showing its high-demand waiting room and it didn't "
        "clear in time. That usually means slots are being released right "
        "now — worth jumping in yourself.\n\n"
        f'<a href="{cfg.clinic_url}">Open booking page</a>'
    )


def _format_heartbeat(result, cfg: Config) -> str:
    label = cfg.target_label or "Monitor"
    when = datetime.now(cfg.tz).strftime("%a %d.%m %H:%M %Z")
    if result.status == AVAILABLE:
        body = f"🟢 and {len(result.slots)} slot(s) are open right now!"
    elif result.status == NONE:
        body = "no slots right now."
    else:
        body = f"but saw “{result.status}” this check."
    return (
        f"✅ <b>{label}</b> — monitor alive, {body}\n"
        f"<i>{when}</i>\n"
        f'<a href="{cfg.clinic_url}">Open booking page</a>'
    )


def run_heartbeat(cfg: Config, *, notify: bool = True) -> None:
    """Daily 'still alive' summary: do a real check and always report the
    result, so a silent monitor (vs simply no slots) becomes obvious."""
    result = _safe_check(cfg)
    log.info("heartbeat status=%s slots=%d", result.status, len(result.slots))
    if notify:
        send_message(cfg.telegram_token, cfg.telegram_chat_id,
                     _format_heartbeat(result, cfg))


def run_once(cfg: Config, *, notify: bool = True) -> list[Slot]:
    """Run a single check. Returns the newly-notified items (possibly empty)."""
    result = _safe_check(cfg)

    if result.status == AVAILABLE:
        items = list(result.slots)
    elif result.status == UNKNOWN:
        items = [_UNKNOWN]
    elif result.status == ERROR:
        items = [_ERROR]
    elif result.status == QUEUE:
        items = [_QUEUE]
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
        elif result.status == QUEUE:
            text = _format_queue(cfg)
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
