from __future__ import annotations

import json
import math
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from .backtest import TradeResult, run_signal_backtest
from .config import load_config
from .metrics import MetricsReport, summarize
from .research import (
    TickParquetStore,
    build_liquidity_level_map,
    evaluate_session_bounds,
    load_bar_parquet,
    new_york_session_bounds,
)


def assess_historical_gate(
    *,
    trade_count: int,
    test_trade_count: int,
    test_expectancy_r: float,
    test_profit_factor: float,
    max_drawdown_r: float,
) -> bool:
    return bool(
        trade_count >= 40
        and test_trade_count >= 8
        and test_expectancy_r > 0
        and test_profit_factor > 1.10
        and max_drawdown_r <= 8.0
    )


def _json_number(value: float) -> float | None:
    return float(value) if math.isfinite(float(value)) else None


def _metrics_payload(report: MetricsReport) -> dict[str, Any]:
    payload = asdict(report)
    return {
        key: _json_number(value) if isinstance(value, float) else value
        for key, value in payload.items()
    }


def _split_map(dates: list[date]) -> tuple[dict[date, str], date, date]:
    development_end = max(1, int(len(dates) * 0.6))
    validation_end = max(development_end + 1, int(len(dates) * 0.8))
    mapping = {
        item: (
            "development"
            if index < development_end
            else "validation"
            if index < validation_end
            else "test_untouched"
        )
        for index, item in enumerate(dates)
    }
    return mapping, dates[development_end - 1], dates[validation_end - 1]


def _decision_row(result: Any, decision: Any, decision_bar: pd.Timestamp) -> dict[str, Any]:
    return {
        "local_date": result.local_date.isoformat(),
        "window": result.window,
        "session_start": result.session_start.isoformat(),
        "session_end": result.session_end.isoformat(),
        "decision_bar": decision_bar.isoformat(),
        "signal_time": None
        if decision.signal_time is None
        else decision.signal_time.isoformat(),
        "eligible": decision.eligible,
        "direction": None if decision.direction is None else decision.direction.value,
        "entry": decision.entry,
        "stop": decision.stop,
        "target": decision.target,
        "level_name": decision.level_name,
        "reasons": "|".join(item.value for item in decision.reasons),
        "diagnostics": json.dumps(dict(decision.diagnostics), sort_keys=True),
    }


def _trade_row(
    trade: TradeResult, *, local_date: date, window: str, split: str
) -> dict[str, Any]:
    payload = asdict(trade)
    payload["direction"] = trade.direction.value
    payload["exit_reason"] = trade.exit_reason.value
    payload["local_date"] = local_date.isoformat()
    payload["window"] = window
    payload["split"] = split
    return payload


def run_frozen_research(
    config_path: Path,
    market_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    config = load_config(config_path)
    market_root = Path(market_root)
    output_dir = Path(output_dir)
    m1 = load_bar_parquet(market_root / "bars" / "M1.parquet")
    m5 = load_bar_parquet(market_root / "bars" / "M5.parquet")
    m15 = load_bar_parquet(market_root / "bars" / "M15.parquet")
    level_map = build_liquidity_level_map(m1)
    dates = sorted(level_map)
    if len(dates) < 5:
        raise ValueError("at least five trading dates are required")
    partitions, development_end, validation_end = _split_map(dates)
    tick_store = TickParquetStore(market_root / "ticks" / "year=*" / "ticks.parquet")
    decisions: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    trade_objects: list[tuple[str, str, TradeResult]] = []
    evaluated_sessions = 0

    for window in config.candidate_sessions_ny:
        for local_date in dates:
            start, end = new_york_session_bounds(local_date, window)
            result = evaluate_session_bounds(
                m5, m15, level_map[local_date], start, end, config, window=window
            )
            if not result.decisions:
                continue
            evaluated_sessions += 1
            left = int(m5.index.searchsorted(start, side="left"))
            bars = m5.index[left : left + len(result.decisions)]
            for decision, decision_bar in zip(result.decisions, bars, strict=True):
                row = _decision_row(result, decision, decision_bar)
                decisions.append(row)
                if decision.eligible:
                    signals.append(row.copy())
            if result.qualified_signals:
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
                    split = partitions[local_date]
                    trade_rows.append(
                        _trade_row(trade, local_date=local_date, window=window, split=split)
                    )
                    trade_objects.append((window, split, trade))

    decision_frame = pd.DataFrame(decisions)
    signal_frame = pd.DataFrame(signals, columns=decision_frame.columns)
    trade_frame = pd.DataFrame(trade_rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    decision_frame.to_csv(output_dir / "v0.1-decisions.csv", index=False)
    decision_frame.loc[~decision_frame["eligible"]].to_csv(
        output_dir / "v0.1-rejections.csv", index=False
    )
    signal_frame.to_csv(output_dir / "v0.1-signals.csv", index=False)
    trade_frame.to_csv(output_dir / "v0.1-trades.csv", index=False)

    split_rows: list[dict[str, Any]] = []
    for window in config.candidate_sessions_ny:
        for split in ("development", "validation", "test_untouched"):
            items = [trade for w, s, trade in trade_objects if w == window and s == split]
            report = summarize(items)
            split_rows.append(
                {
                    "window": window,
                    "partition": split,
                    "trade_count": report.trade_count,
                    "expectancy_r": report.expectancy_r,
                    "profit_factor": _json_number(report.profit_factor),
                    "max_drawdown_r": report.max_drawdown_r,
                }
            )
    walk = pd.DataFrame(split_rows)
    walk.to_csv(output_dir / "v0.1-walk-forward.csv", index=False)

    development_validation = walk.loc[
        walk["partition"].isin(["development", "validation"])
    ]
    eligible_windows = []
    for window, group in development_validation.groupby("window"):
        if group["trade_count"].sum() >= 30:
            eligible_windows.append(window)
    selected_window = None
    if eligible_windows:
        scores = (
            development_validation.loc[
                development_validation["window"].isin(eligible_windows)
            ]
            .groupby("window")["expectancy_r"]
            .mean()
        )
        selected_window = str(scores.idxmax())

    all_report = summarize([item[2] for item in trade_objects])
    if selected_window is None:
        test_report = summarize([])
    else:
        test_report = summarize(
            [
                trade
                for window, split, trade in trade_objects
                if window == selected_window and split == "test_untouched"
            ]
        )
    gate = assess_historical_gate(
        trade_count=all_report.trade_count,
        test_trade_count=test_report.trade_count,
        test_expectancy_r=test_report.expectancy_r,
        test_profit_factor=test_report.profit_factor,
        max_drawdown_r=all_report.max_drawdown_r,
    )
    stress = pd.DataFrame(
        [
            {
                "additional_cost_r": cost,
                "trade_count": all_report.trade_count,
                "stressed_expectancy_r": (
                    all_report.expectancy_r - cost if all_report.trade_count else 0.0
                ),
            }
            for cost in (0.0, 0.05, 0.10, 0.20)
        ]
    )
    stress.to_csv(output_dir / "v0.1-stress.csv", index=False)
    summary = {
        "version": "v0.1",
        "status": "passed" if gate else "failed_insufficient_sample"
        if all_report.trade_count < 40
        else "failed_performance_gate",
        "historical_gate_passed": gate,
        "evaluated_sessions": evaluated_sessions,
        "qualified_signals": len(signals),
        "selected_window": selected_window,
        "development_end": development_end.isoformat(),
        "validation_end": validation_end.isoformat(),
        "all_diagnostic_metrics": _metrics_payload(all_report),
        "untouched_test_metrics": _metrics_payload(test_report),
        "cost_model": "Tickstory bid/ask executable prices; commission unavailable; explicit additional-cost stress reported separately.",
        "notes": [
            "A window is selectable only with at least 30 development-plus-validation trades.",
            "The untouched test partition is not used to tune strategy thresholds.",
            "Demo and shadow gates remain closed when historical_gate_passed is false.",
        ],
    }
    (output_dir / "v0.1-summary.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8"
    )
    return summary
