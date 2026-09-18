"""Deterministic NYSE/Nasdaq trading-session calendar.

Milestone 7's frozen point-in-time functions (``snapshot_cutoff`` and
``align_t0_session`` in ``boe.historical_validation``) take a trading calendar
as an external input rather than computing one themselves. This module
supplies that input without depending on a paid or terms-gated data feed:
holiday dates are derived from published, fixed NYSE observance rules
(nth-weekday-of-month rules, the Gregorian Easter algorithm for Good Friday,
and Juneteenth from its 2022 addition) rather than transcribed by hand for
each year, plus the one documented unscheduled full-day closure in the
project's 2018-2025 cohort window.
"""

from __future__ import annotations

from datetime import date, timedelta

# Full-day closures with no fixed observance rule (e.g. national days of
# mourning). There is exactly one in the 2018-2025 cohort window.
_UNSCHEDULED_CLOSURES = frozenset({date(2018, 12, 5)})  # George H.W. Bush

JUNETEENTH_FIRST_OBSERVED_YEAR = 2022


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    last_day = next_month - timedelta(days=1)
    offset = (last_day.weekday() - weekday) % 7
    return last_day - timedelta(days=offset)


def _easter(year: int) -> date:
    """Gregorian Easter Sunday via the Anonymous/Meeus algorithm."""
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
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = (h + ell - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _observed(holiday: date) -> date:
    """Saturday holidays are observed the preceding Friday, Sunday holidays
    the following Monday - the standard federal/NYSE shift rule."""
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def _new_years_observances_touching(year: int) -> set[date]:
    # A Saturday Jan 1 is observed the prior Friday, which can fall in the
    # previous calendar year - check both this year's and next year's Jan 1.
    touching = set()
    for y in (year, year + 1):
        observed = _observed(date(y, 1, 1))
        if observed.year == year:
            touching.add(observed)
    return touching


def nyse_holidays(year: int) -> frozenset[date]:
    """Full-day NYSE closures falling within a calendar year."""
    holidays = _new_years_observances_touching(year) | {
        _nth_weekday_of_month(year, 1, 0, 3),  # MLK Day
        _nth_weekday_of_month(year, 2, 0, 3),  # Presidents Day
        _easter(year) - timedelta(days=2),  # Good Friday
        _last_weekday_of_month(year, 5, 0),  # Memorial Day
        _observed(date(year, 7, 4)),  # Independence Day
        _nth_weekday_of_month(year, 9, 0, 1),  # Labor Day
        _nth_weekday_of_month(year, 11, 3, 4),  # Thanksgiving
        _observed(date(year, 12, 25)),  # Christmas
    }
    if year >= JUNETEENTH_FIRST_OBSERVED_YEAR:
        holidays.add(_observed(date(year, 6, 19)))
    holidays |= {d for d in _UNSCHEDULED_CLOSURES if d.year == year}
    return frozenset(holidays)


def is_trading_day(day: date) -> bool:
    if day.weekday() >= 5:
        return False
    return day not in nyse_holidays(day.year)


def trading_sessions(start: date, end: date) -> tuple[date, ...]:
    """All trading sessions in ``[start, end]``, inclusive."""
    if end < start:
        raise ValueError("end must not precede start")
    sessions = []
    current = start
    while current <= end:
        if is_trading_day(current):
            sessions.append(current)
        current += timedelta(days=1)
    return tuple(sessions)


def last_complete_session_before(event_date: date) -> date:
    """The most recent trading session strictly before ``event_date``."""
    current = event_date - timedelta(days=1)
    while not is_trading_day(current):
        current -= timedelta(days=1)
    return current
