import json
from dataclasses import FrozenInstanceError, replace
from datetime import date

import pandas as pd
import pytest

from gscalp.pullback_config import PullbackCandidate, load_pullback_config
from gscalp.pullback_models import (
    BiasDecision,
    ExitReason,
    PullbackReason,
    PullbackSetup,
    TradeDirection,
)


def valid_payload():
    return {
        "version": "pullback-v1.1",
        "terminal_path": r"C:\Program Files\FBS MetaTrader 5\terminal64.exe",
        "required_server": "FBS-Demo",
        "symbol": "XAUUSD",
        "mode": "shadow",
        "required_margin_mode": 2,
        "candidate_sessions_ny": [
            "08:45-09:45",
            "09:30-10:30",
            "10:00-11:00",
        ],
        "trigger_timeframes": ["M1", "M5"],
        "target_r_candidates": [0.35, 0.50, 0.65],
        "abort_timeframes": ["M1", "M5"],
        "bias_ema_period": 20,
        "bias_slope_bars": 3,
        "trigger_ema_period": 9,
        "atr_period": 14,
        "trigger_body_fraction_min": 0.35,
        "pullback_atr_min": 0.25,
        "pullback_atr_max": 1.10,
        "stop_buffer_atr": 0.10,
        "stop_buffer_spread_multiple": 2.0,
        "stop_atr_min": 0.35,
        "stop_atr_max": 1.50,
        "reference_spread_minutes": 30,
        "current_spread_multiple": 2.0,
        "nominal_risk_fraction": 0.0020,
        "absolute_risk_fraction": 0.0025,
        "risk_reserve_fraction": 0.0005,
        "max_margin_fraction": 0.10,
        "entry_cutoff_minute": 45,
        "session_minutes": 60,
        "max_trade_attempts_per_session": 1,
        "development_end": "2023-11-29",
        "validation_end": "2025-03-24",
        "test_end": "2026-07-15",
    }


def write_config(tmp_path, payload=None):
    path = tmp_path / "pullback-v1.1.json"
    path.write_text(json.dumps(payload or valid_payload()), encoding="utf-8")
    return path


def test_config_is_frozen_demo_scoped_and_enumerates_exact_candidates(tmp_path):
    config = load_pullback_config(write_config(tmp_path))

    assert config.version == "pullback-v1.1"
    assert config.required_server == "FBS-Demo"
    assert config.symbol == "XAUUSD"
    assert config.mode == "shadow"
    assert config.development_end == date(2023, 11, 29)
    assert len(config.candidates()) == 36
    assert len({item.candidate_id for item in config.candidates()}) == 36
    assert config.candidates()[0].candidate_id == "0845_0945__M1__0.35R__abort_M1"
    assert config.candidates()[-1].candidate_id == "1000_1100__M5__0.65R__abort_M5"
    with pytest.raises(FrozenInstanceError):
        config.mode = "demo"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", "pullback-v1.2"),
        ("terminal_path", r"C:\Other\terminal64.exe"),
        ("required_server", "Other-Demo"),
        ("symbol", "GOLD"),
        ("mode", "demo"),
        ("required_margin_mode", 0),
        ("candidate_sessions_ny", ["08:45-09:45"]),
        ("trigger_timeframes", ["M1"]),
        ("target_r_candidates", [0.50]),
        ("abort_timeframes", ["M5"]),
        ("nominal_risk_fraction", 0.0021),
        ("absolute_risk_fraction", 0.0026),
        ("risk_reserve_fraction", 0.0004),
        ("max_margin_fraction", 0.11),
        ("entry_cutoff_minute", 46),
        ("session_minutes", 59),
        ("max_trade_attempts_per_session", 2),
        ("development_end", "2023-11-30"),
        ("validation_end", "2025-03-25"),
        ("test_end", "2026-07-16"),
    ],
)
def test_config_rejects_safety_or_search_space_drift(tmp_path, field, value):
    payload = valid_payload()
    payload[field] = value

    with pytest.raises(ValueError):
        load_pullback_config(write_config(tmp_path, payload))


def test_config_rejects_unknown_and_missing_keys(tmp_path):
    unknown = valid_payload() | {"surprise": True}
    missing = valid_payload()
    missing.pop("atr_period")

    with pytest.raises(ValueError, match="unknown configuration keys: surprise"):
        load_pullback_config(write_config(tmp_path, unknown))
    with pytest.raises(ValueError, match="missing configuration keys: atr_period"):
        load_pullback_config(write_config(tmp_path, missing))


def test_setup_models_reject_naive_timestamps_and_invalid_prices():
    candidate = PullbackCandidate("08:45-09:45", "M1", 0.35, "M5")
    aware = pd.Timestamp("2026-07-15 12:45:00+00:00")
    bias = BiasDecision(
        TradeDirection.LONG,
        PullbackReason.SETUP_ARMED,
        aware,
        2400.0,
        2399.0,
        2398.0,
        2400.0,
        2399.0,
        2398.0,
    )
    setup = PullbackSetup(
        candidate,
        TradeDirection.LONG,
        2.0,
        2398.0,
        2402.0,
        aware + pd.Timedelta(minutes=5),
        aware + pd.Timedelta(minutes=5),
        2400.0,
        2397.5,
        0.20,
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        replace(bias, session_start=pd.Timestamp("2026-07-15 12:45:00"))
    with pytest.raises(ValueError, match="positive"):
        replace(setup, atr=0.0)
    with pytest.raises(ValueError, match="below pullback swing"):
        replace(setup, stop=2399.0)


def test_exit_reasons_distinguish_no_entry_from_trade_closes():
    assert ExitReason.SPREAD_ABORT_BEFORE_ENTRY.value == "spread_abort_before_entry"
    assert ExitReason.ENTRY_TIMEOUT.value == "entry_timeout"
    assert ExitReason.TARGET_CLOSED.value == "target_closed"
