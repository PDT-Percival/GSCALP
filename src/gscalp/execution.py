from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import pandas as pd

from .config import StrategyConfig
from .models import Direction, SignalDecision
from .mt5_read import SymbolSpec


class ExecutionCode(str, Enum):
    SUBMITTED = "submitted"
    WRONG_SERVER = "wrong_server"
    MODE_BLOCKED = "mode_blocked"
    NEWS_DATA_MISSING = "news_data_missing"
    NEWS_BLACKOUT = "news_blackout"
    DAILY_RISK_LIMIT = "daily_risk_limit"
    TRADE_LIMIT = "trade_limit"
    SPREAD_TOO_WIDE = "spread_too_wide"
    SESSION_CLOSED = "session_closed"
    INVALID_SIGNAL = "invalid_signal"
    POSITION_EXISTS = "position_exists"
    VOLUME_INVALID = "volume_invalid"
    SIZING_FAILED = "sizing_failed"
    PREFLIGHT_FAILED = "preflight_failed"
    SUBMISSION_FAILED = "submission_failed"


@dataclass(frozen=True, slots=True)
class AccountState:
    server: str
    equity: float
    starting_day_equity: float


@dataclass(frozen=True, slots=True)
class SessionState:
    now: pd.Timestamp
    session_start: pd.Timestamp
    session_end: pd.Timestamp
    realized_loss_cash: float
    open_risk_cash: float
    trade_count: int
    spread: float
    max_spread: float
    existing_symbol_positions: int

    def __post_init__(self) -> None:
        if any(
            item.tzinfo is None
            for item in (self.now, self.session_start, self.session_end)
        ):
            raise ValueError("execution timestamps must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    accepted: bool
    code: ExecutionCode
    request: dict[str, Any] | None = None
    raw_result: Any | None = None


class DemoExecutor:
    """The sole demo-only owner of MT5 order checking and submission."""

    MAGIC = 26071701

    def __init__(
        self,
        mt5_module: Any,
        config: StrategyConfig,
        news_path: Path | str,
        *,
        journal_path: Path | str,
    ) -> None:
        self._mt5 = mt5_module
        self.config = config
        self.news_path = Path(news_path)
        self.journal_path = Path(journal_path)

    def _journal(self, payload: dict[str, Any]) -> None:
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with self.journal_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str))
            stream.write("\n")
            stream.flush()

    @staticmethod
    def _raw_payload(value: Any) -> Any:
        if value is None:
            return None
        if hasattr(value, "_asdict"):
            return value._asdict()
        if hasattr(value, "__dict__"):
            return vars(value)
        return str(value)

    @staticmethod
    def _reject(code: ExecutionCode) -> ExecutionResult:
        return ExecutionResult(False, code)

    def _news_gate(self, now: pd.Timestamp) -> ExecutionCode | None:
        if not self.news_path.exists():
            return ExecutionCode.NEWS_DATA_MISSING
        try:
            with self.news_path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
        except (OSError, csv.Error):
            return ExecutionCode.NEWS_DATA_MISSING
        current_rows: list[tuple[pd.Timestamp, pd.Timestamp, dict[str, str]]] = []
        for row in rows:
            try:
                start = pd.Timestamp(row["event_start_utc"])
                end = pd.Timestamp(row["event_end_utc"])
            except (KeyError, ValueError, TypeError):
                continue
            if start.tzinfo is None or end.tzinfo is None:
                continue
            start = start.tz_convert("UTC")
            end = end.tz_convert("UTC")
            if start.date() == now.tz_convert("UTC").date() and row.get("source"):
                current_rows.append((start, end, row))
        if not current_rows:
            return ExecutionCode.NEWS_DATA_MISSING
        for start, end, row in current_rows:
            if (
                start <= now.tz_convert("UTC") < end
                and row.get("currency", "").upper() in {"USD", "ALL"}
                and row.get("impact", "").lower() == "high"
            ):
                return ExecutionCode.NEWS_BLACKOUT
        return None

    def _volume(
        self,
        decision: SignalDecision,
        account: AccountState,
        spec: SymbolSpec,
    ) -> float | None:
        order_type = (
            self._mt5.ORDER_TYPE_BUY
            if decision.direction is Direction.LONG
            else self._mt5.ORDER_TYPE_SELL
        )
        try:
            loss = self._mt5.order_calc_profit(
                order_type,
                spec.name,
                1.0,
                float(decision.entry),
                float(decision.stop),
            )
        except Exception:
            return None
        if loss is None or not math.isfinite(float(loss)) or float(loss) >= 0:
            return None
        cash_cap = account.starting_day_equity * self.config.risk_per_trade
        steps = math.floor((cash_cap / abs(float(loss))) / spec.volume_step + 1e-12)
        volume = round(steps * spec.volume_step, 8)
        if volume < spec.volume_min or volume <= 0:
            return 0.0
        recalculated = self._mt5.order_calc_profit(
            order_type,
            spec.name,
            volume,
            float(decision.entry),
            float(decision.stop),
        )
        if recalculated is None or abs(float(recalculated)) > cash_cap + 1e-8:
            return 0.0
        return volume

    def submit(
        self,
        signal: SignalDecision,
        account: AccountState,
        symbol_spec: SymbolSpec,
        session_state: SessionState,
    ) -> ExecutionResult:
        if account.server != "FBS-Demo" or account.server != self.config.required_server:
            return self._reject(ExecutionCode.WRONG_SERVER)
        if self.config.mode != "demo":
            return self._reject(ExecutionCode.MODE_BLOCKED)
        if not signal.eligible or signal.direction is None or any(
            value is None for value in (signal.entry, signal.stop, signal.target)
        ):
            return self._reject(ExecutionCode.INVALID_SIGNAL)
        if not session_state.session_start <= session_state.now < session_state.session_end:
            return self._reject(ExecutionCode.SESSION_CLOSED)
        if session_state.trade_count >= self.config.max_trades:
            return self._reject(ExecutionCode.TRADE_LIMIT)
        if session_state.existing_symbol_positions:
            return self._reject(ExecutionCode.POSITION_EXISTS)
        if session_state.spread > session_state.max_spread:
            return self._reject(ExecutionCode.SPREAD_TOO_WIDE)
        daily_cap = account.starting_day_equity * self.config.daily_loss_limit
        if session_state.realized_loss_cash + session_state.open_risk_cash >= daily_cap:
            return self._reject(ExecutionCode.DAILY_RISK_LIMIT)
        news_code = self._news_gate(session_state.now)
        if news_code is not None:
            return self._reject(news_code)
        volume = self._volume(signal, account, symbol_spec)
        if volume is None:
            return self._reject(ExecutionCode.SIZING_FAILED)
        if volume < symbol_spec.volume_min:
            return self._reject(ExecutionCode.VOLUME_INVALID)
        order_type = (
            self._mt5.ORDER_TYPE_BUY
            if signal.direction is Direction.LONG
            else self._mt5.ORDER_TYPE_SELL
        )
        proposed_loss = self._mt5.order_calc_profit(
            order_type,
            symbol_spec.name,
            volume,
            float(signal.entry),
            float(signal.stop),
        )
        if proposed_loss is None:
            return self._reject(ExecutionCode.SIZING_FAILED)
        if (
            session_state.realized_loss_cash
            + session_state.open_risk_cash
            + abs(float(proposed_loss))
            > daily_cap + 1e-8
        ):
            return self._reject(ExecutionCode.DAILY_RISK_LIMIT)
        request = {
            "action": self._mt5.TRADE_ACTION_DEAL,
            "symbol": symbol_spec.name,
            "volume": volume,
            "type": order_type,
            "price": float(signal.entry),
            "sl": float(signal.stop),
            "tp": float(signal.target),
            "deviation": 0,
            "magic": self.MAGIC,
            "comment": "GSCALP_v0.1_SWEEP",
            "type_filling": symbol_spec.filling_mode,
        }
        checked = self._mt5.order_check(request)
        if checked is None or getattr(checked, "retcode", None) != 0:
            return ExecutionResult(False, ExecutionCode.PREFLIGHT_FAILED, request, checked)
        self._journal(
            {
                "stage": "request",
                "time": session_state.now.isoformat(),
                "request": request,
                "preflight": self._raw_payload(checked),
            }
        )
        try:
            result = self._mt5.order_send(request)
        except Exception as exc:
            self._journal(
                {
                    "stage": "result",
                    "time": session_state.now.isoformat(),
                    "result": None,
                    "error": repr(exc),
                    "automatic_retry": False,
                }
            )
            return ExecutionResult(False, ExecutionCode.SUBMISSION_FAILED, request, None)
        self._journal(
            {
                "stage": "result",
                "time": session_state.now.isoformat(),
                "result": self._raw_payload(result),
                "automatic_retry": False,
            }
        )
        if result is None or getattr(result, "retcode", None) != self._mt5.TRADE_RETCODE_DONE:
            return ExecutionResult(False, ExecutionCode.SUBMISSION_FAILED, request, result)
        return ExecutionResult(True, ExecutionCode.SUBMITTED, request, result)
