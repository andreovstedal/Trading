"""Norwegian formatting of numbers, percentages and dates for everything the user reads.

Thousands are separated by a non-breaking space, decimals use a comma, and the
percent sign follows a non-breaking space: 1 234 567, 17,70 and 5,3 %.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

NBSP = " "
OSLO = ZoneInfo("Europe/Oslo")
MONTHS = ("jan.", "feb.", "mars", "apr.", "mai", "juni", "juli", "aug.", "sep.", "okt.", "nov.", "des.")


def number(value: float, digits: int = 0) -> str:
    value = round(value, digits) + 0.0  # no "-0" when a small negative number rounds to zero
    text = f"{value:,.{digits}f}"
    return text.replace(",", NBSP).replace(".", ",")


def percent(value: float, digits: int = 1, signed: bool = False) -> str:
    """``value`` is a fraction: 0.053 -> "5,3 %"."""
    text = number(value * 100, digits)
    if signed and value > 0:
        text = "+" + text
    return f"{text}{NBSP}%"


def points(value: float, digits: int = 1) -> str:
    """A number that is already in percent: 2.2 -> "2,2 %"."""
    return f"{number(value, digits)}{NBSP}%"


def nok(value: float, digits: int = 0) -> str:
    return f"{number(value, digits)}{NBSP}NOK"


def date_time(value: datetime) -> str:
    local = _local(value)
    return f"{day(local)}, {local:%H:%M}"


def clock(value: datetime) -> str:
    return f"{_local(value):%H:%M}"


def day(value: date) -> str:
    """A calendar date, "30. sep. 2026"; a datetime is first converted to Oslo time."""
    if isinstance(value, datetime):
        value = _local(value)
    return f"{value.day}. {MONTHS[value.month - 1]} {value.year}"


def _local(value: datetime) -> datetime:
    """Naive datetimes are UTC, as stored."""
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).astimezone(OSLO)


def ago(value: datetime, now: datetime) -> str:
    value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    seconds = (now - value).total_seconds()
    for singular, plural, size in (("dag", "dager", 86400), ("time", "timer", 3600), ("minutt", "minutter", 60)):
        if seconds >= size:
            n = int(seconds // size)
            return f"for {n} {singular if n == 1 else plural} siden"
    return "akkurat nå"
