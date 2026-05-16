"""Ontario electricity TOU/ULO schedule and holiday logic.

Pure functions only: no `hass`, no I/O. Callers pass `datetime` values that
are already localized to ``America/Toronto`` (use ``dt_util.now()`` in HA).

Sources verified 2026-05-15:
- TOU/ULO hours: https://www.oeb.ca/consumer-information-and-protection/electricity-rates
- Holidays + observance rule:
  https://www.oeb.ca/consumer-information-and-protection/electricity-rates/holiday-schedule-time-use-and-ultra-low
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache

from .parser import RateRow


class TouPeriod(StrEnum):
    """Time-of-Use period."""

    ON = "on"
    MID = "mid"
    OFF = "off"


class UloPeriod(StrEnum):
    """Ultra-Low Overnight period."""

    OVERNIGHT = "overnight"
    WEEKEND_OFF = "weekend_off"
    MID = "mid"
    ON = "on"


def _easter_sunday(year: int) -> date:
    """Return Easter Sunday for the given year (Anonymous Gregorian algorithm)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = ((h + l_ - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Return the date of the nth weekday in a given month (weekday: Mon=0)."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + (n - 1) * 7)


def _last_monday_on_or_before(year: int, month: int, day: int) -> date:
    """Return the Monday on or before the given month/day (used for Victoria Day)."""
    d = date(year, month, day)
    return d - timedelta(days=d.weekday())


def _raw_holidays(year: int) -> list[date]:
    """Return the 10 IESO-observed holidays in calendar order, before weekend shifts."""
    return [
        date(year, 1, 1),
        _nth_weekday(year, 2, 0, 3),
        _easter_sunday(year) - timedelta(days=2),
        _last_monday_on_or_before(year, 5, 24),
        date(year, 7, 1),
        _nth_weekday(year, 8, 0, 1),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 10, 0, 2),
        date(year, 12, 25),
        date(year, 12, 26),
    ]


@lru_cache(maxsize=32)
def _observed_holidays(year: int) -> frozenset[date]:
    """Return the set of dates on which IESO holiday pricing is in effect.

    If a holiday falls on a weekend, the off-peak rate moves to the next
    weekday that is not also a holiday (per OEB's holiday-schedule page).
    """
    observed: set[date] = set()
    for raw in _raw_holidays(year):
        if raw.weekday() < 5:
            observed.add(raw)
            continue
        candidate = raw
        while candidate.weekday() >= 5 or candidate in observed:
            candidate += timedelta(days=1)
        observed.add(candidate)
    return frozenset(observed)


def is_ontario_tou_holiday(d: date) -> bool:
    """Return True if the given date is treated as an IESO TOU/ULO holiday."""
    return d in _observed_holidays(d.year)


def _is_off_day(dt: datetime) -> bool:
    """A weekend or observed holiday — TOU off-peak / ULO weekend-off all day."""
    return dt.weekday() >= 5 or is_ontario_tou_holiday(dt.date())


def _is_summer(d: date) -> bool:
    """Summer TOU season: May 1 to Oct 31 (inclusive)."""
    return 5 <= d.month <= 10


def tou_period(dt: datetime) -> TouPeriod:
    """Return the current TOU period for an ``America/Toronto`` datetime."""
    if _is_off_day(dt):
        return TouPeriod.OFF
    hour = dt.hour
    if hour < 7 or hour >= 19:
        return TouPeriod.OFF
    if _is_summer(dt.date()):
        if 11 <= hour < 17:
            return TouPeriod.ON
        return TouPeriod.MID
    if 11 <= hour < 17:
        return TouPeriod.MID
    return TouPeriod.ON


def ulo_period(dt: datetime) -> UloPeriod:
    """Return the current ULO period for an ``America/Toronto`` datetime."""
    hour = dt.hour
    if hour >= 23 or hour < 7:
        return UloPeriod.OVERNIGHT
    if _is_off_day(dt):
        return UloPeriod.WEEKEND_OFF
    if 16 <= hour < 21:
        return UloPeriod.ON
    return UloPeriod.MID


def tou_rate_for(row: RateRow, dt: datetime) -> Decimal:
    """Return the active TOU rate for ``dt`` from a RateRow."""
    period = tou_period(dt)
    if period is TouPeriod.ON:
        return row.tou_on
    if period is TouPeriod.MID:
        return row.tou_mid
    return row.tou_off


def ulo_rate_for(row: RateRow, dt: datetime) -> Decimal:
    """Return the active ULO rate for ``dt`` from a RateRow."""
    period = ulo_period(dt)
    if period is UloPeriod.OVERNIGHT:
        return row.ulo_overnight
    if period is UloPeriod.WEEKEND_OFF:
        return row.ulo_weekend_off
    if period is UloPeriod.ON:
        return row.ulo_on
    return row.ulo_mid
