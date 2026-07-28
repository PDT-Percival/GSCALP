import json
from dataclasses import FrozenInstanceError

import pytest

from gscalp.grid_config import load_grid_config


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
