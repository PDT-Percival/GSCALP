# MT5 Calendar News Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a read-only, provenance-preserving MT5 Economic Calendar export that gives every frozen grid v1.0 and pullback v1.1 candidate session an explicit high-impact USD/XAU blackout or a verified clear confirmation, then rerun the frozen historical pipelines without tuning.

**Architecture:** A one-shot MQL5 script exports monthly USD/XAU query status, raw events, and non-sensitive terminal metadata from the approved FBS-Demo terminal. Focused Python modules validate the raw contract, convert FBS server time to UTC, normalize high-impact events, derive exact candidate-session clear rows, produce atomic artifacts and coverage reports, and expose one offline CLI; a guarded PowerShell runner compiles and launches the script with live trading and DLL imports disabled.

**Tech Stack:** MQL5, MetaTrader 5/MetaEditor 5, PowerShell 7 or Windows PowerShell 5.1, Python 3.11+, pandas, DuckDB, `zoneinfo`, standard-library CSV/JSON/hash/file APIs, pytest, Git.

## Global Constraints

- Terminal path is exactly `C:\Program Files\FBS MetaTrader 5\terminal64.exe`.
- MetaEditor path is exactly `C:\Program Files\FBS MetaTrader 5\metaeditor64.exe`.
- FBS data folder is resolved by matching `origin.txt` to the exact terminal path; no hard-coded instance hash is trusted by the runner.
- Account server is exactly `FBS-Demo`; trade mode is demo (`0`); margin mode is retail hedging (`2`).
- Symbol used only to host the startup script is exactly `XAUUSD`.
- Required calendar range is January 2020 through July 2026; strategy coverage ends `2026-07-15`.
- Queries are monthly and separate for `USD` and `XAU`; exactly 158 status rows are required.
- Zero events is valid only when the call returned `0` with recorded error `0`.
- Any timeout, more-data error, missing/duplicate query, unresolved event, missing source URL, invalid time, or hash mismatch fails closed.
- Exact-time high-impact events normalize to one second; other time modes block their complete FBS server day.
- No new news buffer or strategy parameter is introduced.
- A clear row requires complete USD and XAU queries covering the candidate session.
- The MQL5 source contains no trading library, order/position mutation, persistent handler, DLL import, or web request.
- Startup sets `AllowLiveTrading=0`, `AllowDllImport=0`, and `ShutdownTerminal=1`.
- The runner refuses when the approved terminal is running and never kills it.
- Raw outputs exclude login, password, name, balance, equity, and other personal data.
- `data/news_blackouts.csv` is replaced last, only after every staged validation passes.
- Grid v1.0 and pullback v1.1 configs and thresholds do not change.
- Every task follows red-green-refactor and ends with a focused commit.

---

## File Structure

```text
mt5/GSCALP_NewsExport.mq5                  one-shot read-only calendar exporter
scripts/run_mt5_calendar_export.ps1        guarded compile/start/copy workflow
src/gscalp/fbs_time.py                     FBS EET/EEST conversion
src/gscalp/mt5_calendar_raw.py             strict raw models and parser
src/gscalp/news_sessions.py                canonical strategy sessions
src/gscalp/mt5_calendar_normalize.py       completeness and canonical rows
src/gscalp/news_coverage.py                common coverage reporting
src/gscalp/grid_news_coverage.py           grid compatibility wrapper
src/gscalp/pullback_news_coverage.py       pullback coverage wrapper
src/gscalp/mt5_calendar_pipeline.py        staging, manifest, atomic publication
src/gscalp/cli.py                          import and coverage commands
tests/test_fbs_time.py                     DST tests
tests/test_mt5_calendar_raw.py             raw parser tests
tests/test_news_sessions.py                session enumeration tests
tests/test_mt5_calendar_normalize.py       normalization tests
tests/test_news_coverage.py                coverage semantics tests
tests/test_mt5_calendar_pipeline.py        artifact pipeline tests
tests/test_mt5_calendar_mql5.py            static MQL5 safety tests
tests/test_mt5_calendar_runner.py          static runner tests
tests/test_cli.py                           CLI tests
docs/operations.md                          operator instructions
docs/research/*.md                          frozen rerun evidence
docs/ai-context/*.md                        project handoff/status
docs/changelog/2026-08-11-mt5-news.md       change record
```

---

### Task 1: Implement Exact FBS Server-Time Conversion

**Files:**
- Create: `src/gscalp/fbs_time.py`
- Create: `tests/test_fbs_time.py`

**Interfaces:**
- Produces: `last_sunday_utc(year: int, month: int) -> datetime`.
- Produces: `fbs_utc_offset_at(value_utc: datetime) -> timedelta`.
- Produces: `fbs_server_to_utc(value_server: datetime) -> datetime`.
- Produces: `FbsServerTimeError(ValueError)`.

- [ ] **Step 1: Write failing ordinary-time and transition tests**

```python
from datetime import datetime, timedelta, timezone

import pytest

from gscalp.fbs_time import FbsServerTimeError, fbs_server_to_utc, fbs_utc_offset_at


@pytest.mark.parametrize("year", range(2020, 2027))
def test_fbs_offset_is_two_hours_in_january_and_three_in_july(year):
    assert fbs_utc_offset_at(datetime(year, 1, 15, tzinfo=timezone.utc)) == timedelta(hours=2)
    assert fbs_utc_offset_at(datetime(year, 7, 15, tzinfo=timezone.utc)) == timedelta(hours=3)


def test_server_wall_time_conversion_is_not_local_timezone_dependent():
    assert fbs_server_to_utc(datetime(2023, 1, 3, 15, 30)) == datetime(
        2023, 1, 3, 13, 30, tzinfo=timezone.utc
    )
    assert fbs_server_to_utc(datetime(2023, 7, 3, 16, 30)) == datetime(
        2023, 7, 3, 13, 30, tzinfo=timezone.utc
    )


def test_gap_and_duplicate_wall_times_fail_closed():
    with pytest.raises(FbsServerTimeError, match="nonexistent"):
        fbs_server_to_utc(datetime(2026, 3, 29, 3, 30))
    with pytest.raises(FbsServerTimeError, match="ambiguous"):
        fbs_server_to_utc(datetime(2026, 10, 25, 3, 30))
```

- [ ] **Step 2: Verify the test fails before implementation**

Run `python -m pytest tests/test_fbs_time.py -q`.

Expected: `ModuleNotFoundError: No module named 'gscalp.fbs_time'`.

- [ ] **Step 3: Implement the conversion using two UTC candidates**

```python
class FbsServerTimeError(ValueError):
    pass


def last_sunday_utc(year: int, month: int) -> datetime:
    if month not in {3, 10}:
        raise ValueError("month must be March or October")
    probe = datetime(year, month, 31, 1, tzinfo=timezone.utc)
    return probe - timedelta(days=(probe.weekday() + 1) % 7)


def fbs_utc_offset_at(value_utc: datetime) -> timedelta:
    if value_utc.tzinfo is None:
        raise ValueError("value_utc must be timezone-aware")
    value = value_utc.astimezone(timezone.utc)
    start = last_sunday_utc(value.year, 3)
    end = last_sunday_utc(value.year, 10)
    return timedelta(hours=3 if start <= value < end else 2)


def fbs_server_to_utc(value_server: datetime) -> datetime:
    if value_server.tzinfo is not None:
        raise ValueError("value_server must be a naive FBS wall time")
    candidates = []
    for hours in (2, 3):
        value = (value_server - timedelta(hours=hours)).replace(tzinfo=timezone.utc)
        if fbs_utc_offset_at(value) == timedelta(hours=hours):
            candidates.append(value)
    if not candidates:
        raise FbsServerTimeError(f"nonexistent FBS server time: {value_server}")
    if len(candidates) != 1:
        raise FbsServerTimeError(f"ambiguous FBS server time: {value_server}")
    return candidates[0]
```

- [ ] **Step 4: Assert both sides of every 2020-2026 transition and pass tests**

Run `python -m pytest tests/test_fbs_time.py -q`.

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/gscalp/fbs_time.py tests/test_fbs_time.py
git commit -m "feat: add audited FBS server time conversion"
```

---

### Task 2: Parse the Strict Raw Calendar Contract

**Files:**
- Create: `src/gscalp/mt5_calendar_raw.py`
- Create: `tests/test_mt5_calendar_raw.py`

**Interfaces:**
- Produces frozen `CalendarQueryKey`, `CalendarQueryStatus`, `RawCalendarEvent`, `CalendarMetadata`, and `CalendarExport`.
- Produces `load_calendar_export(events_path: Path | str, metadata_path: Path | str) -> CalendarExport`.
- Produces `CalendarRawError(ValueError)`.

- [ ] **Step 1: Write a failing happy-path parser test**

Use this exact header:

```python
EVENT_HEADER = (
    "query_currency,query_start_server,query_end_server,query_count,query_error,"
    "value_id,event_id,event_time_server,event_time_mode_code,event_time_mode_name,"
    "event_importance_code,event_importance_name,country_id,event_code,event_name,source_url\n"
)
```

The fixture has one query-status row with blank event fields and one event row.
Its metadata keys and exact safety values are:

```python
{
    "script_version": "mt5-calendar-v1",
    "terminal_path": r"C:\Program Files\FBS MetaTrader 5\terminal64.exe",
    "terminal_build": "5440",
    "terminal_company": "MetaQuotes Ltd.",
    "account_server": "FBS-Demo",
    "account_trade_mode": "0",
    "account_margin_mode": "2",
    "requested_from_server": "2020.01.01 00:00:00",
    "requested_to_server": "2026.08.01 00:00:00",
    "generated_at_server": "2026.08.11 19:00:00",
    "current_server_time": "2026.08.11 19:00:00",
    "current_gmt_time": "2026.08.11 16:00:00",
    "calendar_currencies": "EUR;USD",
    "export_status": "complete",
}
```

Assert naive server timestamps, integer IDs/codes, and absence of personal keys.

- [ ] **Step 2: Verify the missing-module failure**

Run `python -m pytest tests/test_mt5_calendar_raw.py -q`.

Expected: `ModuleNotFoundError` for `gscalp.mt5_calendar_raw`.

- [ ] **Step 3: Implement strict frozen models and parsing**

```python
@dataclass(frozen=True, slots=True, order=True)
class CalendarQueryKey:
    currency: str
    start_server: datetime
    end_server: datetime


@dataclass(frozen=True, slots=True)
class CalendarQueryStatus:
    key: CalendarQueryKey
    count: int
    error: int


@dataclass(frozen=True, slots=True)
class RawCalendarEvent:
    query: CalendarQueryKey
    value_id: int
    event_id: int
    time_server: datetime
    time_mode_code: int
    time_mode_name: str
    importance_code: int
    importance_name: str
    country_id: int
    event_code: str
    event_name: str
    source_url: str


@dataclass(frozen=True, slots=True)
class CalendarMetadata:
    values: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class CalendarExport:
    queries: tuple[CalendarQueryStatus, ...]
    events: tuple[RawCalendarEvent, ...]
    metadata: CalendarMetadata
```

Parse timestamps only with `%Y.%m.%d %H:%M:%S`. Require the exact event header
and exact metadata key set. Query rows have blank event fields; event rows have
all event fields.

- [ ] **Step 4: Add malformed-contract cases**

Parametrize duplicate query status, duplicate value ID, count mismatch, blank
source URL, unknown currency, malformed server time, incomplete export status,
unknown/missing columns, and a personal metadata key. Require stable
`CalendarRawError` reasons.

- [ ] **Step 5: Pass tests and commit**

```powershell
python -m pytest tests/test_mt5_calendar_raw.py -q
git add src/gscalp/mt5_calendar_raw.py tests/test_mt5_calendar_raw.py
git commit -m "feat: parse strict MT5 calendar exports"
```

---

### Task 3: Enumerate Canonical Strategy Sessions Once

**Files:**
- Create: `src/gscalp/news_sessions.py`
- Create: `tests/test_news_sessions.py`
- Modify: `src/gscalp/grid_news_coverage.py`
- Modify: `tests/test_grid_news_coverage.py`

**Interfaces:**
- Consumes `GridConfig`, `PullbackConfig`, canonical `bars/M5.parquet`, and `research.new_york_session_bounds`.
- Produces `StrategySessionSpec`, `CandidateSession`, `grid_session_spec`, `pullback_session_spec`, and `candidate_sessions`.
- Preserves `grid_news_coverage.build_news_coverage_report` through a wrapper.

- [ ] **Step 1: Write failing cross-strategy session tests**

```python
grid = candidate_sessions(market, grid_session_spec(load_grid_config("config/grid-v1.0.json")))
pullback = candidate_sessions(
    market, pullback_session_spec(load_pullback_config("config/pullback-v1.1.json"))
)
assert {item.window for item in grid} == {"08:45-09:45", "09:30-10:30"}
assert {item.window for item in pullback} == {
    "08:45-09:45", "09:30-10:30", "10:00-11:00"
}
assert all(item.start_utc.tzname() == "UTC" for item in grid + pullback)
assert all(item.end_utc - item.start_utc == pd.Timedelta(hours=1) for item in grid + pullback)
```

Also assert deterministic `(local_date, window)` ordering and exact date bounds.

- [ ] **Step 2: Verify the missing-module failure**

Run `python -m pytest tests/test_news_sessions.py -q`.

Expected: `ModuleNotFoundError` for `gscalp.news_sessions`.

- [ ] **Step 3: Implement common records and enumeration**

```python
@dataclass(frozen=True, slots=True)
class StrategySessionSpec:
    version: str
    windows_ny: tuple[str, ...]
    first_date: date
    last_date: date


@dataclass(frozen=True, slots=True, order=True)
class CandidateSession:
    version: str
    local_date: date
    window: str
    start_utc: pd.Timestamp
    end_utc: pd.Timestamp
```

Read distinct M5 timestamps with DuckDB, parse them as UTC, convert each actual
timestamp to `America/New_York`, and deduplicate the resulting local dates. This
must match the date derivation in both historical pipelines and must not retain
the existing coverage helper's over-inclusive `-1/0/+1 day` heuristic. Then call
`new_york_session_bounds` and refactor the grid module into a compatibility
wrapper.

- [ ] **Step 4: Pass common and compatibility tests**

Run `python -m pytest tests/test_news_sessions.py tests/test_grid_news_coverage.py -q`.

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/gscalp/news_sessions.py src/gscalp/grid_news_coverage.py tests/test_news_sessions.py tests/test_grid_news_coverage.py
git commit -m "refactor: share canonical news sessions"
```

---

### Task 4: Validate Completeness and Normalize Events/Clear Rows

**Files:**
- Create: `src/gscalp/mt5_calendar_normalize.py`
- Create: `tests/test_mt5_calendar_normalize.py`

**Interfaces:**
- Consumes `CalendarExport`, `CandidateSession`, `fbs_server_to_utc`, and raw SHA-256.
- Produces `NormalizedNewsRow`, `expected_monthly_queries`, `validate_complete_export`, and `normalize_calendar_news`.
- Produces `CalendarNormalizationError(ValueError)`.

- [ ] **Step 1: Write failing completeness tests**

```python
assert expected_monthly_queries(
    datetime(2020, 1, 1), datetime(2020, 3, 1)
) == (
    CalendarQueryKey("USD", datetime(2020, 1, 1), datetime(2020, 2, 1)),
    CalendarQueryKey("XAU", datetime(2020, 1, 1), datetime(2020, 2, 1)),
    CalendarQueryKey("USD", datetime(2020, 2, 1), datetime(2020, 3, 1)),
    CalendarQueryKey("XAU", datetime(2020, 2, 1), datetime(2020, 3, 1)),
)
```

Add rejection cases for missing XAU, query error, negative count, count mismatch,
overlapping chunks, range drift, wrong terminal path/server/modes, and events
outside their query interval.

- [ ] **Step 2: Verify the missing-module failure**

Run `python -m pytest tests/test_mt5_calendar_normalize.py -q`.

Expected: `ModuleNotFoundError` for `gscalp.mt5_calendar_normalize`.

- [ ] **Step 3: Implement the output record and exact completeness gate**

```python
@dataclass(frozen=True, slots=True, order=True)
class NormalizedNewsRow:
    event_start_utc: pd.Timestamp
    event_end_utc: pd.Timestamp
    currency: str
    impact: str
    event_name: str
    source: str

    def csv_dict(self) -> dict[str, str]:
        return {
            "event_start_utc": self.event_start_utc.isoformat(),
            "event_end_utc": self.event_end_utc.isoformat(),
            "currency": self.currency,
            "impact": self.impact,
            "event_name": self.event_name,
            "source": self.source,
        }
```

`validate_complete_export` compares the exact 158-key expected/actual sets,
requires zero errors and exact counts, validates all safety metadata, and rejects
any event outside its half-open parent query interval.

- [ ] **Step 4: Test every time mode and importance**

Use enum names as the semantic authority and assert:

```python
assert exact.event_end_utc - exact.event_start_utc == pd.Timedelta(seconds=1)
assert tentative.event_end_utc - tentative.event_start_utc in {
    pd.Timedelta(hours=23), pd.Timedelta(hours=24), pd.Timedelta(hours=25)
}
assert all(row.impact == "high" for row in rows)
assert "raw=" + ("a" * 64) in rows[0].source
```

Support `CALENDAR_TIMEMODE_DATETIME`, `CALENDAR_TIMEMODE_DATE`,
`CALENDAR_TIMEMODE_NOTIME`, and `CALENDAR_TIMEMODE_TENTATIVE`. Filter moderate
and low events. Reject inconsistent code/name pairs, blank names/source URLs,
unknown enum names, and ambiguous/nonexistent FBS times.

- [ ] **Step 5: Test exact clear-row derivation**

One session overlaps a high event and one does not. Assert only the latter gets:

```python
NormalizedNewsRow(
    event_start_utc=session.start_utc,
    event_end_utc=session.end_utc,
    currency="ALL",
    impact="none",
    event_name="NO_HIGH_IMPACT_EVENTS",
    source=f"MT5 Calendar complete USD+XAU queries; raw={'a' * 64}",
)
```

Remove exact duplicates, retain all normalized high events, and sort
deterministically.

- [ ] **Step 6: Pass tests and commit**

```powershell
python -m pytest tests/test_fbs_time.py tests/test_mt5_calendar_raw.py tests/test_news_sessions.py tests/test_mt5_calendar_normalize.py -q
git add src/gscalp/mt5_calendar_normalize.py tests/test_mt5_calendar_normalize.py
git commit -m "feat: normalize complete MT5 news coverage"
```

---

### Task 5: Make Coverage Strategy-Neutral

**Files:**
- Create: `src/gscalp/news_coverage.py`
- Create: `src/gscalp/pullback_news_coverage.py`
- Create: `tests/test_news_coverage.py`
- Modify: `src/gscalp/grid_news_coverage.py`
- Modify: `tests/test_grid_news_coverage.py`

**Interfaces:**
- Produces common `NewsCoverageItem`, `NewsCoverageReport`, and `build_strategy_news_coverage_report`.
- Preserves the grid wrapper and adds a pullback wrapper.

- [ ] **Step 1: Write failing status-semantic tests**

```python
assert report.coverage_complete is True
assert report.all_sessions_clear is False
assert report.ready is True
assert report.counts == {"clear": 1, "overlapping_blackout": 1}
```

Any `missing_date_confirmation` or `invalid_row` must make `coverage_complete`
and `ready` false. JSON includes version, all three booleans, counts, and items.

- [ ] **Step 2: Verify the missing common module failure**

Run `python -m pytest tests/test_news_coverage.py -q`.

Expected: `ModuleNotFoundError` for `gscalp.news_coverage`.

- [ ] **Step 3: Implement common reporting and wrappers**

```python
coverage_complete = bool(items) and not any(
    item.code in {NewsCode.MISSING_DATE_CONFIRMATION.value, NewsCode.INVALID_ROW.value}
    for item in items
)
all_sessions_clear = coverage_complete and all(
    item.code == NewsCode.CLEAR.value for item in items
)
ready = coverage_complete
```

Move report records to the common module. Keep the grid function signature and
add the same signature using `PullbackConfig` in `pullback_news_coverage.py`.

- [ ] **Step 4: Pass regression tests and commit**

```powershell
python -m pytest tests/test_grid_news.py tests/test_grid_news_coverage.py tests/test_news_coverage.py -q
git add src/gscalp/news_coverage.py src/gscalp/grid_news_coverage.py src/gscalp/pullback_news_coverage.py tests/test_news_coverage.py tests/test_grid_news_coverage.py
git commit -m "feat: audit news coverage across strategies"
```

---

### Task 6: Stage, Hash, Validate, and Publish Artifacts Atomically

**Files:**
- Create: `src/gscalp/mt5_calendar_pipeline.py`
- Create: `tests/test_mt5_calendar_pipeline.py`

**Interfaces:**
- Produces `CalendarImportRequest`, `CalendarImportResult`, and `run_mt5_calendar_import`.
- Produces manifest format `mt5-calendar-manifest-v1`.

- [ ] **Step 1: Write a failing end-to-end fixture test**

Generate all 158 monthly query-status rows for January 2020 through July 2026,
with zero events except one exact high-impact USD event. Use a tiny canonical M5
parquet fixture and the frozen grid/pullback configuration files.

```python
request = CalendarImportRequest(
    raw_events=raw_events,
    raw_metadata=raw_metadata,
    mq5_source=Path("mt5/GSCALP_NewsExport.mq5"),
    market_root=market,
    news_output=tmp_path / "data" / "news_blackouts.csv",
    artifact_root=tmp_path / "artifacts" / "news" / "mt5-calendar",
    grid_config=grid_config,
    pullback_config=pullback_config,
    git_commit="0123456789abcdef",
)
result = run_mt5_calendar_import(request)
assert result.status == "complete"
assert result.application_can_trade is False
assert result.grid_coverage.coverage_complete is True
assert result.pullback_coverage.coverage_complete is True
```

Assert exact CSV headers, finite JSON, and independently matching file hashes.

- [ ] **Step 2: Verify the missing-module failure**

Run `python -m pytest tests/test_mt5_calendar_pipeline.py -q`.

Expected: `ModuleNotFoundError` for `gscalp.mt5_calendar_pipeline`.

- [ ] **Step 3: Implement request/result records and deterministic staging**

```python
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
```

Write CSV as UTF-8/LF with fixed fields. Write JSON with `sort_keys=True`,
`indent=2`, `allow_nan=False`, and final newline. Stage all files in a unique
sibling directory, validate staged hashes/reports, publish artifacts with
`os.replace`, and publish the canonical news CSV last.

- [ ] **Step 4: Implement strict manifest fields**

Require these top-level keys:

```python
{
    "format_version", "status", "retrieved_at_utc", "terminal", "account",
    "query_range_server", "query_counts", "calendar_currencies", "sources",
    "hashes", "coverage", "application_can_trade",
}
```

`sources` contains MetaQuotes Calendar API, calendar structures, platform-start,
and FBS timezone URLs. `hashes` contains raw event, metadata, MQL5, normalized,
and both coverage hashes. `account` contains only server/trade/margin modes.

- [ ] **Step 5: Add prior-good-file preservation tests**

Inject failures for incomplete queries, bad hash, missing coverage, absent MQL5
source, and exception before publication. Assert existing canonical news bytes
remain unchanged and no complete manifest is emitted.

- [ ] **Step 6: Pass tests and commit**

```powershell
python -m pytest tests/test_mt5_calendar_pipeline.py -q
git add src/gscalp/mt5_calendar_pipeline.py tests/test_mt5_calendar_pipeline.py
git commit -m "feat: publish verified MT5 news artifacts"
```

---

### Task 7: Expose Offline Import and Pullback Coverage Commands

**Files:**
- Modify: `src/gscalp/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces `mt5-news-import` and `pullback-news-coverage` commands.
- Adds injectable `mt5_news_import_runner` and `pullback_news_coverage_runner`.

- [ ] **Step 1: Write failing CLI delegation tests**

```python
exit_code = main(
    [
        "mt5-news-import",
        "--raw-events", str(raw_events),
        "--raw-metadata", str(raw_metadata),
        "--market-root", str(market),
        "--news-output", str(news),
        "--artifact-root", str(artifacts),
    ],
    mt5_news_import_runner=runner,
)
```

Assert the runner receives `CalendarImportRequest`; stdout includes status,
coverage, hashes, and `application_can_trade=false`; incomplete returns `2`.
Test pullback coverage full-output behavior like the grid command.

- [ ] **Step 2: Verify argparse rejects both commands**

Run `python -m pytest tests/test_cli.py -q`.

Expected: new tests fail with invalid command choices.

- [ ] **Step 3: Implement exact argument sets and handlers**

`mt5-news-import` defaults:

```text
--mq5-source       mt5/GSCALP_NewsExport.mq5
--market-root      artifacts/market
--news-output      data/news_blackouts.csv
--artifact-root    artifacts/news/mt5-calendar
--grid-config      config/grid-v1.0.json
--pullback-config  config/pullback-v1.1.json
```

`--raw-events` and `--raw-metadata` are required. The pullback coverage command
mirrors grid coverage with its frozen config. Stdout omits items; `--output`
writes the complete report.

- [ ] **Step 4: Pass tests and commit**

```powershell
python -m pytest tests/test_cli.py tests/test_grid_news_coverage.py tests/test_news_coverage.py -q
git add src/gscalp/cli.py tests/test_cli.py
git commit -m "feat: expose verified MT5 news import"
```

---

### Task 8: Implement and Compile the No-Trade MQL5 Exporter

**Files:**
- Create: `mt5/GSCALP_NewsExport.mq5`
- Create: `tests/test_mt5_calendar_mql5.py`

**Interfaces:**
- Reads only the MT5 Economic Calendar and approved environment metadata.
- Produces `MQL5/Files/GSCALP/mt5_calendar_events.csv` and `mt5_calendar_metadata.csv`.
- Executes only `void OnStart()`.

- [ ] **Step 1: Write a failing static safety-contract test**

Require these source tokens:

```python
required = {
    "void OnStart()", "CalendarValueHistory", "CalendarEventById",
    "CalendarCountries", "TERMINAL_PATH", "ACCOUNT_SERVER",
    "ACCOUNT_TRADE_MODE_DEMO", "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING",
    "CP_UTF8", "CALENDAR_IMPORTANCE_HIGH",
}
```

Reject these case-insensitive tokens:

```python
forbidden = {
    "#include <trade/", "ordersend", "ordercheck", "ctrade",
    "positionopen", "positionclose", "webrequest", "dllimport",
    "ontick(", "ontimer(", "onchartevent(",
}
```

Also require the exact raw header and output filenames.

- [ ] **Step 2: Verify the missing-source failure**

Run `python -m pytest tests/test_mt5_calendar_mql5.py -q`.

Expected: failure because the MQL5 source is absent.

- [ ] **Step 3: Implement fixed preconditions and metadata**

```cpp
#property strict

#define EXPORT_VERSION "mt5-calendar-v1"
#define REQUIRED_TERMINAL_DIRECTORY "C:\\Program Files\\FBS MetaTrader 5"
#define REQUIRED_TERMINAL_EXE "C:\\Program Files\\FBS MetaTrader 5\\terminal64.exe"
#define REQUIRED_SERVER "FBS-Demo"
#define EVENTS_FILE "GSCALP\\mt5_calendar_events.csv"
#define METADATA_FILE "GSCALP\\mt5_calendar_metadata.csv"
```

At `OnStart`, compare `TerminalInfoString(TERMINAL_PATH)` with
`REQUIRED_TERMINAL_DIRECTORY`, then compare server, demo mode, and hedging mode
exactly. Record `REQUIRED_TERMINAL_EXE` as the metadata `terminal_path`. Open
UTF-8 CSV using `FILE_ANSI` with `CP_UTF8`. Write only approved metadata.

- [ ] **Step 4: Implement deterministic monthly USD/XAU queries**

Use fixed bounds `D'2020.01.01 00:00:00'` and
`D'2026.08.01 00:00:00'`. For every month/currency:

```cpp
ResetLastError();
MqlCalendarValue values[];
int count = CalendarValueHistory(values, month_start, month_end, NULL, currency);
int error = GetLastError();
```

Write one query-status row before its event rows. Fail if `count < 0`,
`error != 0`, or `ArraySize(values) != count`. Resolve each event with
`CalendarEventById`, write code/name enum pairs, reject blank name/source URL,
and sort values by `(time, event_id, id)`.

- [ ] **Step 5: Implement safe partial-file finalization**

Write `.partial` files. Metadata starts `export_status,started`; only a fully
flushed export becomes `export_status,complete` and is renamed to final names.
Any failure prints a stable reason and leaves no importable complete pair.

- [ ] **Step 6: Pass static tests and compile with the approved MetaEditor**

```powershell
$dataFolder = 'C:\Users\HP\AppData\Roaming\MetaQuotes\Terminal\776D2ACDFA4F66FAF3C8985F75FA9FF6'
$scriptDir = Join-Path $dataFolder 'MQL5\Scripts\GSCALP'
New-Item -ItemType Directory -Force -Path $scriptDir | Out-Null
Copy-Item -LiteralPath 'mt5\GSCALP_NewsExport.mq5' -Destination $scriptDir
& 'C:\Program Files\FBS MetaTrader 5\metaeditor64.exe' "/compile:$scriptDir\GSCALP_NewsExport.mq5" "/log:$scriptDir\GSCALP_NewsExport.log"
Get-Content -Raw "$scriptDir\GSCALP_NewsExport.log"
```

Expected: `0 errors, 0 warnings` and a sibling `.ex5`. Resolve `origin.txt`
again if the data-folder identifier changes.

- [ ] **Step 7: Commit**

```powershell
git add mt5/GSCALP_NewsExport.mq5 tests/test_mt5_calendar_mql5.py
git commit -m "feat: add read-only MT5 calendar exporter"
```

---

### Task 9: Add the Guarded Windows Compile-and-Run Workflow

**Files:**
- Create: `scripts/run_mt5_calendar_export.ps1`
- Create: `tests/test_mt5_calendar_runner.py`
- Modify: `docs/operations.md`

**Interfaces:**
- Resolves the FBS data folder, compiles the exporter, launches a no-trade startup config, and copies raw bytes to `artifacts/news/mt5-calendar/incoming/`.
- Never terminates a running terminal.

- [ ] **Step 1: Write failing static runner tests**

Require:

```python
required = {
    "AllowLiveTrading=0", "AllowDllImport=0",
    "Script=GSCALP\\GSCALP_NewsExport", "Symbol=XAUUSD", "Period=M1",
    "ShutdownTerminal=1", "origin.txt", "metaeditor64.exe", "terminal64.exe",
}
```

Reject `Stop-Process`, `taskkill`, `Remove-Item -Recurse`, `/login:`,
`Password=`, and `AllowLiveTrading=1`.

- [ ] **Step 2: Verify the missing-runner failure**

Run `python -m pytest tests/test_mt5_calendar_runner.py -q`.

Expected: failure because the PowerShell file is absent.

- [ ] **Step 3: Implement exact defaults and data-folder resolution**

```powershell
param(
    [string]$TerminalPath = 'C:\Program Files\FBS MetaTrader 5\terminal64.exe',
    [string]$MetaEditorPath = 'C:\Program Files\FBS MetaTrader 5\metaeditor64.exe',
    [string]$SourcePath = 'mt5\GSCALP_NewsExport.mq5',
    [string]$ArtifactRoot = 'artifacts\news\mt5-calendar\incoming',
    [int]$TimeoutSeconds = 300
)
```

Scan immediate folders under `$env:APPDATA\MetaQuotes\Terminal`, compare trimmed
`origin.txt` with the terminal installation directory, and require one match.
Refuse when the exact terminal executable is running. Compile and require the
log text `0 errors, 0 warnings` before startup.

- [ ] **Step 4: Implement the no-trade startup and bounded wait**

Generate only:

```ini
[Experts]
AllowLiveTrading=0
AllowDllImport=0
Enabled=1

[StartUp]
Script=GSCALP\GSCALP_NewsExport
Symbol=XAUUSD
Period=M1
ShutdownTerminal=1
```

Use `Start-Process -WindowStyle Hidden -PassThru` with `/config:<absolute ini>`.
Poll until exit or timeout. On timeout, return nonzero and leave the terminal for
inspection. After normal exit, require both files and `export_status=complete`,
then copy them unchanged to the incoming folder.

- [ ] **Step 5: Document exact operator commands**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_mt5_calendar_export.ps1
python -m gscalp.cli mt5-news-import `
  --raw-events artifacts/news/mt5-calendar/incoming/mt5_calendar_events.csv `
  --raw-metadata artifacts/news/mt5-calendar/incoming/mt5_calendar_metadata.csv
```

State that the terminal must be closed normally first, the runner never closes
it, and a nonzero result preserves the previous canonical news file.

- [ ] **Step 6: Pass tests and commit**

```powershell
python -m pytest tests/test_mt5_calendar_runner.py tests/test_mt5_calendar_mql5.py -q
git add scripts/run_mt5_calendar_export.ps1 tests/test_mt5_calendar_runner.py docs/operations.md
git commit -m "feat: guard MT5 calendar export execution"
```

---

### Task 10: Run the Real Export and Frozen Source-Backed Evaluations

**Files:**
- Modify generated: `data/news_blackouts.csv`
- Create generated: `artifacts/news/mt5-calendar/**`
- Modify: `docs/research/grid-v1.0-result.md`
- Modify: `docs/research/pullback-v1.1-result.md`
- Modify: `docs/ai-context/current-status.md`
- Modify: `docs/ai-context/open-items.md`
- Modify: `docs/ai-context/agent-handoff.md`
- Create: `docs/changelog/2026-08-11-mt5-news.md`

**Interfaces:**
- Produces authoritative source/coverage/research evidence.
- Decides rejection or eligibility for a separate shadow/parity phase.
- Never submits an order.

- [ ] **Step 1: Verify read-only repository/account preconditions**

```powershell
git status --short
@'
import MetaTrader5 as mt5
path = r"C:\Program Files\FBS MetaTrader 5\terminal64.exe"
assert mt5.initialize(path=path), mt5.last_error()
account = mt5.account_info()
terminal = mt5.terminal_info()
assert terminal.connected
assert account.server == "FBS-Demo"
assert account.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
assert account.margin_mode == mt5.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING
assert len(mt5.positions_get(symbol="XAUUSD") or ()) == 0
assert len(mt5.orders_get(symbol="XAUUSD") or ()) == 0
mt5.shutdown()
print("read_only_preconditions=passed")
'@ | python -
```

Expected: clean worktree and every assertion passes.

- [ ] **Step 2: Close FBS MT5 normally and run the guarded exporter**

Close the exact FBS window through its normal UI, then run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_mt5_calendar_export.ps1
```

Expected: zero compiler errors/warnings, self-shutdown after `OnStart`, and a
complete raw pair under `incoming/`.

- [ ] **Step 3: Import and run both independent coverage audits**

```powershell
python -m gscalp.cli mt5-news-import `
  --raw-events artifacts/news/mt5-calendar/incoming/mt5_calendar_events.csv `
  --raw-metadata artifacts/news/mt5-calendar/incoming/mt5_calendar_metadata.csv `
  --market-root artifacts/market `
  --news-output data/news_blackouts.csv `
  --artifact-root artifacts/news/mt5-calendar

python -m gscalp.cli grid-news-coverage --config config/grid-v1.0.json --market-root artifacts/market --news data/news_blackouts.csv --output artifacts/news/mt5-calendar/grid-v1.0-coverage-independent.json
python -m gscalp.cli pullback-news-coverage --config config/pullback-v1.1.json --market-root artifacts/market --news data/news_blackouts.csv --output artifacts/news/mt5-calendar/pullback-v1.1-coverage-independent.json
```

Expected: zero exit codes, `coverage_complete=true`, and no missing/invalid item.

- [ ] **Step 4: Independently reconcile raw and generated evidence**

Run a separate Python process that does not import pipeline or coverage modules.
It must SHA-256 every file, compare manifest hashes, count exactly 158 unique
monthly status rows, reconcile each query's declared/event counts, compare both
coverage reports by `(local_date, window, code)`, and print
`independent_reconciliation=passed` only after all assertions.

- [ ] **Step 5: Run full automated and static verification**

```powershell
python -m pytest -q
rg -n -i "OrderSend|OrderCheck|CTrade|PositionOpen|PositionClose|WebRequest|OnTick|OnTimer" mt5/GSCALP_NewsExport.mq5
git diff --check
```

Expected: all tests pass, the scan has no matches, and diff check is clean.

- [ ] **Step 6: Prove frozen configuration identity**

```powershell
Get-FileHash config/grid-v1.0.json -Algorithm SHA256
Get-FileHash config/pullback-v1.1.json -Algorithm SHA256
git diff --exit-code -- config/grid-v1.0.json config/pullback-v1.1.json
```

Expected: no diff; record both hashes.

- [ ] **Step 7: Rerun both frozen pipelines with source-backed news**

```powershell
python -m gscalp.cli grid-backtest --config config/grid-v1.0.json --market-root artifacts/market --output artifacts/reports-source-backed-grid-v1.0
python -m gscalp.cli pullback-backtest --config config/pullback-v1.1.json --market-root artifacts/market --news data/news_blackouts.csv --output artifacts/reports-source-backed-pullback-v1.1
```

Expected: both finish with the exact canonical news hash and partition-access
flags intact.

- [ ] **Step 8: Apply the frozen decision branch**

If grid development rejects, require validation/test untouched, document the
source-backed rejection, and reference the already separate v1.1 design/result
without tuning. If grid passes every gate, lock only its selected config hash
and write a separate 10-session no-trade shadow/parity plan; do not enable demo.
Treat pullback v1.1 similarly without changing its candidate values.

- [ ] **Step 9: Update authoritative documents with evidence**

Record source/terminal identity, all raw/normalized/config/coverage/report
hashes, query/event/clear/blackout counts, independent reconciliation, frozen
metrics/gates, partition access, eligibility outcome, and confirmation that no
order API was called or order submitted.

- [ ] **Step 10: Verify and commit tracked evidence**

```powershell
python -m pytest -q
git diff --check
git status --short
git add data/news_blackouts.csv docs/research/grid-v1.0-result.md docs/research/pullback-v1.1-result.md docs/ai-context/current-status.md docs/ai-context/open-items.md docs/ai-context/agent-handoff.md docs/changelog/2026-08-11-mt5-news.md
git commit -m "docs: record source-backed news evaluation"
```

Expected: tests pass and only intended tracked evidence is committed; ignored
artifacts are referenced by exact path and hash in documentation.

---

## Specification Coverage Map

| Design section | Implemented and verified by |
| --- | --- |
| Objective and source contract | Tasks 2, 6, 8, and 10 |
| Safety boundary | Tasks 6, 8, 9, and 10 |
| Requested range and chunking | Tasks 4, 8, and 10 |
| FBS server time to UTC | Task 1 and Task 4 |
| Raw export schema | Task 2 and Task 8 |
| Provenance manifest | Task 6 and Task 10 |
| Normalization rules | Task 4 |
| Explicit clear confirmations | Tasks 3, 4, and 5 |
| Canonical outputs | Tasks 5, 6, 7, and 10 |
| CLI and operational flow | Tasks 7, 9, and 10 |
| Testing requirements | Tasks 1 through 9 plus Task 10 full verification |
| Acceptance criteria | Task 10 and the Plan Completion Gate |

Self-review found no uncovered specification requirement after correcting the
terminal-directory/executable distinction, raw enum columns, safety-mode fields,
full-query test fixture, and non-circular provenance hash.

---

## Plan Completion Gate

1. Full pytest suite passes.
2. MQL5 compiles with zero errors and warnings.
3. Static scans prove no trading APIs or persistent handlers.
4. All 158 monthly USD/XAU query-status rows succeed.
5. Every grid/pullback candidate session is clear or linked to a blackout.
6. Independent hashes, counts, and coverage match generated evidence.
7. Frozen config hashes and git diff prove no tuning.
8. Both source-backed reruns finish with partition locks intact.
9. Documents accurately state rejection or the next conditional shadow phase.
10. No order was checked, staged, enabled, or submitted.
