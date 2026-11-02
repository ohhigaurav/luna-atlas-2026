from __future__ import annotations

from datetime import UTC, datetime

from tools import check_mission_events as tool


def _w(start: str, end: str, st: bool = False, et: bool = False) -> dict:
    return {"start_utc": start, "end_utc": end, "start_truncated": st, "end_truncated": et}


def test_sunset_is_end_of_window_open_at_start_and_sunrise_is_next_start() -> None:
    site = {"sun_windows": [_w("2025-03-02T08:34:00Z", "2025-03-16T18:31:00Z", st=True),
                            _w("2025-03-31T10:00:00Z", "2025-04-01T00:00:00Z", et=True)]}
    sunset, sunrise = tool.sunset_and_next_sunrise(site)
    assert sunset == datetime(2025, 3, 16, 18, 31, tzinfo=UTC)
    assert sunrise == datetime(2025, 3, 31, 10, 0, tzinfo=UTC)


def test_no_sunset_when_sun_is_down_at_start_or_never_sets() -> None:
    assert tool.sunset_and_next_sunrise({"sun_windows": [_w("2025-03-05T00:00:00Z", "2025-03-06T00:00:00Z")]}) == \
        (None, datetime(2025, 3, 5, tzinfo=UTC))
    assert tool.sunset_and_next_sunrise({"sun_windows": [_w("a", "b", st=True, et=True)]})[0] is None


def test_angle_difference_wraps() -> None:
    assert tool.ang_diff(359.9, 0.1) == 0.2 or abs(tool.ang_diff(359.9, 0.1) - 0.2) < 1e-9
    assert abs(tool.ang_diff(10, 350) - 20) < 1e-9
