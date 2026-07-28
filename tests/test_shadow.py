import json

import pandas as pd
import pytest

from gscalp.models import Direction, ReasonCode, SignalDecision
from gscalp.shadow import ShadowLogger, ShadowRecord


class TradingTrap:
    def order_send(self, *args, **kwargs):
        raise AssertionError("shadow mode attempted to trade")


def record(bar_time="2026-07-17 13:00:00+00:00") -> ShadowRecord:
    return ShadowRecord(
        terminal_path=r"C:\Program Files\FBS MetaTrader 5\terminal64.exe",
        server="FBS-Demo",
        symbol="XAUUSD",
        bar_time=pd.Timestamp(bar_time),
        new_york_time=pd.Timestamp(bar_time).tz_convert("America/New_York"),
        bar={"open": 3300.0, "high": 3302.0, "low": 3299.0, "close": 3301.0},
        indicators={"atr": 3.0, "ema20": 3298.0},
        levels={"asian_high": 3305.0},
        state="evaluated",
        spread=0.25,
        decision=SignalDecision(
            eligible=False,
            direction=Direction.LONG,
            signal_time=pd.Timestamp(bar_time),
            entry=None,
            stop=None,
            target=None,
            reasons=(ReasonCode.NO_LEVEL_SWEEP,),
        ),
    )


def test_shadow_logger_never_accesses_order_send(tmp_path):
    logger = ShadowLogger(tmp_path / "signals.jsonl", TradingTrap())

    assert logger.append(
        record(), observed_at=pd.Timestamp("2026-07-17 13:05:00+00:00")
    )
    assert len((tmp_path / "signals.jsonl").read_text().splitlines()) == 1


def test_shadow_logger_suppresses_duplicates_after_restart(tmp_path):
    path = tmp_path / "signals.jsonl"
    first = ShadowLogger(path, TradingTrap())
    assert first.append(record(), observed_at=pd.Timestamp("2026-07-17 13:05:01+00:00"))

    restarted = ShadowLogger(path, TradingTrap())
    assert not restarted.append(
        record(), observed_at=pd.Timestamp("2026-07-17 13:06:00+00:00")
    )
    payload = json.loads(path.read_text().splitlines()[0])
    assert payload["reasons"] == ["no_level_sweep"]
    assert payload["bar_time"] == "2026-07-17T13:00:00+00:00"


def test_shadow_logger_rejects_incomplete_bar(tmp_path):
    logger = ShadowLogger(tmp_path / "signals.jsonl", TradingTrap())

    with pytest.raises(ValueError, match="completed M5"):
        logger.append(
            record(), observed_at=pd.Timestamp("2026-07-17 13:04:59+00:00")
        )
