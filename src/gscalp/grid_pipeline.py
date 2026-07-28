from __future__ import annotations

import hashlib
import inspect
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

from .grid_backtest import CostStress, simulate_grid
from .grid_config import GridConfig, load_grid_config
from .grid_bias import completed_bars, confirmed_pivot, evaluate_locked_bias
from .grid_geometry import build_grid_geometry
from .grid_metrics import (
    GridMetrics,
    bootstrap_expectancy_lower_bound,
    development_gate,
    summarize_baskets,
    test_gate,
    validation_gate,
)
from .grid_models import BasketResult, GridPlan, GridReason
from .grid_sizing import ProfitMarginCalculator, size_grid
from .indicators import atr
from .mt5_read import SymbolSpec
from .research import TickParquetStore, new_york_session_bounds


_PREFIX = "grid-v1.0"
_DEVELOPMENT_START = date(2020, 1, 2)
_COST_ASSUMPTIONS = {
    "base": "observed executable Tickstory bid/ask",
    "spread_multipliers": [1.0, 1.25, 1.5],
    "additional_cost_r": 0.05,
    "target_update_delay_ticks": 1,
    "same_tick_fill_stop_ordering": "fill_then_stop",
}


@dataclass(frozen=True, slots=True)
class GridResearchSummary:
    version: str
    status: str
    selected_window: str | None
    development_passed: bool
    validation_passed: bool
    test_accessed: bool
    test_passed: bool
    config_sha256: str
    data_manifest_sha256: str


@dataclass(frozen=True, slots=True)
class SessionPlanDecision:
    local_date: date
    window: str
    session_start: pd.Timestamp
    session_end: pd.Timestamp
    plan: GridPlan | None
    reason: GridReason
    diagnostics: tuple[tuple[str, float | str], ...] = ()


@dataclass(frozen=True, slots=True)
class WindowEvaluation:
    """Metrics and audit rows for one candidate window in one partition."""

    window: str
    partition: str
    base: GridMetrics
    stressed: GridMetrics
    standard_error: float
    bootstrap_lower: float = 0.0
    baskets: tuple[BasketResult, ...] = ()
    stressed_baskets: tuple[BasketResult, ...] = ()
    reason_counts: Mapping[str, int] = field(default_factory=dict)
    rejection_rows: tuple[Mapping[str, Any], ...] = ()
    stress_metrics: Mapping[str, GridMetrics] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "baskets", tuple(self.baskets))
        object.__setattr__(self, "stressed_baskets", tuple(self.stressed_baskets))
        object.__setattr__(self, "rejection_rows", tuple(self.rejection_rows))


@dataclass(frozen=True, slots=True)
class PartitionEvaluation:
    partition: str
    windows: tuple[WindowEvaluation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "windows", tuple(self.windows))


class PartitionSource(Protocol):
    data_manifest_sha256: str

    def load_development(self) -> PartitionEvaluation: ...

    def load_validation(
        self, windows: tuple[str, ...] = ()
    ) -> PartitionEvaluation: ...

    def load_test(self, windows: tuple[str, ...] = ()) -> PartitionEvaluation: ...


def plan_session(
    *,
    local_date: date,
    window: str,
    m5: pd.DataFrame,
    m15: pd.DataFrame,
    ticks: pd.DataFrame,
    symbol: SymbolSpec,
    config: GridConfig,
    calculator: ProfitMarginCalculator,
    starting_equity: float,
    free_margin: float,
    spread_ceiling: float,
) -> SessionPlanDecision:
    """Create at most one plan from information available at the session open."""
    session_start, session_end = new_york_session_bounds(local_date, window)
    if (
        not isinstance(ticks.index, pd.DatetimeIndex)
        or ticks.index.tz is None
        or not {"bid", "ask"}.issubset(ticks.columns)
    ):
        raise ValueError("ticks must have a timezone-aware index and bid/ask columns")
    market = ticks.copy()
    market.index = market.index.tz_convert("UTC")
    market = market.sort_index()
    session_ticks = market.loc[
        (market.index >= session_start) & (market.index < session_end)
    ]
    reference_ticks = market.loc[
        (market.index >= session_start - pd.Timedelta(minutes=30))
        & (market.index < session_start)
    ]
    if session_ticks.empty or reference_ticks.empty:
        return SessionPlanDecision(
            local_date,
            window,
            session_start,
            session_end,
            None,
            GridReason.SPREAD_TOO_WIDE,
            (("market_data", "missing_open_or_reference_ticks"),),
        )

    bias = evaluate_locked_bias(m15, session_start, config)
    pivot = (
        None
        if bias.direction is None
        else confirmed_pivot(m5, session_start, bias.direction, config)
    )
    completed_m5 = completed_bars(m5, session_start, 5)
    average_true_range = atr(completed_m5, config.atr_period)
    atr_value = (
        None
        if average_true_range.empty or pd.isna(average_true_range.iloc[-1])
        else float(average_true_range.iloc[-1])
    )
    reference_spread = float(
        (reference_ticks["ask"].astype(float) - reference_ticks["bid"].astype(float)).median()
    )
    anchor_tick = session_ticks.iloc[0]
    anchor_bid = float(anchor_tick["bid"])
    anchor_ask = float(anchor_tick["ask"])
    current_spread = anchor_ask - anchor_bid
    geometry = build_grid_geometry(
        bias=bias,
        session_start=session_start,
        anchor_bid=anchor_bid,
        anchor_ask=anchor_ask,
        atr=atr_value,
        reference_spread=reference_spread,
        current_spread=current_spread,
        spread_ceiling=spread_ceiling,
        pivot=pivot,
        symbol=symbol,
        config=config,
    )
    if geometry.geometry is None:
        return SessionPlanDecision(
            local_date,
            window,
            session_start,
            session_end,
            None,
            geometry.reason,
            geometry.diagnostics,
        )
    sized = size_grid(
        geometry=geometry.geometry,
        starting_day_equity=starting_equity,
        free_margin=free_margin,
        symbol=symbol,
        calculator=calculator,
        config=config,
        basket_id=f"{local_date.isoformat()}-{window}",
    )
    return SessionPlanDecision(
        local_date,
        window,
        session_start,
        session_end,
        sized.plan,
        sized.reason,
        sized.diagnostics,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
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


def _metrics_payload(metrics: GridMetrics) -> dict[str, Any]:
    return _json_safe(asdict(metrics))


def _atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    try:
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


def _metric_row(item: WindowEvaluation, passed: bool) -> dict[str, Any]:
    row: dict[str, Any] = {
        "window": item.window,
        "partition": item.partition,
        "gate_passed": passed,
        "standard_error": item.standard_error,
        "selection_score": item.stressed.expectancy_r - item.standard_error,
    }
    row.update({f"base_{key}": value for key, value in asdict(item.base).items()})
    row.update(
        {f"stressed_{key}": value for key, value in asdict(item.stressed).items()}
    )
    return _json_safe(row)


def _basket_rows(items: list[WindowEvaluation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        for basket in item.baskets:
            row = asdict(basket)
            row.pop("legs", None)
            row.update(window=item.window, partition=item.partition)
            rows.append(_json_safe(row))
    return rows


def _leg_rows(items: list[WindowEvaluation]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        for basket in item.baskets:
            for leg in basket.legs:
                row = asdict(leg)
                row.update(
                    basket_id=basket.basket_id,
                    window=item.window,
                    partition=item.partition,
                )
                rows.append(_json_safe(row))
    return rows


def _write_artifacts(
    *,
    output_dir: Path,
    config: GridConfig,
    summary: GridResearchSummary,
    evaluations: Mapping[str, tuple[WindowEvaluation, ...]],
    gates: Mapping[str, Mapping[str, bool]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    all_items = [
        item
        for partition in ("development", "validation", "test")
        for item in evaluations.get(partition, ())
    ]
    for partition in ("development", "validation", "test"):
        rows = [
            _metric_row(item, gates.get(partition, {}).get(item.window, False))
            for item in evaluations.get(partition, ())
        ]
        _atomic_csv(
            output_dir / f"{_PREFIX}-{partition}.csv",
            pd.DataFrame(
                rows,
                columns=(
                    list(rows[0])
                    if rows
                    else [
                        "window",
                        "partition",
                        "gate_passed",
                        "standard_error",
                        "selection_score",
                    ]
                ),
            ),
        )

    basket_rows = _basket_rows(all_items)
    leg_rows = _leg_rows(all_items)
    rejection_rows = [
        _json_safe(
            {
                "window": item.window,
                "partition": item.partition,
                **dict(row),
            }
        )
        for item in all_items
        for row in item.rejection_rows
    ]
    stress_rows = []
    for item in all_items:
        scenarios = item.stress_metrics or {"gate_stress": item.stressed}
        for scenario, metrics in scenarios.items():
            stress_rows.append(
                {
                    "window": item.window,
                    "partition": item.partition,
                    "scenario": scenario,
                    **_metrics_payload(metrics),
                }
            )
    _atomic_csv(
        output_dir / f"{_PREFIX}-baskets.csv",
        pd.DataFrame(
            basket_rows,
            columns=list(basket_rows[0]) if basket_rows else ["basket_id", "window", "partition"],
        ),
    )
    _atomic_csv(
        output_dir / f"{_PREFIX}-legs.csv",
        pd.DataFrame(
            leg_rows,
            columns=list(leg_rows[0]) if leg_rows else ["basket_id", "level_number", "window", "partition"],
        ),
    )
    _atomic_csv(
        output_dir / f"{_PREFIX}-rejections.csv",
        pd.DataFrame(
            rejection_rows,
            columns=list(rejection_rows[0])
            if rejection_rows
            else ["window", "partition", "reason"],
        ),
    )
    _atomic_csv(
        output_dir / f"{_PREFIX}-stress.csv",
        pd.DataFrame(
            stress_rows,
            columns=list(stress_rows[0])
            if stress_rows
            else ["window", "partition", "scenario"],
        ),
    )

    reason_counts: Counter[str] = Counter()
    for item in all_items:
        reason_counts.update(item.reason_counts)
    bounds = {
        "development": {
            "start": _DEVELOPMENT_START.isoformat(),
            "end": config.development_end.isoformat(),
        },
        "validation": {
            "start": (config.development_end + timedelta(days=1)).isoformat(),
            "end": config.validation_end.isoformat(),
        },
        "test": {
            "start": (config.validation_end + timedelta(days=1)).isoformat(),
            "end": config.test_end.isoformat(),
        },
    }
    metric_payload = {
        partition: {
            item.window: {
                "base": _metrics_payload(item.base),
                "stressed": _metrics_payload(item.stressed),
                "standard_error": _json_safe(item.standard_error),
                "selection_score": _json_safe(
                    item.stressed.expectancy_r - item.standard_error
                ),
                "gate_passed": gates.get(partition, {}).get(item.window, False),
            }
            for item in evaluations.get(partition, ())
        }
        for partition in ("development", "validation", "test")
    }
    payload = {
        **asdict(summary),
        "partition_bounds": bounds,
        **metric_payload,
        "gate_booleans": {
            key: dict(value) for key, value in gates.items()
        },
        "reason_counts": dict(sorted(reason_counts.items())),
        "cost_assumptions": _COST_ASSUMPTIONS,
        "application_can_trade": False,
    }
    _atomic_json(output_dir / f"{_PREFIX}-summary.json", payload)


def _partition_by_window(
    result: PartitionEvaluation,
) -> dict[str, WindowEvaluation]:
    if not isinstance(result, PartitionEvaluation):
        raise TypeError("partition source must return PartitionEvaluation")
    return {item.window: item for item in result.windows}


def _load_later_partition(
    source: PartitionSource, name: str, windows: tuple[str, ...]
) -> PartitionEvaluation:
    loader = getattr(source, f"load_{name}")
    if len(inspect.signature(loader).parameters) == 0:
        return loader()
    return loader(windows)


def run_grid_research(
    config_path: Path | str,
    market_root: Path | str,
    output_dir: Path | str,
    *,
    source: PartitionSource | None = None,
) -> GridResearchSummary:
    config_path = Path(config_path)
    config = load_grid_config(config_path)
    if source is None:
        source = ParquetPartitionSource(config, Path(market_root))

    evaluations: dict[str, tuple[WindowEvaluation, ...]] = {
        "development": (),
        "validation": (),
        "test": (),
    }
    gates: dict[str, dict[str, bool]] = {
        "development": {},
        "validation": {},
        "test": {},
    }

    development = _partition_by_window(source.load_development())
    evaluations["development"] = tuple(development.values())
    viable = []
    for window in config.candidate_sessions_ny:
        item = development.get(window)
        passed = item is not None and development_gate(item.base, item.stressed)
        gates["development"][window] = passed
        if passed:
            viable.append(window)

    selected: str | None = None
    validation_passed = False
    test_accessed = False
    test_passed = False
    if not viable:
        status = "development_rejected"
    else:
        validation = _partition_by_window(
            _load_later_partition(source, "validation", tuple(viable))
        )
        evaluations["validation"] = tuple(
            validation[window] for window in viable if window in validation
        )
        passing_validation = []
        for window in viable:
            item = validation.get(window)
            passed = item is not None and validation_gate(item.base, item.stressed)
            gates["validation"][window] = passed
            if passed:
                passing_validation.append(item)
        if not passing_validation:
            status = "validation_rejected"
        else:
            validation_passed = True
            selected = max(
                passing_validation,
                key=lambda item: (
                    item.stressed.expectancy_r - item.standard_error,
                    item.window,
                ),
            ).window
            test_accessed = True
            test_results = _partition_by_window(
                _load_later_partition(source, "test", (selected,))
            )
            selected_test = test_results.get(selected)
            evaluations["test"] = (
                () if selected_test is None else (selected_test,)
            )
            test_passed = bool(
                selected_test is not None
                and test_gate(
                    selected_test.base,
                    selected_test.stressed,
                    selected_test.bootstrap_lower,
                )
            )
            gates["test"][selected] = test_passed
            status = "historical_passed" if test_passed else "test_rejected"

    summary = GridResearchSummary(
        version=config.version,
        status=status,
        selected_window=selected,
        development_passed=bool(viable),
        validation_passed=validation_passed,
        test_accessed=test_accessed,
        test_passed=test_passed,
        config_sha256=_sha256(config_path),
        data_manifest_sha256=source.data_manifest_sha256,
    )
    _write_artifacts(
        output_dir=Path(output_dir),
        config=config,
        summary=summary,
        evaluations=evaluations,
        gates=gates,
    )
    return summary


class ParquetPartitionSource:
    """Canonical parquet source.

    The implementation is intentionally deferred behind partition-specific
    methods so validation and test files cannot be touched before their gates.
    """

    def __init__(self, config: GridConfig, market_root: Path) -> None:
        self.config = config
        self.market_root = market_root
        manifest = market_root / "manifest.json"
        if not manifest.is_file():
            raise FileNotFoundError(f"canonical data manifest is missing: {manifest}")
        self.data_manifest_sha256 = _sha256(manifest)
        self._symbol = SymbolSpec(
            config.symbol,
            digits=2,
            point=0.01,
            tick_size=0.01,
            tick_value=1.0,
            contract_size=100.0,
            volume_min=0.01,
            volume_step=0.01,
            stops_level=0,
            filling_mode=0,
        )
        self._calculator = _ContractCalculator(self._symbol.contract_size)

    def load_development(self) -> PartitionEvaluation:
        return self._evaluate(
            "development",
            _DEVELOPMENT_START,
            self.config.development_end,
            self.config.candidate_sessions_ny,
        )

    def load_validation(
        self, windows: tuple[str, ...] = ()
    ) -> PartitionEvaluation:
        return self._evaluate(
            "validation",
            self.config.development_end + timedelta(days=1),
            self.config.validation_end,
            windows or self.config.candidate_sessions_ny,
        )

    def load_test(self, windows: tuple[str, ...] = ()) -> PartitionEvaluation:
        return self._evaluate(
            "test",
            self.config.validation_end + timedelta(days=1),
            self.config.test_end,
            windows or self.config.candidate_sessions_ny,
        )

    def _load_bars(
        self, timeframe: str, start: pd.Timestamp, end: pd.Timestamp
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
                "AskOpen": "ask_open",
                "AskHigh": "ask_high",
                "AskLow": "ask_low",
                "AskClose": "ask_close",
                "MinSpread": "min_spread",
                "MaxSpread": "max_spread",
            }
        )

    def _evaluate(
        self,
        partition: str,
        first_date: date,
        last_date: date,
        windows: tuple[str, ...],
    ) -> PartitionEvaluation:
        ny = ZoneInfo("America/New_York")
        warmup = pd.Timestamp(
            datetime.combine(first_date - timedelta(days=7), time(), tzinfo=ny)
        ).tz_convert("UTC")
        end = pd.Timestamp(
            datetime.combine(last_date + timedelta(days=1), time(), tzinfo=ny)
        ).tz_convert("UTC")
        m5 = self._load_bars("M5", warmup, end)
        m15 = self._load_bars("M15", warmup, end)
        candidate_dates = sorted(
            {
                item
                for item in m5.index.tz_convert(ny).date
                if first_date <= item <= last_date
            }
        )
        tick_store = TickParquetStore(
            self.market_root / "ticks" / "year=*" / "ticks.parquet"
        )
        scenarios = {
            "base": CostStress(),
            "spread_1.25": CostStress(spread_multiplier=1.25),
            "spread_1.50": CostStress(spread_multiplier=1.50),
            "additional_0.05r": CostStress(additional_cost_r=0.05),
            "gate_stress": CostStress(
                spread_multiplier=1.25, additional_cost_r=0.05
            ),
            "target_delay_one_tick": CostStress(target_update_delay_ticks=1),
        }
        results: list[WindowEvaluation] = []
        empty_aborts = pd.DataFrame(
            {"abort": pd.Series(dtype=bool)},
            index=pd.DatetimeIndex([], tz="UTC"),
        )
        for window in windows:
            baskets_by_scenario: dict[str, list[BasketResult]] = {
                name: [] for name in scenarios
            }
            reasons: Counter[str] = Counter()
            rejections: list[dict[str, Any]] = []
            for local_date in candidate_dates:
                session_start, session_end = new_york_session_bounds(
                    local_date, window
                )
                ticks = tick_store.slice(
                    session_start - pd.Timedelta(minutes=30), session_end
                )
                spread_ceiling = _historical_spread_ceiling(ticks)
                decision = plan_session(
                    local_date=local_date,
                    window=window,
                    m5=m5,
                    m15=m15,
                    ticks=ticks,
                    symbol=self._symbol,
                    config=self.config,
                    calculator=self._calculator,
                    starting_equity=10_000.0,
                    free_margin=10_000.0,
                    spread_ceiling=spread_ceiling,
                )
                if decision.plan is None:
                    reasons[decision.reason.value] += 1
                    rejections.append(
                        {
                            "local_date": local_date.isoformat(),
                            "session_start": session_start.isoformat(),
                            "reason": decision.reason.value,
                        }
                    )
                    continue
                for scenario, costs in scenarios.items():
                    basket = simulate_grid(
                        decision.plan, ticks, empty_aborts, costs
                    )
                    if basket is not None:
                        baskets_by_scenario[scenario].append(basket)
                if not baskets_by_scenario["base"] or (
                    baskets_by_scenario["base"][-1].basket_id
                    != decision.plan.basket_id
                ):
                    reasons[GridReason.PENDING_EXPIRED.value] += 1
                    rejections.append(
                        {
                            "local_date": local_date.isoformat(),
                            "session_start": session_start.isoformat(),
                            "reason": GridReason.PENDING_EXPIRED.value,
                        }
                    )
            base_baskets = baskets_by_scenario["base"]
            stress_metrics = {
                name: summarize_baskets(items)
                for name, items in baskets_by_scenario.items()
            }
            gate_baskets = baskets_by_scenario["gate_stress"]
            net = np.asarray([item.net_r for item in gate_baskets], dtype=float)
            standard_error = (
                float(net.std(ddof=1) / math.sqrt(len(net)))
                if len(net) > 1
                else 0.0
            )
            bootstrap_lower = bootstrap_expectancy_lower_bound(
                [item.net_r for item in base_baskets],
                confidence=0.90,
                samples=5_000,
                seed=260728,
            )
            results.append(
                WindowEvaluation(
                    window=window,
                    partition=partition,
                    base=stress_metrics["base"],
                    stressed=stress_metrics["gate_stress"],
                    standard_error=standard_error,
                    bootstrap_lower=bootstrap_lower,
                    baskets=tuple(base_baskets),
                    stressed_baskets=tuple(gate_baskets),
                    reason_counts=dict(reasons),
                    rejection_rows=tuple(rejections),
                    stress_metrics=stress_metrics,
                )
            )
        return PartitionEvaluation(partition, tuple(results))


class _ContractCalculator:
    def __init__(self, contract_size: float) -> None:
        self.contract_size = contract_size

    def loss_for_one_lot(self, direction, entry: float, stop: float) -> float:
        return -abs(entry - stop) * self.contract_size

    def margin_for_volume(
        self, direction, volume: float, entry: float
    ) -> float:
        return volume * entry * self.contract_size / 100.0


def _historical_spread_ceiling(ticks: pd.DataFrame) -> float:
    if ticks.empty:
        return 0.0
    spreads = ticks["ask"].astype(float) - ticks["bid"].astype(float)
    return float(spreads.quantile(0.90))
