from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .grid_config import load_grid_config
from .grid_news_coverage import build_news_coverage_report as build_grid_coverage
from .mt5_calendar_normalize import (
    CalendarNormalizationError,
    NormalizedNewsRow,
    normalize_calendar_news,
)
from .mt5_calendar_raw import CalendarExport, load_calendar_export
from .news_coverage import NewsCoverageReport
from .news_sessions import (
    candidate_sessions,
    grid_session_spec,
    pullback_session_spec,
)
from .pullback_config import load_pullback_config
from .pullback_news_coverage import (
    build_news_coverage_report as build_pullback_coverage,
)


MANIFEST_VERSION = "mt5-calendar-manifest-v1"
NEWS_FIELDS = (
    "event_start_utc",
    "event_end_utc",
    "currency",
    "impact",
    "event_name",
    "source",
)

SOURCE_URLS = {
    "calendar_api": "https://www.mql5.com/en/docs/calendar/calendarvaluehistory",
    "calendar_structures": (
        "https://www.mql5.com/en/docs/constants/structures/mqlcalendar"
    ),
    "platform_start": (
        "https://www.metatrader5.com/en/terminal/help/start_advanced/start"
    ),
    "fbs_server_time": "https://fbs.com/trading/trading-hours?lang=en",
}


@dataclass(frozen=True, slots=True)
class CalendarImportRequest:
    raw_events: Path
    raw_metadata: Path
    mq5_source: Path
    market_root: Path
    news_output: Path
    artifact_root: Path
    grid_config: Path
    pullback_config: Path
    git_commit: str | None = None


@dataclass(frozen=True, slots=True)
class CalendarImportResult:
    status: str
    manifest_path: Path
    news_path: Path
    raw_sha256: str
    normalized_sha256: str
    grid_coverage: NewsCoverageReport
    pullback_coverage: NewsCoverageReport
    application_can_trade: bool = False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_news(path: Path, rows: tuple[NormalizedNewsRow, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=NEWS_FIELDS,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(row.csv_dict() for row in rows)


def _coverage_payload(report: NewsCoverageReport) -> dict[str, Any]:
    return report.to_json_dict()


def _coverage_summary(report: NewsCoverageReport) -> dict[str, Any]:
    return {
        "strategy_version": report.strategy_version,
        "total_sessions": report.total_sessions,
        "counts": report.counts,
        "coverage_complete": report.coverage_complete,
        "all_sessions_clear": report.all_sessions_clear,
        "ready": report.ready,
    }


def _current_git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _retrieved_at_utc(export: CalendarExport) -> str:
    value = datetime.strptime(
        export.metadata.values["current_gmt_time"],
        "%Y.%m.%d %H:%M:%S",
    ).replace(tzinfo=timezone.utc)
    return value.isoformat()


def _query_counts(export: CalendarExport) -> dict[str, int]:
    currencies = Counter(query.key.currency for query in export.queries)
    return {
        "total": len(export.queries),
        "USD": currencies["USD"],
        "XAU": currencies["XAU"],
        "events": len(export.events),
    }


def _publish_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _validate_request(request: CalendarImportRequest) -> None:
    for label, path in (
        ("raw event CSV", request.raw_events),
        ("raw metadata CSV", request.raw_metadata),
        ("MQL5 source", request.mq5_source),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} does not exist: {path}")
    if not (request.market_root / "bars" / "M5.parquet").is_file():
        raise FileNotFoundError(
            f"canonical M5 parquet does not exist: {request.market_root}"
        )


def run_mt5_calendar_import(
    request: CalendarImportRequest,
) -> CalendarImportResult:
    _validate_request(request)
    raw_sha256 = _sha256(request.raw_events)
    raw_metadata_sha256 = _sha256(request.raw_metadata)
    mq5_sha256 = _sha256(request.mq5_source)
    export = load_calendar_export(request.raw_events, request.raw_metadata)
    grid_config = load_grid_config(request.grid_config)
    pullback_config = load_pullback_config(request.pullback_config)
    sessions = (
        candidate_sessions(request.market_root, grid_session_spec(grid_config))
        + candidate_sessions(
            request.market_root,
            pullback_session_spec(pullback_config),
        )
    )
    normalized = normalize_calendar_news(export, sessions, raw_sha256)

    request.artifact_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".mt5-calendar-stage-",
        dir=request.artifact_root.parent,
    ) as temporary_directory:
        stage = Path(temporary_directory)
        stage_raw = stage / "raw"
        stage_raw.mkdir(parents=True)
        staged_events = stage_raw / "mt5_calendar_events.csv"
        staged_metadata = stage_raw / "mt5_calendar_metadata.csv"
        shutil.copyfile(request.raw_events, staged_events)
        shutil.copyfile(request.raw_metadata, staged_metadata)

        staged_news = stage / "news_blackouts.csv"
        _write_news(staged_news, normalized)

        grid_report = build_grid_coverage(
            grid_config,
            request.market_root,
            staged_news,
        )
        pullback_report = build_pullback_coverage(
            pullback_config,
            request.market_root,
            staged_news,
        )
        if not grid_report.coverage_complete:
            raise CalendarNormalizationError(
                "grid-v1.0 coverage is incomplete after normalization"
            )
        if not pullback_report.coverage_complete:
            raise CalendarNormalizationError(
                "pullback-v1.1 coverage is incomplete after normalization"
            )

        staged_grid = stage / "grid-v1.0-coverage.json"
        staged_pullback = stage / "pullback-v1.1-coverage.json"
        _write_json(staged_grid, _coverage_payload(grid_report))
        _write_json(staged_pullback, _coverage_payload(pullback_report))

        normalized_sha256 = _sha256(staged_news)
        hashes = {
            "raw_events_sha256": raw_sha256,
            "raw_metadata_sha256": raw_metadata_sha256,
            "mq5_source_sha256": mq5_sha256,
            "normalized_news_sha256": normalized_sha256,
            "grid_coverage_sha256": _sha256(staged_grid),
            "pullback_coverage_sha256": _sha256(staged_pullback),
        }
        metadata = export.metadata.values
        manifest = {
            "format_version": MANIFEST_VERSION,
            "status": "complete",
            "retrieved_at_utc": _retrieved_at_utc(export),
            "terminal": {
                "path": metadata["terminal_path"],
                "build": int(metadata["terminal_build"]),
                "company": metadata["terminal_company"],
            },
            "account": {
                "server": metadata["account_server"],
                "trade_mode": int(metadata["account_trade_mode"]),
                "margin_mode": int(metadata["account_margin_mode"]),
            },
            "query_range_server": {
                "from": metadata["requested_from_server"],
                "to": metadata["requested_to_server"],
            },
            "query_counts": _query_counts(export),
            "calendar_currencies": sorted(
                set(metadata["calendar_currencies"].split(";"))
            ),
            "sources": {
                **SOURCE_URLS,
                "importer_version": "mt5-calendar-v1",
                "git_commit": request.git_commit or _current_git_commit(),
            },
            "hashes": hashes,
            "coverage": {
                "grid-v1.0": _coverage_summary(grid_report),
                "pullback-v1.1": _coverage_summary(pullback_report),
            },
            "application_can_trade": False,
        }
        staged_manifest = stage / "manifest.json"
        _write_json(staged_manifest, manifest)

        final_raw = request.artifact_root / "raw"
        final_grid = request.artifact_root / "grid-v1.0-coverage.json"
        final_pullback = request.artifact_root / "pullback-v1.1-coverage.json"
        final_manifest = request.artifact_root / "manifest.json"
        _publish_file(staged_events, final_raw / staged_events.name)
        _publish_file(staged_metadata, final_raw / staged_metadata.name)
        _publish_file(staged_grid, final_grid)
        _publish_file(staged_pullback, final_pullback)
        _publish_file(staged_manifest, final_manifest)
        _publish_file(staged_news, request.news_output)

    return CalendarImportResult(
        status="complete",
        manifest_path=request.artifact_root / "manifest.json",
        news_path=request.news_output,
        raw_sha256=raw_sha256,
        normalized_sha256=normalized_sha256,
        grid_coverage=grid_report,
        pullback_coverage=pullback_report,
        application_can_trade=False,
    )
