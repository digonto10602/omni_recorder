"""Call ids and records folder helpers."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path


def call_id_for(now: datetime) -> str:
    """Base call id: YYYY-MM-DD_HHMM."""
    return now.strftime("%Y-%m-%d_%H%M")


def new_call_id(records_dir: Path, now: datetime | None = None) -> str:
    """Return a call id that does not exist yet in records_dir.

    Collisions get _2, _3, ... appended (the first call keeps the plain id).
    """
    base = call_id_for(now or datetime.now())
    candidate = base
    n = 1
    while (records_dir / candidate).exists():
        n += 1
        candidate = f"{base}_{n}"
    return candidate


def call_dir(records_dir: Path, call_id: str) -> Path:
    return records_dir / call_id


def list_call_ids(records_dir: Path) -> list[str]:
    """Sub-folders of records_dir, sorted by name (names start with the date)."""
    if not records_dir.is_dir():
        return []
    return sorted(p.name for p in records_dir.iterdir() if p.is_dir())
