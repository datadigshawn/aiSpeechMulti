"""Time-window helpers for the realtime transcript search.

DB ``transcripts.created_at`` is written by SQLite ``CURRENT_TIMESTAMP`` and is
therefore **UTC**. The search UI works in the server's local timezone, so we
convert both directions here. Pure functions (now/tz injectable) for testing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

_SQL_FMT = "%Y-%m-%d %H:%M:%S"
_PARSE_FMTS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
)


def local_tzinfo():
    """Return the server's local tzinfo."""
    return datetime.now().astimezone().tzinfo


def _parse_naive(value: str) -> datetime | None:
    """Parse a naive datetime string in any of the accepted formats."""
    if not value:
        return None
    for fmt in _PARSE_FMTS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def resolve_utc_window(
    minutes: int | None = 10,
    from_ts: str | None = None,
    to_ts: str | None = None,
    *,
    now_utc: datetime | None = None,
    tz=None,
) -> tuple[str, str]:
    """Compute (start_utc, end_utc) SQL strings for the ``created_at`` BETWEEN.

    - ``from_ts``/``to_ts`` are **naive local** datetime strings. If ``from_ts``
      is given it overrides ``minutes``; ``to_ts`` empty → end = now.
    - Otherwise use the relative window ``[now - minutes, now]``.
    Both returned strings are UTC, formatted ``YYYY-MM-DD HH:MM:SS``.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    tz = tz or local_tzinfo()

    def _local_to_utc(naive_local: datetime) -> datetime:
        return naive_local.replace(tzinfo=tz).astimezone(timezone.utc)

    from_dt = _parse_naive(from_ts) if from_ts else None
    to_dt = _parse_naive(to_ts) if to_ts else None

    if from_dt is not None:
        start = _local_to_utc(from_dt)
        end = _local_to_utc(to_dt) if to_dt is not None else now_utc
    else:
        span = minutes if (minutes and minutes > 0) else 10
        end = now_utc
        start = now_utc - timedelta(minutes=span)

    if end < start:
        start, end = end, start
    return start.strftime(_SQL_FMT), end.strftime(_SQL_FMT)


def utc_to_local_str(created_at_utc: str | None, *, fmt: str = _SQL_FMT, tz=None) -> str:
    """Convert a UTC ``created_at`` string to a local-time string (display)."""
    dt = _parse_naive(created_at_utc) if created_at_utc else None
    if dt is None:
        return ""
    tz = tz or local_tzinfo()
    return dt.replace(tzinfo=timezone.utc).astimezone(tz).replace(tzinfo=None).strftime(fmt)
