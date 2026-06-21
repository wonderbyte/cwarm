"""Translate 5-field crontab expressions into APScheduler CronTriggers.

APScheduler's own `CronTrigger.from_crontab()` does **not** convert the
day-of-week numbering: crontab uses 0/7=Sunday..6=Saturday, while APScheduler
uses 0=Monday..6=Sunday. Passing crontab numbers straight through shifts every
weekday by one (so `1-5`, meant as Mon-Fri, schedules as Tue-Sat). We translate
the day-of-week field to weekday names so a crontab expression means what a user
typing it into `crontab` would expect.
"""

from __future__ import annotations

from datetime import datetime

from apscheduler.triggers.cron import CronTrigger

# crontab day-of-week: index 0..6 = Sun..Sat (and 7 also = Sun).
_DOW_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")


def to_trigger(expression: str, timezone: str) -> CronTrigger:
    minute, hour, day, month, dow = expression.split()
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=_translate_dow(dow),
        timezone=timezone,
    )


def next_fire(expression: str, timezone: str, now: datetime) -> datetime | None:
    return to_trigger(expression, timezone).get_next_fire_time(None, now)


def _translate_dow(field: str) -> str:
    if field == "*":
        return "*"
    return ",".join(_translate_part(part) for part in field.split(","))


def _translate_part(part: str) -> str:
    step = ""
    if "/" in part:
        part, _, step = part.partition("/")
        step = "/" + step
    if part == "*":
        return "*" + step
    if "-" in part:
        lo, hi = part.split("-", 1)
        return f"{_name(lo)}-{_name(hi)}{step}"
    return _name(part) + step


def _name(token: str) -> str:
    """crontab day-of-week token -> APScheduler weekday name (numbers only)."""
    try:
        n = int(token)
    except ValueError:
        return token.lower()  # already a name like "mon"
    if not 0 <= n <= 7:
        raise ValueError(f"day-of-week out of range (0-7): {token!r}")
    return _DOW_NAMES[0 if n == 7 else n]
