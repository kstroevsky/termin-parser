"""Command-line entrypoint.

  clinic-monitor check          one-shot check (for GitHub Actions / cron)
  clinic-monitor loop           run forever, checking on INTERVAL_MINUTES
  clinic-monitor test-telegram  send a test message to confirm Telegram works
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime

from .config import load_config
from .monitor import next_sleep_seconds, run_once, within_window
from .telegram import send_message

log = logging.getLogger("clinic_monitor")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _cmd_check(args: argparse.Namespace) -> int:
    cfg = load_config()
    now = datetime.now(tz=cfg.tz)
    if not args.ignore_window and not within_window(now, cfg):
        log.info("Outside window %s–%s (%s) — skipping.",
                 cfg.window_start, cfg.window_end, cfg.tz)
        return 0
    run_once(cfg, notify=not args.dry_run)
    return 0


def _cmd_loop(args: argparse.Namespace) -> int:
    cfg = load_config()
    log.info("Loop started: ~every %d min (±%ds jitter), window %s–%s (%s)",
             cfg.interval_minutes, cfg.jitter_seconds,
             cfg.window_start, cfg.window_end, cfg.tz)
    while True:
        now = datetime.now(tz=cfg.tz)
        if within_window(now, cfg):
            try:
                run_once(cfg)
            except Exception:  # never let one bad check kill the loop
                log.exception("Check failed; will retry next cycle.")
            sleep_for = next_sleep_seconds(cfg)
        else:
            # Outside the window, idle in coarse steps until it reopens.
            sleep_for = min(next_sleep_seconds(cfg), 5 * 60)
            log.info("Outside window — sleeping %d min.", int(sleep_for // 60))
        log.info("Next check in %d min %02ds", int(sleep_for // 60), int(sleep_for % 60))
        time.sleep(sleep_for)


def _cmd_test_telegram(args: argparse.Namespace) -> int:
    cfg = load_config()
    resp = send_message(
        cfg.telegram_token,
        cfg.telegram_chat_id,
        "✅ <b>Clinic monitor</b> connected. You'll get a message here when "
        "appointment slots open up.",
    )
    log.info("Telegram OK: message id %s", resp.get("result", {}).get("message_id"))
    return 0


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(prog="clinic-monitor")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="run a single check")
    p_check.add_argument("--ignore-window", action="store_true",
                         help="check even outside the daily window")
    p_check.add_argument("--dry-run", action="store_true",
                         help="check and log, but don't send Telegram")
    p_check.set_defaults(func=_cmd_check)

    p_loop = sub.add_parser("loop", help="run continuously")
    p_loop.set_defaults(func=_cmd_loop)

    p_test = sub.add_parser("test-telegram", help="send a test Telegram message")
    p_test.set_defaults(func=_cmd_test_telegram)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
