from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from gscalp.grid_config import load_grid_config
from gscalp.grid_models import BiasDirection, GridGeometry, GridReason
from gscalp.grid_sizing import MT5ProfitMarginCalculator, floor_volume, size_grid
from gscalp.mt5_read import SymbolSpec


class FixedCalculator:
    def __init__(self, losses=(100.0, 70.0, 40.0), margin_per_level=100.0):
        self.losses = iter(losses)
        self.margin_per_level = margin_per_level

    def loss_for_one_lot(self, direction, entry, stop):
        return next(self.losses)

    def margin_for_volume(self, direction, volume, entry):
        return self.margin_per_level


@pytest.fixture
def config():
    return load_grid_config(Path(__file__).parents[1] / "config" / "grid-v1.0.json")


@pytest.fixture
def geometry():
    start = pd.Timestamp("2026-07-15 12:45:00+00:00")
    return GridGeometry(
        BiasDirection.LONG, start, start + pd.Timedelta(hours=1), 100.0, 90.0,
        10.0, 0.3, 0.3, 2.5, (97.5, 95.0, 92.5),
    )


@pytest.fixture
def symbol():
    return SymbolSpec("XAUUSD", 2, 0.01, 0.01, 1.0, 100.0, 0.01, 0.01, 10, 0)


def test_floor_volume_never_rounds_up_to_a_broker_step():
    assert floor_volume(0.095238, 0.01) == 0.09


def test_sizes_equal_three_level_basket_within_nominal_plus_reserve(
    geometry, config, symbol
):
    result = size_grid(
        geometry=geometry, starting_day_equity=10_000.0, free_margin=10_000.0,
        symbol=symbol, calculator=FixedCalculator(), config=config, basket_id="basket-1",
    )

    assert result.reason is GridReason.GRID_ARMED
    assert result.plan is not None
    assert tuple(level.volume for level in result.plan.levels) == (0.09, 0.09, 0.09)
    assert result.plan.projected_loss_cash + 5.0 <= 25.0
    assert tuple(level.provisional_target for level in result.plan.levels) == (100.0, 97.49, 95.0)


def test_rejects_a_volume_below_the_broker_minimum(geometry, config, symbol):
    result = size_grid(
        geometry=geometry, starting_day_equity=10_000.0, free_margin=10_000.0,
        symbol=replace(symbol, volume_min=0.10), calculator=FixedCalculator(),
        config=config, basket_id="basket-1",
    )

    assert result.plan is None
    assert result.reason is GridReason.VOLUME_BELOW_MINIMUM


def test_rejects_a_projected_loss_above_the_absolute_cap(geometry, config, symbol):
    unconstrained_nominal = SimpleNamespace(
        nominal_risk_fraction=0.003, absolute_risk_fraction=config.absolute_risk_fraction,
        max_margin_fraction=config.max_margin_fraction,
    )
    result = size_grid(
        geometry=geometry, starting_day_equity=10_000.0, free_margin=10_000.0,
        symbol=symbol, calculator=FixedCalculator(), config=unconstrained_nominal,
        basket_id="basket-1",
    )

    assert result.plan is None
    assert result.reason is GridReason.BASKET_RISK_EXCEEDED


def test_rejects_all_level_margin_above_ten_percent_of_free_margin(geometry, config, symbol):
    result = size_grid(
        geometry=geometry, starting_day_equity=10_000.0, free_margin=10_000.0,
        symbol=symbol, calculator=FixedCalculator(margin_per_level=400.0),
        config=config, basket_id="basket-1",
    )

    assert result.plan is None
    assert result.reason is GridReason.MARGIN_LIMIT_EXCEEDED


@pytest.mark.parametrize("losses", [(0.0, 70.0, 40.0), (None, 70.0, 40.0)])
def test_rejects_nonpositive_or_missing_one_lot_loss(geometry, config, symbol, losses):
    result = size_grid(
        geometry=geometry, starting_day_equity=10_000.0, free_margin=10_000.0,
        symbol=symbol, calculator=FixedCalculator(losses), config=config, basket_id="basket-1",
    )

    assert result.plan is None
    assert result.reason is GridReason.BASKET_RISK_EXCEEDED


def test_mt5_calculator_uses_only_profit_and_margin_calculators():
    class FakeMT5:
        ORDER_TYPE_BUY = 0
        ORDER_TYPE_SELL = 1

        def order_calc_profit(self, order_type, symbol, volume, entry, stop):
            assert (order_type, symbol, volume, entry, stop) == (0, "XAUUSD", 1.0, 100.0, 90.0)
            return -100.0

        def order_calc_margin(self, order_type, symbol, volume, entry):
            assert (order_type, symbol, volume, entry) == (1, "XAUUSD", 0.1, 100.0)
            return 250.0

    calculator = MT5ProfitMarginCalculator(FakeMT5(), "XAUUSD")

    assert calculator.loss_for_one_lot(BiasDirection.LONG, 100.0, 90.0) == -100.0
    assert calculator.margin_for_volume(BiasDirection.SHORT, 0.1, 100.0) == 250.0
