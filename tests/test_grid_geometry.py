from dataclasses import FrozenInstanceError
from pathlib import Path

import pandas as pd
import pytest

from gscalp.grid_config import GridConfig, load_grid_config
from gscalp.grid_geometry import basket_target, build_grid_geometry
from gscalp.grid_models import BiasDecision, BiasDirection, GeometryDecision, GridReason
from gscalp.mt5_read import SymbolSpec


@pytest.fixture
def grid_config() -> GridConfig:
    return load_grid_config(Path(__file__).parents[1] / "config" / "grid-v1.0.json")


@pytest.fixture
def symbol() -> SymbolSpec:
    return SymbolSpec("XAUUSD", 2, 0.01, 0.01, 1.0, 100.0, 0.01, 0.01, 10, 0)


@pytest.fixture
def session_start() -> pd.Timestamp:
    return pd.Timestamp("2026-07-15 12:45:00+00:00")


def bias(direction: BiasDirection | None, session_start: pd.Timestamp) -> BiasDecision:
    return BiasDecision(direction, GridReason.BIAS_LOCKED, session_start, 101.0, 100.0)


def decision(
    *,
    direction: BiasDirection = BiasDirection.LONG,
    anchor_bid: float = 99.70,
    anchor_ask: float = 100.00,
    atr: float | None = 10.0,
    reference_spread: float | None = 0.25,
    current_spread: float = 0.30,
    spread_ceiling: float = 0.50,
    pivot_price: float | None = 91.0,
    symbol: SymbolSpec,
    grid_config: GridConfig,
    session_start: pd.Timestamp,
):
    pivot = None if pivot_price is None else (session_start - pd.Timedelta(minutes=5), pivot_price)
    return build_grid_geometry(
        bias=bias(direction, session_start),
        session_start=session_start,
        anchor_bid=anchor_bid,
        anchor_ask=anchor_ask,
        atr=atr,
        reference_spread=reference_spread,
        current_spread=current_spread,
        spread_ceiling=spread_ceiling,
        pivot=pivot,
        symbol=symbol,
        config=grid_config,
    )


def test_geometry_decision_is_immutable():
    result = GeometryDecision(None, GridReason.INVALIDATION_TOO_FAR)

    with pytest.raises(FrozenInstanceError):
        result.reason = GridReason.GRID_ARMED


def test_long_geometry_uses_executable_ask_and_hand_derived_levels(
    grid_config, symbol, session_start
):
    result = decision(symbol=symbol, grid_config=grid_config, session_start=session_start)

    assert result.reason is GridReason.GRID_ARMED
    assert result.geometry.level_prices == (97.5, 95.0, 92.5)
    assert result.geometry.profit_distance == 2.5
    assert result.geometry.stop == 90.0


def test_short_geometry_is_symmetric_around_executable_bid(
    grid_config, symbol, session_start
):
    result = decision(
        direction=BiasDirection.SHORT,
        anchor_bid=200.0,
        anchor_ask=200.3,
        pivot_price=209.0,
        symbol=symbol,
        grid_config=grid_config,
        session_start=session_start,
    )

    assert result.reason is GridReason.GRID_ARMED
    assert result.geometry.level_prices == (202.5, 205.0, 207.5)
    assert result.geometry.profit_distance == 2.5
    assert result.geometry.stop == 210.0


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"atr": None}, GridReason.ATR_UNAVAILABLE),
        ({"pivot_price": None}, GridReason.NO_CONFIRMED_PIVOT),
        ({"pivot_price": 96.0}, GridReason.INVALIDATION_TOO_CLOSE),
        ({"pivot_price": 84.0}, GridReason.INVALIDATION_TOO_FAR),
        ({"current_spread": 0.51}, GridReason.SPREAD_TOO_WIDE),
        ({"reference_spread": 1.10, "pivot_price": 92.20}, GridReason.SPREAD_TOO_WIDE),
    ],
)
def test_geometry_returns_stable_reason_for_each_rejection(
    kwargs, reason, grid_config, symbol, session_start
):
    result = decision(
        symbol=symbol, grid_config=grid_config, session_start=session_start, **kwargs
    )

    assert result.geometry is None
    assert result.reason is reason


def test_geometry_rejects_broker_minimum_distance_with_stable_reason(
    grid_config, session_start
):
    restrictive_symbol = SymbolSpec(
        "XAUUSD", 2, 0.01, 0.01, 1.0, 100.0, 0.01, 0.01, 300, 0
    )

    result = decision(
        symbol=restrictive_symbol, grid_config=grid_config, session_start=session_start
    )

    assert result.geometry is None
    assert result.reason is GridReason.BROKER_DISTANCE_INVALID


@pytest.mark.parametrize(
    ("direction", "fills", "expected"),
    [
        (BiasDirection.LONG, ((97.5, 1.0), (95.0, 2.0)), 98.33),
        (BiasDirection.SHORT, ((202.5, 1.0), (205.0, 2.0)), 201.67),
    ],
)
def test_basket_target_rounds_against_favorable_research_bias(direction, fills, expected):
    assert basket_target(direction, fills, 2.5, 0.01) == expected
