from datetime import datetime
from zoneinfo import ZoneInfo

from app.routers.events import _resolve_event_times

_TZ = ZoneInfo("America/Denver")


def test_resolve_event_times_defaults_end_to_one_hour():
    start, end, err = _resolve_event_times("2026-09-16T09:00", "")
    assert err is None
    assert start == datetime(2026, 9, 16, 9, 0, tzinfo=_TZ)
    assert end == datetime(2026, 9, 16, 10, 0, tzinfo=_TZ)


def test_resolve_event_times_keeps_explicit_end():
    start, end, err = _resolve_event_times("2026-09-16T09:00", "2026-09-16T11:30")
    assert err is None
    assert start.hour == 9
    assert end.hour == 11
    assert end.minute == 30


def test_resolve_event_times_fixes_end_before_start():
    start, end, err = _resolve_event_times("2026-09-16T09:00", "2026-09-16T08:00")
    assert err is None
    assert end == start.replace(hour=10)
