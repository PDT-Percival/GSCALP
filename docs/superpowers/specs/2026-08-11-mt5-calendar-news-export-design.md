# MT5 Calendar News Export Design

**Status:** Approved for implementation planning

**Date:** 11 August 2026

**Approved source:** MetaTrader 5 Economic Calendar through the connected FBS-Demo terminal

**Terminal:** `C:\Program Files\FBS MetaTrader 5\terminal64.exe`

**Scope:** Source-backed scheduled high-impact USD/XAU calendar coverage for every grid v1.0 and pullback v1.1 candidate session from 2 January 2020 through 15 July 2026

## 1. Objective

Create a reproducible, read-only path from the MetaTrader 5 Economic Calendar to
the repository's canonical `data/news_blackouts.csv` file. The resulting data
must prove either that a candidate session overlaps a scheduled high-impact USD
or XAU event, or that a complete source query found no such event for that
session.

This work exists to remove the final historical-news uncertainty before the
frozen grid v1.0 pipeline is rerun. It does not change a strategy parameter,
place an order, enable demo execution, or promote either strategy.

## 2. Source Contract

The approved source is the Economic Calendar embedded in the installed
MetaTrader 5 terminal. The exporter uses these MQL5 APIs:

- `CalendarValueHistory` to retrieve values over bounded time ranges;
- `CalendarEventById` to resolve name, importance, time mode, event code, and
  publisher `source_url`;
- `CalendarCountryById` when country metadata is required; and
- `TimeTradeServer` and `TimeGMT` only for runtime audit metadata.

Queries are made separately with `currency="USD"` and `currency="XAU"`.
The exporter also records the currencies exposed by `CalendarCountries` so a
zero-result XAU query is distinguishable from an undocumented assumption about
the source taxonomy.

The source universe is limited to scheduled events indexed by the MT5 Economic
Calendar. It does not claim to enumerate unscheduled geopolitical events,
headlines, market shocks, or gold-related publications that the source does not
index. A successful zero-result query means no qualifying event exists in this
declared source universe; it is not a claim that no market-moving information
existed anywhere.

## 3. Safety Boundary

The MQL5 component is a script, not an Expert Advisor. It must:

- contain no `OrderSend`, `OrderCheck`, position, order, or deal mutation call;
- contain no `CTrade` include or trading-library dependency;
- contain no timer, tick, chart-event, or persistent execution handler;
- perform work only from `OnStart` and terminate after export;
- verify that the running terminal path, account server, demo trade mode (`0`),
  and retail-hedging margin mode (`2`) match the approved FBS-Demo environment
  before reading calendar data; and
- stop with a nonzero failure marker when any required precondition or calendar
  query fails.

Python-side import and validation are offline-only and must not initialize MT5
or access any trading function.

## 4. Requested Range and Chunking

The required historical interval is 2 January 2020 through 15 July 2026,
inclusive. To avoid calendar timeouts and partial-array errors, the exporter
queries one FBS server-time calendar month at a time, separately for USD and
XAU.

Each query uses a half-open logical interval:

```text
[first second of month, first second of next month)
```

The MQL5 API's returned event values are deduplicated by value ID. The exporter
must dynamically size arrays and treat these conditions as failures, not empty
results:

- return value `-1`;
- `ERR_CALENDAR_TIMEOUT`;
- `ERR_CALENDAR_MORE_DATA`;
- allocation failure;
- failure to resolve an event ID; or
- a write or close failure.

A returned count of zero is valid only when the call itself succeeded and the
recorded error code is zero.

## 5. FBS Server Time to UTC

MQL5 Economic Calendar timestamps use trade-server time. FBS publishes this
server-time rule:

- GMT+2 from the last Sunday in October at 01:00 UTC until the last Sunday in
  March at 01:00 UTC;
- GMT+3 from the last Sunday in March at 01:00 UTC until the last Sunday in
  October at 01:00 UTC.

The Python importer converts exported FBS wall-clock timestamps to UTC with an
explicit, tested implementation of that rule. It does not use the workstation's
local timezone. The importer records both the original server timestamp and the
derived UTC timestamp.

Because the offset changes at a known UTC instant, conversion tests cover both
sides of every March and October transition from 2020 through 2026. Any
ambiguous or nonexistent converted wall time fails the import instead of being
guessed.

## 6. Raw Export Schema

The MQL5 script writes an immutable UTF-8 CSV with this logical schema:

```text
query_currency,query_start_server,query_end_server,query_count,query_error,
value_id,event_id,event_time_server,event_time_mode_code,event_time_mode_name,
event_importance_code,event_importance_name,country_id,event_code,event_name,
source_url
```

Every successful month/currency query also produces a query-status row even
when no events were returned; query-status rows leave event fields empty. Event
rows retain the raw numeric importance and time-mode values as well as stable
text labels.

The exporter also writes a UTF-8 `key,value` metadata sidecar containing the
script version, approved terminal path, terminal build and company, account
server, numeric trade mode, numeric margin mode, requested range,
generation/server/GMT times, and the currencies exposed by
`CalendarCountries`. It must not contain the account login, password, balance,
equity, or other personal/account values.

The export is written inside the FBS terminal's own MQL5 file sandbox. It is
then copied into a versioned repository artifact directory without changing the
raw bytes.

## 7. Provenance Manifest

The offline importer writes a strict JSON manifest containing:

- export format version;
- retrieval timestamp;
- approved terminal path;
- terminal build and company;
- account server, numeric trade mode, and numeric margin mode, excluding login
  and personal data;
- requested server-time chunks and currency filters;
- per-query returned count and error code;
- currencies reported by `CalendarCountries`;
- raw export SHA-256;
- importer version and git commit;
- FBS timezone-rule source URL;
- MQL5 API documentation URLs;
- normalized CSV SHA-256;
- coverage-report SHA-256 values; and
- overall status: `complete`, `incomplete`, or `invalid`.

The importer may write the canonical news file only when every required query is
successful and the manifest status is `complete`.

## 8. Normalization Rules

Only `CALENDAR_IMPORTANCE_HIGH` events are emitted as blackout rows.

For exact-time events (`CALENDAR_TIMEMODE_DATETIME`):

```text
event_start_utc = converted event timestamp
event_end_utc   = event_start_utc + 1 second
```

This preserves the frozen strategy rule that a scheduled event blocks only if
its timestamp overlaps the candidate session. No new pre-news or post-news
buffer is introduced by this data pipeline.

For date-only, no-time, or tentative high-impact events, the normalized interval
covers the complete FBS server calendar day converted to UTC. This deliberately
blocks any candidate session intersecting that day.

Normalized event rows use:

```text
currency   = USD or XAU from the successful query
impact     = high
event_name = MT5 event name
source     = MT5 Calendar event <event_id>; <source_url>; raw=<raw_export_sha256>
```

Missing event names, missing publisher source URLs, invalid timestamps, unknown
importance values, and unknown time modes make the import invalid.

## 9. Explicit Clear Confirmations

The importer derives candidate sessions from the canonical M5 market data and
the frozen configuration files. It evaluates every grid v1.0 window and every
pullback v1.1 window on every available candidate trading date.

For a candidate session, the importer may emit a
`NO_HIGH_IMPACT_EVENTS` row only when:

1. the USD and XAU queries covering the entire session both succeeded;
2. the relevant raw export and manifest hashes validate;
3. no normalized high-impact USD or XAU event overlaps the session; and
4. the session is within the requested historical interval.

The clear row covers exactly that session and uses:

```text
currency   = ALL
impact     = none
event_name = NO_HIGH_IMPACT_EVENTS
source     = MT5 Calendar complete USD+XAU queries; raw=<raw_export_sha256>
```

Overlapping session windows may produce duplicate logical clear intervals; the
normalizer removes exact duplicates but does not merge intervals in a way that
could imply unqueried coverage.

If either currency query is missing or invalid, no clear row is generated and
the existing fail-closed `missing_date_confirmation` result remains in force.

Canonical rows reference the immutable raw-export hash rather than the manifest
hash. This avoids a circular dependency: the manifest can hash the normalized
CSV and coverage reports after those files are generated, while every derived
row still points back to the exact source bytes.

## 10. Canonical Outputs

The implementation produces:

- `mt5/GSCALP_NewsExport.mq5` — read-only terminal exporter;
- `artifacts/news/mt5-calendar/raw/` — immutable raw export;
- `artifacts/news/mt5-calendar/manifest.json` — provenance and completeness;
- `data/news_blackouts.csv` — normalized canonical event and clear rows;
- `artifacts/news/mt5-calendar/grid-v1.0-coverage.json` — every grid session;
- `artifacts/news/mt5-calendar/pullback-v1.1-coverage.json` — every pullback
  session; and
- a command summary reporting query, event, clear, blackout, invalid, and
  missing-confirmation counts.

Generated artifacts must use atomic replacement. A failed import cannot partly
replace the last validated canonical news file.

## 11. CLI and Operational Flow

The intended workflow is:

1. Compile the read-only script with the approved FBS MetaEditor.
2. Run it once in the connected FBS-Demo terminal.
3. Copy the raw export from the terminal sandbox into the artifact directory.
4. Run an offline import/validation command.
5. Run full grid and pullback coverage audits.
6. Verify hashes and independently reconcile event counts.
7. Rerun frozen grid v1.0 with no parameter changes.
8. Rerun frozen pullback v1.1 only as a corroborating source-backed evaluation;
   it may not revive a development-rejected candidate by tuning.

The CLI must return nonzero for incomplete queries, invalid provenance, hash
mismatch, missing session coverage, or any event-normalization error.

## 12. Testing Requirements

Tests must cover:

- parsing successful event and zero-event query rows;
- rejecting timeouts, more-data responses, partial months, missing currencies,
  unresolved event IDs, and missing source URLs;
- FBS GMT+2/GMT+3 conversion on ordinary dates and every DST boundary;
- exact-time one-second intervals;
- conservative whole-day handling for date-only, no-time, and tentative events;
- high-importance filtering without promoting moderate or low events;
- USD/XAU dual-query completeness before a clear row is emitted;
- deterministic ordering, deduplication, and byte-stable output;
- raw and normalized SHA-256 verification;
- atomic output replacement and preservation of the previous good file on
  failure;
- complete grid v1.0 and pullback v1.1 candidate-session coverage; and
- a static scan proving the MQL5 script contains no trading or order APIs.

The full existing repository test suite must remain green.

## 13. Acceptance Criteria

The news-data stage is complete only when all of these are true:

- every monthly USD and XAU query from January 2020 through July 2026 is recorded
  as successful;
- the raw export, normalized file, and manifest hashes verify;
- every grid v1.0 candidate session through 15 July 2026 is either explicitly
  clear or linked to an overlapping high-impact event;
- every pullback v1.1 candidate session through 15 July 2026 is either
  explicitly clear or linked to an overlapping high-impact event;
- no coverage item has `missing_date_confirmation` or `invalid_row`;
- independent count reconciliation matches the generated reports;
- no strategy configuration or threshold changed; and
- no order API was called or enabled.

Only after these criteria pass may the frozen historical pipelines be rerun and
their source-backed results evaluated.
