import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import duckdb

from gscalp.grid_config import load_grid_config
from gscalp.grid_metrics import GridMetrics
from gscalp.grid_pipeline import (
    PartitionEvaluation,
    WindowEvaluation,
    plan_session,
    run_grid_research,
)
from gscalp.grid_models import GridReason
from gscalp.mt5_read import SymbolSpec


def metrics(**changes: float | int) -> GridMetrics:
    baseline = GridMetrics(
        basket_count=100,
        win_rate=0.60,
        expectancy_r=0.20,
        profit_factor=1.50,
        max_drawdown_r=3.0,
        max_consecutive_losses=3,
        average_mfe_r=0.60,
        average_mae_r=-0.20,
        forced_close_rate=0.10,
        average_levels_filled=1.50,
        maximum_year_share=0.30,
        worst_basket_r=-1.00,
    )
    return replace(baseline, **changes)


def evaluation(
    window: str,
    *,
    partition: str,
    base_expectancy: float = 0.20,
    stressed_expectancy: float = 0.10,
    standard_error: float = 0.01,
    basket_count: int = 100,
) -> WindowEvaluation:
    return WindowEvaluation(
        window=window,
        partition=partition,
        base=metrics(basket_count=basket_count, expectancy_r=base_expectancy),
        stressed=metrics(
            basket_count=basket_count, expectancy_r=stressed_expectancy
        ),
        standard_error=standard_error,
    )


class SpySource:
    data_manifest_sha256 = "d" * 64

    def __init__(self, development, validation=(), test=()):
        self.calls = []
        self._development = PartitionEvaluation("development", tuple(development))
        self._validation = PartitionEvaluation("validation", tuple(validation))
        self._test = PartitionEvaluation("test", tuple(test))

    def load_development(self):
        self.calls.append("development")
        return self._development

    def load_validation(self):
        self.calls.append("validation")
        return self._validation

    def load_test(self):
        self.calls.append("test")
        return self._test


@pytest.fixture
def grid_config_path() -> Path:
    return Path(__file__).parents[1] / "config" / "grid-v1.0.json"


def test_failed_development_never_reads_validation_or_test(
    tmp_path, grid_config_path
):
    source = SpySource(
        [
            evaluation(
                "08:45-09:45",
                partition="development",
                basket_count=99,
            ),
            evaluation(
                "09:30-10:30",
                partition="development",
                stressed_expectancy=0.0,
            ),
        ]
    )

    summary = run_grid_research(
        grid_config_path,
        tmp_path / "market",
        tmp_path / "reports",
        source=source,
    )

    assert source.calls == ["development"]
    assert summary.status == "development_rejected"
    assert not summary.test_accessed


def test_failed_validation_never_reads_test(tmp_path, grid_config_path):
    source = SpySource(
        [
            evaluation("08:45-09:45", partition="development"),
            evaluation("09:30-10:30", partition="development"),
        ],
        [
            evaluation(
                "08:45-09:45", partition="validation", basket_count=29
            ),
            evaluation(
                "09:30-10:30",
                partition="validation",
                stressed_expectancy=0.0,
                basket_count=30,
            ),
        ],
    )

    summary = run_grid_research(
        grid_config_path,
        tmp_path / "market",
        tmp_path / "reports",
        source=source,
    )

    assert source.calls == ["development", "validation"]
    assert summary.status == "validation_rejected"
    assert not summary.test_accessed


def test_passing_validation_reads_test_once(tmp_path, grid_config_path):
    source = SpySource(
        [
            evaluation("08:45-09:45", partition="development"),
            evaluation("09:30-10:30", partition="development"),
        ],
        [
            evaluation(
                "08:45-09:45",
                partition="validation",
                basket_count=30,
            ),
            evaluation(
                "09:30-10:30",
                partition="validation",
                stressed_expectancy=0.09,
                basket_count=30,
            ),
        ],
        [
            evaluation(
                "08:45-09:45",
                partition="test",
                basket_count=20,
            )
        ],
    )

    summary = run_grid_research(
        grid_config_path,
        tmp_path / "market",
        tmp_path / "reports",
        source=source,
    )

    assert source.calls == ["development", "validation", "test"]
    assert summary.status == "historical_passed"
    assert summary.test_accessed


def test_window_selection_uses_validation_stress_penalty_and_not_test_metrics(
    tmp_path, grid_config_path
):
    source = SpySource(
        [
            evaluation("08:45-09:45", partition="development"),
            evaluation("09:30-10:30", partition="development"),
        ],
        [
            evaluation(
                "08:45-09:45",
                partition="validation",
                base_expectancy=0.30,
                stressed_expectancy=0.12,
                standard_error=0.01,
                basket_count=30,
            ),
            evaluation(
                "09:30-10:30",
                partition="validation",
                base_expectancy=0.10,
                stressed_expectancy=0.20,
                standard_error=0.12,
                basket_count=30,
            ),
        ],
        [
            evaluation(
                "08:45-09:45",
                partition="test",
                base_expectancy=0.01,
                basket_count=20,
            ),
            evaluation(
                "09:30-10:30",
                partition="test",
                base_expectancy=9.0,
                basket_count=20,
            ),
        ],
    )

    summary = run_grid_research(
        grid_config_path,
        tmp_path / "market",
        tmp_path / "reports",
        source=source,
    )

    assert summary.selected_window == "08:45-09:45"
    assert source.calls == ["development", "validation", "test"]


def test_partition_source_evaluates_only_viable_then_selected_windows(
    tmp_path, grid_config_path
):
    class WindowAwareSource:
        data_manifest_sha256 = "a" * 64

        def __init__(self):
            self.calls = []

        def load_development(self):
            self.calls.append(("development", None))
            return PartitionEvaluation(
                "development",
                (
                    evaluation("08:45-09:45", partition="development"),
                    evaluation(
                        "09:30-10:30",
                        partition="development",
                        basket_count=99,
                    ),
                ),
            )

        def load_validation(self, windows):
            self.calls.append(("validation", tuple(windows)))
            return PartitionEvaluation(
                "validation",
                (
                    evaluation(
                        "08:45-09:45",
                        partition="validation",
                        basket_count=30,
                    ),
                ),
            )

        def load_test(self, windows):
            self.calls.append(("test", tuple(windows)))
            return PartitionEvaluation(
                "test",
                (
                    evaluation(
                        "08:45-09:45", partition="test", basket_count=20
                    ),
                ),
            )

    source = WindowAwareSource()

    run_grid_research(
        grid_config_path,
        tmp_path / "market",
        tmp_path / "reports",
        source=source,
    )

    assert source.calls == [
        ("development", None),
        ("validation", ("08:45-09:45",)),
        ("test", ("08:45-09:45",)),
    ]


def test_pipeline_writes_all_artifacts_and_strict_json(
    tmp_path, grid_config_path
):
    no_losses = metrics(profit_factor=float("inf"))
    source = SpySource(
        [
            WindowEvaluation(
                "08:45-09:45",
                "development",
                no_losses,
                no_losses,
                0.01,
                reason_counts={"neutral_bias": 2},
            )
        ]
    )
    output = tmp_path / "reports"

    summary = run_grid_research(
        grid_config_path, tmp_path / "market", output, source=source
    )

    expected = {
        "development",
        "validation",
        "test",
        "baskets",
        "legs",
        "rejections",
        "stress",
        "summary",
    }
    assert {
        path.name.removeprefix("grid-v1.0-").split(".")[0]
        for path in output.iterdir()
    } == expected
    payload = json.loads(
        (output / "grid-v1.0-summary.json").read_text(encoding="utf-8"),
        parse_constant=lambda value: pytest.fail(f"non-finite JSON: {value}"),
    )
    assert payload["development"]["08:45-09:45"]["base"]["profit_factor"] is None
    assert payload["reason_counts"] == {"neutral_bias": 2}
    assert payload["config_sha256"] == summary.config_sha256
    assert payload["data_manifest_sha256"] == "d" * 64


def test_plan_session_uses_only_pre_session_inputs_and_first_session_tick(
    grid_config_path,
):
    config = load_grid_config(grid_config_path)
    m15_index = pd.date_range(
        "2026-07-15 05:00", periods=31, freq="15min", tz="UTC"
    )
    close = pd.Series(
        [88.0 + number * 0.4 for number in range(len(m15_index))],
        index=m15_index,
    )
    m15 = pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
        },
        index=m15_index,
    )
    m5_index = pd.date_range(
        "2026-07-15 11:00", periods=21, freq="5min", tz="UTC"
    )
    lows = [95.0] * 18 + [91.0, 96.0, 97.0]
    m5 = pd.DataFrame(
        {
            "open": [100.0] * 21,
            "high": [105.0] * 21,
            "low": lows,
            "close": [100.0] * 21,
        },
        index=m5_index,
    )
    ticks = pd.DataFrame(
        {
            "bid": [99.8, 99.8, 99.8, 99.7, 1.0],
            "ask": [100.0, 100.0, 100.0, 100.0, 1_000.0],
        },
        index=pd.DatetimeIndex(
            [
                "2026-07-15 12:20:00+00:00",
                "2026-07-15 12:30:00+00:00",
                "2026-07-15 12:40:00+00:00",
                "2026-07-15 12:45:00+00:00",
                "2026-07-15 12:46:00+00:00",
            ]
        ),
    )

    class FixedCalculator:
        def loss_for_one_lot(self, direction, entry, stop):
            return -100.0

        def margin_for_volume(self, direction, volume, entry):
            return 100.0

    result = plan_session(
        local_date=date(2026, 7, 15),
        window="08:45-09:45",
        m5=m5,
        m15=m15,
        ticks=ticks,
        symbol=SymbolSpec(
            "XAUUSD", 2, 0.01, 0.01, 1.0, 100.0, 0.01, 0.01, 10, 0
        ),
        config=config,
        calculator=FixedCalculator(),
        starting_equity=10_000.0,
        free_margin=10_000.0,
        spread_ceiling=0.50,
    )

    assert result.reason is GridReason.GRID_ARMED
    assert result.plan is not None
    assert result.plan.geometry.anchor == 100.0
    assert result.plan.geometry.reference_spread == pytest.approx(0.20)


def test_default_source_consumes_canonical_partitioned_parquet_without_mt5(
    tmp_path, grid_config_path
):
    market = tmp_path / "market"
    bars = market / "bars"
    ticks = market / "ticks" / "year=2020"
    bars.mkdir(parents=True)
    ticks.mkdir(parents=True)
    (market / "manifest.json").write_text(
        json.dumps({"dataset": "canonical-test-fixture"}), encoding="utf-8"
    )

    def write_parquet(frame, path):
        connection = duckdb.connect()
        try:
            connection.register("fixture", frame)
            connection.execute(f"COPY fixture TO '{path.as_posix()}' (FORMAT PARQUET)")
        finally:
            connection.close()

    def canonical_bars(index):
        close = [100.0] * len(index)
        return pd.DataFrame(
            {
                "Timestamp": index.tz_localize(None),
                "BidOpen": close,
                "BidHigh": [101.0] * len(index),
                "BidLow": [99.0] * len(index),
                "BidClose": close,
            }
        )

    write_parquet(
        canonical_bars(
            pd.date_range("2020-01-02 00:00", periods=180, freq="5min", tz="UTC")
        ),
        bars / "M5.parquet",
    )
    write_parquet(
        canonical_bars(
            pd.date_range("2020-01-01 00:00", periods=80, freq="15min", tz="UTC")
        ),
        bars / "M15.parquet",
    )
    tick_index = pd.DatetimeIndex(
        [
            "2020-01-02 13:20:00+00:00",
            "2020-01-02 13:30:00+00:00",
            "2020-01-02 13:45:00+00:00",
            "2020-01-02 14:00:00+00:00",
            "2020-01-02 14:30:00+00:00",
        ]
    )
    write_parquet(
        pd.DataFrame(
            {
                "Timestamp": tick_index.tz_localize(None),
                "Bid": [99.8] * len(tick_index),
                "Ask": [100.0] * len(tick_index),
            }
        ),
        ticks / "ticks.parquet",
    )

    summary = run_grid_research(
        grid_config_path, market, tmp_path / "reports"
    )

    assert summary.status == "development_rejected"
    assert not summary.test_accessed
    assert len(summary.data_manifest_sha256) == 64
