# Current status

- Branch: `feat/grid-v1-research`
- Pull request: `https://github.com/PDT-Percival/GSCALP/pull/1`
- Latest implementation commit: `5fb7f81`
- Safety state: historical research only; no pullback candidate is eligible for
  shadow or demo execution.
- Verification observed after the latest implementation changes: `308 passed`
  and the static pullback no-order API scan was clean.

## Built research modules

Pullback v1.1 now has a frozen configuration contract, completed-bar bias and
setup detection, risk-capped sizing, tick execution/exit simulation, partition
gates, canonical Parquet ingestion, reason-coded artifacts, and a CLI research
command. Performance work aggregates reference spreads, loads raw ticks only
for armed sessions, batches tick joins by year, detects each trigger-timeframe
setup once per session, and vectorizes the first-exit scan.

## Current research decision

Grid v1.0 and directional pullback v1.1 are both rejected at development. The
pullback no-news run completed on 11 August 2026 with 36 candidates, 1,896 base
trade rows, 41,772 rejection rows, and zero gate passes. Validation and test
were not accessed. See `docs/research/pullback-v1.1-result.md`.

The source-backed news requirement remains incomplete. The conservative
header-only run blocks every candidate session; the user-approved bypass is
not promotion evidence.
