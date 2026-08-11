import pandas as pd
import pytest

from gscalp.pullback_bias import completed_before, evaluate_locked_bias
from gscalp.pullback_config import load_pullback_config
from gscalp.pullback_models import PullbackReason, TradeDirection


SESSION_START = pd.Timestamp("2026-07-15 13:45:00+00:00")


@pytest.fixture
def config():
    return load_pullback_config("config/pullback-v1.1.json")


def trend_bars(start, periods, freq, *, rising=True):
    index = pd.date_range(start, periods=periods, freq=freq, tz="UTC")
    step = 0.5 if rising else -0.5
    close = pd.Series(
        [2400.0 + step * number for number in range(periods)],
        index=index,
    )
    return pd.DataFrame(
        {
            "open": close - step / 2,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
        },
        index=index,
    )


def aligned_frames(*, rising=True):
    h1 = trend_bars("2026-07-13 00:00", 62, "1h", rising=rising)
    m15 = trend_bars("2026-07-14 18:00", 84, "15min", rising=rising)
    return h1, m15


def test_completed_before_requires_the_bar_close_not_only_its_open():
    bars = trend_bars("2026-07-15 12:00", 4, "1h")

    completed = completed_before(bars, SESSION_START, timeframe_minutes=60)

    assert list(completed.index) == [pd.Timestamp("2026-07-15 12:00:00+00:00")]


def test_bullish_bias_requires_completed_h1_and_m15_agreement(config):
    h1, m15 = aligned_frames(rising=True)

    decision = evaluate_locked_bias(h1, m15, SESSION_START, config)

    assert decision.direction is TradeDirection.LONG
    assert decision.reason is PullbackReason.SETUP_ARMED
    assert decision.h1_close > decision.h1_ema_now > decision.h1_ema_three_bars_ago
    assert decision.m15_close > decision.m15_ema_now > decision.m15_ema_three_bars_ago


def test_bearish_bias_requires_completed_h1_and_m15_agreement(config):
    h1, m15 = aligned_frames(rising=False)

    decision = evaluate_locked_bias(h1, m15, SESSION_START, config)

    assert decision.direction is TradeDirection.SHORT
    assert decision.h1_close < decision.h1_ema_now < decision.h1_ema_three_bars_ago
    assert decision.m15_close < decision.m15_ema_now < decision.m15_ema_three_bars_ago


def test_disagreement_is_neutral(config):
    h1, _ = aligned_frames(rising=True)
    _, m15 = aligned_frames(rising=False)

    decision = evaluate_locked_bias(h1, m15, SESSION_START, config)

    assert decision.direction is None
    assert decision.reason is PullbackReason.NEUTRAL_BIAS


def test_incomplete_bars_cannot_change_locked_bias(config):
    h1, m15 = aligned_frames(rising=True)
    baseline = evaluate_locked_bias(h1, m15, SESSION_START, config)
    mutated_h1 = h1.copy()
    mutated_m15 = m15.copy()
    mutated_h1.loc[mutated_h1.index >= SESSION_START.floor("h"), "close"] = 1.0
    mutated_m15.loc[mutated_m15.index >= SESSION_START, "close"] = 1.0

    assert evaluate_locked_bias(mutated_h1, mutated_m15, SESSION_START, config) == baseline


def test_insufficient_history_is_reason_coded(config):
    h1 = trend_bars("2026-07-15 10:00", 2, "1h")
    m15 = trend_bars("2026-07-15 12:00", 3, "15min")

    decision = evaluate_locked_bias(h1, m15, SESSION_START, config)

    assert decision.direction is None
    assert decision.reason is PullbackReason.INSUFFICIENT_BARS
    assert decision.h1_close is None


def test_bias_rejects_naive_bar_indexes(config):
    h1, m15 = aligned_frames(rising=True)
    h1.index = h1.index.tz_localize(None)

    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_locked_bias(h1, m15, SESSION_START, config)

