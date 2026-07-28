import json
from pathlib import Path

import pytest

from gscalp.config import StrategyConfig, load_config


def valid_payload() -> dict:
    return {
        "terminal_path": r"C:\Program Files\FBS MetaTrader 5\terminal64.exe",
        "required_server": "FBS-Demo",
        "symbol": "XAUUSD",
        "mode": "shadow",
        "risk_per_trade": 0.0025,
        "daily_loss_limit": 0.005,
        "max_trades": 2,
        "candidate_sessions_ny": ["08:45-09:45", "09:30-10:30"],
        "ema_period": 20,
        "atr_period": 14,
        "sweep_atr_min": 0.15,
        "sweep_atr_max": 0.50,
        "displacement_atr_min": 0.50,
        "max_stop_atr": 0.80,
        "minimum_room_r": 1.20,
        "target_r": 1.40,
    }


def write_payload(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "strategy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_valid_configuration_is_immutable_and_demo_scoped(tmp_path: Path):
    config = load_config(write_payload(tmp_path, valid_payload()))

    assert isinstance(config, StrategyConfig)
    assert config.mode == "shadow"
    assert config.required_server == "FBS-Demo"
    assert config.risk_per_trade == 0.0025
    assert config.allow_same_bar_reclaim is False
    with pytest.raises((AttributeError, TypeError)):
        config.mode = "demo"


@pytest.mark.parametrize("mode", ["live", "production", "paper"])
def test_prohibited_mode_is_rejected(tmp_path: Path, mode: str):
    payload = valid_payload()
    payload["mode"] = mode

    with pytest.raises(ValueError, match="mode must be one of"):
        load_config(write_payload(tmp_path, payload))


def test_non_demo_server_is_rejected(tmp_path: Path):
    payload = valid_payload()
    payload["required_server"] = "FBS-Real"

    with pytest.raises(ValueError, match="FBS-Demo"):
        load_config(write_payload(tmp_path, payload))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("risk_per_trade", 0.0026, "risk_per_trade"),
        ("daily_loss_limit", 0.0051, "daily_loss_limit"),
        ("max_trades", 3, "max_trades"),
    ],
)
def test_risk_caps_cannot_be_exceeded(
    tmp_path: Path, field: str, value: float, message: str
):
    payload = valid_payload()
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        load_config(write_payload(tmp_path, payload))


def test_unknown_configuration_keys_are_rejected(tmp_path: Path):
    payload = valid_payload()
    payload["secret_override"] = True

    with pytest.raises(ValueError, match="unknown configuration keys"):
        load_config(write_payload(tmp_path, payload))


def test_session_must_be_exactly_sixty_minutes(tmp_path: Path):
    payload = valid_payload()
    payload["candidate_sessions_ny"] = ["09:30-10:15"]

    with pytest.raises(ValueError, match="60 minutes"):
        load_config(write_payload(tmp_path, payload))
