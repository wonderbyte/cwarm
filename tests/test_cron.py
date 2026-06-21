"""Crontab -> CronTrigger translation, esp. the day-of-week numbering fix.

crontab: 0/7=Sun..6=Sat;  APScheduler: 0=Mon..6=Sun. Without translation,
`1-5` (Mon-Fri) would schedule as Tue-Sat. These tests pin the mapping.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from cwarm.cron import next_fire, to_trigger

TZ = "Asia/Kolkata"
SUNDAY = datetime(2026, 6, 21, 10, 30, tzinfo=ZoneInfo(TZ))  # a known Sunday


def _next(cron):
    return next_fire(cron, TZ, SUNDAY)


def test_weekday_range_is_monday_to_friday():
    # From a Sunday, the next "0 5 * * 1-5" must be Monday, not Tuesday.
    nxt = _next("0 5 * * 1-5")
    assert nxt.strftime("%a %Y-%m-%d") == "Mon 2026-06-22"


def test_single_weekday_numbers():
    assert _next("0 5 * * 1").strftime("%a") == "Mon"  # 1 = Monday
    assert _next("0 5 * * 5").strftime("%a") == "Fri"  # 5 = Friday
    assert _next("0 5 * * 6").strftime("%a") == "Sat"  # 6 = Saturday


def test_sunday_is_zero_and_seven():
    # Sunday now is 10:30; next 05:00 Sunday is next week, for both 0 and 7.
    for sunday in ("0 5 * * 0", "0 5 * * 7"):
        assert _next(sunday).strftime("%a %Y-%m-%d") == "Sun 2026-06-28"


def test_weekday_list():
    # Mon & Wed & Fri -> next from Sunday is Monday.
    assert _next("0 5 * * 1,3,5").strftime("%a") == "Mon"


def test_daily_wildcard_unaffected():
    assert _next("0 5 * * *").strftime("%a %Y-%m-%d") == "Mon 2026-06-22"


def test_invalid_field_raises():
    with pytest.raises((ValueError, TypeError)):
        to_trigger("0 5 * * 9", TZ)  # 9 is not a valid weekday
