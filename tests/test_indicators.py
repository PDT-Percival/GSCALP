from datetime import time

import pandas as pd
import pytest

from gscalp.indicators import atr, ema, session_high_low, true_range


def test_ema_uses_completed_values_without_backfill():
    values = pd.Series([1.0, 2.0, 3.0, 4.0])

    result = ema(values, period=3)

    expected = values.ewm(span=3, adjust=False, min_periods=3).mean()
    pd.testing.assert_series_equal(result, expected)
    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[1])


def test_true_range_accounts_for_previous_close_gap():
    bars = pd.DataFrame(
        {
            "high": [10.0, 13.0],
            "low": [8.0, 11.0],
            "close": [9.0, 12.0],
        }
    )

    result = true_range(bars)

    assert result.tolist() == [2.0, 4.0]


def test_atr_is_wilder_smoothed_and_requires_warmup():
    bars = pd.DataFrame(
        {
            "high": [10.0, 11.0, 12.0, 13.0],
            "low": [8.0, 9.0, 10.0, 11.0],
            "close": [9.0, 10.0, 11.0, 12.0],
        }
    )

    result = atr(bars, period=3)

    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[1])
    assert result.iloc[2] == pytest.approx(2.0)
    assert result.iloc[3] == pytest.approx(2.0)


def test_session_high_low_uses_utc_then_new_york_conversion():
    index = pd.DatetimeIndex(
        [
            "2024-07-01 12:44:00+00:00",
            "2024-07-01 12:45:00+00:00",
            "2024-07-01 13:00:00+00:00",
            "2024-07-01 13:44:00+00:00",
            "2024-07-01 13:45:00+00:00",
        ]
    )
    bars = pd.DataFrame(
        {"high": [1, 4, 7, 5, 100], "low": [0, 3, 2, 1, -100]}, index=index
    )

    high, low = session_high_low(
        bars,
        local_date="2024-07-01",
        start=time(8, 45),
        end=time(9, 45),
        timezone_name="America/New_York",
    )

    assert high == 7
    assert low == 1
