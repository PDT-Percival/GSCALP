import json
from types import SimpleNamespace

from gscalp.cli import main

from test_config import valid_payload


class DoctorMT5:
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 60
    def initialize(self, *, path):
        return True

    def last_error(self):
        return (0, "ok")

    def terminal_info(self):
        return SimpleNamespace(connected=True, path="C:/Program Files/FBS MetaTrader 5")

    def account_info(self):
        return SimpleNamespace(server="FBS-Demo", trade_mode=0, currency="USD")

    def symbol_select(self, symbol, enabled):
        return True

    def symbol_info(self, symbol):
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
            }
        ]

    def shutdown(self):
        pass


def test_doctor_reports_read_only_application_state(tmp_path, capsys):
    config = tmp_path / "strategy.json"
    config.write_text(json.dumps(valid_payload()), encoding="utf-8")

    exit_code = main(
        ["doctor", "--config", str(config)], mt5_module=DoctorMT5()
    )

    report = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert report["connected"] is True
    assert report["server"] == "FBS-Demo"
    assert report["symbol"] == "XAUUSD"
    assert report["application_can_trade"] is False


def test_download_writes_csv_and_manifest_without_trading(tmp_path, capsys):
    config = tmp_path / "strategy.json"
    config.write_text(json.dumps(valid_payload()), encoding="utf-8")
    output = tmp_path / "market"

    exit_code = main(
        [
            "download",
            "--config",
            str(config),
            "--days",
            "1",
            "--timeframes",
            "M1",
            "M5",
            "--output",
            str(output),
        ],
        mt5_module=DoctorMT5(),
    )

    report = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert (output / "M1.csv").exists()
    assert (output / "M5.csv").exists()
    assert (output / "manifest.json").exists()
    assert report["application_can_trade"] is False


def test_backtest_command_delegates_to_reproducible_runner(tmp_path, capsys):
    config = tmp_path / "strategy.json"
    config.write_text(json.dumps(valid_payload()), encoding="utf-8")
    calls = []

    def runner(config_path, market_root, output_dir):
        calls.append((config_path, market_root, output_dir))
        return {"status": "failed_insufficient_sample", "historical_gate_passed": False}

    exit_code = main(
        ["backtest", "--config", str(config), "--walk-forward"],
        research_runner=runner,
    )

    assert exit_code == 0
    assert len(calls) == 1
    assert json.loads(capsys.readouterr().out)["historical_gate_passed"] is False


def test_shadow_command_refuses_when_historical_gate_failed(tmp_path, capsys):
    config = tmp_path / "strategy.json"
    config.write_text(json.dumps(valid_payload()), encoding="utf-8")
    summary = tmp_path / "v0.1-summary.json"
    summary.write_text(json.dumps({"historical_gate_passed": False}), encoding="utf-8")

    exit_code = main(
        ["shadow", "--config", str(config), "--summary", str(summary)]
    )

    assert exit_code == 2
    assert json.loads(capsys.readouterr().out)["code"] == "historical_gate_failed"


def test_recalibrate_command_delegates_to_development_only_runner(tmp_path, capsys):
    config = tmp_path / "strategy.json"
    config.write_text(json.dumps(valid_payload()), encoding="utf-8")
    calls = []

    def runner(config_path, market_root, output_dir):
        calls.append((config_path, market_root, output_dir))
        return {
            "status": "development_rejected",
            "validation_accessed": False,
            "test_accessed": False,
        }

    exit_code = main(
        ["recalibrate", "--config", str(config), "--development-only"],
        recalibration_runner=runner,
    )

    assert exit_code == 0
    assert len(calls) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["validation_accessed"] is False
    assert report["test_accessed"] is False


def test_grid_backtest_command_delegates_to_partition_safe_runner(tmp_path, capsys):
    config = tmp_path / "grid-v1.0.json"
    config.write_text("{}", encoding="utf-8")
    market = tmp_path / "canonical-market"
    output = tmp_path / "grid-reports"
    calls = []

    def runner(config_path, market_root, output_dir):
        calls.append((config_path, market_root, output_dir))
        return {
            "version": "grid-v1.0",
            "status": "development_rejected",
            "test_accessed": False,
        }

    exit_code = main(
        [
            "grid-backtest",
            "--config",
            str(config),
            "--market-root",
            str(market),
            "--output",
            str(output),
        ],
        grid_runner=runner,
    )

    assert exit_code == 0
    assert calls == [(config, market, output)]
    assert json.loads(capsys.readouterr().out) == {
        "version": "grid-v1.0",
        "status": "development_rejected",
        "test_accessed": False,
    }


def test_grid_news_coverage_command_reports_nonzero_when_not_ready(tmp_path, capsys):
    config = tmp_path / "grid-v1.0.json"
    config.write_text("{}", encoding="utf-8")
    market = tmp_path / "canonical-market"
    news = tmp_path / "news.csv"
    calls = []

    class Report:
        ready = False

        def to_json_dict(self):
            return {
                "total_sessions": 2,
                "counts": {"missing_date_confirmation": 2},
                "ready": False,
                "items": [],
            }

    def runner(config_path, market_root, news_path):
        calls.append((config_path, market_root, news_path))
        return Report()

    exit_code = main(
        [
            "grid-news-coverage",
            "--config",
            str(config),
            "--market-root",
            str(market),
            "--news",
            str(news),
        ],
        grid_news_coverage_runner=runner,
    )

    assert exit_code == 2
    assert calls == [(config, market, news)]
    payload = json.loads(capsys.readouterr().out)
    assert payload["ready"] is False
    assert "items" not in payload


def test_grid_news_coverage_command_returns_zero_when_ready(tmp_path, capsys):
    config = tmp_path / "grid-v1.0.json"
    config.write_text("{}", encoding="utf-8")

    class Report:
        ready = True

        def to_json_dict(self):
            return {
                "total_sessions": 2,
                "counts": {"clear": 2},
                "ready": True,
                "items": [],
            }

    exit_code = main(
        ["grid-news-coverage", "--config", str(config)],
        grid_news_coverage_runner=lambda config_path, market_root, news_path: Report(),
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["ready"] is True


def test_grid_news_coverage_command_writes_full_output(tmp_path, capsys):
    config = tmp_path / "grid-v1.0.json"
    config.write_text("{}", encoding="utf-8")
    output = tmp_path / "coverage.json"

    class Report:
        ready = False

        def to_json_dict(self):
            return {
                "total_sessions": 1,
                "counts": {"missing_date_confirmation": 1},
                "ready": False,
                "items": [{"local_date": "2020-01-02"}],
            }

    exit_code = main(
        ["grid-news-coverage", "--config", str(config), "--output", str(output)],
        grid_news_coverage_runner=lambda config_path, market_root, news_path: Report(),
    )

    assert exit_code == 2
    assert "items" not in json.loads(capsys.readouterr().out)
    assert json.loads(output.read_text(encoding="utf-8"))["items"] == [
        {"local_date": "2020-01-02"}
    ]
