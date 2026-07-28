import pandas as pd
import pytest

from gscalp.backtest import ExitReason, run_signal_backtest, simulate_trade
from gscalp.models import Direction, ReasonCode, SignalDecision


def signal(direction: Direction, *, signal_time="2020-01-02 09:00:00+00:00"):
    if direction is Direction.LONG:
        entry, stop, target = 100.2, 99.0, 101.4
    else:
        entry, stop, target = 100.0, 101.2, 98.8
    return SignalDecision(
        eligible=True,
        direction=direction,
        signal_time=pd.Timestamp(signal_time),
        entry=entry,
        stop=stop,
        target=target,
        reasons=(ReasonCode.QUALIFIED,),
    )


def ticks(rows):
    frame = pd.DataFrame(rows, columns=["time", "bid", "ask"])
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    return frame.set_index("time")


def test_long_enters_at_ask_and_targets_on_bid_after_next_bar_opens():
    market = ticks(
        [
            ("2020-01-02 09:04:59+00:00", 90.0, 90.2),
            ("2020-01-02 09:05:00+00:00", 100.0, 100.2),
            ("2020-01-02 09:06:00+00:00", 101.4, 101.6),
        ]
    )

    trade = simulate_trade(
        signal(Direction.LONG), market, pd.Timestamp("2020-01-02 10:00:00+00:00")
    )

    assert trade.entry_price == 100.2
    assert trade.exit_price == 101.4
    assert trade.exit_reason is ExitReason.TARGET
    assert trade.net_r == pytest.approx(1.0)


def test_short_enters_at_bid_and_stops_on_ask():
    market = ticks(
        [
            ("2020-01-02 09:05:00+00:00", 100.0, 100.2),
            ("2020-01-02 09:06:00+00:00", 101.0, 101.2),
        ]
    )

    trade = simulate_trade(
        signal(Direction.SHORT), market, pd.Timestamp("2020-01-02 10:00:00+00:00")
    )

    assert trade.entry_price == 100.0
    assert trade.exit_price == 101.2
    assert trade.exit_reason is ExitReason.STOP
    assert trade.net_r == pytest.approx(-1.0)


def test_open_trade_is_closed_on_the_last_tick_before_session_end():
    market = ticks(
        [
            ("2020-01-02 09:05:00+00:00", 100.0, 100.2),
            ("2020-01-02 09:59:59+00:00", 100.5, 100.7),
            ("2020-01-02 10:00:01+00:00", 200.0, 200.2),
        ]
    )

    trade = simulate_trade(
        signal(Direction.LONG), market, pd.Timestamp("2020-01-02 10:00:00+00:00")
    )

    assert trade.exit_time == pd.Timestamp("2020-01-02 09:59:59+00:00")
    assert trade.exit_price == 100.5
    assert trade.exit_reason is ExitReason.SESSION_END


def test_mfe_and_mae_use_executable_side_of_market():
    market = ticks(
        [
            ("2020-01-02 09:05:00+00:00", 100.0, 100.2),
            ("2020-01-02 09:06:00+00:00", 99.6, 99.8),
            ("2020-01-02 09:07:00+00:00", 100.8, 101.0),
            ("2020-01-02 09:59:59+00:00", 100.4, 100.6),
        ]
    )

    trade = simulate_trade(
        signal(Direction.LONG), market, pd.Timestamp("2020-01-02 10:00:00+00:00")
    )

    assert trade.mfe_r == pytest.approx(0.5)
    assert trade.mae_r == pytest.approx(-0.5)


def test_session_runner_caps_entries_at_two():
    signals = [
        signal(Direction.LONG, signal_time=f"2020-01-02 09:{minute:02d}:00+00:00")
        for minute in (0, 10, 20)
    ]
    market = ticks(
        [
            ("2020-01-02 09:05:00+00:00", 100.0, 100.2),
            ("2020-01-02 09:06:00+00:00", 101.4, 101.6),
            ("2020-01-02 09:15:00+00:00", 100.0, 100.2),
            ("2020-01-02 09:16:00+00:00", 101.4, 101.6),
            ("2020-01-02 09:25:00+00:00", 100.0, 100.2),
            ("2020-01-02 09:26:00+00:00", 101.4, 101.6),
        ]
    )

    trades = run_signal_backtest(
        signals,
        market,
        session_end=pd.Timestamp("2020-01-02 10:00:00+00:00"),
        max_trades=2,
        daily_loss_limit_r=2.0,
    )

    assert len(trades) == 2

