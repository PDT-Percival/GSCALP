from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .backtest import TradeResult, run_signal_backtest
from .config import load_config
from .metrics import summarize
from .research import (
    TickParquetStore,
    build_liquidity_level_map,
    evaluate_session_bounds,
    load_bar_parquet,
    new_york_session_bounds,
)


DEVELOPMENT_SWEEP_MAXIMA = (0.75, 1.0, 1.5)
DEVELOPMENT_STOP_MAXIMA = (1.0, 1.5, 2.0, 2.5)
DEVELOPMENT_SAME_BAR_RECLAIM = (True,)
DEVELOPMENT_ADDITIONAL_COST_R = 0.10


def assess_development_candidate(
    *,
    trade_count: int,
    stressed_expectancy_r: float,
    profit_factor: float,
    max_drawdown_r: float,
    maximum_year_share: float,
) -> bool:
    return bool(
        trade_count >= 30
        and stressed_expectancy_r > 0
        and profit_factor > 1.05
        and max_drawdown_r <= 8.0
        and maximum_year_share <= 0.35
    )


def select_development_candidate(
    grid: pd.DataFrame, *, parameter: str = "sweep_atr_max"
) -> dict[str, Any] | None:
    viable = grid.loc[grid["development_viable"].astype(bool)]
    if viable.empty:
        return None
    best = viable.sort_values(
        ["robust_score", "trade_count", parameter],
        ascending=[False, False, True],
    ).iloc[0]
    parameter_value = best[parameter]
    if hasattr(parameter_value, "item"):
        parameter_value = parameter_value.item()
    return {
        parameter: parameter_value,
        "window": str(best["window"]),
    }


def _trade_payload(
    trade: TradeResult,
    *,
    local_date: Any,
    window: str,
    parameter: str,
    parameter_value: float,
) -> dict[str, Any]:
    payload = asdict(trade)
    payload["direction"] = trade.direction.value
    payload["exit_reason"] = trade.exit_reason.value
    payload["local_date"] = local_date.isoformat()
    payload["year"] = local_date.year
    payload["window"] = window
    payload[parameter] = parameter_value
    return payload


def run_development_experiment(
    config_path: Path,
    market_root: Path,
    output_dir: Path,
    *,
    version: str = "v0.2",
    parameter: str = "sweep_atr_max",
    candidate_values: tuple[Any, ...] = DEVELOPMENT_SWEEP_MAXIMA,
) -> dict[str, Any]:
    """Evaluate one declared parameter family on the 60% development split only."""
    base = load_config(config_path)
    market_root = Path(market_root)
    output_dir = Path(output_dir)
    m1 = load_bar_parquet(market_root / "bars" / "M1.parquet")
    m5 = load_bar_parquet(market_root / "bars" / "M5.parquet")
    m15 = load_bar_parquet(market_root / "bars" / "M15.parquet")
    level_map = build_liquidity_level_map(m1)
    all_dates = sorted(level_map)
    development_count = int(len(all_dates) * 0.6)
    development_dates = all_dates[:development_count]
    development_end = development_dates[-1]
    tick_store = TickParquetStore(market_root / "ticks" / "year=*" / "ticks.parquet")
    grid_rows: list[dict[str, Any]] = []
    all_trade_rows: list[dict[str, Any]] = []
    funnel = Counter()

    if parameter not in {
        "sweep_atr_max",
        "max_stop_atr",
        "allow_same_bar_reclaim",
    }:
        raise ValueError(f"unsupported recalibration parameter: {parameter}")
    for parameter_value in candidate_values:
        config = replace(base, **{parameter: parameter_value})
        for window in base.candidate_sessions_ny:
            trades: list[TradeResult] = []
            trade_years: list[int] = []
            signal_count = 0
            evaluated_sessions = 0
            for local_date in development_dates:
                start, end = new_york_session_bounds(local_date, window)
                result = evaluate_session_bounds(
                    m5,
                    m15,
                    level_map[local_date],
                    start,
                    end,
                    config,
                    window=window,
                )
                if not result.decisions:
                    continue
                evaluated_sessions += 1
                for decision in result.decisions:
                    funnel[
                        (
                            parameter_value,
                            window,
                            decision.reasons[-1].value,
                        )
                    ] += 1
                if not result.qualified_signals:
                    continue
                signal_count += len(result.qualified_signals)
                ticks = tick_store.slice(start, end)
                session_trades = run_signal_backtest(
                    result.qualified_signals,
                    ticks,
                    session_end=end,
                    max_trades=config.max_trades,
                    daily_loss_limit_r=config.daily_loss_limit
                    / config.risk_per_trade,
                )
                for trade in session_trades:
                    trades.append(trade)
                    trade_years.append(local_date.year)
                    all_trade_rows.append(
                        _trade_payload(
                            trade,
                            local_date=local_date,
                            window=window,
                            parameter=parameter,
                            parameter_value=parameter_value,
                        )
                    )
            metrics = summarize(trades)
            net = np.array([item.net_r for item in trades], dtype=float)
            standard_error = (
                float(net.std(ddof=1) / math.sqrt(len(net))) if len(net) > 1 else float("inf")
            )
            stressed_expectancy = (
                metrics.expectancy_r - DEVELOPMENT_ADDITIONAL_COST_R
                if metrics.trade_count
                else 0.0
            )
            robust_score = stressed_expectancy - standard_error
            if trade_years:
                year_counts = pd.Series(trade_years).value_counts()
                maximum_year_share = float(year_counts.max() / len(trade_years))
            else:
                maximum_year_share = 1.0
            viable = assess_development_candidate(
                trade_count=metrics.trade_count,
                stressed_expectancy_r=stressed_expectancy,
                profit_factor=metrics.profit_factor,
                max_drawdown_r=metrics.max_drawdown_r,
                maximum_year_share=maximum_year_share,
            )
            grid_rows.append(
                {
                    parameter: parameter_value,
                    "window": window,
                    "development_start": development_dates[0].isoformat(),
                    "development_end": development_end.isoformat(),
                    "evaluated_sessions": evaluated_sessions,
                    "qualified_signals": signal_count,
                    "trade_count": metrics.trade_count,
                    "win_rate": metrics.win_rate,
                    "expectancy_r": metrics.expectancy_r,
                    "stressed_expectancy_r": stressed_expectancy,
                    "profit_factor": metrics.profit_factor
                    if math.isfinite(metrics.profit_factor)
                    else None,
                    "max_drawdown_r": metrics.max_drawdown_r,
                    "maximum_year_share": maximum_year_share,
                    "standard_error_r": standard_error
                    if math.isfinite(standard_error)
                    else None,
                    "robust_score": robust_score
                    if math.isfinite(robust_score)
                    else -999.0,
                    "development_viable": viable,
                }
            )

    grid = pd.DataFrame(grid_rows)
    selected = select_development_candidate(grid, parameter=parameter)
    output_dir.mkdir(parents=True, exist_ok=True)
    grid.to_csv(output_dir / f"{version}-development-grid.csv", index=False)
    pd.DataFrame(all_trade_rows).to_csv(
        output_dir / f"{version}-development-trades.csv", index=False
    )
    pd.DataFrame(
        [
            {
                parameter: key[0],
                "window": key[1],
                "final_reason": key[2],
                "decision_count": count,
            }
            for key, count in sorted(funnel.items())
        ]
    ).to_csv(output_dir / f"{version}-development-funnel.csv", index=False)
    selected_config = None
    if selected is not None:
        selected_config = asdict(
            replace(base, **{parameter: selected[parameter]})
        )
        selected_config["candidate_sessions_ny"] = [selected["window"]]
        (output_dir / f"{version}-development-selected-config.json").write_text(
            json.dumps(selected_config, indent=2), encoding="utf-8"
        )
    summary = {
        "version": f"{version}-development",
        "parameter_changed": parameter,
        "base_value": getattr(base, parameter),
        "candidate_values": list(candidate_values),
        "additional_cost_stress_r": DEVELOPMENT_ADDITIONAL_COST_R,
        "development_start": development_dates[0].isoformat(),
        "development_end": development_end.isoformat(),
        "validation_accessed": False,
        "test_accessed": False,
        "selected": selected,
        "status": "development_candidate_selected"
        if selected is not None
        else "development_rejected",
    }
    (output_dir / f"{version}-development-summary.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8"
    )
    return summary


def run_stop_development_experiment(
    config_path: Path,
    market_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    return run_development_experiment(
        config_path,
        market_root,
        output_dir,
        version="v0.3",
        parameter="max_stop_atr",
        candidate_values=DEVELOPMENT_STOP_MAXIMA,
    )


def run_same_bar_development_experiment(
    config_path: Path,
    market_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    return run_development_experiment(
        config_path,
        market_root,
        output_dir,
        version="v0.4",
        parameter="allow_same_bar_reclaim",
        candidate_values=DEVELOPMENT_SAME_BAR_RECLAIM,
    )
