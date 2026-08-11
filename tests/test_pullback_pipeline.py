import json

import duckdb
import pandas as pd
import pytest

from gscalp.pullback_config import load_pullback_config
from gscalp.pullback_metrics import PullbackMetrics
from gscalp.pullback_pipeline import (
    CandidateEvaluation,
    ParquetPullbackSource,
    PartitionEvaluation,
    session_bar_context,
    run_pullback_research,
)


def metrics(count, *, expectancy=0.10, error=0.02, profit_factor=1.30):
    return PullbackMetrics(
        trade_count=count,
        win_rate=0.55 if count else 0.0,
        expectancy_r=expectancy if count else float("-inf"),
        standard_deviation_r=0.50 if count else float("inf"),
        standard_error_r=error if count else float("inf"),
        profit_factor=profit_factor if count else 0.0,
        max_drawdown_r=4.0 if count else 0.0,
        minimum_trade_r=-1.0 if count else float("-inf"),
        maximum_year_share=0.34 if count else 1.0,
    )


def evaluation(candidate, partition, count, *, stressed_expectancy=0.08, error=0.02):
    base = metrics(count)
    stressed = metrics(count, expectancy=stressed_expectancy, error=error)
    return CandidateEvaluation(
        candidate=candidate,
        partition=partition,
        base=base,
        spread_stress=stressed,
        cost_stress=stressed,
        bootstrap_lower=0.0,
        spread_ceiling=0.30,
    )


class SpySource:
    data_manifest_sha256 = "a" * 64
    news_sha256 = "b" * 64

    def __init__(self, development, validation=(), test=(), *, bypass=False):
        self.development = PartitionEvaluation("development", tuple(development))
        self.validation = PartitionEvaluation("validation", tuple(validation))
        self.test = PartitionEvaluation("test", tuple(test))
        self.news_bypass_used = bypass
        self.validation_calls = []
        self.test_calls = []

    def load_development(self):
        return self.development

    def load_validation(self, candidate_ids):
        self.validation_calls.append(candidate_ids)
        return self.validation

    def load_test(self, candidate_id):
        self.test_calls.append(candidate_id)
        return self.test


def candidates():
    config = load_pullback_config("config/pullback-v1.1.json")
    return config.candidates()[0], config.candidates()[1]


def run(tmp_path, source):
    return run_pullback_research(
        "config/pullback-v1.1.json",
        tmp_path / "market-unused",
        tmp_path / "reports",
        source=source,
    )


def test_failed_development_never_reads_validation_or_test(tmp_path):
    first, _ = candidates()
    source = SpySource([evaluation(first, "development", 0)])

    summary = run(tmp_path, source)

    assert summary.status == "development_rejected"
    assert summary.development_accessed is True
    assert summary.validation_accessed is False
    assert summary.test_accessed is False
    assert source.validation_calls == []
    assert source.test_calls == []


def test_failed_validation_never_reads_test(tmp_path):
    first, _ = candidates()
    source = SpySource(
        [evaluation(first, "development", 100)],
        [evaluation(first, "validation", 0)],
    )

    summary = run(tmp_path, source)

    assert summary.status == "validation_rejected"
    assert source.validation_calls == [(first.candidate_id,)]
    assert source.test_calls == []
    assert summary.test_accessed is False


def test_validation_score_selects_one_candidate_before_test_access(tmp_path):
    first, second = candidates()
    source = SpySource(
        [
            evaluation(first, "development", 100),
            evaluation(second, "development", 100),
        ],
        [
            evaluation(first, "validation", 30, stressed_expectancy=0.20, error=0.10),
            evaluation(second, "validation", 30, stressed_expectancy=0.15, error=0.01),
        ],
        [evaluation(second, "test", 20)],
    )

    summary = run(tmp_path, source)

    assert summary.status == "historical_passed"
    assert summary.selected_candidate == second.candidate_id
    assert source.test_calls == [second.candidate_id]
    assert summary.historical_gate_passed is True
    assert summary.promotion_eligible is True


def test_exact_validation_score_tie_uses_lexical_candidate_id(tmp_path):
    first, second = candidates()
    expected = min(first.candidate_id, second.candidate_id)
    source = SpySource(
        [evaluation(first, "development", 100), evaluation(second, "development", 100)],
        [
            evaluation(first, "validation", 30, stressed_expectancy=0.15, error=0.05),
            evaluation(second, "validation", 30, stressed_expectancy=0.15, error=0.05),
        ],
        [evaluation(first if first.candidate_id == expected else second, "test", 20)],
    )

    summary = run(tmp_path, source)

    assert summary.selected_candidate == expected
    assert source.test_calls == [expected]


def test_failed_test_retires_candidate(tmp_path):
    first, _ = candidates()
    source = SpySource(
        [evaluation(first, "development", 100)],
        [evaluation(first, "validation", 30)],
        [evaluation(first, "test", 19)],
    )

    summary = run(tmp_path, source)

    assert summary.status == "test_rejected"
    assert summary.historical_gate_passed is False
    assert summary.promotion_eligible is False


def test_news_bypass_can_pass_performance_but_never_promote(tmp_path):
    first, _ = candidates()
    source = SpySource(
        [evaluation(first, "development", 100)],
        [evaluation(first, "validation", 30)],
        [evaluation(first, "test", 20)],
        bypass=True,
    )

    summary = run(tmp_path, source)

    assert summary.status == "historical_passed"
    assert summary.historical_gate_passed is True
    assert summary.promotion_eligible is False


def test_pipeline_writes_all_strict_versioned_artifacts(tmp_path):
    first, _ = candidates()
    source = SpySource([evaluation(first, "development", 0)])

    run(tmp_path, source)

    reports = tmp_path / "reports"
    expected = {
        "pullback-v1.1-development.csv",
        "pullback-v1.1-validation.csv",
        "pullback-v1.1-test.csv",
        "pullback-v1.1-trades.csv",
        "pullback-v1.1-rejections.csv",
        "pullback-v1.1-stress.csv",
        "pullback-v1.1-summary.json",
    }
    assert {path.name for path in reports.iterdir()} == expected
    raw = (reports / "pullback-v1.1-summary.json").read_text(encoding="utf-8")
    payload = json.loads(raw)
    assert "Infinity" not in raw
    assert "NaN" not in raw
    assert payload["application_can_trade"] is False
    assert payload["data_manifest_sha256"] == "a" * 64
    assert payload["news_sha256"] == "b" * 64
    assert payload["development"][first.candidate_id]["base"]["expectancy_r"] is None


def write_parquet(frame, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    connection = duckdb.connect()
    try:
        connection.register("fixture", frame)
        connection.execute(
            f"COPY fixture TO '{path.as_posix()}' (FORMAT PARQUET)"
        )
    finally:
        connection.close()


def canonical_market(tmp_path):
    market = tmp_path / "market"
    (market / "manifest.json").parent.mkdir(parents=True, exist_ok=True)
    (market / "manifest.json").write_text(
        json.dumps(
            {
                "timezone": "UTC",
                "fbs_demo_symbol": {
                    "server": "FBS-Demo",
                    "symbol": "XAUUSD",
                    "digits": 2,
                    "point": 0.01,
                    "tick_size": 0.01,
                    "contract_size": 100.0,
                    "volume_min": 0.01,
                    "volume_step": 0.01,
                    "volume_max": 100.0,
                    "stops_level": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    timestamps = pd.date_range("2020-01-02 12:00", periods=30, freq="1min")
    bars = pd.DataFrame(
        {
            "Timestamp": timestamps,
            "BidOpen": [100.0] * 30,
            "BidHigh": [101.0] * 30,
            "BidLow": [99.0] * 30,
            "BidClose": [100.0] * 30,
        }
    )
    for timeframe in ("M1", "M5", "M15", "H1"):
        write_parquet(bars, market / "bars" / f"{timeframe}.parquet")
    tick_times = pd.DatetimeIndex(
        [
            "2020-01-02 14:29:00",
            "2020-01-02 14:30:00",
            "2020-01-02 14:31:00",
            "2020-01-02 14:32:00",
            "2020-01-02 14:33:00",
            "2020-01-02 14:34:00",
        ]
    )
    write_parquet(
        pd.DataFrame(
            {
                "Timestamp": tick_times,
                "Bid": [100.0] * 6,
                "Ask": [100.1, 100.1, 100.2, 100.3, 100.4, 100.5],
            }
        ),
        market / "ticks" / "year=2020" / "ticks.parquet",
    )
    return market


def test_parquet_source_loads_canonical_bars_and_manifest_without_mt5(tmp_path):
    market = canonical_market(tmp_path)
    news = tmp_path / "news.csv"
    news.write_text(
        "event_start_utc,event_end_utc,currency,impact,event_name,source\n",
        encoding="utf-8",
    )
    source = ParquetPullbackSource(
        load_pullback_config("config/pullback-v1.1.json"),
        market,
        news_path=news,
    )

    for timeframe in ("M1", "M5", "M15", "H1"):
        frame = source._load_bars(
            timeframe,
            pd.Timestamp("2020-01-02 11:00:00+00:00"),
            pd.Timestamp("2020-01-02 13:00:00+00:00"),
        )
        assert frame.index.tz is not None
        assert list(frame.columns[:4]) == ["open", "high", "low", "close"]
        assert len(frame) == 30
    assert len(source.data_manifest_sha256) == 64


def test_strict_news_decisions_and_bypass_label_are_auditable(tmp_path):
    market = canonical_market(tmp_path)
    config = load_pullback_config("config/pullback-v1.1.json")
    start = pd.Timestamp("2020-01-02 14:30:00+00:00")
    end = start + pd.Timedelta(hours=1)
    missing = ParquetPullbackSource(config, market, news_path=tmp_path / "missing.csv")

    assert missing._news_block_details(start, end)["news_status"] == "missing_confirmation"

    clear_path = tmp_path / "clear.csv"
    clear_path.write_text(
        "event_start_utc,event_end_utc,currency,impact,event_name,source\n"
        "2020-01-02T14:00:00Z,2020-01-02T16:00:00Z,ALL,none,"
        "NO_HIGH_IMPACT_EVENTS,verified-source\n",
        encoding="utf-8",
    )
    clear = ParquetPullbackSource(config, market, news_path=clear_path)
    assert clear._news_block_details(start, end) is None
    assert clear.news_bypass_used is False

    blackout_path = tmp_path / "blackout.csv"
    blackout_path.write_text(
        "event_start_utc,event_end_utc,currency,impact,event_name,source\n"
        "2020-01-02T15:00:00Z,2020-01-02T15:15:00Z,USD,high,CPI,official\n",
        encoding="utf-8",
    )
    blackout = ParquetPullbackSource(config, market, news_path=blackout_path)
    details = blackout._news_block_details(start, end)
    assert details == {
        "news_status": "high_impact_overlap",
        "news_event": "CPI",
        "news_source": "official",
    }

    bypass_path = tmp_path / "bypass.csv"
    bypass_path.write_text(
        "event_start_utc,event_end_utc,currency,impact,event_name,source\n"
        "2020-01-02T14:00:00Z,2020-01-02T16:00:00Z,ALL,none,"
        "NO_HIGH_IMPACT_EVENTS,USER_APPROVED_NEWS_BYPASS_NOT_SOURCE_BACKED\n",
        encoding="utf-8",
    )
    bypass = ParquetPullbackSource(config, market, news_path=bypass_path)
    assert bypass.news_bypass_used is True


def test_development_spread_ceiling_is_exact_window_quantile(tmp_path):
    market = canonical_market(tmp_path)
    news = tmp_path / "news.csv"
    news.write_text(
        "event_start_utc,event_end_utc,currency,impact,event_name,source\n",
        encoding="utf-8",
    )
    source = ParquetPullbackSource(
        load_pullback_config("config/pullback-v1.1.json"), market, news_path=news
    )

    source._lock_development_spread_ceilings([pd.Timestamp("2020-01-02").date()])

    assert source.development_spread_ceilings["09:30-10:30"] == pytest.approx(0.46)


def test_tick_batch_returns_session_keyed_frames(tmp_path):
    market = canonical_market(tmp_path)
    news = tmp_path / "news.csv"
    news.write_text(
        "event_start_utc,event_end_utc,currency,impact,event_name,source\n",
        encoding="utf-8",
    )
    source = ParquetPullbackSource(
        load_pullback_config("config/pullback-v1.1.json"), market, news_path=news
    )
    local_date = pd.Timestamp("2020-01-02").date()

    batches = source._load_tick_batch([local_date], ("09:30-10:30",))

    frame = batches[("09:30-10:30", local_date)]
    assert list(frame.columns) == ["bid", "ask"]
    assert frame.index.tz is not None
    assert list(frame.index) == list(
        pd.to_datetime(
            [
                "2020-01-02 14:29:00Z",
                "2020-01-02 14:30:00Z",
                "2020-01-02 14:31:00Z",
                "2020-01-02 14:32:00Z",
                "2020-01-02 14:33:00Z",
                "2020-01-02 14:34:00Z",
            ]
        )
    )


def test_reference_spreads_are_aggregated_per_session(tmp_path):
    market = canonical_market(tmp_path)
    news = tmp_path / "news.csv"
    news.write_text(
        "event_start_utc,event_end_utc,currency,impact,event_name,source\n",
        encoding="utf-8",
    )
    source = ParquetPullbackSource(
        load_pullback_config("config/pullback-v1.1.json"), market, news_path=news
    )
    local_date = pd.Timestamp("2020-01-02").date()

    spreads = source._load_reference_spreads(
        [local_date],
        ("09:30-10:30",),
    )

    assert spreads[("09:30-10:30", local_date)] == pytest.approx(0.10)


def test_unarmed_setup_does_not_materialize_session_ticks(tmp_path, monkeypatch):
    import gscalp.pullback_pipeline as pipeline
    from gscalp.pullback_models import (
        BiasDecision,
        PullbackReason,
        SetupDecision,
        TradeDirection,
    )

    market = canonical_market(tmp_path)
    news = tmp_path / "clear.csv"
    news.write_text(
        "event_start_utc,event_end_utc,currency,impact,event_name,source\n"
        "2020-01-02T14:00:00Z,2020-01-02T16:00:00Z,ALL,none,"
        "NO_HIGH_IMPACT_EVENTS,verified-source\n",
        encoding="utf-8",
    )
    config = load_pullback_config("config/pullback-v1.1.json")
    source = ParquetPullbackSource(config, market, news_path=news)
    selected = config.candidates()[12]
    source.development_spread_ceilings[selected.session_ny] = 0.30

    def bullish_bias(_h1, _m15, session_start, _config):
        return BiasDecision(
            TradeDirection.LONG,
            PullbackReason.SETUP_ARMED,
            session_start,
            101.0,
            100.0,
            99.0,
            101.0,
            100.0,
            99.0,
        )

    monkeypatch.setattr(pipeline, "evaluate_locked_bias", bullish_bias)
    monkeypatch.setattr(
        pipeline,
        "detect_pullback_setup",
        lambda *_args, **_kwargs: SetupDecision(None, PullbackReason.NO_PULLBACK),
    )
    monkeypatch.setattr(
        source,
        "_load_tick_batch",
        lambda *_args, **_kwargs: pytest.fail(
            "raw session ticks must not load before a setup arms"
        ),
    )

    result = source._evaluate(
        "validation",
        pd.Timestamp("2020-01-02").date(),
        pd.Timestamp("2020-01-02").date(),
        (selected.candidate_id,),
    )

    assert result.candidates[0].reason_counts == {"no_pullback": 1}


def test_missing_news_blocks_candidate_before_any_signal_evaluation(tmp_path):
    market = canonical_market(tmp_path)
    config = load_pullback_config("config/pullback-v1.1.json")
    source = ParquetPullbackSource(config, market, news_path=tmp_path / "missing.csv")
    first = config.candidates()[12]
    source.development_spread_ceilings[first.session_ny] = 0.30

    result = source._evaluate(
        "development",
        pd.Timestamp("2020-01-02").date(),
        pd.Timestamp("2020-01-02").date(),
        (first.candidate_id,),
    )

    assert len(result.candidates) == 1
    item = result.candidates[0]
    assert item.base.trade_count == 0
    assert item.reason_counts == {"news_blocked": 1}
    assert item.rejection_rows[0]["news_status"] == "missing_confirmation"


def test_source_runs_one_causal_session_from_bias_through_tick_exit(tmp_path):
    from test_pullback_bias import aligned_frames
    from test_pullback_setup import long_frames

    market = canonical_market(tmp_path)
    m1, m5 = long_frames()
    h1, m15 = aligned_frames(rising=True)

    def canonical(frame):
        result = frame.reset_index(names="Timestamp").rename(
            columns={
                "open": "BidOpen",
                "high": "BidHigh",
                "low": "BidLow",
                "close": "BidClose",
            }
        )
        result["Timestamp"] = result["Timestamp"].dt.tz_localize(None)
        return result

    for timeframe, frame in (("M1", m1), ("M5", m5), ("M15", m15), ("H1", h1)):
        write_parquet(canonical(frame), market / "bars" / f"{timeframe}.parquet")
    tick_index = pd.DatetimeIndex(
        [
            "2026-07-15 13:00:00",
            "2026-07-15 13:29:59",
            "2026-07-15 13:30:00",
            "2026-07-15 13:55:59",
            "2026-07-15 13:56:00",
            "2026-07-15 13:57:00",
        ]
    )
    write_parquet(
        pd.DataFrame(
            {
                "Timestamp": tick_index,
                "Bid": [99.8, 99.8, 99.8, 100.4, 100.6, 101.3],
                "Ask": [100.0, 100.0, 100.0, 100.6, 100.8, 101.5],
            }
        ),
        market / "ticks" / "year=2026" / "ticks.parquet",
    )
    news = tmp_path / "clear.csv"
    news.write_text(
        "event_start_utc,event_end_utc,currency,impact,event_name,source\n"
        "2026-07-15T13:00:00Z,2026-07-15T15:00:00Z,ALL,none,"
        "NO_HIGH_IMPACT_EVENTS,verified-source\n",
        encoding="utf-8",
    )
    config = load_pullback_config("config/pullback-v1.1.json")
    source = ParquetPullbackSource(config, market, news_path=news)
    selected = config.candidates()[12]
    source.development_spread_ceilings[selected.session_ny] = 0.30

    result = source._evaluate(
        "validation",
        pd.Timestamp("2026-07-15").date(),
        pd.Timestamp("2026-07-15").date(),
        (selected.candidate_id,),
    )

    item = result.candidates[0]
    assert item.base.trade_count == 1
    assert len(item.trades) == 1
    assert item.trades[0].entry_time == pd.Timestamp("2026-07-15 13:56:00+00:00")
    assert item.trades[0].exit_time == pd.Timestamp("2026-07-15 13:57:00+00:00")
    assert item.trades[0].reason.value == "target_closed"


def test_session_bar_context_discards_unrelated_partition_history():
    index = pd.date_range("2020-01-01", periods=10_000, freq="1min", tz="UTC")
    bars = pd.DataFrame({"close": range(10_000)}, index=index)
    session_start = index[8_000]
    session_end = session_start + pd.Timedelta(minutes=60)

    context = session_bar_context(
        bars,
        session_start,
        session_end,
        warmup_rows=40,
    )

    assert len(context) == 100
    assert context.index[0] == index[7_960]
    assert context.index[-1] == index[8_059]
