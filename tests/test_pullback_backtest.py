from dataclasses import replace

import pandas as pd
import pytest

from gscalp.pullback_backtest import CostStress, simulate_trade
from gscalp.pullback_config import PullbackCandidate
from gscalp.pullback_models import (
    ExitReason,
    PullbackSetup,
    TradeDirection,
    TradePlan,
)


START = pd.Timestamp("2026-07-15 13:45:00+00:00")
AVAILABLE = START + pd.Timedelta(minutes=11)
END = START + pd.Timedelta(hours=1)


def make_plan(direction=TradeDirection.LONG):
    long = direction is TradeDirection.LONG
    setup = PullbackSetup(
        PullbackCandidate("09:30-10:30", "M1", 0.50, "M1"),
        direction,
        2.0,
        99.4 if long else 100.6,
        101.0 if long else 99.0,
        AVAILABLE,
        AVAILABLE,
        100.0,
        99.0 if long else 101.0,
        0.20,
    )
    return TradePlan(
        "trade-1",
        setup,
        100.0,
        100.5 if long else 99.5,
        0.10,
        0.30,
        15.0,
        50.0,
        10_000.0,
    )


def ticks(rows):
    return pd.DataFrame(
        [(bid, ask) for _, bid, ask in rows],
        columns=["bid", "ask"],
        index=pd.DatetimeIndex([timestamp for timestamp, _, _ in rows]),
    )


def empty_abort_bars():
    return pd.DataFrame(
        columns=["open", "high", "low", "close"],
        index=pd.DatetimeIndex([], tz="UTC"),
    )


def test_long_enters_on_first_eligible_ask_and_targets_on_bid():
    market = ticks(
        [
            (AVAILABLE - pd.Timedelta(milliseconds=1), 99.7, 99.9),
            (AVAILABLE, 99.8, 100.0),
            (AVAILABLE + pd.Timedelta(minutes=1), 100.5, 100.7),
        ]
    )

    result = simulate_trade(make_plan(), market, empty_abort_bars(), END, 100.0)

    assert result.reason is ExitReason.TARGET_CLOSED
    assert result.trade.entry_time == AVAILABLE
    assert result.trade.entry_price == pytest.approx(100.0)
    assert result.trade.exit_price == pytest.approx(100.5)
    assert result.trade.pnl_cash == pytest.approx(5.0)
    assert result.trade.net_r == pytest.approx(0.5)


def test_short_enters_on_bid_and_targets_on_ask():
    market = ticks(
        [
            (AVAILABLE, 100.0, 100.2),
            (AVAILABLE + pd.Timedelta(minutes=1), 99.3, 99.5),
        ]
    )

    result = simulate_trade(
        make_plan(TradeDirection.SHORT), market, empty_abort_bars(), END, 100.0
    )

    assert result.reason is ExitReason.TARGET_CLOSED
    assert result.trade.entry_price == pytest.approx(100.0)
    assert result.trade.exit_price == pytest.approx(99.5)
    assert result.trade.net_r == pytest.approx(0.5)


def test_stop_is_checked_before_any_later_recovery():
    market = ticks(
        [
            (AVAILABLE, 99.8, 100.0),
            (AVAILABLE + pd.Timedelta(seconds=1), 98.9, 99.1),
            (AVAILABLE + pd.Timedelta(seconds=2), 100.6, 100.8),
        ]
    )

    result = simulate_trade(make_plan(), market, empty_abort_bars(), END, 100.0)

    assert result.reason is ExitReason.STOPPED
    assert result.trade.exit_time == AVAILABLE + pd.Timedelta(seconds=1)
    assert result.trade.exit_price == pytest.approx(98.9)
    assert result.trade.net_r == pytest.approx(-1.1)


def test_wide_spread_aborts_before_entry_without_waiting_or_retrying():
    market = ticks(
        [
            (AVAILABLE, 99.8, 100.2),
            (AVAILABLE + pd.Timedelta(seconds=1), 99.9, 100.0),
        ]
    )

    result = simulate_trade(make_plan(), market, empty_abort_bars(), END, 100.0)

    assert result.trade is None
    assert result.reason is ExitReason.SPREAD_ABORT_BEFORE_ENTRY


def test_no_tick_before_cutoff_is_entry_timeout():
    market = ticks(
        [(START + pd.Timedelta(minutes=46), 99.8, 100.0)]
    )

    result = simulate_trade(make_plan(), market, empty_abort_bars(), END, 100.0)

    assert result.trade is None
    assert result.reason is ExitReason.ENTRY_TIMEOUT


def test_open_trade_flattens_on_last_tick_before_minute_60():
    market = ticks(
        [
            (AVAILABLE, 99.8, 100.0),
            (END - pd.Timedelta(seconds=2), 100.1, 100.3),
            (END - pd.Timedelta(seconds=1), 100.2, 100.4),
            (END, 500.0, 500.2),
        ]
    )

    result = simulate_trade(make_plan(), market, empty_abort_bars(), END, 100.0)

    assert result.reason is ExitReason.SESSION_FLATTENED
    assert result.trade.exit_time == END - pd.Timedelta(seconds=1)
    assert result.trade.exit_price == pytest.approx(100.2)


def abort_bars():
    index = pd.date_range(AVAILABLE - pd.Timedelta(minutes=9), periods=10, freq="1min")
    closes = [100.2] * 8 + [100.4, 99.5]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [value + 0.2 for value in closes],
            "low": [value - 0.2 for value in closes],
            "close": closes,
        },
        index=index,
    )


def test_momentum_cross_is_executable_only_after_bar_close():
    market = ticks(
        [
            (AVAILABLE, 99.8, 100.0),
            (AVAILABLE + pd.Timedelta(minutes=1) - pd.Timedelta(milliseconds=1), 99.9, 100.1),
            (AVAILABLE + pd.Timedelta(minutes=1), 99.8, 100.0),
        ]
    )

    result = simulate_trade(make_plan(), market, abort_bars(), END, 100.0)

    assert result.reason is ExitReason.MOMENTUM_ABORT
    assert result.trade.exit_time == AVAILABLE + pd.Timedelta(minutes=1)
    assert result.trade.exit_price == pytest.approx(99.8)


def test_target_available_at_abort_boundary_wins_before_abort():
    market = ticks(
        [
            (AVAILABLE, 99.8, 100.0),
            (AVAILABLE + pd.Timedelta(minutes=1), 100.5, 100.7),
        ]
    )

    result = simulate_trade(make_plan(), market, abort_bars(), END, 100.0)

    assert result.reason is ExitReason.TARGET_CLOSED


def test_tick_exit_scan_is_vectorized_without_dataframe_row_iteration(monkeypatch):
    market = ticks(
        [
            (AVAILABLE, 99.8, 100.0),
            (AVAILABLE + pd.Timedelta(seconds=1), 100.1, 100.3),
            (AVAILABLE + pd.Timedelta(seconds=2), 100.5, 100.7),
        ]
    )

    monkeypatch.setattr(
        pd.DataFrame,
        "iterrows",
        lambda _self: pytest.fail("tick exits must use a vectorized first-event scan"),
    )

    result = simulate_trade(make_plan(), market, empty_abort_bars(), END, 100.0)

    assert result.reason is ExitReason.TARGET_CLOSED
    assert result.trade.exit_time == AVAILABLE + pd.Timedelta(seconds=2)


def test_spread_stress_never_improves_long_entry():
    market = ticks(
        [
            (AVAILABLE, 99.8, 100.0),
            (AVAILABLE + pd.Timedelta(minutes=1), 100.5, 100.7),
        ]
    )

    result = simulate_trade(
        replace(make_plan(), development_spread_ceiling=1.0),
        market,
        empty_abort_bars(),
        END,
        100.0,
        CostStress(spread_multiplier=1.25),
    )

    assert result.trade.entry_price == pytest.approx(100.05)
    assert result.trade.net_r < 0.5


@pytest.mark.parametrize("problem", ["naive", "duplicate", "unsorted"])
def test_tick_input_must_be_utc_sorted_and_unique(problem):
    market = ticks(
        [
            (AVAILABLE, 99.8, 100.0),
            (AVAILABLE + pd.Timedelta(seconds=1), 100.5, 100.7),
        ]
    )
    if problem == "naive":
        market.index = market.index.tz_localize(None)
    elif problem == "duplicate":
        market.index = pd.DatetimeIndex([AVAILABLE, AVAILABLE])
    else:
        market = market.iloc[::-1]

    with pytest.raises(ValueError):
        simulate_trade(make_plan(), market, empty_abort_bars(), END, 100.0)
