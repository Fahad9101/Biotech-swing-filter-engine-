from __future__ import annotations

from datetime import UTC, date, datetime

from boe.market_calendar import (
    expected_latest_session_as_of,
    is_trading_day,
    last_complete_session_before,
    nyse_holidays,
    trading_sessions,
)

# Independently known NYSE holiday dates, 2018-2025, used to cross-check the
# rule-derived calendar rather than trusting the algorithm alone.
KNOWN_HOLIDAYS = {
    date(2018, 1, 1),
    date(2018, 1, 15),
    date(2018, 2, 19),
    date(2018, 3, 30),
    date(2018, 5, 28),
    date(2018, 7, 4),
    date(2018, 9, 3),
    date(2018, 11, 22),
    date(2018, 12, 5),  # unscheduled: George H.W. Bush day of mourning
    date(2018, 12, 25),
    date(2019, 1, 1),
    date(2019, 4, 19),
    date(2020, 1, 1),
    date(2020, 7, 3),  # Jul 4 falls on Saturday
    date(2021, 12, 31),  # New Year's 2022 observed the prior Friday
    date(2022, 6, 20),  # Juneteenth first observed, shifted from Sunday
    date(2023, 1, 2),  # New Year's 2023 observed the following Monday
    date(2023, 6, 19),
    date(2024, 6, 19),
    date(2025, 6, 19),
}

# Independently known regular trading days that must NOT be treated as
# holidays, guarding against an overly broad rule.
KNOWN_TRADING_DAYS = {
    date(2018, 12, 24),  # early close, but the session itself is open
    date(2020, 3, 23),  # NYSE trading floor closed for COVID; exchange stayed open
    date(2021, 6, 18),  # Juneteenth became a federal holiday but not yet an NYSE one
    date(2019, 12, 26),
}


def test_known_holidays_are_detected() -> None:
    for day in KNOWN_HOLIDAYS:
        assert not is_trading_day(day), f"{day} should be a closure"


def test_known_trading_days_are_open() -> None:
    for day in KNOWN_TRADING_DAYS:
        assert is_trading_day(day), f"{day} should be a trading day"


def test_weekends_are_never_trading_days() -> None:
    assert not is_trading_day(date(2024, 6, 15))  # Saturday
    assert not is_trading_day(date(2024, 6, 16))  # Sunday


def test_juneteenth_only_from_2022() -> None:
    assert date(2021, 6, 18) not in nyse_holidays(2021)
    assert date(2022, 6, 20) in nyse_holidays(2022)


def test_new_years_backward_shift_lands_in_prior_year() -> None:
    # Jan 1, 2022 is a Saturday - the observed closure is Fri Dec 31, 2021,
    # which must appear in the 2021 calendar, not a nonexistent 2022 date.
    assert date(2021, 12, 31) in nyse_holidays(2021)
    assert date(2022, 1, 1) not in nyse_holidays(2022)


def test_trading_sessions_excludes_weekends_and_holidays() -> None:
    sessions = trading_sessions(date(2024, 12, 23), date(2024, 12, 27))
    assert sessions == (
        date(2024, 12, 23),
        date(2024, 12, 24),
        date(2024, 12, 26),
        date(2024, 12, 27),
    )


def test_trading_sessions_rejects_inverted_range() -> None:
    import pytest

    with pytest.raises(ValueError, match="end must not precede start"):
        trading_sessions(date(2024, 1, 2), date(2024, 1, 1))


def test_last_complete_session_before_skips_weekend_and_holiday() -> None:
    # Presidents Day 2024 is Mon Feb 19; the prior session is Fri Feb 16.
    assert last_complete_session_before(date(2024, 2, 20)) == date(2024, 2, 16)


def test_last_complete_session_before_plain_weekday() -> None:
    assert last_complete_session_before(date(2024, 3, 6)) == date(2024, 3, 5)


def test_expected_latest_session_as_of_before_close_uses_prior_session() -> None:
    # 2024-03-06 09:00 UTC = 04:00 ET (EST, before market open) - today's
    # own session is not finalized yet.
    as_of = datetime(2024, 3, 6, 9, 0, tzinfo=UTC)
    assert expected_latest_session_as_of(as_of) == date(2024, 3, 5)


def test_expected_latest_session_as_of_after_close_uses_todays_session() -> None:
    # 2024-03-06 23:00 UTC = 18:00 ET (EST, well after the 16:00 close).
    as_of = datetime(2024, 3, 6, 23, 0, tzinfo=UTC)
    assert expected_latest_session_as_of(as_of) == date(2024, 3, 6)


def test_expected_latest_session_as_of_on_a_weekend_falls_back() -> None:
    # 2024-03-09 is a Saturday.
    as_of = datetime(2024, 3, 9, 23, 0, tzinfo=UTC)
    assert expected_latest_session_as_of(as_of) == date(2024, 3, 8)
