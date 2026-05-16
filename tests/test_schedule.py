"""Tests for ``custom_components.ontario_energy.schedule``."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.ontario_energy.schedule import (
    TouPeriod,
    UloPeriod,
    is_ontario_tou_holiday,
    tou_period,
    ulo_period,
)

TZ = ZoneInfo("America/Toronto")


def _dt(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


# --- TOU SUMMER WEEKDAY ------------------------------------------------------

SUMMER_WEEKDAY = date(2026, 7, 8)  # Wednesday, July 8, 2026 — not a holiday


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (6, 59, TouPeriod.OFF),
        (7, 0, TouPeriod.MID),
        (10, 59, TouPeriod.MID),
        (11, 0, TouPeriod.ON),
        (16, 59, TouPeriod.ON),
        (17, 0, TouPeriod.MID),
        (18, 59, TouPeriod.MID),
        (19, 0, TouPeriod.OFF),
        (23, 30, TouPeriod.OFF),
        (0, 0, TouPeriod.OFF),
    ],
)
def test_tou_summer_weekday_boundaries(
    hour: int, minute: int, expected: TouPeriod
) -> None:
    dt = datetime(
        SUMMER_WEEKDAY.year,
        SUMMER_WEEKDAY.month,
        SUMMER_WEEKDAY.day,
        hour,
        minute,
        tzinfo=TZ,
    )
    assert tou_period(dt) is expected


# --- TOU WINTER WEEKDAY ------------------------------------------------------

WINTER_WEEKDAY = date(2026, 1, 7)  # Wednesday, January 7, 2026 — not a holiday


@pytest.mark.parametrize(
    ("hour", "expected"),
    [
        (6, TouPeriod.OFF),
        (7, TouPeriod.ON),
        (10, TouPeriod.ON),
        (11, TouPeriod.MID),
        (16, TouPeriod.MID),
        (17, TouPeriod.ON),
        (18, TouPeriod.ON),
        (19, TouPeriod.OFF),
        (22, TouPeriod.OFF),
    ],
)
def test_tou_winter_weekday_boundaries(hour: int, expected: TouPeriod) -> None:
    dt = datetime(
        WINTER_WEEKDAY.year,
        WINTER_WEEKDAY.month,
        WINTER_WEEKDAY.day,
        hour,
        tzinfo=TZ,
    )
    assert tou_period(dt) is expected


# --- TOU WEEKENDS AND HOLIDAYS ----------------------------------------------


def test_tou_saturday_is_all_off() -> None:
    for hour in range(24):
        assert tou_period(_dt(2026, 7, 11, hour)) is TouPeriod.OFF  # Saturday


def test_tou_holiday_is_all_off() -> None:
    # Canada Day 2026 = Wednesday, July 1 — would otherwise be on-peak summer.
    assert is_ontario_tou_holiday(date(2026, 7, 1))
    for hour in range(24):
        assert tou_period(_dt(2026, 7, 1, hour)) is TouPeriod.OFF


# --- ULO ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hour", "expected"),
    [
        (0, UloPeriod.OVERNIGHT),
        (6, UloPeriod.OVERNIGHT),
        (7, UloPeriod.MID),
        (15, UloPeriod.MID),
        (16, UloPeriod.ON),
        (20, UloPeriod.ON),
        (21, UloPeriod.MID),
        (22, UloPeriod.MID),
        (23, UloPeriod.OVERNIGHT),
    ],
)
def test_ulo_weekday(hour: int, expected: UloPeriod) -> None:
    dt = _dt(2026, 7, 8, hour)  # Wednesday, summer; ULO is year-round
    assert ulo_period(dt) is expected


@pytest.mark.parametrize(
    ("hour", "expected"),
    [
        (0, UloPeriod.OVERNIGHT),
        (6, UloPeriod.OVERNIGHT),
        (7, UloPeriod.WEEKEND_OFF),
        (16, UloPeriod.WEEKEND_OFF),
        (22, UloPeriod.WEEKEND_OFF),
        (23, UloPeriod.OVERNIGHT),
    ],
)
def test_ulo_weekend(hour: int, expected: UloPeriod) -> None:
    dt = _dt(2026, 7, 11, hour)  # Saturday
    assert ulo_period(dt) is expected


def test_ulo_holiday_treated_as_weekend() -> None:
    # Christmas 2026 = Friday Dec 25, an observed holiday.
    assert is_ontario_tou_holiday(date(2026, 12, 25))
    assert ulo_period(_dt(2026, 12, 25, 12)) is UloPeriod.WEEKEND_OFF


# --- HOLIDAY CALENDAR -------------------------------------------------------


@pytest.mark.parametrize(
    ("year", "expected_dates"),
    [
        # 2026 — exact dates from OEB's 2026 schedule.
        (
            2026,
            {
                date(2026, 1, 1),
                date(2026, 2, 16),
                date(2026, 4, 3),  # Good Friday
                date(2026, 5, 18),
                date(2026, 7, 1),
                date(2026, 8, 3),
                date(2026, 9, 7),
                date(2026, 10, 12),
                date(2026, 12, 25),
                date(2026, 12, 28),  # Boxing Day Dec 26 = Saturday → Mon Dec 28
            },
        ),
        # 2025 — all weekday holidays except none shift.
        (
            2025,
            {
                date(2025, 1, 1),   # Wed
                date(2025, 2, 17),  # 3rd Mon Feb
                date(2025, 4, 18),  # Good Friday
                date(2025, 5, 19),  # Victoria Day
                date(2025, 7, 1),   # Canada Day
                date(2025, 8, 4),   # Civic Mon
                date(2025, 9, 1),   # Labour Mon
                date(2025, 10, 13), # Thanksgiving Mon
                date(2025, 12, 25), # Christmas Thu
                date(2025, 12, 26), # Boxing Fri
            },
        ),
    ],
)
def test_holiday_dates(year: int, expected_dates: set[date]) -> None:
    holidays = {d for d in expected_dates if is_ontario_tou_holiday(d)}
    assert holidays == expected_dates


def test_christmas_on_saturday_observance_shifts() -> None:
    # Dec 25, 2027 = Saturday; Dec 26 = Sunday.
    # Observance: Christmas → Mon Dec 27, Boxing Day → Tue Dec 28 (not Mon, taken).
    assert not is_ontario_tou_holiday(date(2027, 12, 25))
    assert not is_ontario_tou_holiday(date(2027, 12, 26))
    assert is_ontario_tou_holiday(date(2027, 12, 27))
    assert is_ontario_tou_holiday(date(2027, 12, 28))


def test_canada_day_on_sunday_observance_shifts() -> None:
    # July 1, 2029 = Sunday; observance → Mon July 2.
    assert not is_ontario_tou_holiday(date(2029, 7, 1))
    assert is_ontario_tou_holiday(date(2029, 7, 2))


def test_leap_day_is_not_a_holiday() -> None:
    assert not is_ontario_tou_holiday(date(2028, 2, 29))


def test_non_holiday_weekday_is_not_observed() -> None:
    assert not is_ontario_tou_holiday(date(2026, 3, 17))


# --- DST TRANSITIONS --------------------------------------------------------


def test_tou_across_dst_spring_forward() -> None:
    # In 2026, DST springs forward on March 8 (Sunday). Test the following Monday.
    dt = _dt(2026, 3, 9, 11)
    assert tou_period(dt) is TouPeriod.MID  # winter weekday at 11:00


def test_tou_across_dst_fall_back() -> None:
    # In 2026, DST falls back on November 1 (Sunday). Test Monday Nov 2.
    dt = _dt(2026, 11, 2, 11)
    assert tou_period(dt) is TouPeriod.MID  # winter weekday at 11:00


# --- RATE LOOKUP -------------------------------------------------------------

from decimal import Decimal  # noqa: E402

from custom_components.ontario_energy.parser import RateRow  # noqa: E402
from custom_components.ontario_energy.schedule import (  # noqa: E402
    tou_rate_for,
    ulo_rate_for,
)


def _row() -> RateRow:
    return RateRow(
        distributor="x",
        customer_class="RESIDENTIAL",
        rate_year=2026,
        tier1_threshold_kwh=Decimal(600),
        tier1_rate=Decimal("0.12"),
        tier2_rate=Decimal("0.142"),
        tou_off=Decimal("0.098"),
        tou_mid=Decimal("0.157"),
        tou_on=Decimal("0.203"),
        ulo_overnight=Decimal("0.039"),
        ulo_weekend_off=Decimal("0.098"),
        ulo_mid=Decimal("0.157"),
        ulo_on=Decimal("0.391"),
        service_charge=Decimal(0),
        distribution_volumetric=Decimal(0),
        network=Decimal(0),
        connection=Decimal(0),
        wmsr=Decimal(0),
        rrrp=Decimal(0),
        sss_admin=Decimal(0),
        loss_factor=Decimal(1),
        hst=Decimal("0.13"),
        rebate=Decimal("0.235"),
    )


def test_tou_rate_for_each_period() -> None:
    row = _row()
    assert tou_rate_for(row, _dt(2026, 7, 8, 12)) == row.tou_on   # summer wkdy 12:00
    assert tou_rate_for(row, _dt(2026, 7, 8, 8)) == row.tou_mid    # summer wkdy 08:00
    assert tou_rate_for(row, _dt(2026, 7, 8, 23)) == row.tou_off   # late evening


def test_ulo_rate_for_each_period() -> None:
    row = _row()
    assert ulo_rate_for(row, _dt(2026, 7, 8, 3)) == row.ulo_overnight
    assert ulo_rate_for(row, _dt(2026, 7, 11, 12)) == row.ulo_weekend_off
    assert ulo_rate_for(row, _dt(2026, 7, 8, 18)) == row.ulo_on
    assert ulo_rate_for(row, _dt(2026, 7, 8, 10)) == row.ulo_mid
