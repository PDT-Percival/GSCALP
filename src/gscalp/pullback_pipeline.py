from __future__ import annotations

import hashlib
import csv
import json
import math
import os
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Mapping, Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

import duckdb
import numpy as np
import pandas as pd

from .grid_news import NewsCode, news_gate
from .mt5_read import SymbolSpec
from .pullback_backtest import CostStress, simulate_trade
from .pullback_bias import evaluate_locked_bias
from .pullback_config import (
    PullbackCandidate,
    PullbackConfig,
    load_pullback_config,
)
from .pullback_metrics import (
    PullbackMetrics,
    bootstrap_expectancy_lower_bound,
    development_gate,
    summarize_trades,
    test_gate,
    validation_gate,
    validation_score,
)
from .pullback_models import PullbackReason, TradeDirection, TradeResult
from .pullback_setup import detect_pullback_setup
from .pullback_sizing import ProfitMarginCalculator, size_trade
from .research import new_york_session_bounds


_PREFIX = "pullback-v1.1"
_DEVELOPMENT_START = date(2020, 1, 2)
_DEFAULT_NEWS_PATH = Path(__file__).resolve().parents[2] / "data" / "news_blackouts.csv"


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    candidate: PullbackCandidate
    partition: str
    base: PullbackMetrics
    spread_stress: PullbackMetrics
    cost_stress: PullbackMetrics
    bootstrap_lower: float
    spread_ceiling: float
    trades: tuple[TradeResult, ...] = ()
    spread_trades: tuple[TradeResult, ...] = ()
    cost_trades: tuple[TradeResult, ...] = ()
    reason_counts: Mapping[str, int] = field(default_factory=dict)
    rejection_rows: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "trades", tuple(self.trades))
        object.__setattr__(self, "spread_trades", tuple(self.spread_trades))
        object.__setattr__(self, "cost_trades", tuple(self.cost_trades))
        object.__setattr__(self, "rejection_rows", tuple(self.rejection_rows))

    @property
    def candidate_id(self) -> str:
        return self.candidate.candidate_id


@dataclass(frozen=True, slots=True)
class PartitionEvaluation:
    partition: str
    candidates: tuple[CandidateEvaluation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))


class PartitionSource(Protocol):
    data_manifest_sha256: str
    news_sha256: str
    news_bypass_used: bool

    def load_development(self) -> PartitionEvaluation: ...

    def load_validation(self, candidate_ids: tuple[str, ...]) -> PartitionEvaluation: ...

    def load_test(self, candidate_id: str) -> PartitionEvaluation: ...


@dataclass(frozen=True, slots=True)
class PullbackResearchSummary:
    version: str
    status: str
    selected_candidate: str | None
    development_accessed: bool
    validation_accessed: bool
    test_accessed: bool
    development_passed: bool
    validation_passed: bool
    historical_gate_passed: bool
    promotion_eligible: bool
    config_sha256: str
    data_manifest_sha256: str
    news_sha256: str

    def to_json_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "value") and isinstance(value.value, str):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    return value


def _atomic_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        frame = pd.DataFrame(rows, columns=list(rows[0]) if rows else columns)
        frame.to_csv(temporary, index=False)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(_json_safe(payload), indent=2, allow_nan=False),
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _metrics_payload(metrics: PullbackMetrics) -> dict[str, Any]:
    return _json_safe(asdict(metrics))


def _trade_row(item: CandidateEvaluation, trade: TradeResult) -> dict[str, Any]:
    return _json_safe(
        {
            "candidate_id": item.candidate_id,
            "partition": item.partition,
            "trade_id": trade.plan.trade_id,
            "local_date": trade.local_date,
            "direction": trade.plan.setup.direction,
            "entry_time": trade.entry_time,
            "entry_price": trade.entry_price,
            "exit_time": trade.exit_time,
            "exit_price": trade.exit_price,
            "exit_reason": trade.reason,
            "volume": trade.plan.volume,
            "pnl_cash": trade.pnl_cash,
            "net_r": trade.net_r,
            "spread_paid": trade.spread_paid,
        }
    )


def _write_artifacts(
    output_dir: Path,
    config: PullbackConfig,
    summary: PullbackResearchSummary,
    evaluations: Mapping[str, tuple[CandidateEvaluation, ...]],
    gates: Mapping[str, Mapping[str, bool]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    all_items = [
        item
        for partition in ("development", "validation", "test")
        for item in evaluations.get(partition, ())
    ]
    for partition in ("development", "validation", "test"):
        rows: list[dict[str, Any]] = []
        for item in evaluations.get(partition, ()):
            row = {
                "candidate_id": item.candidate_id,
                "partition": partition,
                "gate_passed": gates.get(partition, {}).get(item.candidate_id, False),
                "spread_ceiling": item.spread_ceiling,
                "bootstrap_lower": item.bootstrap_lower,
                "selection_score": validation_score(item.spread_stress),
            }
            row.update({f"base_{key}": value for key, value in asdict(item.base).items()})
            row.update(
                {
                    f"spread_{key}": value
                    for key, value in asdict(item.spread_stress).items()
                }
            )
            row.update(
                {
                    f"cost_{key}": value
                    for key, value in asdict(item.cost_stress).items()
                }
            )
            rows.append(_json_safe(row))
        _atomic_csv(
            output_dir / f"{_PREFIX}-{partition}.csv",
            rows,
            ["candidate_id", "partition", "gate_passed"],
        )

    trade_rows = [_trade_row(item, trade) for item in all_items for trade in item.trades]
    rejection_rows = [
        _json_safe(
            {
                "candidate_id": item.candidate_id,
                "partition": item.partition,
                **dict(row),
            }
        )
        for item in all_items
        for row in item.rejection_rows
    ]
    stress_rows: list[dict[str, Any]] = []
    for item in all_items:
        for scenario, metrics in (
            ("base", item.base),
            ("spread_1.25", item.spread_stress),
            ("additional_0.05r", item.cost_stress),
        ):
            stress_rows.append(
                {
                    "candidate_id": item.candidate_id,
                    "partition": item.partition,
                    "scenario": scenario,
                    **_metrics_payload(metrics),
                }
            )
    _atomic_csv(
        output_dir / f"{_PREFIX}-trades.csv",
        trade_rows,
        ["candidate_id", "partition", "trade_id"],
    )
    _atomic_csv(
        output_dir / f"{_PREFIX}-rejections.csv",
        rejection_rows,
        ["candidate_id", "partition", "local_date", "reason"],
    )
    _atomic_csv(
        output_dir / f"{_PREFIX}-stress.csv",
        stress_rows,
        ["candidate_id", "partition", "scenario"],
    )

    reason_counts: Counter[str] = Counter()
    for item in all_items:
        reason_counts.update(item.reason_counts)
    partition_payload = {
        partition: {
            item.candidate_id: {
                "base": _metrics_payload(item.base),
                "spread_stress": _metrics_payload(item.spread_stress),
                "cost_stress": _metrics_payload(item.cost_stress),
                "bootstrap_lower": _json_safe(item.bootstrap_lower),
                "spread_ceiling": item.spread_ceiling,
                "selection_score": _json_safe(validation_score(item.spread_stress)),
                "gate_passed": gates.get(partition, {}).get(item.candidate_id, False),
            }
            for item in evaluations.get(partition, ())
        }
        for partition in ("development", "validation", "test")
    }
    payload = {
        **summary.to_json_dict(),
        "partition_bounds": {
            "development": {
                "start": _DEVELOPMENT_START,
                "end": config.development_end,
            },
            "validation": {
                "start": config.development_end + timedelta(days=1),
                "end": config.validation_end,
            },
            "test": {
                "start": config.validation_end + timedelta(days=1),
                "end": config.test_end,
            },
        },
        **partition_payload,
        "gate_booleans": {key: dict(value) for key, value in gates.items()},
        "reason_counts": dict(sorted(reason_counts.items())),
        "application_can_trade": False,
    }
    _atomic_json(output_dir / f"{_PREFIX}-summary.json", payload)


def _by_candidate(result: PartitionEvaluation) -> dict[str, CandidateEvaluation]:
    if not isinstance(result, PartitionEvaluation):
        raise TypeError("partition source must return PartitionEvaluation")
    return {item.candidate_id: item for item in result.candidates}


def session_bar_context(
    bars: pd.DataFrame,
    session_start: pd.Timestamp,
    session_end: pd.Timestamp,
    *,
    warmup_rows: int,
) -> pd.DataFrame:
    if not isinstance(bars.index, pd.DatetimeIndex) or bars.index.tz is None:
        raise ValueError("bars must have a timezone-aware DatetimeIndex")
    if session_start.tzinfo is None or session_end.tzinfo is None:
        raise ValueError("session bounds must be timezone-aware")
    if not bars.index.is_monotonic_increasing or not bars.index.is_unique:
        raise ValueError("bars must be sorted and unique")
    if warmup_rows < 0 or session_end <= session_start:
        raise ValueError("session context bounds are invalid")
    start = session_start.tz_convert(bars.index.tz)
    end = session_end.tz_convert(bars.index.tz)
    left = int(bars.index.searchsorted(start, side="left"))
    right = int(bars.index.searchsorted(end, side="left"))
    return bars.iloc[max(0, left - warmup_rows) : right]


def run_pullback_research(
    config_path: Path | str,
    market_root: Path | str,
    output_dir: Path | str,
    *,
    news_path: Path | str = _DEFAULT_NEWS_PATH,
    source: PartitionSource | None = None,
) -> PullbackResearchSummary:
    config_path = Path(config_path)
    config = load_pullback_config(config_path)
    if source is None:
        source = ParquetPullbackSource(
            config,
            Path(market_root),
            news_path=Path(news_path),
        )
    evaluations: dict[str, tuple[CandidateEvaluation, ...]] = {
        "development": (),
        "validation": (),
        "test": (),
    }
    gates: dict[str, dict[str, bool]] = {
        "development": {},
        "validation": {},
        "test": {},
    }

    development = _by_candidate(source.load_development())
    evaluations["development"] = tuple(development.values())
    viable: list[str] = []
    for candidate in config.candidates():
        item = development.get(candidate.candidate_id)
        passed = bool(
            item
            and development_gate(
                item.base,
                item.spread_stress,
                item.cost_stress,
                item.bootstrap_lower,
            )
        )
        gates["development"][candidate.candidate_id] = passed
        if passed:
            viable.append(candidate.candidate_id)

    selected: str | None = None
    validation_accessed = False
    test_accessed = False
    validation_passed = False
    historical_passed = False
    if not viable:
        status = "development_rejected"
    else:
        validation_accessed = True
        validation = _by_candidate(source.load_validation(tuple(viable)))
        evaluations["validation"] = tuple(
            validation[item] for item in viable if item in validation
        )
        survivors: list[CandidateEvaluation] = []
        for candidate_id in viable:
            item = validation.get(candidate_id)
            passed = bool(
                item and validation_gate(item.base, item.spread_stress)
            )
            gates["validation"][candidate_id] = passed
            if passed and item is not None:
                survivors.append(item)
        if not survivors:
            status = "validation_rejected"
        else:
            validation_passed = True
            chosen = sorted(
                survivors,
                key=lambda item: (
                    -validation_score(item.spread_stress),
                    item.candidate_id,
                ),
            )[0]
            selected = chosen.candidate_id
            test_accessed = True
            test_results = _by_candidate(source.load_test(selected))
            selected_test = test_results.get(selected)
            evaluations["test"] = () if selected_test is None else (selected_test,)
            historical_passed = bool(
                selected_test
                and test_gate(
                    selected_test.base,
                    selected_test.spread_stress,
                    selected_test.bootstrap_lower,
                )
            )
            gates["test"][selected] = historical_passed
            status = "historical_passed" if historical_passed else "test_rejected"

    summary = PullbackResearchSummary(
        version=config.version,
        status=status,
        selected_candidate=selected,
        development_accessed=True,
        validation_accessed=validation_accessed,
        test_accessed=test_accessed,
        development_passed=bool(viable),
        validation_passed=validation_passed,
        historical_gate_passed=historical_passed,
        promotion_eligible=historical_passed
        and not bool(getattr(source, "news_bypass_used", False)),
        config_sha256=_sha256(config_path),
        data_manifest_sha256=source.data_manifest_sha256,
        news_sha256=source.news_sha256,
    )
    _write_artifacts(Path(output_dir), config, summary, evaluations, gates)
    return summary


class ParquetPullbackSource:
    """Read-only canonical Tickstory source with partition-gated access."""

    def __init__(
        self,
        config: PullbackConfig,
        market_root: Path,
        *,
        news_path: Path = _DEFAULT_NEWS_PATH,
    ) -> None:
        self.config = config
        self.market_root = Path(market_root)
        manifest_path = self.market_root / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(
                f"canonical data manifest is missing: {manifest_path}"
            )
        self.data_manifest_sha256 = _sha256(manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        symbol = manifest.get("fbs_demo_symbol", {})
        if symbol.get("server") != config.required_server:
            raise ValueError("market manifest server does not match frozen config")
        if symbol.get("symbol") != config.symbol:
            raise ValueError("market manifest symbol does not match frozen config")
        point = float(symbol["point"])
        self._symbol = SymbolSpec(
            name=config.symbol,
            digits=int(symbol["digits"]),
            point=point,
            tick_size=float(symbol.get("tick_size", point)),
            tick_value=float(symbol.get("tick_value", 1.0)),
            contract_size=float(symbol["contract_size"]),
            volume_min=float(symbol["volume_min"]),
            volume_step=float(symbol["volume_step"]),
            stops_level=int(symbol.get("stops_level", 0)),
            filling_mode=0,
            volume_max=float(symbol.get("volume_max", 100.0)),
        )
        self._calculator = _ContractCalculator(self._symbol.contract_size)
        self.news_path = Path(news_path)
        self.news_sha256 = (
            _sha256(self.news_path)
            if self.news_path.is_file()
            else hashlib.sha256(b"").hexdigest()
        )
        self.news_bypass_used = self._detect_news_bypass()
        self.development_spread_ceilings: dict[str, float] = {}

    def _detect_news_bypass(self) -> bool:
        try:
            with self.news_path.open(encoding="utf-8", newline="") as stream:
                return any(
                    "BYPASS" in row.get("source", "").upper()
                    for row in csv.DictReader(stream)
                )
        except (OSError, csv.Error):
            return False

    def _news_block_details(
        self,
        session_start: pd.Timestamp,
        session_end: pd.Timestamp,
    ) -> Mapping[str, str] | None:
        decision = news_gate(
            self.news_path,
            session_start,
            session_end,
            pd.Timedelta(0),
        )
        if decision.code is NewsCode.MISSING_DATE_CONFIRMATION:
            return {
                "news_status": "missing_confirmation",
                "news_event": "",
                "news_source": str(self.news_path),
            }
        if decision.code is NewsCode.OVERLAPPING_BLACKOUT:
            row = decision.matching_rows[0] if decision.matching_rows else {}
            return {
                "news_status": "high_impact_overlap",
                "news_event": row.get("event_name", ""),
                "news_source": row.get("source", ""),
            }
        return None

    def _load_bars(
        self,
        timeframe: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> pd.DataFrame:
        path = (
            (self.market_root / "bars" / f"{timeframe}.parquet")
            .resolve()
            .as_posix()
            .replace("'", "''")
        )
        start_value = start.tz_convert("UTC").tz_localize(None)
        end_value = end.tz_convert("UTC").tz_localize(None)
        frame = duckdb.sql(
            f"""
            SELECT *
            FROM read_parquet('{path}')
            WHERE Timestamp >= TIMESTAMP '{start_value}'
              AND Timestamp < TIMESTAMP '{end_value}'
            ORDER BY Timestamp
            """
        ).df()
        if frame.empty:
            return pd.DataFrame(
                columns=["open", "high", "low", "close"],
                index=pd.DatetimeIndex([], name="Timestamp", tz="UTC"),
            )
        frame["Timestamp"] = pd.to_datetime(frame["Timestamp"], utc=True)
        return frame.set_index("Timestamp").rename(
            columns={
                "BidOpen": "open",
                "BidHigh": "high",
                "BidLow": "low",
                "BidClose": "close",
            }
        )

    def _lock_development_spread_ceilings(
        self,
        candidate_dates: list[date],
    ) -> None:
        intervals: list[dict[str, Any]] = []
        for window in self.config.candidate_sessions_ny:
            for local_date in candidate_dates:
                session_start, _ = new_york_session_bounds(local_date, window)
                intervals.append(
                    {
                        "window": window,
                        "start_utc": session_start.tz_localize(None),
                        "end_utc": (
                            session_start
                            + pd.Timedelta(minutes=self.config.entry_cutoff_minute)
                        ).tz_localize(None),
                    }
                )
        self.development_spread_ceilings = {
            window: 0.0 for window in self.config.candidate_sessions_ny
        }
        if not intervals:
            return
        years = {local_date.year for local_date in candidate_dates}
        partition = f"year={next(iter(years))}" if len(years) == 1 else "year=*"
        pattern = (
            (self.market_root / "ticks" / partition / "ticks.parquet")
            .resolve()
            .as_posix()
            .replace("'", "''")
        )
        connection = duckdb.connect()
        try:
            connection.register("intervals", pd.DataFrame(intervals))
            result = connection.execute(
                f"""
                SELECT i.window,
                       quantile_cont(t.Ask - t.Bid, 0.90) AS ceiling
                FROM read_parquet('{pattern}', hive_partitioning=true) AS t
                JOIN intervals AS i
                  ON t.Timestamp >= i.start_utc
                 AND t.Timestamp < i.end_utc
                WHERE t.Ask >= t.Bid
                GROUP BY i.window
                """
            ).fetchall()
        finally:
            connection.close()
        for window, ceiling in result:
            self.development_spread_ceilings[str(window)] = float(ceiling)

    def _load_tick_batch(
        self,
        candidate_dates: list[date],
        windows: tuple[str, ...],
    ) -> dict[tuple[str, date], pd.DataFrame]:
        empty = lambda: pd.DataFrame(
            columns=["bid", "ask"],
            index=pd.DatetimeIndex([], name="Timestamp", tz="UTC"),
        )
        batches = {
            (window, local_date): empty()
            for window in windows
            for local_date in candidate_dates
        }
        intervals: list[dict[str, Any]] = []
        for window in windows:
            for local_date in candidate_dates:
                session_start, session_end = new_york_session_bounds(
                    local_date,
                    window,
                )
                intervals.append(
                    {
                        "window": window,
                        "local_date": local_date,
                        "start_utc": (
                            session_start
                            - pd.Timedelta(
                                minutes=self.config.reference_spread_minutes
                            )
                        ).tz_localize(None),
                        "end_utc": session_end.tz_localize(None),
                    }
                )
        if not intervals:
            return batches
        years = {local_date.year for local_date in candidate_dates}
        partition = f"year={next(iter(years))}" if len(years) == 1 else "year=*"
        pattern = (
            (self.market_root / "ticks" / partition / "ticks.parquet")
            .resolve()
            .as_posix()
            .replace("'", "''")
        )
        connection = duckdb.connect()
        try:
            connection.register("intervals", pd.DataFrame(intervals))
            frame = connection.execute(
                f"""
                SELECT i.window AS session_window,
                       i.local_date,
                       t.Timestamp,
                       t.Bid,
                       t.Ask
                FROM read_parquet('{pattern}', hive_partitioning=true) AS t
                JOIN intervals AS i
                  ON t.Timestamp >= i.start_utc
                 AND t.Timestamp < i.end_utc
                ORDER BY session_window, local_date, Timestamp
                """
            ).df()
        finally:
            connection.close()
        if frame.empty:
            return batches
        frame["Timestamp"] = pd.to_datetime(frame["Timestamp"], utc=True)
        for (window, local_date), group in frame.groupby(
            ["session_window", "local_date"],
            sort=False,
        ):
            key = (
                str(window),
                pd.Timestamp(local_date).date(),
            )
            batches[key] = group.set_index("Timestamp")[["Bid", "Ask"]].rename(
                columns={"Bid": "bid", "Ask": "ask"}
            )
        return batches

    def _iter_window_markets(
        self,
        window: str,
        candidate_dates: list[date],
    ):
        months: dict[tuple[int, int], list[date]] = {}
        for local_date in candidate_dates:
            months.setdefault((local_date.year, local_date.month), []).append(
                local_date
            )
        for dates in months.values():
            batch = self._load_tick_batch(dates, (window,))
            for local_date in dates:
                yield local_date, batch[(window, local_date)]

    def load_development(self) -> PartitionEvaluation:
        candidate_ids = tuple(item.candidate_id for item in self.config.candidates())
        return self._evaluate(
            "development",
            _DEVELOPMENT_START,
            self.config.development_end,
            candidate_ids,
        )

    def load_validation(
        self,
        candidate_ids: tuple[str, ...],
    ) -> PartitionEvaluation:
        return self._evaluate(
            "validation",
            self.config.development_end + timedelta(days=1),
            self.config.validation_end,
            candidate_ids,
        )

    def load_test(self, candidate_id: str) -> PartitionEvaluation:
        return self._evaluate(
            "test",
            self.config.validation_end + timedelta(days=1),
            self.config.test_end,
            (candidate_id,),
        )

    def _evaluate(
        self,
        partition: str,
        first_date: date,
        last_date: date,
        candidate_ids: tuple[str, ...],
    ) -> PartitionEvaluation:
        by_id = {item.candidate_id: item for item in self.config.candidates()}
        selected = tuple(by_id[item] for item in candidate_ids)
        ny = ZoneInfo("America/New_York")
        warmup = pd.Timestamp(
            datetime.combine(first_date - timedelta(days=14), time(), tzinfo=ny)
        ).tz_convert("UTC")
        end = pd.Timestamp(
            datetime.combine(last_date + timedelta(days=1), time(), tzinfo=ny)
        ).tz_convert("UTC")
        bars = {
            timeframe: self._load_bars(timeframe, warmup, end)
            for timeframe in ("M1", "M5", "M15", "H1")
        }
        candidate_dates = sorted(
            {
                value
                for value in bars["M5"].index.tz_convert(ny).date
                if first_date <= value <= last_date
            }
        )
        if partition == "development" and any(
            item.session_ny not in self.development_spread_ceilings
            for item in selected
        ):
            self._lock_development_spread_ceilings(candidate_dates)
        missing = sorted(
            {
                item.session_ny
                for item in selected
                if item.session_ny not in self.development_spread_ceilings
            }
        )
        if missing:
            raise RuntimeError(
                "development spread ceiling must be locked before "
                f"{partition}: {', '.join(missing)}"
            )

        scenario_trades: dict[str, dict[str, list[TradeResult]]] = {
            item.candidate_id: {"base": [], "spread": [], "cost": []}
            for item in selected
        }
        reasons: dict[str, Counter[str]] = {
            item.candidate_id: Counter() for item in selected
        }
        rejections: dict[str, list[dict[str, Any]]] = {
            item.candidate_id: [] for item in selected
        }
        by_window: dict[str, list[PullbackCandidate]] = {}
        for item in selected:
            by_window.setdefault(item.session_ny, []).append(item)
        def reject(
            candidates: list[PullbackCandidate],
            local_date: date,
            session_start: pd.Timestamp,
            reason: str,
            details: Mapping[str, Any] | None = None,
        ) -> None:
            for candidate in candidates:
                reasons[candidate.candidate_id][reason] += 1
                rejections[candidate.candidate_id].append(
                    {
                        "local_date": local_date.isoformat(),
                        "session_start": session_start.isoformat(),
                        "reason": reason,
                        **dict(details or {}),
                    }
                )

        for window, window_candidates in by_window.items():
            ceiling = self.development_spread_ceilings[window]
            for local_date, market in self._iter_window_markets(
                window,
                candidate_dates,
            ):
                session_start, session_end = new_york_session_bounds(
                    local_date,
                    window,
                )
                news_block = self._news_block_details(session_start, session_end)
                if news_block is not None:
                    reject(
                        window_candidates,
                        local_date,
                        session_start,
                        PullbackReason.NEWS_BLOCKED.value,
                        news_block,
                    )
                    continue
                reference = market.loc[
                    (market.index >= session_start - pd.Timedelta(minutes=30))
                    & (market.index < session_start)
                ]
                active_ticks = market.loc[
                    (market.index >= session_start)
                    & (market.index < session_end)
                ]
                if reference.empty or active_ticks.empty:
                    reject(
                        window_candidates,
                        local_date,
                        session_start,
                        PullbackReason.SPREAD_TOO_WIDE.value,
                        {"market_data": "missing_reference_or_session_ticks"},
                    )
                    continue
                reference_spread = float(
                    (reference["ask"] - reference["bid"]).median()
                )
                local_bars = {
                    "M1": session_bar_context(
                        bars["M1"],
                        session_start,
                        session_end,
                        warmup_rows=20,
                    ),
                    "M5": session_bar_context(
                        bars["M5"],
                        session_start,
                        session_end,
                        warmup_rows=40,
                    ),
                    "M15": session_bar_context(
                        bars["M15"],
                        session_start,
                        session_end,
                        warmup_rows=30,
                    ),
                    "H1": session_bar_context(
                        bars["H1"],
                        session_start,
                        session_end,
                        warmup_rows=30,
                    ),
                }
                locked_bias = evaluate_locked_bias(
                    local_bars["H1"],
                    local_bars["M15"],
                    session_start,
                    self.config,
                )
                if locked_bias.direction is None:
                    reject(
                        window_candidates,
                        local_date,
                        session_start,
                        locked_bias.reason.value,
                    )
                    continue
                for candidate in window_candidates:
                    setup_decision = detect_pullback_setup(
                        local_bars["M1"],
                        local_bars["M5"],
                        locked_bias,
                        candidate,
                        session_start,
                        session_end,
                        reference_spread,
                        self.config,
                    )
                    if setup_decision.setup is None:
                        reject(
                            [candidate],
                            local_date,
                            session_start,
                            setup_decision.reason.value,
                        )
                        continue
                    eligible = active_ticks.loc[
                        (active_ticks.index >= setup_decision.setup.entry_available_time)
                        & (
                            active_ticks.index
                            <= session_start
                            + pd.Timedelta(minutes=self.config.entry_cutoff_minute)
                        )
                    ]
                    if eligible.empty:
                        reject(
                            [candidate],
                            local_date,
                            session_start,
                            "entry_timeout",
                        )
                        continue
                    first_tick = eligible.iloc[0]
                    executable_entry = (
                        float(first_tick["ask"])
                        if setup_decision.setup.direction is TradeDirection.LONG
                        else float(first_tick["bid"])
                    )
                    plan = size_trade(
                        setup=setup_decision.setup,
                        executable_entry=executable_entry,
                        development_spread_ceiling=ceiling,
                        starting_day_equity=10_000.0,
                        free_margin=10_000.0,
                        symbol=self._symbol,
                        calculator=self._calculator,
                        config=self.config,
                        trade_id=(
                            f"{local_date.isoformat()}-{candidate.candidate_id}"
                        ),
                    )
                    if plan.plan is None:
                        reject(
                            [candidate],
                            local_date,
                            session_start,
                            plan.reason.value,
                        )
                        continue
                    abort_bars = (
                        local_bars["M1"]
                        if candidate.abort_timeframe == "M1"
                        else local_bars["M5"]
                    )
                    simulations = {
                        "base": simulate_trade(
                            plan.plan,
                            active_ticks,
                            abort_bars,
                            session_end,
                            self._symbol.contract_size,
                        ),
                        "spread": simulate_trade(
                            plan.plan,
                            active_ticks,
                            abort_bars,
                            session_end,
                            self._symbol.contract_size,
                            CostStress(spread_multiplier=1.25),
                        ),
                        "cost": simulate_trade(
                            plan.plan,
                            active_ticks,
                            abort_bars,
                            session_end,
                            self._symbol.contract_size,
                            CostStress(additional_r_cost=0.05),
                        ),
                    }
                    base = simulations["base"]
                    if base.trade is None:
                        reject(
                            [candidate],
                            local_date,
                            session_start,
                            base.reason.value,
                        )
                        continue
                    for scenario, simulation in simulations.items():
                        if simulation.trade is not None:
                            scenario_trades[candidate.candidate_id][scenario].append(
                                simulation.trade
                            )

        results: list[CandidateEvaluation] = []
        for candidate in selected:
            trades = scenario_trades[candidate.candidate_id]
            base_metrics = summarize_trades(trades["base"])
            results.append(
                CandidateEvaluation(
                    candidate=candidate,
                    partition=partition,
                    base=base_metrics,
                    spread_stress=summarize_trades(trades["spread"]),
                    cost_stress=summarize_trades(trades["cost"]),
                    bootstrap_lower=bootstrap_expectancy_lower_bound(
                        [item.net_r for item in trades["base"]]
                    ),
                    spread_ceiling=self.development_spread_ceilings[
                        candidate.session_ny
                    ],
                    trades=tuple(trades["base"]),
                    spread_trades=tuple(trades["spread"]),
                    cost_trades=tuple(trades["cost"]),
                    reason_counts=dict(reasons[candidate.candidate_id]),
                    rejection_rows=tuple(rejections[candidate.candidate_id]),
                )
            )
        return PartitionEvaluation(partition, tuple(results))


class _ContractCalculator(ProfitMarginCalculator):
    def __init__(self, contract_size: float) -> None:
        self.contract_size = contract_size

    def loss_for_one_lot(
        self,
        direction: TradeDirection,
        entry: float,
        stop: float,
    ) -> float:
        return -abs(entry - stop) * self.contract_size

    def margin_for_volume(
        self,
        direction: TradeDirection,
        volume: float,
        entry: float,
    ) -> float:
        return volume * entry * self.contract_size / 100.0
