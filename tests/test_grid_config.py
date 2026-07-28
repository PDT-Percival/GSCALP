import json
from dataclasses import FrozenInstanceError

import pytest
import pandas as pd

from gscalp.grid_config import load_grid_config
from gscalp.grid_models import (
    BiasDecision,
    BiasDirection,
    GridGeometry,
    GridLevelPlan,
    GridPlan,
    GridReason,
)


def valid_grid_payload():
    return {
        "version": "grid-v1.0",
        "terminal_path": r"C:\Program Files\FBS MetaTrader 5\terminal64.exe",
        "required_server": "FBS-Demo",
        "symbol": "XAUUSD",
        "mode": "shadow",
        "required_margin_mode": 2,
        "candidate_sessions_ny": ["08:45-09:45", "09:30-10:30"],
        "ema_period": 20,
        "atr_period": 14,
        "pivot_left": 2,
        "pivot_right": 2,
        "pivot_lookback": 12,
        "stop_buffer_atr": 0.10,
        "stop_buffer_spread_multiple": 2.0,
        "invalidation_atr_min": 0.60,
        "invalidation_atr_max": 1.50,
        "level_fractions": [0.25, 0.50, 0.75],
        "profit_distance_fraction": 0.25,
        "reference_spread_multiple": 4.0,
        "current_spread_multiple": 2.0,
        "profit_distance_max_fraction": 0.40,
        "nominal_risk_fraction": 0.0020,
        "absolute_risk_fraction": 0.0025,
        "max_margin_fraction": 0.10,
        "pending_expiry_minute": 45,
        "session_minutes": 60,
        "max_baskets_per_session": 1,
        "development_end": "2023-11-29",
        "validation_end": "2025-03-24",
        "test_end": "2026-07-15",
    }


def test_grid_config_is_frozen_and_exactly_demo_scoped(tmp_path):
    path = tmp_path / "grid.json"
    path.write_text(json.dumps(valid_grid_payload()))
    config = load_grid_config(path)
    assert config.level_fractions == (0.25, 0.50, 0.75)
    assert config.nominal_risk_fraction == 0.002
    assert config.absolute_risk_fraction == 0.0025
    with pytest.raises(FrozenInstanceError):
        config.mode = "demo"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("required_server", "FBS-Real"),
        ("nominal_risk_fraction", 0.0021),
        ("absolute_risk_fraction", 0.0026),
        ("max_baskets_per_session", 2),
        ("level_fractions", [0.25, 0.50, 0.80]),
        ("pivot_left", 1),
        ("pivot_right", 1),
        ("pending_expiry_minute", 46),
        ("session_minutes", 59),
    ],
)
def test_grid_config_rejects_safety_drift(tmp_path, field, value):
    payload = valid_grid_payload()
    payload[field] = value
    path = tmp_path / "grid.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        load_grid_config(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("development_end", "2023-11-28"),
        ("validation_end", "2025-03-23"),
        ("test_end", "2026-07-14"),
    ],
)
def test_grid_config_rejects_partition_date_drift(tmp_path, field, value):
    payload = valid_grid_payload()
    payload[field] = value
    path = tmp_path / "grid.json"
    path.write_text(json.dumps(payload))

    with pytest.raises(ValueError):
        load_grid_config(path)


def geometry(*, level_prices=(100.0, 101.0, 102.0)):
    return GridGeometry(
        direction=BiasDirection.LONG,
        session_start=pd.Timestamp("2026-07-15 12:45:00+00:00"),
        session_end=pd.Timestamp("2026-07-15 13:45:00+00:00"),
        anchor=100.0,
        stop=99.0,
        atr=1.0,
        reference_spread=0.2,
        current_spread=0.1,
        profit_distance=0.5,
        level_prices=level_prices,
    )


def test_grid_models_reject_naive_timestamps():
    with pytest.raises(ValueError):
        BiasDecision(
            direction=BiasDirection.LONG,
            reason=GridReason.BIAS_LOCKED,
            as_of=pd.Timestamp("2026-07-15 12:45:00"),
            ema_now=100.0,
            ema_three_bars_ago=99.0,
        )


@pytest.mark.parametrize("level_prices", [(100.0, 101.0), (100.0, 102.0, 101.0)])
def test_grid_models_require_three_monotonically_ordered_levels(level_prices):
    with pytest.raises(ValueError):
        geometry(level_prices=level_prices)


def test_grid_plan_requires_equal_level_volumes():
    levels = (
        GridLevelPlan(1, 100.0, 0.01, 99.0, 101.0),
        GridLevelPlan(2, 101.0, 0.02, 99.0, 102.0),
        GridLevelPlan(3, 102.0, 0.01, 99.0, 103.0),
    )

    with pytest.raises(ValueError):
        GridPlan("basket-1", geometry=geometry(), levels=levels, projected_loss_cash=1.0, projected_margin_cash=1.0)
