from __future__ import annotations

import argparse
import json
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
