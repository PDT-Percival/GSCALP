from datetime import datetime, timedelta, timezone

import pytest

from gscalp.fbs_time import (
    FbsServerTimeError,
    fbs_server_to_utc,
    fbs_utc_offset_at,
    last_sunday_utc,
)


@pytest.mark.parametrize("year", range(2020, 2027))
def test_fbs_offset_is_two_hours_in_january_and_three_in_july(year):
    assert fbs_utc_offset_at(
        datetime(year, 1, 15, tzinfo=timezone.utc)
    ) == timedelta(hours=2)
    assert fbs_utc_offset_at(
        datetime(year, 7, 15, tzinfo=timezone.utc)
    ) == timedelta(hours=3)


@pytest.mark.parametrize(
    ("year", "march_day", "october_day"),
    [
        (2020, 29, 25),
        (2021, 28, 31),
        (2022, 27, 30),
        (2023, 26, 29),
        (2024, 31, 27),
        (2025, 30, 26),
        (2026, 29, 25),
    ],
)
def test_fbs_offset_changes_at_one_utc_on_last_sundays(
    year, march_day, october_day
):
    march = datetime(year, 3, march_day, 1, tzinfo=timezone.utc)
    october = datetime(year, 10, october_day, 1, tzinfo=timezone.utc)

    assert last_sunday_utc(year, 3) == march
    assert last_sunday_utc(year, 10) == october
    assert fbs_utc_offset_at(march - timedelta(seconds=1)) == timedelta(hours=2)
    assert fbs_utc_offset_at(march) == timedelta(hours=3)
    assert fbs_utc_offset_at(october - timedelta(seconds=1)) == timedelta(hours=3)
    assert fbs_utc_offset_at(october) == timedelta(hours=2)


def test_server_wall_time_conversion_is_not_local_timezone_dependent():
    assert fbs_server_to_utc(datetime(2023, 1, 3, 15, 30)) == datetime(
        2023, 1, 3, 13, 30, tzinfo=timezone.utc
    )
    assert fbs_server_to_utc(datetime(2023, 7, 3, 16, 30)) == datetime(
        2023, 7, 3, 13, 30, tzinfo=timezone.utc
    )


def test_spring_gap_and_autumn_duplicate_wall_times_fail_closed():
    with pytest.raises(FbsServerTimeError, match="nonexistent"):
        fbs_server_to_utc(datetime(2026, 3, 29, 3, 30))
    with pytest.raises(FbsServerTimeError, match="ambiguous"):
        fbs_server_to_utc(datetime(2026, 10, 25, 3, 30))


def test_timezone_awareness_contract_rejects_wrong_input_kinds():
    with pytest.raises(ValueError, match="timezone-aware"):
        fbs_utc_offset_at(datetime(2026, 8, 11, 12, 0))
    with pytest.raises(ValueError, match="naive FBS wall time"):
        fbs_server_to_utc(datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc))


@pytest.mark.parametrize("month", [1, 2, 4, 9, 11, 12])
def test_last_sunday_only_accepts_fbs_transition_months(month):
    with pytest.raises(ValueError, match="March or October"):
        last_sunday_utc(2026, month)
