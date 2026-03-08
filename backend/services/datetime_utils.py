"""Shared datetime parsing utilities."""
from datetime import datetime, timezone

_DT_FORMATS = [
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
]


def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in _DT_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def ensure_utc(dt: datetime | None) -> datetime | None:
    """Coerce a naive or aware datetime to an aware UTC datetime."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def utcnow_naive() -> datetime:
    """Return naive UTC for comparisons against SQLite DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
