"""Tiny on-disk store of which slots we've already notified about.

Persisting this between runs is what stops the bot from spamming you every
15 minutes while the same slot stays open. A slot is re-announced only if it
disappears and later comes back.
"""

from __future__ import annotations

import json
from pathlib import Path


def load_seen(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data.get("seen", []))
    except (json.JSONDecodeError, OSError, ValueError):
        # Corrupt/unreadable state is non-fatal — start fresh.
        return set()


def save_seen(path: Path, seen: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps({"seen": sorted(seen)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)  # atomic on the same filesystem
