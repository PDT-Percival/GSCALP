import pandas as pd
import pytest

from gscalp.grid_backtest import CostStress, simulate_grid
from gscalp.grid_models import BiasDirection, GridGeometry, GridLevelPlan, GridPlan, GridReason


START = pd.Timestamp("2026-07-15 12:00:00+00:00")


def plan(direction: BiasDirection = BiasDirection.LONG) -> GridPlan:
    if direction is BiasDirection.LONG:
        anchor, stop, levels = 100.0, 96.0, (99.0, 98.0, 97.0)
    else:
        anchor, stop, levels = 100.0, 104.0, (101.0, 102.0, 103.0)
    geometry = GridGeometry(
        direction, START, START + pd.Timedelta(minutes=60), anchor, stop,
        1.0, 0.2, 0.2, 1.0, levels,
    )
    targets = (100.0, 99.0, 98.0) if direction is BiasDirection.LONG else (100.0, 101.0, 102.0)
    return GridPlan(
        "basket-1", geometry,
        tuple(
            GridLevelPlan(number, price, 1.0, stop, target)
            for number, (price, target) in enumerate(zip(levels, targets), start=1)
        ),
        projected_loss_cash=6.0,
        projected_margin_cash=10.0,
    )


def ticks(*rows: tuple[int, float, float]) -> pd.DataFrame:
    index = [START + pd.Timedelta(minutes=minute) for minute, _, _ in rows]
    return pd.DataFrame(
        {"bid": [bid for _, bid, _ in rows], "ask": [ask for _, _, ask in rows]},
        index=index,
    )


def abort_bars(*minutes: int) -> pd.DataFrame:
    index = [START + pd.Timedelta(minutes=minute) for minute in minutes]
    return pd.DataFrame({"abort": [True] * len(index)}, index=pd.DatetimeIndex(index))


def no_abort_bars() -> pd.DataFrame:
    return pd.DataFrame({"abort": pd.Series(dtype=bool)}, index=pd.DatetimeIndex([], tz="UTC"))


def test_long_limits_fill_on_ask_and_exit_on_bid():
    result = simulate_grid(
        plan(),
        ticks((1, 99.0, 99.2), (2, 98.8, 99.0), (3, 100.0, 100.2)),
        no_abort_bars(),
        CostStress(additional_cost_r=0.25),
    )

    assert result is not None
    assert [(leg.fill_price, leg.exit_price, leg.reason) for leg in result.legs] == [
        (99.0, 100.0, GridReason.TARGET_CLOSED)
    ]
    assert result.gross_r == pytest.approx(1 / 6)
    assert result.cost_r == 0.25
    assert result.net_r == pytest.approx(-1 / 12)


def test_short_limits_fill_on_bid_and_exit_on_ask():
    result = simulate_grid(
        plan(BiasDirection.SHORT),
        ticks((1, 100.8, 101.0), (2, 101.0, 101.2), (3, 99.8, 100.0)),
        no_abort_bars(),
        CostStress(),
    )

    assert result is not None
    assert [(leg.fill_price, leg.exit_price, leg.reason) for leg in result.legs] == [
        (101.0, 100.0, GridReason.TARGET_CLOSED)
    ]


def test_target_recalculates_after_each_fill():
    result = simulate_grid(
        plan(),
        ticks((1, 98.8, 99.0), (2, 97.8, 98.0), (3, 99.5, 99.7)),
        no_abort_bars(),
        CostStress(),
    )

    assert result is not None
    # E1's one-leg target is 100.0; after E2 the common weighted target is 99.5.
    assert [(leg.level_number, leg.exit_price) for leg in result.legs] == [(1, 99.5), (2, 99.5)]


def test_same_tick_gap_fill_then_stop_is_conservative():
    result = simulate_grid(
        plan(), ticks((1, 95.5, 98.9)), no_abort_bars(), CostStress()
    )

    assert result is not None
    assert [(leg.level_number, leg.exit_price, leg.reason) for leg in result.legs] == [
        (1, 95.5, GridReason.STOPPED)
    ]
    assert result.gross_r == pytest.approx(-3.5 / 6)


def test_unfilled_levels_expire_at_minute_45():
    result = simulate_grid(
        plan(), ticks((45, 98.8, 99.0), (46, 98.0, 98.1)), no_abort_bars(), CostStress()
    )

    assert result is None


def test_open_legs_flatten_on_last_tick_before_minute_60():
    result = simulate_grid(
        plan(), ticks((1, 98.8, 99.0), (59, 98.5, 98.7), (60, 98.0, 98.2)), no_abort_bars(), CostStress()
    )

    assert result is not None
    assert result.exit_time == START + pd.Timedelta(minutes=59)
    assert [(leg.exit_price, leg.reason) for leg in result.legs] == [
        (98.5, GridReason.SESSION_FLATTENED)
    ]


def test_bias_abort_cancels_orders_and_closes_filled_legs():
    result = simulate_grid(
        plan(),
        ticks((1, 98.8, 99.0), (15, 98.7, 99.1), (20, 97.8, 98.0)),
        abort_bars(15),
        CostStress(),
    )

    assert result is not None
    assert result.reason is GridReason.BIAS_ABORT
    assert [(leg.level_number, leg.exit_price, leg.reason) for leg in result.legs] == [
        (1, 98.7, GridReason.BIAS_ABORT)
    ]


def test_one_plan_never_creates_more_than_three_fills():
    result = simulate_grid(
        plan(),
        ticks((1, 96.8, 96.9), (2, 96.8, 96.9), (3, 99.0, 99.2)),
        no_abort_bars(),
        CostStress(),
    )

    assert result is not None
    assert [leg.level_number for leg in result.legs] == [1, 2, 3]
    assert result.maximum_levels_filled == 3
