from __future__ import annotations

from datetime import datetime, timedelta, timezone

from utils.time_window import resolve_utc_window, utc_to_local_str

UTC = timezone.utc
TPE = timezone(timedelta(hours=8))  # 固定 +08:00，測試不依賴執行環境時區


def test_relative_window_is_now_minus_minutes_in_utc():
    now = datetime(2026, 6, 22, 12, 0, 0, tzinfo=UTC)
    start, end = resolve_utc_window(minutes=10, now_utc=now, tz=TPE)
    assert start == "2026-06-22 11:50:00"
    assert end == "2026-06-22 12:00:00"


def test_absolute_window_converts_local_to_utc():
    now = datetime(2026, 6, 22, 13, 0, 0, tzinfo=UTC)
    start, end = resolve_utc_window(
        from_ts="2026-06-22T20:00", to_ts="2026-06-22T20:30", now_utc=now, tz=TPE
    )
    # 本地 +8 的 20:00 / 20:30 → UTC 12:00 / 12:30
    assert start == "2026-06-22 12:00:00"
    assert end == "2026-06-22 12:30:00"


def test_absolute_empty_to_uses_now():
    now = datetime(2026, 6, 22, 13, 0, 0, tzinfo=UTC)
    start, end = resolve_utc_window(from_ts="2026-06-22T20:00", to_ts=None, now_utc=now, tz=TPE)
    assert start == "2026-06-22 12:00:00"
    assert end == "2026-06-22 13:00:00"  # = now


def test_window_swaps_when_reversed():
    now = datetime(2026, 6, 22, 13, 0, 0, tzinfo=UTC)
    start, end = resolve_utc_window(
        from_ts="2026-06-22T21:00", to_ts="2026-06-22T20:00", now_utc=now, tz=TPE
    )
    assert start <= end  # 自動交換


def test_utc_to_local_str_shifts_to_local():
    assert utc_to_local_str("2026-06-22 12:00:00", tz=TPE) == "2026-06-22 20:00:00"
    assert utc_to_local_str("", tz=TPE) == ""
