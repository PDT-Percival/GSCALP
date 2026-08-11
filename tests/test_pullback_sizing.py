from dataclasses import replace
from types import SimpleNamespace

import pandas as pd
import pytest

from gscalp.mt5_read import SymbolSpec
from gscalp.pullback_config import PullbackCandidate, load_pullback_config
from gscalp.pullback_models import (
    PullbackReason,
    PullbackSetup,
    TradeDirection,
)
from gscalp.pullback_sizing import floor_volume, size_trade


class FixedCalculator:
    def __init__(self, loss=100.0, margin=50.0):
        self.loss = loss
        self.margin = margin

    def loss_for_one_lot(self, direction, entry, stop):
        return self.loss

    def margin_for_volume(self, direction, volume, entry):
        return self.margin


@pytest.fixture
def config():
    return load_pullback_config("config/pullback-v1.1.json")


@pytest.fixture
def setup():
    timestamp = pd.Timestamp("2026-07-15 13:56:00+00:00")
    return PullbackSetup(
        PullbackCandidate("09:30-10:30", "M1", 0.35, "M5"),
        TradeDirection.LONG,
        2.0,
        99.8,
        101.0,
        timestamp,
        timestamp,
        100.7,
        99.4,
        0.20,
    )


@pytest.fixture
def symbol():
    return SymbolSpec(
        "XAUUSD", 2, 0.01, 0.01, 1.0, 100.0, 0.01, 0.01, 10, 0,
        volume_max=100.0,
    )


def plan(setup, config, symbol, calculator=None, **changes):
    arguments = {
        "setup": setup,
        "executable_entry": 100.7,
        "development_spread_ceiling": 0.30,
        "starting_day_equity": 10_000.0,
        "free_margin": 10_000.0,
        "symbol": symbol,
        "calculator": calculator or FixedCalculator(),
        "config": config,
        "trade_id": "trade-1",
    }
    arguments.update(changes)
    return size_trade(**arguments)


def test_floor_volume_never_rounds_up():
    assert floor_volume(0.199999, 0.01) == pytest.approx(0.19)


def test_single_trade_uses_nominal_risk_plus_fixed_reserve(setup, config, symbol):
    decision = plan(setup, config, symbol)

    assert decision.reason is PullbackReason.TRADE_PLANNED
    assert decision.plan.volume == pytest.approx(0.20)
    assert decision.plan.projected_loss == pytest.approx(25.0)
    assert decision.plan.projected_margin == pytest.approx(50.0)
    assert decision.plan.target == pytest.approx(101.15)
    assert decision.plan.setup.stop == pytest.approx(99.4)


@pytest.mark.parametrize(
    ("entry", "reason"),
    [
        (100.0, PullbackReason.STOP_TOO_CLOSE),
        (102.5, PullbackReason.STOP_TOO_FAR),
    ],
)
def test_rejects_stop_distance_outside_atr_bounds(
    setup, config, symbol, entry, reason
):
    decision = plan(setup, config, symbol, executable_entry=entry)

    assert decision.plan is None
    assert decision.reason is reason


def test_rejects_stop_inside_broker_minimum(setup, config, symbol):
    decision = plan(
        setup,
        config,
        replace(symbol, stops_level=200),
    )

    assert decision.plan is None
    assert decision.reason is PullbackReason.BROKER_STOP_INVALID


def test_rejects_volume_below_broker_minimum(setup, config, symbol):
    decision = plan(
        setup,
        config,
        replace(symbol, volume_min=0.30),
    )

    assert decision.plan is None
    assert decision.reason is PullbackReason.VOLUME_BELOW_MINIMUM


def test_rejects_volume_above_broker_maximum(setup, config, symbol):
    decision = plan(
        setup,
        config,
        replace(symbol, volume_max=0.10),
    )

    assert decision.plan is None
    assert decision.reason is PullbackReason.RISK_EXCEEDED


@pytest.mark.parametrize("loss", [None, 0.0, float("nan")])
def test_rejects_unavailable_contract_loss(setup, config, symbol, loss):
    decision = plan(setup, config, symbol, FixedCalculator(loss=loss))

    assert decision.plan is None
    assert decision.reason is PullbackReason.RISK_EXCEEDED


def test_rejects_projected_loss_above_absolute_cap(setup, config, symbol):
    unsafe = SimpleNamespace(**{
        field: getattr(config, field)
        for field in (
            "nominal_risk_fraction",
            "absolute_risk_fraction",
            "risk_reserve_fraction",
            "max_margin_fraction",
            "stop_atr_min",
            "stop_atr_max",
        )
    })
    unsafe.nominal_risk_fraction = 0.0030
    decision = plan(setup, unsafe, symbol)

    assert decision.plan is None
    assert decision.reason is PullbackReason.RISK_EXCEEDED


@pytest.mark.parametrize("margin", [None, -1.0, float("nan"), 1000.01])
def test_rejects_invalid_or_excessive_margin(setup, config, symbol, margin):
    decision = plan(setup, config, symbol, FixedCalculator(margin=margin))

    assert decision.plan is None
    assert decision.reason is PullbackReason.MARGIN_EXCEEDED


def test_short_target_and_rounding_are_symmetric(setup, config, symbol):
    short = replace(
        setup,
        direction=TradeDirection.SHORT,
        pullback_swing=100.2,
        pre_pullback_swing=99.0,
        trigger_close=99.3,
        stop=100.6,
    )

    decision = plan(short, config, symbol, executable_entry=99.3)

    assert decision.reason is PullbackReason.TRADE_PLANNED
    assert decision.plan.target == pytest.approx(98.85)
    assert decision.plan.setup.stop == pytest.approx(100.6)
