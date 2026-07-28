from dataclasses import replace

import pandas as pd
import pytest

from gscalp.config import StrategyConfig
from gscalp.models import Direction, LevelSide, LiquidityLevel, ReasonCode, StrategyContext
from gscalp.strategy import evaluate_setup

from test_config import valid_payload


def config() -> StrategyConfig:
    return StrategyConfig(**valid_payload())


def bullish_m15() -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=30, freq="15min", tz="UTC")
    close = pd.Series([90 + i * 0.4 for i in range(30)], index=index)
    return pd.DataFrame(
        {"open": close - 0.1, "high": close + 0.3, "low": close - 0.3, "close": close},
        index=index,
    )


def bearish_m15() -> pd.DataFrame:
    bars = bullish_m15().copy()
    for column in ["open", "high", "low", "close"]:
        bars[column] = 220 - bars[column]
    bars[["high", "low"]] = bars[["low", "high"]].to_numpy()
    return bars


def qualifying_long_m5() -> pd.DataFrame:
    index = pd.date_range("2020-01-01 08:00", periods=17, freq="5min", tz="UTC")
    rows = [
        {"open": 100.6, "high": 101.2, "low": 100.0, "close": 100.8}
        for _ in range(14)
    ]
    rows.extend(
        [
            {"open": 100.5, "high": 100.9, "low": 99.8, "close": 99.9},
            {"open": 99.9, "high": 101.6, "low": 99.8, "close": 101.4},
            {"open": 101.4, "high": 101.5, "low": 100.5, "close": 100.7},
        ]
    )
    return pd.DataFrame(rows, index=index)


def context(
    *,
    m5: pd.DataFrame | None = None,
    m15: pd.DataFrame | None = None,
    high_level: float = 102.0,
) -> StrategyContext:
    bars = qualifying_long_m5() if m5 is None else m5
    return StrategyContext(
        as_of=bars.index[-1] + pd.Timedelta(minutes=5),
        session_start=bars.index[14],
        session_end=bars.index[14] + pd.Timedelta(minutes=60),
        m15=bullish_m15() if m15 is None else m15,
        m5=bars,
        levels=(
            LiquidityLevel("session_low", 100.0, LevelSide.LOW),
            LiquidityLevel("session_high", high_level, LevelSide.HIGH),
        ),
        spread=0.01,
        config=config(),
    )


def mirror_context(source: StrategyContext) -> StrategyContext:
    mirrored = source.m5.copy()
    for column in ["open", "high", "low", "close"]:
        mirrored[column] = 220 - mirrored[column]
    mirrored[["high", "low"]] = mirrored[["low", "high"]].to_numpy()
    levels = tuple(
        LiquidityLevel(
            level.name,
            220 - level.price,
            LevelSide.HIGH if level.side is LevelSide.LOW else LevelSide.LOW,
        )
        for level in source.levels
    )
    return replace(source, m15=bearish_m15(), m5=mirrored, levels=levels)


def test_qualifying_long_has_structural_prices_and_ordered_reasons():
    decision = evaluate_setup(context())

    assert decision.eligible is True
    assert decision.direction is Direction.LONG
    assert decision.entry == pytest.approx(100.71)
    assert decision.stop == pytest.approx(99.79)
    assert decision.target <= 102.0
    assert decision.reasons == (
        ReasonCode.SWEEP_DETECTED,
        ReasonCode.RECLAIMED,
        ReasonCode.DISPLACED,
        ReasonCode.RETESTED,
        ReasonCode.QUALIFIED,
    )


def test_short_signal_is_a_price_mirror_of_long_signal():
    long_decision = evaluate_setup(context())
    short_decision = evaluate_setup(mirror_context(context()))

    assert short_decision.eligible is True
    assert short_decision.direction is Direction.SHORT
    assert short_decision.entry == 220 - 100.7
    assert short_decision.stop == 220 - long_decision.stop
    assert short_decision.reasons == long_decision.reasons


def test_neutral_m15_rejects_before_searching_for_a_sweep():
    flat = bullish_m15()
    flat.loc[:, ["open", "high", "low", "close"]] = [100.0, 100.2, 99.8, 100.0]

    decision = evaluate_setup(context(m15=flat))

    assert decision.reasons == (ReasonCode.NEUTRAL_M15,)


def test_no_level_sweep_is_reason_coded():
    bars = qualifying_long_m5()
    bars.iloc[14:, bars.columns.get_loc("low")] = 100.0

    assert evaluate_setup(context(m5=bars)).reasons[-1] is ReasonCode.NO_LEVEL_SWEEP


def test_small_and_deep_sweeps_are_distinguished():
    small = qualifying_long_m5()
    small.iloc[14, small.columns.get_loc("low")] = 99.95
    deep = qualifying_long_m5()
    deep.iloc[14, deep.columns.get_loc("low")] = 98.0

    assert evaluate_setup(context(m5=small)).reasons[-1] is ReasonCode.SWEEP_TOO_SMALL
    assert evaluate_setup(context(m5=deep)).reasons[-1] is ReasonCode.SWEEP_TOO_DEEP


def test_missing_reclaim_is_reason_coded():
    bars = qualifying_long_m5()
    bars.iloc[15:, bars.columns.get_loc("close")] = 99.9

    assert evaluate_setup(context(m5=bars)).reasons[-1] is ReasonCode.NO_RECLAIM


def test_weak_displacement_is_reason_coded():
    bars = qualifying_long_m5()
    bars.iloc[15] = {"open": 99.9, "high": 100.2, "low": 99.8, "close": 100.1}

    assert evaluate_setup(context(m5=bars)).reasons[-1] is ReasonCode.WEAK_DISPLACEMENT


def test_missing_retest_is_reason_coded():
    bars = qualifying_long_m5()
    bars.iloc[16] = {"open": 101.4, "high": 101.8, "low": 101.3, "close": 101.7}

    assert evaluate_setup(context(m5=bars)).reasons[-1] is ReasonCode.NO_RETEST


def test_wide_stop_and_insufficient_room_are_distinguished():
    wide = qualifying_long_m5()
    wide.iloc[16] = {"open": 101.4, "high": 101.5, "low": 100.5, "close": 101.3}

    assert evaluate_setup(context(m5=wide)).reasons[-1] is ReasonCode.STOP_TOO_WIDE
    assert evaluate_setup(context(high_level=101.0)).reasons[-1] is ReasonCode.INSUFFICIENT_ROOM


def test_incomplete_future_bars_cannot_change_current_decision():
    base = context()
    expected = evaluate_setup(base)
    future = base.m5.copy()
    future.loc[base.as_of] = {"open": 1, "high": 1000, "low": 0, "close": 999}

    actual = evaluate_setup(replace(base, m5=future))

    assert actual == expected


def test_warmup_bars_cannot_create_a_pre_session_signal():
    bars = qualifying_long_m5()
    bars.iloc[13] = {"open": 100.5, "high": 100.9, "low": 99.8, "close": 99.9}
    bars.iloc[14] = {"open": 99.9, "high": 101.6, "low": 99.8, "close": 101.4}
    bars.iloc[15] = {"open": 101.4, "high": 101.5, "low": 100.5, "close": 100.7}
    bars.iloc[16] = {"open": 100.7, "high": 101.0, "low": 100.5, "close": 100.8}

    decision = evaluate_setup(context(m5=bars))

    assert decision.reasons[-1] is ReasonCode.NO_LEVEL_SWEEP


def test_same_bar_wick_reclaim_is_versioned_and_disabled_by_default():
    bars = qualifying_long_m5()
    bars.iloc[14] = {"open": 100.5, "high": 100.9, "low": 99.8, "close": 100.2}
    baseline = context(m5=bars)

    disabled = evaluate_setup(baseline)
    enabled = evaluate_setup(
        replace(
            baseline,
            config=replace(baseline.config, allow_same_bar_reclaim=True),
        )
    )

    assert disabled.reasons[-1] is ReasonCode.NO_LEVEL_SWEEP
    assert enabled.eligible
    assert enabled.reasons[-1] is ReasonCode.QUALIFIED
