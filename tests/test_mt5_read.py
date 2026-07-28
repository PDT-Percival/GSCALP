from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from gscalp.mt5_read import MT5ReadGateway


class FakeMT5:
    COPY_TICKS_ALL = 3

    def __init__(self, server: str = "FBS-Demo") -> None:
        self.server = server
        self.initialized_path = None
        self.shutdown_calls = 0
        self.selected = []

    def initialize(self, *, path: str) -> bool:
        self.initialized_path = path
        return True

    def last_error(self):
        return (0, "ok")

    def terminal_info(self):
        return SimpleNamespace(connected=True, path="C:/Program Files/FBS MetaTrader 5")

    def account_info(self):
        return SimpleNamespace(server=self.server, trade_mode=0, currency="USD")

    def symbol_select(self, symbol: str, enabled: bool) -> bool:
        self.selected.append((symbol, enabled))
        return True

    def symbol_info(self, symbol: str):
        return SimpleNamespace(
            name=symbol,
            digits=2,
            point=0.01,
            trade_tick_size=0.01,
            trade_tick_value=1.0,
            trade_contract_size=100.0,
            volume_min=0.01,
            volume_step=0.01,
            trade_stops_level=0,
            filling_mode=1,
        )

    def copy_rates_range(self, symbol, timeframe, start, end):
        return [
            {
                "time": 1_700_000_000,
                "open": 2000.0,
                "high": 2001.0,
                "low": 1999.0,
                "close": 2000.5,
                "tick_volume": 10,
                "spread": 30,
                "real_volume": 0,
            }
        ]

    def copy_ticks_range(self, symbol, start, end, flags):
        return [{"time_msc": 1_700_000_000_123, "bid": 2000.0, "ask": 2000.3}]

    def history_deals_get(self, start, end, *, group):
        return [SimpleNamespace(ticket=1, time=1_700_000_000, symbol="XAUUSD")]

    def shutdown(self):
        self.shutdown_calls += 1


def test_connect_verifies_demo_server_and_captures_symbol_spec():
    fake = FakeMT5()
    gateway = MT5ReadGateway(
        fake,
        terminal_path=r"C:\Program Files\FBS MetaTrader 5\terminal64.exe",
        required_server="FBS-Demo",
        symbol="XAUUSD",
    )

    snapshot = gateway.connect()

    assert fake.initialized_path.endswith("terminal64.exe")
    assert fake.selected == [("XAUUSD", True)]
    assert snapshot.server == "FBS-Demo"
    assert snapshot.symbol.contract_size == 100.0
    assert snapshot.symbol.volume_step == 0.01


def test_connect_rejects_any_non_demo_server_and_shuts_down():
    fake = FakeMT5(server="FBS-Real")
    gateway = MT5ReadGateway(fake, "terminal64.exe", "FBS-Demo", "XAUUSD")

    with pytest.raises(RuntimeError, match="unexpected MT5 server"):
        gateway.connect()

    assert fake.shutdown_calls == 1


def test_rates_ticks_and_deals_are_returned_with_utc_timestamps():
    fake = FakeMT5()
    gateway = MT5ReadGateway(fake, "terminal64.exe", "FBS-Demo", "XAUUSD")
    gateway.connect()
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    end = datetime(2023, 1, 2, tzinfo=timezone.utc)

    rates = gateway.get_rates(5, start, end)
    ticks = gateway.get_ticks(start, end)
    deals = gateway.get_deals(start, end)

    assert isinstance(rates, pd.DataFrame)
    assert str(rates["time"].dt.tz) == "UTC"
    assert str(ticks["time"].dt.tz) == "UTC"
    assert str(deals["time"].dt.tz) == "UTC"
    assert list(ticks[["bid", "ask"]].iloc[0]) == [2000.0, 2000.3]


def test_empty_history_has_stable_columns():
    fake = FakeMT5()
    fake.history_deals_get = lambda *args, **kwargs: ()
    gateway = MT5ReadGateway(fake, "terminal64.exe", "FBS-Demo", "XAUUSD")
    gateway.connect()

    deals = gateway.get_deals(
        datetime(2023, 1, 1, tzinfo=timezone.utc),
        datetime(2023, 1, 2, tzinfo=timezone.utc),
    )

    assert deals.empty
    assert list(deals.columns) == ["ticket", "time", "symbol"]


def test_context_manager_always_shuts_down():
    fake = FakeMT5()

    with MT5ReadGateway(fake, "terminal64.exe", "FBS-Demo", "XAUUSD"):
        pass

    assert fake.shutdown_calls == 1

