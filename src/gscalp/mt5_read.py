from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd


@dataclass(frozen=True, slots=True)
class SymbolSpec:
    name: str
    digits: int
    point: float
    tick_size: float
    tick_value: float
    contract_size: float
    volume_min: float
    volume_step: float
    stops_level: int
    filling_mode: int
    volume_max: float = math.inf


@dataclass(frozen=True, slots=True)
class TerminalSnapshot:
    terminal_path: str
    server: str
    account_currency: str
    account_trade_mode: int
    symbol: SymbolSpec


class MT5ReadGateway:
    """Read-only adapter around the MetaTrader5 Python module.

    This class intentionally has no order-checking or order-submission method.
    """

    DEAL_COLUMNS = ["ticket", "time", "symbol"]

    def __init__(
        self,
        mt5_module: Any,
        terminal_path: str,
        required_server: str,
        symbol: str,
    ) -> None:
        self._mt5 = mt5_module
        self.terminal_path = terminal_path
        self.required_server = required_server
        self.symbol = symbol
        self._connected = False

    def connect(self) -> TerminalSnapshot:
        if not self._mt5.initialize(path=self.terminal_path):
            raise RuntimeError(f"MT5 initialize failed: {self._mt5.last_error()}")
        try:
            terminal = self._mt5.terminal_info()
            if terminal is None or not terminal.connected:
                raise RuntimeError("MT5 terminal is not connected")
            account = self._mt5.account_info()
            if account is None:
                raise RuntimeError("MT5 account information is unavailable")
            if account.server != self.required_server:
                raise RuntimeError(
                    f"unexpected MT5 server: {account.server}; "
                    f"required {self.required_server}"
                )
            if not self._mt5.symbol_select(self.symbol, True):
                raise RuntimeError(f"unable to select symbol {self.symbol}")
            raw_spec = self._mt5.symbol_info(self.symbol)
            if raw_spec is None:
                raise RuntimeError(f"symbol specification unavailable: {self.symbol}")
            spec = SymbolSpec(
                name=raw_spec.name,
                digits=int(raw_spec.digits),
                point=float(raw_spec.point),
                tick_size=float(raw_spec.trade_tick_size),
                tick_value=float(raw_spec.trade_tick_value),
                contract_size=float(raw_spec.trade_contract_size),
                volume_min=float(raw_spec.volume_min),
                volume_step=float(raw_spec.volume_step),
                stops_level=int(raw_spec.trade_stops_level),
                filling_mode=int(raw_spec.filling_mode),
                volume_max=float(getattr(raw_spec, "volume_max", math.inf)),
            )
            self._connected = True
            return TerminalSnapshot(
                terminal_path=str(terminal.path),
                server=str(account.server),
                account_currency=str(account.currency),
                account_trade_mode=int(account.trade_mode),
                symbol=spec,
            )
        except Exception:
            self.close()
            raise

    def _require_connection(self) -> None:
        if not self._connected:
            raise RuntimeError("MT5 gateway is not connected")

    @staticmethod
    def _frame(records: Any) -> pd.DataFrame:
        if records is None:
            raise RuntimeError("MT5 returned no result")
        rows = list(records)
        if not rows:
            return pd.DataFrame()
        first = rows[0]
        if hasattr(first, "_asdict"):
            return pd.DataFrame([row._asdict() for row in rows])
        if hasattr(first, "__dict__"):
            return pd.DataFrame([vars(row) for row in rows])
        return pd.DataFrame(rows)

    def get_rates(
        self, timeframe: int, start_utc: datetime, end_utc: datetime
    ) -> pd.DataFrame:
        self._require_connection()
        frame = self._frame(
            self._mt5.copy_rates_range(
                self.symbol, timeframe, start_utc, end_utc
            )
        )
        if "time" in frame:
            frame["time"] = pd.to_datetime(frame["time"], unit="s", utc=True)
        return frame

    def get_ticks(self, start_utc: datetime, end_utc: datetime) -> pd.DataFrame:
        self._require_connection()
        frame = self._frame(
            self._mt5.copy_ticks_range(
                self.symbol, start_utc, end_utc, self._mt5.COPY_TICKS_ALL
            )
        )
        if "time_msc" in frame:
            frame["time"] = pd.to_datetime(frame["time_msc"], unit="ms", utc=True)
        return frame

    def get_deals(self, start_utc: datetime, end_utc: datetime) -> pd.DataFrame:
        self._require_connection()
        records = self._mt5.history_deals_get(
            start_utc, end_utc, group=f"*{self.symbol}*"
        )
        if records is None:
            raise RuntimeError(f"MT5 deal history failed: {self._mt5.last_error()}")
        frame = self._frame(records)
        if frame.empty:
            return pd.DataFrame(columns=self.DEAL_COLUMNS)
        if "time" in frame:
            frame["time"] = pd.to_datetime(frame["time"], unit="s", utc=True)
        return frame

    def close(self) -> None:
        self._mt5.shutdown()
        self._connected = False

    def __enter__(self) -> "MT5ReadGateway":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

