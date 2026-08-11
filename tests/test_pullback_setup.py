from dataclasses import replace

import pandas as pd
import pytest

from gscalp.pullback_config import PullbackCandidate, load_pullback_config
from gscalp.pullback_models import (
    BiasDecision,
    PullbackReason,
    TradeDirection,
)
from gscalp.pullback_setup import atr, detect_pullback_setup


START = pd.Timestamp("2026-07-15 13:45:00+00:00")
END = START + pd.Timedelta(hours=1)


@pytest.fixture
def config():
    return load_pullback_config("config/pullback-v1.1.json")


def bias(direction):
    if direction is TradeDirection.LONG:
        values = (101.0, 100.0, 99.0, 101.0, 100.0, 99.0)
    else:
        values = (99.0, 100.0, 101.0, 99.0, 100.0, 101.0)
    return BiasDecision(
        direction,
        PullbackReason.SETUP_ARMED,
        START,
        *values,
    )


def long_frames(*, trigger_timeframe="M1"):
    warmup_index = pd.date_range(
        START - pd.Timedelta(minutes=100), periods=20, freq="5min"
    )
    m5 = pd.DataFrame(
        {
            "open": [99.0] * 20,
            "high": [100.2] * 20,
            "low": [98.2] * 20,
            "close": [99.2] * 20,
        },
        index=warmup_index,
    )
    session = pd.DataFrame(
        {
            "open": [99.5, 100.5, 100.0],
            "high": [101.0, 100.8, 101.3],
            "low": [99.4, 99.8, 99.9],
            "close": [100.5, 100.0, 101.2],
        },
        index=pd.DatetimeIndex([START, START + pd.Timedelta(minutes=5), START + pd.Timedelta(minutes=10)]),
    )
    m5 = pd.concat([m5, session])

    m1_index = pd.date_range(START - pd.Timedelta(minutes=20), periods=27, freq="1min")
    m1 = pd.DataFrame(
        {
            "open": [99.8] * 27,
            "high": [100.2] * 27,
            "low": [99.4] * 27,
            "close": [99.9] * 27,
        },
        index=m1_index,
    )
    trigger_open = START + pd.Timedelta(minutes=10)
    prior_open = trigger_open - pd.Timedelta(minutes=1)
    m1.loc[prior_open] = [99.9, 100.2, 99.7, 100.0]
    m1.loc[trigger_open] = [100.0, 100.8, 99.9, 100.7]
    return m1.sort_index(), m5.sort_index()


def mirror(frame):
    result = frame.copy()
    result["open"] = 200.0 - frame["open"]
    result["close"] = 200.0 - frame["close"]
    result["high"] = 200.0 - frame["low"]
    result["low"] = 200.0 - frame["high"]
    return result


def candidate(trigger="M1", *, target=0.35, abort="M5"):
    return PullbackCandidate("09:30-10:30", trigger, target, abort)


def test_atr_uses_wilder_completed_bar_ranges():
    _, m5 = long_frames()

    values = atr(m5.iloc[:20], 14)

    assert values.iloc[-1] == pytest.approx(2.0)


def test_long_m1_continuation_arms_after_valid_pullback(config):
    m1, m5 = long_frames()

    decision = detect_pullback_setup(
        m1,
        m5,
        bias(TradeDirection.LONG),
        candidate("M1"),
        START,
        END,
        reference_spread=0.20,
        config=config,
    )

    assert decision.reason is PullbackReason.SETUP_ARMED
    assert decision.setup.direction is TradeDirection.LONG
    assert decision.setup.pullback_swing == pytest.approx(99.8)
    assert decision.setup.pre_pullback_swing == pytest.approx(101.0)
    assert decision.setup.atr == pytest.approx(1.9153061224489794)
    assert decision.setup.stop == pytest.approx(99.4)
    assert decision.setup.trigger_close_time == START + pd.Timedelta(minutes=11)
    assert decision.setup.entry_available_time == START + pd.Timedelta(minutes=11)


def test_short_m5_continuation_is_symmetric(config):
    m1, m5 = long_frames(trigger_timeframe="M5")

    decision = detect_pullback_setup(
        mirror(m1),
        mirror(m5),
        bias(TradeDirection.SHORT),
        candidate("M5"),
        START,
        END,
        reference_spread=0.20,
        config=config,
    )

    assert decision.reason is PullbackReason.SETUP_ARMED
    assert decision.setup.direction is TradeDirection.SHORT
    assert decision.setup.pullback_swing == pytest.approx(100.2)
    assert decision.setup.pre_pullback_swing == pytest.approx(99.0)
    assert decision.setup.stop == pytest.approx(100.6)
    assert decision.setup.trigger_close_time == START + pd.Timedelta(minutes=15)


def test_pullback_below_minimum_atr_is_rejected(config):
    m1, m5 = long_frames()
    m5.loc[START, "close"] = 100.8
    m5.loc[START + pd.Timedelta(minutes=5), ["high", "low", "close"]] = [100.85, 100.6, 100.7]

    decision = detect_pullback_setup(
        m1, m5, bias(TradeDirection.LONG), candidate(), START, END, 0.20, config
    )

    assert decision.setup is None
    assert decision.reason is PullbackReason.PULLBACK_TOO_SHALLOW


def test_pullback_above_maximum_atr_is_rejected(config):
    m1, m5 = long_frames()
    m5.loc[START + pd.Timedelta(minutes=5), "low"] = 98.6

    decision = detect_pullback_setup(
        m1, m5, bias(TradeDirection.LONG), candidate(), START, END, 0.20, config
    )

    assert decision.setup is None
    assert decision.reason is PullbackReason.PULLBACK_TOO_DEEP


def test_missing_atr_history_is_rejected(config):
    m1, m5 = long_frames()
    m5 = m5.loc[m5.index >= START]

    decision = detect_pullback_setup(
        m1, m5, bias(TradeDirection.LONG), candidate(), START, END, 0.20, config
    )

    assert decision.setup is None
    assert decision.reason is PullbackReason.INVALID_ATR


def test_small_trigger_body_does_not_arm(config):
    m1, m5 = long_frames()
    trigger = START + pd.Timedelta(minutes=10)
    m1.loc[trigger] = [100.65, 100.80, 99.90, 100.70]

    decision = detect_pullback_setup(
        m1, m5, bias(TradeDirection.LONG), candidate(), START, END, 0.20, config
    )

    assert decision.setup is None
    assert decision.reason is PullbackReason.TRIGGER_BODY_TOO_SMALL


def test_trigger_after_minute_45_is_rejected(config):
    m1, m5 = long_frames()
    original = START + pd.Timedelta(minutes=10)
    late = START + pd.Timedelta(minutes=45)
    m1.loc[late] = m1.loc[original]
    m1.loc[original] = [99.9, 100.1, 99.7, 100.0]
    m5.loc[START + pd.Timedelta(minutes=10)] = [100.0, 100.9, 99.9, 100.8]

    decision = detect_pullback_setup(
        m1.sort_index(), m5, bias(TradeDirection.LONG), candidate(), START, END, 0.20, config
    )

    assert decision.setup is None
    assert decision.reason is PullbackReason.TRIGGER_AFTER_CUTOFF


def test_future_bars_cannot_change_first_setup(config):
    m1, m5 = long_frames()
    baseline = detect_pullback_setup(
        m1, m5, bias(TradeDirection.LONG), candidate(), START, END, 0.20, config
    )
    future_time = baseline.setup.entry_available_time + pd.Timedelta(minutes=1)
    m1.loc[future_time] = [5000.0, 6000.0, 1.0, 2.0]
    m5.loc[START + pd.Timedelta(minutes=15)] = [5000.0, 6000.0, 1.0, 2.0]

    changed = detect_pullback_setup(
        m1.sort_index(), m5.sort_index(), bias(TradeDirection.LONG), candidate(), START, END, 0.20, config
    )

    assert changed == baseline
