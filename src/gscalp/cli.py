from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from .config import load_config
from .mt5_read import MT5ReadGateway


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gscalp")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="verify read-only MT5 access")
    doctor.add_argument("--config", type=Path, default=Path("config/strategy.json"))
    download = commands.add_parser("download", help="download read-only MT5 bars")
    download.add_argument("--config", type=Path, default=Path("config/strategy.json"))
    download.add_argument("--days", type=int, default=180)
    download.add_argument("--timeframes", nargs="+", default=["M1", "M5", "M15", "H1"])
    download.add_argument("--output", type=Path, default=Path("artifacts/market/mt5"))
    backtest = commands.add_parser("backtest", help="run frozen historical research")
    backtest.add_argument("--config", type=Path, default=Path("config/strategy.json"))
    backtest.add_argument("--market-root", type=Path, default=Path("artifacts/market"))
    backtest.add_argument("--output", type=Path, default=Path("artifacts/reports"))
    backtest.add_argument("--walk-forward", action="store_true")
    recalibrate = commands.add_parser(
        "recalibrate", help="run versioned development-only parameter research"
    )
    recalibrate.add_argument("--config", type=Path, default=Path("config/strategy.json"))
    recalibrate.add_argument("--market-root", type=Path, default=Path("artifacts/market"))
    recalibrate.add_argument("--output", type=Path, default=Path("artifacts/reports"))
    recalibrate.add_argument("--development-only", action="store_true")
    recalibrate.add_argument(
        "--parameter",
        choices=("sweep_atr_max", "max_stop_atr", "allow_same_bar_reclaim"),
        default="sweep_atr_max",
    )
    grid = commands.add_parser(
        "grid-backtest", help="run frozen grid v1.0 research"
    )
    grid.add_argument("--config", type=Path, default=Path("config/grid-v1.0.json"))
    grid.add_argument("--market-root", type=Path, default=Path("artifacts/market"))
    grid.add_argument("--output", type=Path, default=Path("artifacts/reports"))
    pullback = commands.add_parser(
        "pullback-backtest", help="run frozen pullback v1.1 research"
    )
    pullback.add_argument(
        "--config", type=Path, default=Path("config/pullback-v1.1.json")
    )
    pullback.add_argument(
        "--market-root", type=Path, default=Path("artifacts/market")
    )
    pullback.add_argument(
        "--news", type=Path, default=Path("data/news_blackouts.csv")
    )
    pullback.add_argument("--output", type=Path, default=Path("artifacts/reports"))
    grid_news = commands.add_parser(
        "grid-news-coverage",
        help="verify explicit source-backed news coverage for grid sessions",
    )
    grid_news.add_argument("--config", type=Path, default=Path("config/grid-v1.0.json"))
    grid_news.add_argument("--market-root", type=Path, default=Path("artifacts/market"))
    grid_news.add_argument("--news", type=Path, default=Path("data/news_blackouts.csv"))
    grid_news.add_argument("--output", type=Path)
    shadow = commands.add_parser("shadow", help="run non-trading forward logger")
    shadow.add_argument("--config", type=Path, default=Path("config/strategy.json"))
    shadow.add_argument("--summary", type=Path, default=Path("artifacts/reports/v0.1-summary.json"))
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    mt5_module: Any | None = None,
    research_runner: Callable[[Path, Path, Path], dict[str, Any]] | None = None,
    recalibration_runner: Callable[[Path, Path, Path], dict[str, Any]] | None = None,
    grid_runner: Callable[[Path, Path, Path], Any] | None = None,
    grid_news_coverage_runner: Callable[[Path, Path, Path], Any] | None = None,
    pullback_runner: Callable[..., Any] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    if args.command == "doctor":
        config = load_config(args.config)
        if mt5_module is None:
            import MetaTrader5 as mt5_module

        gateway = MT5ReadGateway(
            mt5_module,
            config.terminal_path,
            config.required_server,
            config.symbol,
        )
        try:
            snapshot = gateway.connect()
            report = {
                "connected": True,
                "server": snapshot.server,
                "terminal_path": snapshot.terminal_path,
                "symbol": snapshot.symbol.name,
                "digits": snapshot.symbol.digits,
                "point": snapshot.symbol.point,
                "contract_size": snapshot.symbol.contract_size,
                "volume_min": snapshot.symbol.volume_min,
                "volume_step": snapshot.symbol.volume_step,
                "configuration_mode": config.mode,
                "application_can_trade": False,
            }
            print(json.dumps(report, indent=2))
            return 0
        finally:
            gateway.close()
    if args.command == "download":
        if args.days < 1:
            raise ValueError("download days must be positive")
        config = load_config(args.config)
        if mt5_module is None:
            import MetaTrader5 as mt5_module
        gateway = MT5ReadGateway(mt5_module, config.terminal_path, config.required_server, config.symbol)
        try:
            snapshot = gateway.connect()
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=args.days)
            args.output.mkdir(parents=True, exist_ok=True)
            rows: dict[str, int] = {}
            for name in args.timeframes:
                constant_name = f"TIMEFRAME_{name.upper()}"
                if not hasattr(mt5_module, constant_name):
                    raise ValueError(f"unsupported MT5 timeframe: {name}")
                frame = gateway.get_rates(getattr(mt5_module, constant_name), start, end)
                frame.to_csv(args.output / f"{name.upper()}.csv", index=False)
                rows[name.upper()] = len(frame)
            report = {
                "retrieved_at_utc": end.isoformat(),
                "start_utc": start.isoformat(),
                "end_utc": end.isoformat(),
                "server": snapshot.server,
                "symbol": snapshot.symbol.name,
                "rows": rows,
                "application_can_trade": False,
            }
            (args.output / "manifest.json").write_text(
                json.dumps(report, indent=2), encoding="utf-8"
            )
            print(json.dumps(report, indent=2))
            return 0
        finally:
            gateway.close()
    if args.command == "backtest":
        if not args.walk_forward:
            raise ValueError("the frozen research command requires --walk-forward")
        if research_runner is None:
            from .pipeline import run_frozen_research

            research_runner = run_frozen_research
        report = research_runner(args.config, args.market_root, args.output)
        print(json.dumps(report, indent=2, allow_nan=False))
        return 0
    if args.command == "recalibrate":
        if not args.development_only:
            raise ValueError("recalibration requires --development-only")
        if recalibration_runner is None:
            if args.parameter == "sweep_atr_max":
                from .recalibration import run_development_experiment

                recalibration_runner = run_development_experiment
            elif args.parameter == "max_stop_atr":
                from .recalibration import run_stop_development_experiment

                recalibration_runner = run_stop_development_experiment
            else:
                from .recalibration import run_same_bar_development_experiment

                recalibration_runner = run_same_bar_development_experiment
        report = recalibration_runner(args.config, args.market_root, args.output)
        print(json.dumps(report, indent=2, allow_nan=False))
        return 0
    if args.command == "grid-backtest":
        if grid_runner is None:
            from .grid_pipeline import run_grid_research

            grid_runner = run_grid_research
        report = grid_runner(args.config, args.market_root, args.output)
        payload = asdict(report) if is_dataclass(report) else report
        print(json.dumps(payload, indent=2, allow_nan=False))
        return 0
    if args.command == "pullback-backtest":
        if pullback_runner is None:
            from .pullback_pipeline import run_pullback_research

            pullback_runner = run_pullback_research
        report = pullback_runner(
            args.config,
            args.market_root,
            args.output,
            news_path=args.news,
        )
        payload = (
            report.to_json_dict()
            if hasattr(report, "to_json_dict")
            else asdict(report)
            if is_dataclass(report)
            else report
        )
        print(json.dumps(payload, indent=2, allow_nan=False))
        return 0
    if args.command == "grid-news-coverage":
        if grid_news_coverage_runner is None:
            from .grid_config import load_grid_config
            from .grid_news_coverage import build_news_coverage_report

            def grid_news_coverage_runner(
                config_path: Path,
                market_root: Path,
                news_path: Path,
            ):
                return build_news_coverage_report(
                    load_grid_config(config_path), market_root, news_path
                )

        report = grid_news_coverage_runner(args.config, args.market_root, args.news)
        payload = report.to_json_dict() if hasattr(report, "to_json_dict") else report
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8"
            )
        summary_payload = {
            key: value for key, value in payload.items() if key != "items"
        }
        if args.output is not None:
            summary_payload["output"] = str(args.output)
        print(json.dumps(summary_payload, indent=2, allow_nan=False))
        return 0 if payload.get("ready", False) else 2
    if args.command == "shadow":
        load_config(args.config)
        summary = json.loads(args.summary.read_text(encoding="utf-8"))
        if not summary.get("historical_gate_passed", False):
            print(
                json.dumps(
                    {
                        "started": False,
                        "code": "historical_gate_failed",
                        "application_can_trade": False,
                    }
                )
            )
            return 2
        raise RuntimeError("shadow runner requires a locked validated session")
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
